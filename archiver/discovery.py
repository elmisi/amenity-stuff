from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import os
from pathlib import Path
import shutil
import subprocess


@dataclass(frozen=True)
class ProviderInfo:
    name: str
    available: bool
    details: str
    models: tuple[str, ...] = ()
    command: Optional[str] = None


@dataclass(frozen=True)
class DiscoveryResult:
    providers: tuple[ProviderInfo, ...]
    chosen_text: Optional[str] = None
    chosen_vision: Optional[str] = None
    notes: tuple[str, ...] = ()


def _run(cmd: list[str], timeout_s: float = 2.5) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        text=True,
        capture_output=True,
        timeout=timeout_s,
        check=False,
    )


def _discover_ollama() -> ProviderInfo:
    path = shutil.which("ollama")
    if not path:
        return ProviderInfo(name="ollama", available=False, details="Not found in PATH")

    proc = _run(["ollama", "list"], timeout_s=3.5)
    if proc.returncode != 0:
        details = proc.stderr.strip() or "Comando presente ma non risponde"
        return ProviderInfo(name="ollama", available=False, details=details, command=path)

    lines = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
    models: list[str] = []
    for ln in lines[1:]:
        model = ln.split()[0].strip()
        if model:
            models.append(model)

    details = "OK"
    if not models:
        details = "OK (no models listed)"

    return ProviderInfo(
        name="ollama",
        available=True,
        details=details,
        models=tuple(models),
        command=path,
    )

def discover_providers() -> DiscoveryResult:
    providers: list[ProviderInfo] = []
    notes: list[str] = []

    ollama = _discover_ollama()
    providers.append(ollama)

    # Reserved for future local model discovery (GGUF etc). Keep notes minimal in the main UI.

    chosen_text = None
    chosen_vision = None
    if ollama.available and ollama.models:
        chosen_text = "ollama"
    elif ollama.available and not ollama.models:
        notes.append("Ollama is installed but has no models: run 'ollama pull <model>'.")

    return DiscoveryResult(
        providers=tuple(providers),
        chosen_text=chosen_text,
        chosen_vision=chosen_vision,
        notes=tuple(notes),
    )
