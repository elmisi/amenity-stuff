from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Optional


def read_text_file(path: Path, *, max_chars: int) -> Optional[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        try:
            data = path.read_bytes()
        except Exception:
            return None
        text = data.decode("utf-8", errors="ignore")
    text = text.strip()
    return text[:max_chars] if text else None


def flatten_json_text(raw: str, *, max_chars: int) -> Optional[str]:
    try:
        data = json.loads(raw)
    except Exception:
        return None

    lines: list[str] = []
    budget_items = 1200

    def emit(path_parts: Iterable[str], value: object) -> None:
        if len(lines) >= budget_items:
            return
        key = ".".join(path_parts)
        if isinstance(value, bool):
            v = "true" if value else "false"
        else:
            v = str(value)
        v = " ".join(v.split())
        if not v:
            return
        if len(v) > 400:
            v = v[:400] + "…"
        if key:
            lines.append(f"{key}: {v}")
        else:
            lines.append(v)

    def walk(node: object, path_parts: list[str]) -> None:
        if len(lines) >= budget_items:
            return
        if node is None:
            return
        if isinstance(node, (str, int, float, bool)):
            emit(path_parts, node)
            return
        if isinstance(node, dict):
            for k, v in node.items():
                if len(lines) >= budget_items:
                    break
                if not isinstance(k, str):
                    continue
                walk(v, [*path_parts, k])
            return
        if isinstance(node, list):
            for idx, v in enumerate(node[:200]):
                if len(lines) >= budget_items:
                    break
                walk(v, [*path_parts, str(idx)])
            return

    walk(data, [])
    out = "\n".join(lines).strip()
    if not out:
        return None
    return out[:max_chars]

