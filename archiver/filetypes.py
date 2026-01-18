from __future__ import annotations

from pathlib import Path
from typing import Optional


KIND_BY_EXTENSION: dict[str, str] = {
    # Documents
    "pdf": "pdf",
    # Images
    "jpg": "image",
    "jpeg": "image",
    "png": "image",
    # Office
    "doc": "doc",
    "docx": "docx",
    "odt": "odt",
    "xls": "xls",
    "xlsx": "xlsx",
    # Text-ish
    "json": "json",
    "md": "md",
    "txt": "txt",
    "rtf": "rtf",
    "svg": "svg",
    "kmz": "kmz",
}


def infer_kind(path: Path) -> Optional[str]:
    ext = path.suffix.lower().lstrip(".")
    if not ext:
        return None
    return KIND_BY_EXTENSION.get(ext)

