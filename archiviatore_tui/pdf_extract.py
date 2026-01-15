from __future__ import annotations

from pathlib import Path
import shutil
from typing import Optional, Tuple


def extract_pdf_text(path: Path, *, max_chars: int = 15000) -> Optional[str]:
    text, _reason = extract_pdf_text_with_reason(path, max_chars=max_chars)
    return text


def extract_pdf_text_with_reason(path: Path, *, max_chars: int = 15000) -> Tuple[Optional[str], Optional[str]]:
    try:
        from pypdf import PdfReader
    except Exception:
        return None, "Missing dependency: pypdf"

    try:
        reader = PdfReader(str(path))
    except Exception:
        return None, "Failed to open PDF"

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
    if not joined:
        ocr_text = _extract_pdf_text_ocr(path, max_chars=max_chars)
        if not ocr_text:
            return None, "No extractable text and OCR not available"
        return ocr_text, "ocr"
    return joined[:max_chars], "text"


def _extract_pdf_text_ocr(path: Path, *, max_chars: int) -> Optional[str]:
    if not shutil.which("tesseract"):
        return None
    try:
        import fitz  # PyMuPDF
    except Exception:
        return None
    try:
        from PIL import Image
    except Exception:
        return None
    try:
        import pytesseract
    except Exception:
        return None

    try:
        doc = fitz.open(str(path))
    except Exception:
        return None

    ocr_parts: list[str] = []
    max_pages = 3
    for page_index in range(min(len(doc), max_pages)):
        try:
            page = doc.load_page(page_index)
            pix = page.get_pixmap(dpi=200)
            mode = "RGB" if pix.alpha == 0 else "RGBA"
            img = Image.frombytes(mode, (pix.width, pix.height), pix.samples)
        except Exception:
            continue

        text = ""
        try:
            text = pytesseract.image_to_string(img, lang="eng+ita")
        except Exception:
            try:
                text = pytesseract.image_to_string(img, lang="eng")
            except Exception:
                text = ""
        if text.strip():
            ocr_parts.append(text.strip())
        if sum(len(p) for p in ocr_parts) >= max_chars:
            break

    joined = "\n\n".join(ocr_parts).strip()
    if not joined:
        return None
    return joined[:max_chars]
