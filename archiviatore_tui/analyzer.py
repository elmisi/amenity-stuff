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


def _is_year(value: str) -> bool:
    return bool(re.fullmatch(r"(19\d{2}|20\d{2})", value))


def _extract_year_hint_from_path(path: Path) -> Optional[str]:
    """Best-effort year extraction from filename/path.

    Examples it should catch:
    - 2021/...
    - ..._12.2019_...
    - 17.03.2020
    - 20200105_101112
    """

    text = " ".join([*path.parts, path.name])

    # Prefer a directory or token that is exactly a year.
    for part in reversed(path.parts):
        if _is_year(part):
            return part

    # Month-year like mm.yyyy or mm-yyyy or mm_yyyy.
    m = re.search(r"(?<!\d)\d{1,2}[._-](19\d{2}|20\d{2})(?!\d)", text)
    if m:
        return m.group(1)

    # Dates like dd.mm.yyyy or dd-mm-yyyy or dd_mm_yyyy.
    m = re.search(r"(?<!\d)\d{1,2}[._-]\d{1,2}[._-](19\d{2}|20\d{2})(?!\d)", text)
    if m:
        return m.group(1)

    # ISO date yyyy-mm-dd.
    m = re.search(r"(?<!\d)(19\d{2}|20\d{2})-\d{1,2}-\d{1,2}(?!\d)", text)
    if m:
        return m.group(1)

    # Timestamps like yyyymmdd or yyyymmdd_hhmmss.
    m = re.search(r"(?<!\d)(19\d{2}|20\d{2})(0[1-9]|1[0-2])([0-2]\d|3[01])(?!\d)", text)
    if m:
        return m.group(1)

    # Last resort: any year occurrence.
    m = re.search(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)", text)
    if m:
        return m.group(1)

    return None


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
    reference_year_hint: Optional[str],
) -> AnalysisResult:
    year_hint_line = f"reference_year_hint: {reference_year_hint}" if reference_year_hint else "reference_year_hint: null"
    prompt = f"""
You are a document archiving assistant. Reply with VALID JSON only (no extra text).

Goal:
- understand what the document is about
- choose a category from: {list(_ALLOWED_CATEGORIES)}
- estimate the reference year (reference_year) the document refers to
- estimate the production year (production_year) (if unknown: null)
- propose a descriptive file name (proposed_name) WITHOUT category/year unless necessary
- if unsure, set low confidence and provide skip_reason
- if reference_year_hint is present, use it ONLY if the content doesn't clearly contradict it

Input:
filename: {filename}
mtime_iso: {mtime_iso}
{year_hint_line}
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
    if isinstance(reference_year, str) and not _is_year(reference_year.strip()):
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

    # If the model didn't provide a usable year, fall back to filename/path hint.
    hint = reference_year_hint if (reference_year_hint and _is_year(reference_year_hint)) else None
    if (not reference_year) and hint:
        reference_year = hint

    # If both exist but differ, trust content only when confidence is sufficiently high.
    if reference_year and hint and reference_year != hint:
        if conf is None or conf < 0.6:
            reference_year = hint

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

    year_hint = _extract_year_hint_from_path(path)

    if item.kind == "pdf":
        text, reason = extract_pdf_text_with_reason(path)
        if not text:
            return AnalysisResult(status="skipped", reason=reason or "No extractable PDF text")
        return _classify_from_text(
            model=config.text_model,
            content=text,
            filename=path.name,
            mtime_iso=item.mtime_iso,
            base_url=config.ollama_base_url,
            reference_year_hint=year_hint,
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
            reference_year_hint=year_hint,
        )

    return AnalysisResult(status="skipped", reason="Tipo non supportato")
