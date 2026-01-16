from __future__ import annotations

import json
import re
from typing import Optional


def extract_json_dict(text: str) -> Optional[dict]:
    """Best-effort extraction of a JSON object (dict) from model output."""
    raw = (text or "").strip()
    if not raw:
        return None
    try:
        val = json.loads(raw)
        return val if isinstance(val, dict) else None
    except Exception:
        pass
    match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
    if not match:
        return None
    try:
        val = json.loads(match.group(0))
        return val if isinstance(val, dict) else None
    except Exception:
        return None


def extract_json_any(text: str) -> Optional[object]:
    """Best-effort extraction of any JSON value from model output.

    Prefers lists first, then dicts, since batch operations often return JSON lists.
    """
    raw = (text or "").strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        pass
    match = re.search(r"\[.*\]", raw, flags=re.DOTALL)
    if not match:
        match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except Exception:
        return None

