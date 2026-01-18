from __future__ import annotations

import time
from pathlib import Path
from typing import Optional, Tuple

from .types import TextExtractMeta
from .utils_text import flatten_json_text, read_text_file


def extract_textish_with_meta(
    path: Path,
    *,
    max_chars: int = 15000,
) -> Tuple[Optional[str], Optional[str], Optional[TextExtractMeta]]:
    """Extract text from lightweight text-ish formats with minimal deps.

    Supported:
    - .txt, .md: read as UTF-8 (errors=ignore)
    - .json: parse + flatten to key/value lines (fallback to raw)
    - .rtf: prefer `unrtf` if available, fallback to naive stripping
    - .svg: parse XML and collect <text>/<title>/<desc> plus raw text nodes
    - .kmz: read embedded .kml (zip) and extract placemarks (best-effort)
    """
    ext = path.suffix.lower().lstrip(".")
    t0 = time.perf_counter()

    if ext in {"txt", "md"}:
        text = read_text_file(path, max_chars=max_chars)
        if not text:
            return None, "Empty file", None
        return text, ext, TextExtractMeta(method=ext, extract_time_s=time.perf_counter() - t0)

    if ext == "json":
        raw = read_text_file(path, max_chars=max_chars * 4) or ""
        text = flatten_json_text(raw, max_chars=max_chars) or raw.strip()[:max_chars]
        if not text:
            return None, "Empty JSON", None
        return text, "json", TextExtractMeta(method="json", extract_time_s=time.perf_counter() - t0)

    if ext == "rtf":
        from .textish_rtf import extract_rtf_text

        text = extract_rtf_text(path, max_chars=max_chars)
        if not text:
            return None, "No extractable RTF text (install unrtf for best results)", None
        return text, "rtf", TextExtractMeta(method="rtf", extract_time_s=time.perf_counter() - t0)

    if ext == "svg":
        from .textish_svg import extract_svg_text

        text = extract_svg_text(path, max_chars=max_chars)
        if not text:
            return None, "No extractable SVG text", None
        return text, "svg", TextExtractMeta(method="svg", extract_time_s=time.perf_counter() - t0)

    if ext == "kmz":
        from .textish_kmz import extract_kmz_text

        text = extract_kmz_text(path, max_chars=max_chars)
        if not text:
            return None, "No extractable KMZ/KML text", None
        return text, "kmz", TextExtractMeta(method="kmz", extract_time_s=time.perf_counter() - t0)

    return None, "Unsupported text type", None

