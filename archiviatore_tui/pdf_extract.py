from __future__ import annotations

from pathlib import Path
from typing import Optional


def extract_pdf_text(path: Path, *, max_chars: int = 15000) -> Optional[str]:
    try:
        from pypdf import PdfReader
    except Exception:
        return None

    try:
        reader = PdfReader(str(path))
    except Exception:
        return None

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
        return None
    return joined[:max_chars]

