from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from .utils_text import read_text_file


def extract_svg_text(path: Path, *, max_chars: int) -> Optional[str]:
    raw = read_text_file(path, max_chars=max_chars * 4)
    if not raw:
        return None
    try:
        from xml.etree import ElementTree as ET

        root = ET.fromstring(raw)
    except Exception:
        text = re.sub(r"<[^>]+>", " ", raw)
        text = " ".join(text.split())
        return text[:max_chars] if text else None

    parts: list[str] = []

    def add(value: str) -> None:
        v = " ".join((value or "").strip().split())
        if not v:
            return
        parts.append(v)

    for tag in ["title", "desc", "text"]:
        for el in root.findall(f".//{{*}}{tag}"):
            if el.text:
                add(el.text)
            if sum(len(p) for p in parts) >= max_chars:
                break

    if sum(len(p) for p in parts) < max_chars:
        for el in root.iter():
            if el.text and el.tag and not str(el.tag).endswith(("style", "script")):
                add(el.text)
            if sum(len(p) for p in parts) >= max_chars:
                break

    out = "\n".join(parts).strip()
    return out[:max_chars] if out else None

