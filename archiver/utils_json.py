from __future__ import annotations

import json
import re
from typing import Optional


_FENCE_RE = re.compile(r"```(?:json)?\\s*(.*?)\\s*```", flags=re.DOTALL | re.IGNORECASE)


def _strip_code_fences(text: str) -> str:
    raw = (text or "").strip()
    if not raw:
        return ""
    m = _FENCE_RE.search(raw)
    if m:
        return m.group(1).strip()
    return raw


def extract_json_dict(text: str) -> Optional[dict]:
    """Best-effort extraction of a JSON object (dict) from model output."""
    raw = _strip_code_fences(text)
    if not raw:
        return None
    decoder = json.JSONDecoder()
    try:
        val = json.loads(raw)
        return val if isinstance(val, dict) else None
    except Exception:
        pass
    starts = [m.start() for m in re.finditer(r"\{", raw)]
    for start in starts:
        try:
            val, _end = decoder.raw_decode(raw[start:])
        except Exception:
            continue
        if isinstance(val, dict):
            return val
    return None


def extract_json_any(text: str) -> Optional[object]:
    """Best-effort extraction of any JSON value from model output.

    Prefers lists first, then dicts, since batch operations often return JSON lists.
    """
    raw = _strip_code_fences(text)
    if not raw:
        return None
    decoder = json.JSONDecoder()
    try:
        return json.loads(raw)
    except Exception:
        pass
    starts = [m.start() for m in re.finditer(r"[\\[{]", raw)]
    for start in starts:
        try:
            val, _end = decoder.raw_decode(raw[start:])
        except Exception:
            continue
        if val is not None:
            return val
    return None
