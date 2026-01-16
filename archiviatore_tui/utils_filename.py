from __future__ import annotations

import re


def sanitize_name(name: str, *, max_len: int = 180) -> str:
    text = (name or "").strip()
    text = re.sub(r"[\\/:*?\"<>|]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text[:max_len].strip()

