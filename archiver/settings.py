from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .taxonomy import DEFAULT_TAXONOMY_LINES


@dataclass(frozen=True)
class Settings:
    source_root: Path
    archive_root: Path
    max_files: int = 100
    recursive: bool = True
    include_extensions: tuple[str, ...] = ("pdf", "jpg", "jpeg", "png")
    exclude_dirnames: tuple[str, ...] = (".git", ".venv", "ARCHIVE")
    output_language: str = "auto"  # auto | it | en
    taxonomy_lines: tuple[str, ...] = DEFAULT_TAXONOMY_LINES
    text_model: str = "auto"
    vision_model: str = "auto"
    filename_separator: str = "space"  # space | underscore | dash
    ocr_mode: str = "balanced"  # fast | balanced | high
    skip_initial_setup: bool = False
