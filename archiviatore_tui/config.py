from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class AppConfig:
    last_archive_root: Optional[str] = None


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
    last = data.get("last_archive_root")
    if isinstance(last, str) and last.strip():
        return AppConfig(last_archive_root=last.strip())
    return AppConfig()


def save_config(config: AppConfig) -> None:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(config.__dict__, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)

