from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple, Union

from .textish import extract_textish_with_meta
from .types import TextExtractMeta
from .office import OfficeExtractMeta, extract_office_text_with_meta
from .pdf import PdfExtractMeta, extract_pdf_text_with_meta

ExtractMeta = Union[PdfExtractMeta, OfficeExtractMeta, TextExtractMeta]


def extract_with_meta(
    *,
    kind: str,
    path: Path,
    max_chars: int = 15000,
    ocr_mode: str = "balanced",
) -> Tuple[Optional[str], Optional[str], Optional[ExtractMeta]]:
    """Single entrypoint for text extraction across supported kinds.

    Notes:
    - This is for the "scan/facts" phase. Image handling (OCR/vision) remains elsewhere.
    - Return shape matches the legacy per-module helpers: (text, reason, meta).
    """
    if kind == "pdf":
        return extract_pdf_text_with_meta(path, max_chars=max_chars, ocr_mode=ocr_mode)
    if kind in {"doc", "docx", "odt", "xls", "xlsx"}:
        return extract_office_text_with_meta(path, max_chars=max_chars)
    if kind in {"json", "md", "txt", "rtf", "svg", "kmz", "gpx", "html", "csv", "yaml"}:
        return extract_textish_with_meta(path, max_chars=max_chars)
    return None, "Unsupported file type", None
