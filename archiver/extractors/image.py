from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import time
from typing import Optional

from ..ollama_client import generate_with_image_file


@dataclass(frozen=True)
class ImageOcrMeta:
    ocr_time_s: float
    dpi: int
    variants: int


@dataclass(frozen=True)
class ImageCaptionMeta:
    caption_time_s: float
    vision_model_used: Optional[str] = None
    last_error: Optional[str] = None


def extract_image_text_ocr(
    path: Path,
    *,
    max_chars: int,
    ocr_mode: str,
) -> tuple[Optional[str], Optional[ImageOcrMeta]]:
    """Best-effort OCR for image files (jpg/png). Returns text + meta or (None, None)."""
    import shutil

    if not shutil.which("tesseract"):
        return None, None
    try:
        from PIL import Image, ImageOps
    except Exception:
        return None, None
    try:
        import pytesseract
    except Exception:
        return None, None

    def ocr_profile(mode: str) -> tuple[int, list[str], tuple[str, ...], bool, float]:
        m = (mode or "").lower()
        if m == "fast":
            return 220, ["6"], ("ita+eng", "eng"), False, 12.0
        if m == "high":
            return 300, ["3", "4", "6", "11"], ("ita+eng", "eng+ita", "eng"), True, 60.0
        return 260, ["6", "3"], ("ita+eng", "eng"), True, 25.0

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

    try:
        img = Image.open(path)
    except Exception:
        return None, None

    dpi, psms, langs, heavy_preprocess, budget_s = ocr_profile(ocr_mode)
    t0 = time.perf_counter()
    tesseract_config = "--oem 1 --psm 6 -c preserve_interword_spaces=1"

    variants: list[Image.Image] = []
    try:
        variants.append(img)
        gray = img.convert("L")
        variants.append(gray)
        if heavy_preprocess:
            variants.append(ImageOps.autocontrast(gray))
            variants.append(ImageOps.autocontrast(gray).point(lambda x: 255 if x > 180 else 0, mode="1"))
    except Exception:
        variants = [img]

    best_text = ""
    best_score = 0.0
    for v in variants:
        for psm in psms:
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

    text = best_text.strip()
    if not text:
        return None, None
    # Avoid using very low-signal OCR (photos, noise).
    if best_score < 40.0 and len(text) < 120:
        return None, None
    ocr_elapsed = time.perf_counter() - t0
    return text[:max_chars], ImageOcrMeta(ocr_time_s=ocr_elapsed, dpi=dpi, variants=len(variants))


def caption_image(
    image_path: Path,
    *,
    vision_models: tuple[str, ...],
    prompt: str,
    base_url: str,
    timeout_s: float = 180.0,
) -> tuple[str, ImageCaptionMeta]:
    """Try a list of vision models until one returns a caption (best-effort)."""
    caption = ""
    used: str | None = None
    last_error: str | None = None
    t0 = time.perf_counter()
    for vm in vision_models:
        try:
            cap = generate_with_image_file(
                model=vm,
                prompt=prompt,
                image_path=str(image_path),
                base_url=base_url,
                timeout_s=timeout_s,
            )
        except Exception as exc:  # noqa: BLE001
            last_error = f"{type(exc).__name__}"
            continue
        if cap.error:
            last_error = cap.error
            continue
        caption = (cap.response or "").strip()
        if caption:
            used = vm
            break

    elapsed = time.perf_counter() - t0
    return caption, ImageCaptionMeta(caption_time_s=elapsed, vision_model_used=used, last_error=last_error)

