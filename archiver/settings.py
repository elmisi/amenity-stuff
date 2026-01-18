from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .taxonomy import DEFAULT_TAXONOMY_LINES


@dataclass(frozen=True)
class Settings:
    source_root: Path
    archive_root: Path
    recursive: bool = True
    include_extensions: tuple[str, ...] = (
        "pdf",
        "jpg",
        "jpeg",
        "png",
        "doc",
        "docx",
        "odt",
        "xls",
        "xlsx",
        "json",
        "md",
        "txt",
        "rtf",
        "svg",
        "kmz",
    )
    exclude_dirnames: tuple[str, ...] = (".git", ".venv", ".amenity-stuff", "ARCHIVE")
    output_language: str = "auto"  # auto | it | en
    taxonomy_lines: tuple[str, ...] = DEFAULT_TAXONOMY_LINES
    facts_model: str = "auto"
    classify_model: str = "auto"
    vision_model: str = "auto"
    filename_separator: str = "space"  # space | underscore | dash
    ocr_mode: str = "balanced"  # fast | balanced | high
    undated_folder_name: str = "undated"
    skip_initial_setup: bool = False
