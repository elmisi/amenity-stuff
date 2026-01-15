from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
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

    # Dates like dd-mm-yy / dd.mm.yy (2-digit year). Use a conservative pivot.
    m = re.search(r"(?<!\d)\d{1,2}[._-]\d{1,2}[._-](\d{2})(?!\d)", text)
    if m:
        yy = int(m.group(1))
        # 00-69 -> 2000-2069, 70-99 -> 1970-1999
        return str(2000 + yy) if yy <= 69 else str(1900 + yy)

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


def _extract_year_hint_from_text(text: str) -> Optional[str]:
    # Keep it cheap and stable: first part of the document only.
    sample = text[:8000]
    years = re.findall(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)", sample)
    if not years:
        return None
    counts: dict[str, int] = {}
    for y in years:
        counts[y] = counts.get(y, 0) + 1
    # Prefer most frequent; tie-breaker: latest year.
    best = sorted(counts.items(), key=lambda kv: (kv[1], kv[0]))[-1][0]
    return best


def _category_hint_from_signals(*, path: Path, text: Optional[str]) -> Optional[str]:
    hay = f"{path.as_posix()} {path.name}".lower()
    sample = (text or "")[:8000].lower()
    hay = hay + " " + sample

    # Energy / utilities invoices and bills -> finance.
    finance_signals = [
        "bolletta",
        "fattura",
        "riepilogo fatture",
        "periodo riferimento",
        "protocollo",
        "gas naturale",
        "energia",
        "energia elettrica",
        "fornitura",
        "consumo",
        "kwh",
        "mc",
        "codice fiscale",
        "p.iva",
        "dolomiti energia",
    ]
    if any(s in hay for s in finance_signals):
        return "finance"

    # Technical docs / manuals -> technical.
    technical_signals = ["manual", "datasheet", "specification", "technical", "guide", "sdk", "api"]
    if any(s in hay for s in technical_signals):
        return "technical"

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
    return name[:180].strip()


def _ensure_extension(proposed_name: str, original_filename: str) -> str:
    original_ext = Path(original_filename).suffix
    if not original_ext:
        return proposed_name
    if proposed_name.lower().endswith(original_ext.lower()):
        return proposed_name
    return proposed_name.rstrip(".") + original_ext


_STOPWORDS = {
    # EN
    "the",
    "a",
    "an",
    "and",
    "or",
    "of",
    "to",
    "for",
    "in",
    "on",
    "with",
    "by",
    "from",
    # IT
    "il",
    "lo",
    "la",
    "i",
    "gli",
    "le",
    "un",
    "uno",
    "una",
    "e",
    "o",
    "di",
    "da",
    "del",
    "della",
    "dei",
    "delle",
    "al",
    "alla",
    "alle",
    "agli",
    "per",
    "con",
    "su",
    "nel",
    "nella",
    "nelle",
    "all",
}


def _fallback_name_from_summary(*, summary: Optional[str], original_filename: str) -> str:
    stem = Path(original_filename).stem
    ext = Path(original_filename).suffix
    if not summary:
        return _sanitize_name(stem) + ext

    words = re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9]+", summary)
    tokens: list[str] = []
    for w in words:
        lower = w.lower()
        if lower in _STOPWORDS:
            continue
        if re.fullmatch(r"(19\d{2}|20\d{2})", w):
            continue
        if len(w) <= 2:
            continue
        tokens.append(w)
        if len(tokens) >= 10:
            break
    if not tokens:
        return _sanitize_name(stem) + ext
    name = "_".join(tokens)
    return _sanitize_name(name) + ext


