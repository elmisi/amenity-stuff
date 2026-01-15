from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class AppConfig:
    last_archive_root: Optional[str] = None
    last_source_root: Optional[str] = None
    output_language: str = "auto"  # auto | it | en
    taxonomy_lines: tuple[str, ...] = ()


def _config_path() -> Path:
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "amenity-stuff" / "config.json"


def load_config() -> AppConfig:
    path = _config_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return AppConfig()
    if not isinstance(data, dict):
        return AppConfig()
    last_archive = data.get("last_archive_root")
    last_source = data.get("last_source_root")
    output_language = data.get("output_language")
    taxonomy_lines = data.get("taxonomy_lines")

    kwargs: dict[str, object] = {}
    if isinstance(last_archive, str) and last_archive.strip():
        kwargs["last_archive_root"] = last_archive.strip()
    if isinstance(last_source, str) and last_source.strip():
        kwargs["last_source_root"] = last_source.strip()
    if isinstance(output_language, str) and output_language.strip():
        lang = output_language.strip().lower()
        if lang in {"auto", "it", "en"}:
            kwargs["output_language"] = lang
    if isinstance(taxonomy_lines, list):
        lines: list[str] = []
        for v in taxonomy_lines:
            if isinstance(v, str) and v.strip():
                lines.append(v.rstrip("\n"))
        kwargs["taxonomy_lines"] = tuple(lines)
    return AppConfig(**kwargs)  # type: ignore[arg-type]


def save_config(config: AppConfig) -> None:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(config.__dict__, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)
