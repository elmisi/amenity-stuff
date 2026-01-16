from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
from typing import Optional, Tuple


@dataclass(frozen=True)
class PdfExtractMeta:
    method: str
    extract_time_s: float
    ocr_time_s: Optional[float] = None
    ocr_mode: Optional[str] = None
    pages: Optional[int] = None
    dpi: Optional[int] = None


def extract_pdf_text(path: Path, *, max_chars: int = 15000) -> Optional[str]:
    text, _reason = extract_pdf_text_with_reason(path, max_chars=max_chars)
    return text


def extract_pdf_text_with_reason(path: Path, *, max_chars: int = 15000) -> Tuple[Optional[str], Optional[str]]:
    text, reason, _meta = extract_pdf_text_with_meta(path, max_chars=max_chars, ocr_mode="balanced")
    return text, reason


def extract_pdf_text_with_meta(
    path: Path,
    *,
    max_chars: int = 15000,
    ocr_mode: str = "balanced",
) -> Tuple[Optional[str], Optional[str], Optional[PdfExtractMeta]]:
    t0 = time.perf_counter()
    # 1) pypdf extraction (if available)
    joined = ""
    try:
        from pypdf import PdfReader

        try:
            reader = PdfReader(str(path))
            parts: list[str] = []
            for page in reader.pages[:50]:
                try:
                    text = page.extract_text() or ""
                except Exception:
                    text = ""
                if text.strip():
                    parts.append(text.strip())
                if sum(len(p) for p in parts) >= max_chars:
                    break
            joined = "\n\n".join(parts).strip()
        except Exception:
            joined = ""
    except Exception:
        joined = ""

    if joined:
        elapsed = time.perf_counter() - t0
        return joined[:max_chars], "text", PdfExtractMeta(method="text", extract_time_s=elapsed)

    # 2) poppler pdftotext (often better on some PDFs)
    poppler_text = _extract_pdf_text_pdftotext(path, max_chars=max_chars)
    if poppler_text:
        elapsed = time.perf_counter() - t0
        return poppler_text, "pdftotext", PdfExtractMeta(method="pdftotext", extract_time_s=elapsed)

    # 3) OCR fallback
    ocr_text, ocr_meta = _extract_pdf_text_ocr(path, max_chars=max_chars, ocr_mode=ocr_mode)
    if not ocr_text:
        return None, "No extractable text (enable OCR with system tesseract)", None
    elapsed = time.perf_counter() - t0
    meta = PdfExtractMeta(
        method="ocr",
        extract_time_s=elapsed,
        ocr_time_s=ocr_meta.ocr_time_s if ocr_meta else elapsed,
        ocr_mode=ocr_mode,
        pages=ocr_meta.pages if ocr_meta else None,
        dpi=ocr_meta.dpi if ocr_meta else None,
    )
    return ocr_text, "ocr", meta


def _extract_pdf_text_pdftotext(path: Path, *, max_chars: int) -> Optional[str]:
    if not shutil.which("pdftotext"):
        return None
    try:
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            proc = subprocess.run(
                ["pdftotext", str(path), str(tmp_path)],
                text=True,
                capture_output=True,
                timeout=15,
                check=False,
            )
            if proc.returncode != 0:
                return None
            text = tmp_path.read_text(encoding="utf-8", errors="ignore")
        finally:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass
    except Exception:
        return None
    text = text.strip()
    if not text:
        return None
    return text[:max_chars]


@dataclass(frozen=True)
class OcrMeta:
    ocr_time_s: float
    pages: int
    dpi: int


def _ocr_profile(mode: str) -> tuple[int, int, list[str], tuple[str, ...], bool]:
    """Return (dpi, max_pages, psms, langs, heavy_preprocess)."""
    m = (mode or "").lower()
    if m == "fast":
        return 220, 2, ["6"], ("ita+eng", "eng"), False
    if m == "high":
        return 300, 4, ["3", "4", "6", "11"], ("ita+eng", "eng+ita", "eng"), True
    return 260, 3, ["6", "3"], ("ita+eng", "eng"), True


