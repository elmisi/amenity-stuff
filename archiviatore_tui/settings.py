from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class Settings:
    source_root: Path
    archive_root: Path
    max_files: int = 100
    localai_base_url: Optional[str] = None
    recursive: bool = True
    include_extensions: tuple[str, ...] = ("pdf", "jpg", "jpeg")
    exclude_dirnames: tuple[str, ...] = (".git", ".venv", "ARCHIVIO")

