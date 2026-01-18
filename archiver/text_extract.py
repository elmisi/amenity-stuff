from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple

from .extractors.textish import extract_textish_with_meta
from .extractors.types import TextExtractMeta


def extract_text_file_with_meta(
    path: Path,
    *,
    max_chars: int = 15000,
) -> Tuple[Optional[str], Optional[str], Optional[TextExtractMeta]]:
    """Backward-compatible wrapper.

    The real implementation lives in `archiver.extractors`.
    """
    return extract_textish_with_meta(path, max_chars=max_chars)

