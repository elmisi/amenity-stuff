from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


def open_with_default_app(path: Path) -> None:
    """Open a file with the OS default application (silent failure by design)."""
    try:
        if sys.platform.startswith("linux"):
            subprocess.Popen(
                ["xdg-open", str(path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        elif sys.platform == "darwin":
            subprocess.Popen(
                ["open", str(path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        elif os.name == "nt":
            os.startfile(str(path))  # type: ignore[attr-defined]
    except Exception:
        return

