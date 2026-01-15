from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .ollama_client import generate, generate_with_image_file
from .pdf_extract import extract_pdf_text_with_reason
from .scanner import ScanItem


_ALLOWED_CATEGORIES = (
    "finance",
    "legal",
    "work",
    "personal",
    "medical",
    "education",
    "media",
    "technical",
    "unknown",
)


@dataclass(frozen=True)
class AnalysisConfig:
    text_model: str = "qwen2.5:7b-instruct"
    vision_model: str = "moondream:latest"
    ollama_base_url: str = "http://localhost:11434"


@dataclass(frozen=True)
class AnalysisResult:
    status: str
    reason: Optional[str] = None
    category: Optional[str] = None
    reference_year: Optional[str] = None
    proposed_name: Optional[str] = None
    summary: Optional[str] = None
    confidence: Optional[float] = None


def _extract_json(text: str) -> Optional[dict]:
    text = text.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except Exception:
        return None


def _sanitize_name(name: str) -> str:
    name = name.strip()
    name = re.sub(r"[\\/:*?\"<>|]", " ", name)
    name = re.sub(r"\s+", " ", name)
    return name[:120].strip()


def _classify_from_text(
    *,
    model: str,
    content: str,
    filename: str,
    mtime_iso: str,
    base_url: str,
) -> AnalysisResult:
    prompt = f"""
You are a document archiving assistant. Reply with VALID JSON only (no extra text).

Goal:
- understand what the document is about
- choose a category from: {list(_ALLOWED_CATEGORIES)}
- estimate the reference year (reference_year) the document refers to
- estimate the production year (production_year) (if unknown: null)
- propose a descriptive file name (proposed_name) WITHOUT category/year unless necessary
- if unsure, set low confidence and provide skip_reason

Input:
filename: {filename}
mtime_iso: {mtime_iso}
content:
\"\"\"{content}\"\"\"

Output JSON schema:
{{
  "summary": string,
  "category": string,
  "reference_year": string|null,
  "production_year": string|null,
  "proposed_name": string,
  "confidence": number,
  "skip_reason": string|null
}}
"""
    try:
        gen = generate(model=model, prompt=prompt, base_url=base_url, timeout_s=180.0)
    except Exception as exc:  # noqa: BLE001 (MVP: best-effort)
        return AnalysisResult(status="error", reason=f"Ollama errore: {type(exc).__name__}")
    if gen.error:
        return AnalysisResult(status="error", reason=f"Ollama errore: {gen.error}")
    out = gen.response
    data = _extract_json(out)
    if not isinstance(data, dict):
        return AnalysisResult(status="skipped", reason="Unparseable output (JSON)")

    skip_reason = data.get("skip_reason")
    if isinstance(skip_reason, str) and skip_reason.strip():
        return AnalysisResult(status="skipped", reason=skip_reason.strip())

    category = data.get("category")
    if not isinstance(category, str) or category not in _ALLOWED_CATEGORIES:
        category = "unknown"

    reference_year = data.get("reference_year")
    if reference_year is not None and not isinstance(reference_year, str):
        reference_year = None

    proposed_name = data.get("proposed_name")
    if not isinstance(proposed_name, str) or not proposed_name.strip():
        return AnalysisResult(status="skipped", reason="Missing proposed name")

    summary = data.get("summary")
    if not isinstance(summary, str):
        summary = None

    confidence = data.get("confidence")
    if isinstance(confidence, (int, float)):
        conf = float(confidence)
    else:
        conf = None

    if conf is not None and conf < 0.35:
        return AnalysisResult(status="skipped", reason="Low confidence", confidence=conf)

    return AnalysisResult(
        status="ready",
        category=category,
        reference_year=reference_year,
        proposed_name=_sanitize_name(proposed_name),
        summary=(summary or "").strip()[:200] or None,
        confidence=conf,
    )


def analyze_item(item: ScanItem, *, config: AnalysisConfig) -> AnalysisResult:
    path = item.path
    if item.status != "pending":
        return AnalysisResult(status=item.status, reason=item.reason)

    if item.kind == "pdf":
        text, reason = extract_pdf_text_with_reason(path)
        if not text:
            return AnalysisResult(status="skipped", reason=reason or "PDF senza testo estraibile")
        return _classify_from_text(
            model=config.text_model,
            content=text,
            filename=path.name,
            mtime_iso=item.mtime_iso,
            base_url=config.ollama_base_url,
        )

    if item.kind == "image":
        caption_prompt = "Describe this image in one sentence."
        try:
            cap = generate_with_image_file(
                model=config.vision_model,
                prompt=caption_prompt,
                image_path=str(path),
                base_url=config.ollama_base_url,
                timeout_s=180.0,
            )
        except Exception as exc:  # noqa: BLE001 (MVP: best-effort)
            return AnalysisResult(status="error", reason=f"Ollama vision errore: {type(exc).__name__}")
        if cap.error:
            return AnalysisResult(status="error", reason=f"Ollama vision errore: {cap.error}")
        caption = cap.response.strip()
        if not caption:
            return AnalysisResult(status="skipped", reason="Caption vuota")
        return _classify_from_text(
            model=config.text_model,
            content=f"IMAGE_CAPTION: {caption}",
            filename=path.name,
            mtime_iso=item.mtime_iso,
            base_url=config.ollama_base_url,
        )

    return AnalysisResult(status="skipped", reason="Tipo non supportato")
