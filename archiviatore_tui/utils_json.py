from __future__ import annotations

import json
import re
from typing import Optional


def _scan_json_value(raw: str) -> Optional[object]:
    """Best-effort JSON value extractor from arbitrary text.

    Uses JSONDecoder.raw_decode to find the first valid JSON value (dict/list/etc).
    """
    text = (raw or "").strip()
    if not text:
        return None

    decoder = json.JSONDecoder()
    # Fast path: full string is JSON.
    try:
        return json.loads(text)
    except Exception:
        pass

    # Try to locate a JSON value start and decode from there.
    for m in re.finditer(r"[\{\[]", text):
        idx = m.start()
        try:
            val, _end = decoder.raw_decode(text[idx:])
        except Exception:
            continue
        return val
    return None


def extract_json_dict(text: str) -> Optional[dict]:
    """Best-effort extraction of a JSON object (dict) from model output."""
    val = _scan_json_value(text)
    return val if isinstance(val, dict) else None


def extract_json_any(text: str) -> Optional[object]:
    """Best-effort extraction of any JSON value from model output.

    Prefers lists first, then dicts, since batch operations often return JSON lists.
    """
    return _scan_json_value(text)