def _classify_from_text(
    *,
    model: str,
    content: str,
    filename: str,
    mtime_iso: str,
    base_url: str,
    reference_year_hint: Optional[str],
    category_hint: Optional[str],
) -> AnalysisResult:
    year_hint_line = f"reference_year_hint: {reference_year_hint}" if reference_year_hint else "reference_year_hint: null"
    category_hint_line = f"category_hint: {category_hint}" if category_hint else "category_hint: null"
    prompt = f"""
You are a document archiving assistant. Reply with VALID JSON only (no extra text).

Goal:
- understand what the document is about
- choose a category from: {list(_ALLOWED_CATEGORIES)}
- if category_hint is present, you may use it unless the content clearly indicates a different category
- estimate the reference year (reference_year) the document refers to
- estimate the production year (production_year) (if unknown: null)
- propose a meaningful, descriptive file name (proposed_name)
  - use 6-12 words when possible (not too short)
  - include key entities (company/person), document type, and month/period if present
  - do NOT include category/year unless there is no other useful info
  - keep it readable (avoid random IDs)
- if unsure, set low confidence and provide skip_reason
- if reference_year_hint is present, use it ONLY if the content doesn't clearly contradict it

Input:
filename: {filename}
mtime_iso: {mtime_iso}
{year_hint_line}
{category_hint_line}
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

    proposed_name = _ensure_extension(_sanitize_name(proposed_name), filename)

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

    # If the proposed name is too short / low-signal, derive one from summary.
    if len(Path(proposed_name).stem) < 12 or Path(proposed_name).stem.count("_") < 1:
        proposed_name = _fallback_name_from_summary(summary=summary, original_filename=filename)

    # If category is unknown, fall back to hint.
    if category == "unknown" and category_hint in _ALLOWED_CATEGORIES:
        category = category_hint

    # If the model didn't provide a usable year, fall back to filename/path hint.
    hint = reference_year_hint if (reference_year_hint and _is_year(reference_year_hint)) else None
    if (not reference_year) and hint:
        reference_year = hint

    # If still missing, allow using a year embedded in the proposed name.
    if not reference_year:
        year_from_name = _extract_year_hint_from_path(Path(proposed_name))
        if year_from_name and _is_year(year_from_name):
            reference_year = year_from_name

    # If both exist but differ, trust content only when confidence is sufficiently high.
    if reference_year and hint and reference_year != hint:
        if conf is None or conf < 0.6:
            reference_year = hint

    return AnalysisResult(
        status="ready",
        category=category,
        reference_year=reference_year,
        proposed_name=proposed_name,
        summary=(summary or "").strip()[:200] or None,
        confidence=conf,
    )


def analyze_item(item: ScanItem, *, config: AnalysisConfig) -> AnalysisResult:
    path = item.path
    if item.status != "pending":
        return AnalysisResult(status=item.status, reason=item.reason)

    filename_year_hint = _extract_year_hint_from_path(path)

    def skipped(reason: str) -> AnalysisResult:
        return AnalysisResult(
            status="skipped",
            reason=reason,
            category="unknown",
            reference_year=filename_year_hint,
            proposed_name=path.name,
        )

    def skipped_with_year(reason: str, year_hint: Optional[str]) -> AnalysisResult:
        return AnalysisResult(
            status="skipped",
            reason=reason,
            category="unknown",
            reference_year=year_hint,
            proposed_name=path.name,
        )

    if item.kind == "pdf":
        text, reason = extract_pdf_text_with_reason(path)
        if not text:
            return skipped(reason or "No extractable PDF text")
        content_year_hint = _extract_year_hint_from_text(text)
        effective_year_hint = filename_year_hint or content_year_hint
        category_hint = _category_hint_from_signals(path=path, text=text)
        res = _classify_from_text(
            model=config.text_model,
            content=text,
            filename=path.name,
            mtime_iso=item.mtime_iso,
            base_url=config.ollama_base_url,
            reference_year_hint=effective_year_hint,
            category_hint=category_hint,
        )
        if res.status == "skipped":
            return replace(
                res,
                category="unknown",
                reference_year=res.reference_year or effective_year_hint,
                proposed_name=path.name,
            )
        return res

    if item.kind == "image":
        effective_year_hint = filename_year_hint
        category_hint = _category_hint_from_signals(path=path, text=None)
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
            return skipped_with_year("Empty caption", effective_year_hint)
        res = _classify_from_text(
            model=config.text_model,
            content=f"IMAGE_CAPTION: {caption}",
            filename=path.name,
            mtime_iso=item.mtime_iso,
            base_url=config.ollama_base_url,
            reference_year_hint=effective_year_hint,
            category_hint=category_hint,
        )
        if res.status == "skipped":
            return replace(
                res,
                category="unknown",
                reference_year=res.reference_year or effective_year_hint,
                proposed_name=path.name,
            )
        return res

    return skipped_with_year("Unsupported file type", filename_year_hint)
