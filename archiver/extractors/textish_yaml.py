"""YAML text extraction.

Extracts content from YAML files. Since YAML is already human-readable,
this mainly normalizes the content and extracts top-level keys.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional


def extract_yaml_text(path: Path, *, max_chars: int = 15000) -> Optional[str]:
    """Extract text content from a YAML file.

    Since YAML is already human-readable, we:
    - Extract top-level keys as summary
    - Include the raw content (truncated)
    - Remove excessive blank lines
    """
    try:
        raw = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None

    if not raw.strip():
        return None

    lines: list[str] = []

    # Extract top-level keys (lines that start with a word followed by colon)
    top_keys: list[str] = []
    for line in raw.splitlines():
        # Top-level key: no leading whitespace, word followed by colon
        match = re.match(r"^([a-zA-Z_][a-zA-Z0-9_-]*)\s*:", line)
        if match:
            top_keys.append(match.group(1))

    if top_keys:
        lines.append(f"YAML keys ({len(top_keys)}): {', '.join(top_keys[:20])}")
        if len(top_keys) > 20:
            lines.append(f"  ... and {len(top_keys) - 20} more keys")
        lines.append("")

    # Normalize content: remove excessive blank lines
    content_lines = raw.splitlines()
    normalized: list[str] = []
    blank_count = 0
    for line in content_lines:
        if not line.strip():
            blank_count += 1
            if blank_count <= 1:
                normalized.append("")
        else:
            blank_count = 0
            normalized.append(line)

    lines.append("Content:")
    lines.extend(normalized)

    text = "\n".join(lines)
    return text[:max_chars] if len(text) > max_chars else text
