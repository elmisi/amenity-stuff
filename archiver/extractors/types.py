from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TextExtractMeta:
    method: str
    extract_time_s: float

