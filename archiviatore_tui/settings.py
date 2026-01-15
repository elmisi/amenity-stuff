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
    localai_base_url: Optional[str] = None
    recursive: bool = True
    include_extensions: tuple[str, ...] = ("pdf", "jpg", "jpeg")
    exclude_dirnames: tuple[str, ...] = (".git", ".venv", "ARCHIVIO")
    output_language: str = "auto"  # auto | it | en
    taxonomy_lines: tuple[str, ...] = DEFAULT_TAXONOMY_LINES
