"""HTML text extraction.

Extracts visible text content from HTML files.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional


def extract_html_text(path: Path, *, max_chars: int = 15000) -> Optional[str]:
    """Extract visible text from an HTML file.

    Removes:
    - Script and style blocks
    - HTML tags
    - Excessive whitespace

    Preserves:
    - Title (if present)
    - Visible text content
    """
    try:
        # Try UTF-8 first, then latin-1 as fallback
        try:
            raw = path.read_text(encoding="utf-8", errors="ignore")
        except UnicodeDecodeError:
            raw = path.read_text(encoding="latin-1", errors="ignore")
    except Exception:
        return None

    if not raw.strip():
        return None

    # Extract title
    title_match = re.search(r"<title[^>]*>(.*?)</title>", raw, re.IGNORECASE | re.DOTALL)
    title = title_match.group(1).strip() if title_match else None

    # Remove script and style blocks
    text = re.sub(r"<script[^>]*>.*?</script>", " ", raw, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)

    # Remove HTML comments
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.DOTALL)

    # Remove all remaining tags
    text = re.sub(r"<[^>]+>", " ", text)

    # Decode common HTML entities
    entities = {
        "&nbsp;": " ",
        "&amp;": "&",
        "&lt;": "<",
        "&gt;": ">",
        "&quot;": '"',
        "&apos;": "'",
        "&#39;": "'",
        "&euro;": "€",
        "&copy;": "©",
        "&reg;": "®",
    }
    for entity, char in entities.items():
        text = text.replace(entity, char)

    # Decode numeric entities
    text = re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))), text)
    text = re.sub(r"&#x([0-9a-fA-F]+);", lambda m: chr(int(m.group(1), 16)), text)

    # Normalize whitespace
    text = re.sub(r"\s+", " ", text).strip()

    if not text:
        return None

    # Prepend title if present
    if title and title not in text[:200]:
        text = f"Title: {title}\n\n{text}"

    return text[:max_chars] if len(text) > max_chars else text
