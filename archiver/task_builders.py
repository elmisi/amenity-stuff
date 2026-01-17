from __future__ import annotations

from typing import TYPE_CHECKING

from .analyzer import AnalysisConfig
from .model_selection import pick_model_candidates

if TYPE_CHECKING:  # pragma: no cover
    from .discovery import DiscoveryResult
    from .settings import Settings
    from .taxonomy import Taxonomy


def build_analysis_config(*, settings: "Settings", discovery: "DiscoveryResult | None", taxonomy: "Taxonomy") -> AnalysisConfig:
    text_models, vision_models = pick_model_candidates(discovery)
    # Facts extraction is latency-sensitive: prefer a smaller model when available.
    if (not settings.facts_model) or settings.facts_model == "auto":
        prefer_fast = (
            "llama3.2:3b-instruct",
            "phi3:mini",
            "phi3:medium",
            "mistral:7b-instruct",
            "qwen2.5:7b-instruct",
        )
        ordered = [m for m in prefer_fast if m in text_models] + [m for m in text_models if m not in prefer_fast]
        text_models = tuple(ordered)
    if settings.facts_model and settings.facts_model != "auto":
        text_models = (settings.facts_model, *tuple(m for m in text_models if m != settings.facts_model))
    if settings.vision_model and settings.vision_model != "auto":
        vision_models = (settings.vision_model, *tuple(m for m in vision_models if m != settings.vision_model))

    return AnalysisConfig(
        output_language=settings.output_language,
        taxonomy=taxonomy,
        text_models=text_models,
        vision_models=vision_models,
        filename_separator=settings.filename_separator,
        ocr_mode=settings.ocr_mode,
    )
