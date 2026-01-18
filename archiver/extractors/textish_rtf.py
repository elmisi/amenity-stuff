from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from .utils_text import read_text_file


def extract_rtf_text(path: Path, *, max_chars: int) -> Optional[str]:
    if shutil.which("unrtf"):
        try:
            proc = subprocess.run(
                ["unrtf", "--text", str(path)],
                text=True,
                capture_output=True,
                timeout=30,
                check=False,
            )
        except Exception:
            proc = None
        if proc and proc.returncode == 0:
            text = (proc.stdout or "").strip()
            return text[:max_chars] if text else None

    raw = read_text_file(path, max_chars=max_chars * 6)
    if not raw:
        return None

    s = raw
    s = re.sub(r"\\'[0-9a-fA-F]{2}", " ", s)  # hex escapes
    s = re.sub(r"\\[a-zA-Z]+-?\d* ?", " ", s)  # control words
    s = s.replace("{", " ").replace("}", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s[:max_chars] if s else None

