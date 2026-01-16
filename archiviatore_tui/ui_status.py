from __future__ import annotations

from importlib import metadata
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from .discovery import DiscoveryResult
    from .settings import Settings


def app_title(*, provider_line: str = "") -> str:
    try:
        ver = metadata.version("amenity-stuff")
    except Exception:
        ver = "dev"
    base = f"amenity-stuff v{ver}"
    if provider_line:
        return f"{base} • {provider_line}"
    return base


def status_cell(status: str) -> str:
    # Backward-compatible mapping for older cache entries / statuses.
    status = {
        "analysis": "scanning",
        "extracting": "scanning",
        "extracted": "scanned",
        "ready": "classified",
        "normalizing": "classifying",
        "normalized": "classified",
    }.get(status, status)
    marker = {
        "pending": "·",
        "scanning": "…",
        "scanned": "✓",
        "classifying": "≈",
        "classified": "★",
        "skipped": "↷",
        "error": "×",
    }.get(status, "?")
    short = {
        "pending": "pend",
        "scanning": "scan",
        "scanned": "scan",
        "classifying": "cls",
        "classified": "done",
        "skipped": "skip",
        "error": "err",
    }.get(status, status[:4])
    return f"{marker} {short}"


def provider_summary(discovery: "DiscoveryResult | None", settings: "Settings", *, model_picker) -> str:
    if not discovery:
        return ""
    provider = None
    models: tuple[str, ...] = ()
    for p in discovery.providers:
        if p.name == "ollama":
            provider = "ollama" if p.available else "ollama(missing)"
            models = p.models
            break
    if not provider:
        return ""

    text_models, vision_models = model_picker(discovery)
    if settings.text_model and settings.text_model != "auto":
        text = settings.text_model
    else:
        text = text_models[0] if text_models else "auto"
    if settings.vision_model and settings.vision_model != "auto":
        vision = settings.vision_model
    else:
        vision = vision_models[0] if vision_models else "auto"

    models_count = f"{len(models)} models" if models else "no models"
    return f"{provider} • {models_count} • text={text} • vision={vision}"


def notes_line(
    *,
    scan_items_total: int,
    pending: int,
    scanning: int,
    scanned: int,
    classifying: int,
    classified: int,
    skipped: int,
    error: int,
    task_state: str,
) -> str:
    bits = [
        f"files: {scan_items_total}" if scan_items_total else "files: 0",
        f"pending: {pending}",
        f"scanning: {scanning}",
        f"scanned: {scanned}",
        f"classifying: {classifying}",
        f"classified: {classified}",
        f"skipped: {skipped}",
        f"error: {error}",
        f"task: {task_state}",
    ]
    return " • ".join([b for b in bits if b])