def _ocr_budget_s(mode: str) -> float:
    m = (mode or "").lower()
    if m == "fast":
        return 20.0
    if m == "high":
        return 120.0
    return 45.0


def _extract_pdf_text_ocr(path: Path, *, max_chars: int, ocr_mode: str) -> tuple[Optional[str], Optional[OcrMeta]]:
    if not shutil.which("tesseract"):
        return None, None
    try:
        import fitz  # PyMuPDF
    except Exception:
        return None, None
    try:
        from PIL import Image
    except Exception:
        return None, None
    try:
        import pytesseract
    except Exception:
        return None, None

    try:
        doc = fitz.open(str(path))
    except Exception:
        return None, None

    dpi, max_pages, alt_psm, langs, heavy_preprocess = _ocr_profile(ocr_mode)
    t0 = time.perf_counter()
    budget_s = _ocr_budget_s(ocr_mode)
    ocr_parts: list[str] = []
    tesseract_config = "--oem 1 --psm 6 -c preserve_interword_spaces=1"

    def score_text(text: str) -> float:
        t = (text or "").strip()
        if not t:
            return 0.0
        sample = t[:2000]
        alnum = sum(ch.isalnum() for ch in sample)
        letters = sum(ch.isalpha() for ch in sample)
        spaces = sum(ch.isspace() for ch in sample)
        weird = sum(ord(ch) < 9 or ord(ch) == 127 for ch in sample)
        artifacts = len(re.findall(r"(?<=[A-Za-zÀ-ÖØ-öø-ÿ])_(?=[A-Za-zÀ-ÖØ-öø-ÿ])", sample))
        return (alnum + letters * 0.5 + spaces * 0.1) - (weird * 5.0 + artifacts * 3.0)

    def clean_ocr_artifacts(text: str) -> str:
        return re.sub(r"(?<=[A-Za-zÀ-ÖØ-öø-ÿ])_(?=[A-Za-zÀ-ÖØ-öø-ÿ])", "", text or "")

    for page_index in range(min(len(doc), max_pages)):
        try:
            page = doc.load_page(page_index)
            pix = page.get_pixmap(dpi=dpi)
            mode = "RGB" if pix.alpha == 0 else "RGBA"
            img = Image.frombytes(mode, (pix.width, pix.height), pix.samples)
        except Exception:
            continue

        variants: list[Image.Image] = []
        variants.append(img)
        try:
            gray = img.convert("L")
            variants.append(gray)
            if heavy_preprocess:
                from PIL import ImageOps

                variants.append(ImageOps.autocontrast(gray))
                variants.append(ImageOps.autocontrast(gray).point(lambda x: 255 if x > 180 else 0, mode="1"))
        except Exception:
            pass

        best_text = ""
        best_score = 0.0
        for v in variants:
            for psm in alt_psm:
                if time.perf_counter() - t0 > budget_s:
                    break
                cfg = tesseract_config.replace("--psm 6", f"--psm {psm}")
                for lang in langs:
                    if time.perf_counter() - t0 > budget_s:
                        break
                    try:
                        text = pytesseract.image_to_string(v, lang=lang, config=cfg, timeout=30)
                    except Exception:
                        continue
                    text = clean_ocr_artifacts(text)
                    s = score_text(text)
                    if s > best_score:
                        best_score = s
                        best_text = text
                if time.perf_counter() - t0 > budget_s:
                    break
            if time.perf_counter() - t0 > budget_s:
                break

        if best_text.strip():
            ocr_parts.append(best_text.strip())
        if sum(len(p) for p in ocr_parts) >= max_chars:
            break
        if time.perf_counter() - t0 > budget_s:
            break

    joined = "\n\n".join(ocr_parts).strip()
    if not joined:
        return None, None
    ocr_elapsed = time.perf_counter() - t0
    return joined[:max_chars], OcrMeta(ocr_time_s=ocr_elapsed, pages=min(len(doc), max_pages), dpi=dpi)
