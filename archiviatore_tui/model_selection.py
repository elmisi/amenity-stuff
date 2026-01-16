from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from .discovery import DiscoveryResult


def pick_model_candidates(discovery: "DiscoveryResult | None") -> tuple[tuple[str, ...], tuple[str, ...]]:
    models: list[str] = []
    if discovery:
        for p in discovery.providers:
            if p.name == "ollama" and p.available and p.models:
                models = list(p.models)
                break

    if not models:
        return (), ()

    known_text_prefer = [
        "qwen2.5:7b-instruct",
        "qwen2.5:14b-instruct",
        "llama3.1:8b-instruct",
        "llama3.2:3b-instruct",
        "mistral:7b-instruct",
        "gemma2:9b-instruct",
        "phi3:medium",
    ]
    text_candidates: list[str] = [m for m in known_text_prefer if m in models]
    for m in models:
        ml = m.lower()
        if m in text_candidates:
            continue
        if any(v in ml for v in ("vision", "llava", "moondream", "minicpm", "bakllava")):
            continue
        if "instruct" in ml or "chat" in ml:
            text_candidates.append(m)

    known_vision_prefer = [
        "moondream:latest",
        "llama3.2-vision:latest",
        "llava:latest",
        "bakllava:latest",
        "minicpm-v:latest",
    ]
    vision_candidates: list[str] = [m for m in known_vision_prefer if m in models]
    for m in models:
        ml = m.lower()
        if m in vision_candidates:
            continue
        if any(v in ml for v in ("vision", "llava", "moondream", "minicpm", "bakllava")):
            vision_candidates.append(m)

    return tuple(text_candidates[:4]), tuple(vision_candidates[:3])

