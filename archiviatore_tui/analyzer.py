from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Optional

from .ollama_client import generate, generate_with_image_file
import time

from .pdf_extract import extract_pdf_text_with_meta
from .scanner import ScanItem
from .taxonomy import DEFAULT_TAXONOMY_LINES, Taxonomy, parse_taxonomy_lines, taxonomy_to_prompt_block
from .utils_filename import sanitize_name
from .utils_json import extract_json_dict

_DEFAULT_TAXONOMY, _ = parse_taxonomy_lines(DEFAULT_TAXONOMY_LINES)


@dataclass(frozen=True)
class AnalysisConfig:
    text_model: str = "qwen2.5:7b-instruct"
    vision_model: str = "moondream:latest"
    text_models: tuple[str, ...] = ()
    vision_models: tuple[str, ...] = ()
    ollama_base_url: str = "http://localhost:11434"
    output_language: str = "auto"  # auto | it | en
    taxonomy: Taxonomy = _DEFAULT_TAXONOMY
    filename_separator: str = "space"  # space | underscore | dash
    ocr_mode: str = "balanced"  # fast | balanced | high


@dataclass(frozen=True)
class AnalysisResult:
    status: str
    reason: Optional[str] = None
    category: Optional[str] = None
    reference_year: Optional[str] = None
    proposed_name: Optional[str] = None
    summary: Optional[str] = None
    confidence: Optional[float] = None
    model_used: Optional[str] = None
    summary_long: Optional[str] = None
    facts_json: Optional[str] = None
    extract_method: Optional[str] = None
    extract_time_s: Optional[float] = None
    llm_time_s: Optional[float] = None
    ocr_time_s: Optional[float] = None
    ocr_mode: Optional[str] = None


@dataclass(frozen=True)
class FactsResult:
    status: str  # scanned | skipped | error
    reason: Optional[str] = None
    summary_long: Optional[str] = None
    facts_json: Optional[str] = None
    confidence: Optional[float] = None
    extract_method: Optional[str] = None
    extract_time_s: Optional[float] = None
    llm_time_s: Optional[float] = None
    ocr_time_s: Optional[float] = None
    ocr_mode: Optional[str] = None
    model_used: Optional[str] = None


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
    return extract_json_dict(text)


def _sanitize_name(name: str) -> str:
    return sanitize_name(name)


def _name_separator(kind: str) -> str:
    return {"space": " ", "underscore": "_", "dash": "-"}.get(kind, " ")


_JOIN_BLOCKLIST = {
    "of",
    "the",
    "and",
    "or",
    "di",
    "da",
    "del",
    "della",
    "dei",
    "delle",
}


def _split_and_repair_tokens(stem: str) -> list[str]:
    """Split a filename stem into tokens and repair common OCR/encoding artifacts.

    Example artifact: "Mi_iti" -> ["Miiti"] (missing character, but keeps the word together)
    """

    raw = [t for t in re.split(r"[\s_\-]+", stem.strip()) if t]
    tokens: list[str] = []
    for t in raw:
        t2 = re.sub(r"[\\/:*?\"<>|]", " ", t).strip()
        if t2:
            tokens.append(t2)

    i = 0
    while i < len(tokens) - 1:
        a = tokens[i]
        b = tokens[i + 1]
        if a.isalpha() and b.isalpha() and b[:1].islower() and len(a) <= 3 and a.lower() not in _JOIN_BLOCKLIST:
            tokens[i] = a + b
            del tokens[i + 1]
            continue
        i += 1
    return tokens


def _normalize_separators(name: str, *, sep: str) -> str:
    desired = _name_separator(sep)
    stem = Path(name).stem
    ext = Path(name).suffix
    tokens = _split_and_repair_tokens(stem)
    if not tokens:
        return _sanitize_name(stem) + ext
    if desired == " ":
        return _sanitize_name(" ".join(tokens)) + ext
    return _sanitize_name(desired.join(tokens)) + ext


def _name_token_count(name: str) -> int:
    return len(re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9]+", Path(name).stem))


def _coerce_list(value) -> list[str]:
    if isinstance(value, list):
        out: list[str] = []
        for v in value:
            if isinstance(v, str) and v.strip():
                out.append(v.strip())
        return out
    return []


def _coerce_date_candidates(value) -> list[dict]:
    out: list[dict] = []
    if not isinstance(value, list):
        return out
    for v in value:
        if not isinstance(v, dict):
            continue
        year = v.get("year")
        if isinstance(year, str) and _is_year(year.strip()):
            typ = v.get("type")
            conf = v.get("confidence")
            out.append(
                {
                    "year": year.strip(),
                    "type": typ if isinstance(typ, str) and typ.strip() else "other",
                    "confidence": float(conf) if isinstance(conf, (int, float)) else None,
                }
            )
    return out


def _content_excerpt_for_llm(text: str, *, max_chars: int = 14000) -> str:
    """Keep within a predictable size while preserving high-signal regions.

    Strategy: if too long, keep head + tail (documents often contain totals/ids on the last part).
    """
    t = (text or "").strip()
    if len(t) <= max_chars:
        return t
    head = int(max_chars * 0.7)
    tail = max_chars - head
    return (t[:head].rstrip() + "\n\n…\n\n" + t[-tail:].lstrip()).strip()


_EVIDENCE_PATTERNS: tuple[re.Pattern[str], ...] = (
    # IT/EN generic fields
    re.compile(r"\b(oggetto|subject|scopo|finalit[aà]|purpose)\b\s*[:\-]", re.IGNORECASE),
    re.compile(r"\b(data|date|emissione|issue)\b\s*[:\-]", re.IGNORECASE),
    re.compile(r"\b(importo|totale|total|amount|eur|€)\b", re.IGNORECASE),
    re.compile(r"\b(codice|id|identificativo|protocollo|pratica|invoice)\b", re.IGNORECASE),
    re.compile(r"\b(ente|creditore|cliente|debitor[e]?|payer|payee)\b", re.IGNORECASE),
)


def _build_evidence_pack(text: str, *, max_chars: int = 3500, max_snippets: int = 6) -> tuple[str, list[dict]]:
    """Build a token-efficient evidence pack + audit snippets.

    The pack is a curated excerpt: head + tail + key lines around known patterns.
    """
    t = (text or "").strip()
    if not t:
        return "", []
    lines = [ln.strip() for ln in t.splitlines() if ln.strip()]

    # Collect candidate line indices that match patterns.
    idxs: list[int] = []
    for i, ln in enumerate(lines):
        if any(p.search(ln) for p in _EVIDENCE_PATTERNS):
            idxs.append(i)

    # Expand around hits (small context).
    picked: list[str] = []
    for i in idxs:
        for j in range(max(0, i - 1), min(len(lines), i + 2)):
            picked.append(lines[j])

    # De-duplicate preserving order and keep short.
    seen: set[str] = set()
    uniq: list[str] = []
    for ln in picked:
        key = ln.lower()
        if key in seen:
            continue
        seen.add(key)
        uniq.append(ln)
        if len(uniq) >= max_snippets:
            break

    evidence = [{"snippet": ln[:200]} for ln in uniq]

    # Build the evidence pack.
    # Important: if the document is already short, do NOT concatenate head+mid+tail (it would duplicate content).
    if len(t) <= max_chars:
        pack = t
    else:
        head = t[: int(max_chars * 0.45)].strip()
        tail = t[-int(max_chars * 0.25) :].strip()
        mid = "\n".join(uniq).strip()
        pack = "\n\n".join([p for p in [head, mid, tail] if p]).strip()
        pack = _content_excerpt_for_llm(pack, max_chars=max_chars)
    return pack, evidence


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
    # Generic / low-signal words often seen in LLM-generated names
    "this",
    "document",
    "doc",
    "file",
    "text",
    "image",
    "photo",
    "picture",
    "scan",
    "scanned",
    "documento",
    "immagine",
    "foto",
    "testo",
    "scansione",
}


_GENERIC_NAME_TOKENS = {
    "this",
    "document",
    "doc",
    "file",
    "text",
    "image",
    "photo",
    "picture",
    "scan",
    "scanned",
    "documento",
    "immagine",
    "foto",
    "testo",
    "scansione",
}


def _cleanup_generic_words_in_name(*, proposed_name: str, original_filename: str) -> str:
    """Remove generic words like 'this document' from model-proposed names.

    Keep meaningful document types (e.g. invoice, payslip) untouched.
    """

    original_ext = Path(original_filename).suffix
    ext = Path(proposed_name).suffix or original_ext
    stem = Path(proposed_name).stem
    tokens = _split_and_repair_tokens(stem)
    cleaned: list[str] = []
    for t in tokens:
        if not t:
            continue
        if t.lower() in _GENERIC_NAME_TOKENS:
            continue
        cleaned.append(t)
    if not cleaned:
        return _sanitize_name(Path(original_filename).stem) + ext
    return _sanitize_name(" ".join(cleaned)) + ext


def _fallback_name_from_summary(*, summary: Optional[str], original_filename: str, sep: str) -> str:
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
    name = _name_separator(sep).join(tokens)
    return _sanitize_name(name) + ext


_LEGAL_SUFFIXES_RE = re.compile(
    r"\b(s\.?p\.?a\.?|s\.?r\.?l\.?|srl|spa|inc\.?|llc|ltd\.?|gmbh|s\.?a\.?s\.?)\b",
    re.IGNORECASE,
)


def _short_entity(entity: str) -> str:
    e = re.sub(r"[^\w\sÀ-ÖØ-öø-ÿ]", " ", entity).strip()
    e = _LEGAL_SUFFIXES_RE.sub("", e).strip()
    e = re.sub(r"\s+", " ", e)
    parts = [p for p in e.split() if len(p) >= 2]
    # Drop common leftover suffix tokens after punctuation removal: "S P A", "S R L", etc.
    drop = {"sp", "spa", "srl", "sa", "sas", "llc", "inc", "ltd", "gmbh"}
    parts = [p for p in parts if p.lower() not in drop]
    return " ".join(parts[:3]).strip()


_MONTHS = {
    # it
    "gennaio": 1,
    "febbraio": 2,
    "marzo": 3,
    "aprile": 4,
    "maggio": 5,
    "giugno": 6,
    "luglio": 7,
    "agosto": 8,
    "settembre": 9,
    "ottobre": 10,
    "novembre": 11,
    "dicembre": 12,
    # en
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


def _extract_date_token(text: str) -> Optional[str]:
    t = text
    m = re.search(r"(?<!\d)(19\d{2}|20\d{2})-(\d{1,2})-(\d{1,2})(?!\d)", t)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return f"{y:04d}-{mo:02d}-{d:02d}"

    m = re.search(r"(?<!\d)(\d{1,2})[./-](\d{1,2})[./-](19\d{2}|20\d{2})(?!\d)", t)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return f"{y:04d}-{mo:02d}-{d:02d}"

    m = re.search(
        r"(?<!\d)(\d{1,2})\s+([A-Za-zÀ-ÖØ-öø-ÿ]+)\s+(19\d{2}|20\d{2})(?!\d)",
        t,
        flags=re.IGNORECASE,
    )
    if m:
        d = int(m.group(1))
        mon_name = m.group(2).strip().lower()
        y = int(m.group(3))
        mo = _MONTHS.get(mon_name)
        if mo:
            return f"{y:04d}-{mo:02d}-{d:02d}"

    return None


def _extract_amount_token(text: str) -> Optional[str]:
    # Typical: "225,58 €" or "€ 225.58" or "225.58 EUR"
    m = re.search(r"(€)\s*([0-9]{1,3}(?:[.,][0-9]{3})*[.,][0-9]{2})", text)
    if m:
        amount = m.group(2).replace(".", "").replace(",", ".")
        return f"{amount} EUR"
    m = re.search(r"([0-9]{1,3}(?:[.,][0-9]{3})*[.,][0-9]{2})\s*(€|eur|euro)", text, flags=re.IGNORECASE)
    if m:
        amount = m.group(1).replace(".", "").replace(",", ".")
        return f"{amount} EUR"
    return None


def _propose_name_from_summary_and_facts(
    *,
    summary_long: Optional[str],
    facts: dict,
    reference_year: Optional[str],
    original_filename: str,
    filename_separator: str,
) -> Optional[str]:
    if not summary_long:
        return None

    doc_type = facts.get("doc_type") if isinstance(facts.get("doc_type"), str) else ""
    tags = facts.get("tags") if isinstance(facts.get("tags"), list) else []
    doc_kind = doc_type.strip()
    if not doc_kind and tags:
        doc_kind = str(tags[0])
    doc_kind = re.sub(r"\b(document|documento|file|testo|immagine|image|text)\b", "", doc_kind, flags=re.IGNORECASE)
    doc_kind = re.sub(r"\s+", " ", doc_kind).strip()

    orgs = facts.get("organizations") if isinstance(facts.get("organizations"), list) else []
    people = facts.get("people") if isinstance(facts.get("people"), list) else []
    entity = ""
    if orgs:
        entity = _short_entity(str(orgs[0]))
    elif people:
        entity = _short_entity(str(people[0]))

    date_token = _extract_date_token(summary_long) or (reference_year if reference_year and _is_year(reference_year) else None)
    amount_token = _extract_amount_token(summary_long)

    pieces: list[str] = []
    if doc_kind:
        pieces.extend(_split_and_repair_tokens(doc_kind)[:4])
    if entity:
        pieces.extend(_split_and_repair_tokens(entity)[:3])
    if date_token:
        pieces.append(date_token)
    if amount_token:
        pieces.extend(_split_and_repair_tokens(amount_token)[:2])

    # De-duplicate while preserving order.
    seen: set[str] = set()
    cleaned: list[str] = []
    for p in pieces:
        pl = p.lower()
        if not pl or pl in _STOPWORDS or pl in _GENERIC_NAME_TOKENS:
            continue
        if pl in seen:
            continue
        seen.add(pl)
        cleaned.append(p)
        if len(cleaned) >= 10:
            break

    if len(cleaned) < 3:
        return None

    ext = Path(original_filename).suffix
    name = _name_separator(filename_separator).join(cleaned)
    proposed = _sanitize_name(name) + ext
    proposed = _cleanup_generic_words_in_name(proposed_name=proposed, original_filename=original_filename)
    proposed = _normalize_separators(proposed, sep=filename_separator)
    return proposed


def _classify_from_text(
    *,
    model: str,
    content: str,
    filename: str,
    mtime_iso: str,
    base_url: str,
    reference_year_hint: Optional[str],
    category_hint: Optional[str],
    output_language: str,
    taxonomy: Taxonomy,
    filename_separator: str,
) -> AnalysisResult:
    year_hint_line = f"reference_year_hint: {reference_year_hint}" if reference_year_hint else "reference_year_hint: null"
    category_hint_line = f"category_hint: {category_hint}" if category_hint else "category_hint: null"
    categories = taxonomy.allowed_names
    taxonomy_block = taxonomy_to_prompt_block(taxonomy)
    if output_language == "it":
        language_line = "Output language: Italian"
    elif output_language == "en":
        language_line = "Output language: English"
    else:
        language_line = "Output language: match the input document language (if unclear: English)"
    prompt = f"""
You are a document archiving assistant. Reply with VALID JSON only (no extra text).

Goal:
- understand what the document is about
- choose a category from: {list(categories)}
- taxonomy (meaning + examples):
{taxonomy_block}
- if category_hint is present, you may use it unless the content clearly indicates a different category
- estimate the reference year (reference_year) the document refers to
- estimate the production year (production_year) (if unknown: null)
- extract structured facts for later normalization (language, doc_type, tags, people, organizations, date candidates)
- write a richer summary_long (4-10 sentences)
- propose a meaningful, descriptive file name (proposed_name) using words separated by spaces (not underscores)
  - use 6-12 words when possible (not too short)
  - include key entities (company/person), and month/period if present
  - copy proper names as-is (do not guess spellings; if uncertain, omit the entity)
  - do NOT include category/year unless there is no other useful info
  - do NOT include generic words like "this document", "text", "image"
  - keep it readable (avoid random IDs)
- {language_line}
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
  "language": "it"|"en"|"unknown",
  "doc_type": string,
  "tags": string[],
  "people": string[],
  "organizations": string[],
  "date_candidates": [{{"year": string, "type": "reference"|"production"|"other", "confidence": number}}],
  "summary_long": string,
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
        return AnalysisResult(status="error", reason=f"Ollama errore: {type(exc).__name__}", model_used=model)
    if gen.error:
        return AnalysisResult(status="error", reason=f"Ollama errore: {gen.error}", model_used=model)
    out = gen.response
    data = _extract_json(out)
    if not isinstance(data, dict):
        return AnalysisResult(status="skipped", reason="Unparseable output (JSON)", model_used=model)

    skip_reason = data.get("skip_reason")
    if isinstance(skip_reason, str) and skip_reason.strip():
        return AnalysisResult(status="skipped", reason=skip_reason.strip(), model_used=model)

    category = data.get("category")
    if not isinstance(category, str) or category not in categories:
        category = "unknown"

    reference_year = data.get("reference_year")
    if reference_year is not None and not isinstance(reference_year, str):
        reference_year = None
    if isinstance(reference_year, str) and not _is_year(reference_year.strip()):
        reference_year = None

    proposed_name = data.get("proposed_name")
    if not isinstance(proposed_name, str) or not proposed_name.strip():
        return AnalysisResult(status="skipped", reason="Missing proposed name", model_used=model)

    proposed_name = _ensure_extension(_sanitize_name(proposed_name), filename)
    proposed_name = _cleanup_generic_words_in_name(proposed_name=proposed_name, original_filename=filename)
    proposed_name = _normalize_separators(proposed_name, sep=filename_separator)

    summary = data.get("summary")
    if not isinstance(summary, str):
        summary = None
    summary_long = data.get("summary_long")
    if not isinstance(summary_long, str) or not summary_long.strip():
        summary_long = None

    facts = {
        "language": data.get("language") if isinstance(data.get("language"), str) else None,
        "doc_type": data.get("doc_type") if isinstance(data.get("doc_type"), str) else None,
        "tags": _coerce_list(data.get("tags")),
        "people": _coerce_list(data.get("people")),
        "organizations": _coerce_list(data.get("organizations")),
        "date_candidates": _coerce_date_candidates(data.get("date_candidates")),
    }
    facts_json = json.dumps(facts, ensure_ascii=False, sort_keys=True)

    confidence = data.get("confidence")
    if isinstance(confidence, (int, float)):
        conf = float(confidence)
    else:
        conf = None

    if conf is not None and conf < 0.35:
        return AnalysisResult(status="skipped", reason="Low confidence", confidence=conf, model_used=model)

    # If the model produced a generic/low-signal name, rebuild it from summary+facts.
    if summary_long:
        orgs = facts.get("organizations") if isinstance(facts.get("organizations"), list) else []
        org_hint = _short_entity(str(orgs[0])) if orgs else ""
        low_signal = len(Path(proposed_name).stem) < 18 or _name_token_count(proposed_name) < 4
        missing_entity = bool(org_hint) and (org_hint.lower().split()[0] not in proposed_name.lower())
        if low_signal or missing_entity:
            better = _propose_name_from_summary_and_facts(
                summary_long=summary_long,
                facts=facts,
                reference_year=reference_year,
                original_filename=filename,
                filename_separator=filename_separator,
            )
            if better:
                proposed_name = better

    # If the proposed name is too short / low-signal, derive one from summary.
    if len(Path(proposed_name).stem) < 12 or _name_token_count(proposed_name) < 3:
        proposed_name = _fallback_name_from_summary(summary=summary, original_filename=filename, sep=filename_separator)
        proposed_name = _cleanup_generic_words_in_name(proposed_name=proposed_name, original_filename=filename)
        proposed_name = _normalize_separators(proposed_name, sep=filename_separator)

    # If category is unknown, fall back to hint.
    if category == "unknown" and category_hint in categories:
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
        model_used=model,
        summary_long=(summary_long or "").strip()[:4000] or None,
        facts_json=facts_json,
    )

def _text_model_candidates(cfg: AnalysisConfig) -> tuple[str, ...]:
    if cfg.text_models:
        return cfg.text_models
    return (cfg.text_model,)


def _vision_model_candidates(cfg: AnalysisConfig) -> tuple[str, ...]:
    if cfg.vision_models:
        return cfg.vision_models
    return (cfg.vision_model,)


def _try_text_models(
    *,
    cfg: AnalysisConfig,
    content: str,
    filename: str,
    mtime_iso: str,
    reference_year_hint: Optional[str],
    category_hint: Optional[str],
) -> AnalysisResult:
    last: AnalysisResult | None = None
    for model in _text_model_candidates(cfg):
        res = _classify_from_text(
            model=model,
            content=content,
            filename=filename,
            mtime_iso=mtime_iso,
            base_url=cfg.ollama_base_url,
            reference_year_hint=reference_year_hint,
            category_hint=category_hint,
            output_language=cfg.output_language,
            taxonomy=cfg.taxonomy,
            filename_separator=cfg.filename_separator,
        )
        last = res
        if res.status == "ready":
            return res
    return last or AnalysisResult(status="error", reason="No text models available")


def _extract_facts_from_text(
    *,
    model: str,
    content: str,
    filename: str,
    mtime_iso: str,
    base_url: str,
    year_hint_filename: Optional[str],
    year_hint_text: Optional[str],
    output_language: str,
    detail_level: str = "fast",  # fast | deep
) -> FactsResult:
    if output_language == "it":
        language_line = "Output language: Italian"
    elif output_language == "en":
        language_line = "Output language: English"
    else:
        language_line = "Output language: match the input document language (if unclear: English)"

    level = (detail_level or "fast").lower()
    if level == "deep":
        summary_line = '  "summary_long": string,   // 8-14 sentences, include the most important extracted values (who/what/when/how much/ids)'
    else:
        summary_line = '  "summary_long": string,   // 3-6 sentences, include the most important extracted values (who/what/when/how much/ids)'

    prompt = f"""
You are a document understanding assistant. Reply with VALID JSON only (no extra text).

Goal:
- Extract high-signal facts for later batch classification and coherent renaming.
- Do NOT classify or propose a filename in this step.
- Prefer precision over brevity: if a value is present, copy it exactly; do not guess.
- {language_line}

Inputs:
filename: {filename}
mtime_iso: {mtime_iso}
year_hint_filename: {year_hint_filename or "null"}
year_hint_text: {year_hint_text or "null"}
content:
\"\"\"{content}\"\"\"

Return a single JSON object with exactly these keys:
language, doc_type, purpose, tags, people, organizations, addresses, amounts, identifiers, date_candidates, summary_long, confidence, skip_reason.

Constraints:
- purpose: 1 sentence (why this document exists)
- people: string[] (names only, max 5)
- organizations: string[] (names only, max 5)
- addresses: string[] (max 3)
- amounts: max 3 items, each {{"value": number, "currency": string, "raw": string}}
- identifiers: max 6 items, each {{"type": string, "value": string}}
- summary_long: {summary_line.split('//')[1].strip() if '//' in summary_line else ''}
"""
    try:
        # Limit generated tokens to keep scan fast; deep scan increases the budget.
        num_predict = 780 if level == "deep" else 420
        # Retry with higher budget if JSON is truncated / unparseable.
        for attempt in range(2):
            gen = generate(
                model=model,
                prompt=prompt,
                base_url=base_url,
                timeout_s=180.0,
                options={"temperature": 0.2 if attempt == 0 else 0.0, "num_predict": num_predict},
                response_format="json",
            )
            data = _extract_json(gen.response)
            if isinstance(data, dict):
                break
            num_predict = int(num_predict * 1.4)
    except Exception as exc:  # noqa: BLE001
        return FactsResult(status="error", reason=f"Ollama errore: {type(exc).__name__}", model_used=model)
    if gen.error:
        return FactsResult(status="error", reason=f"Ollama errore: {gen.error}", model_used=model)

    if not isinstance(data, dict):
        return FactsResult(status="skipped", reason="Unparseable output (JSON)", model_used=model)

    skip_reason = data.get("skip_reason")
    if isinstance(skip_reason, str) and skip_reason.strip():
        return FactsResult(status="skipped", reason=skip_reason.strip(), model_used=model)

    summary_long = data.get("summary_long")
    if not isinstance(summary_long, str) or not summary_long.strip():
        summary_long = None

    confidence = data.get("confidence")
    conf = float(confidence) if isinstance(confidence, (int, float)) else None
    if conf is not None and conf < 0.30:
        return FactsResult(status="skipped", reason="Low confidence", confidence=conf, model_used=model)

    facts = {
        "language": data.get("language") if isinstance(data.get("language"), str) else None,
        "doc_type": data.get("doc_type") if isinstance(data.get("doc_type"), str) else None,
        "purpose": data.get("purpose") if isinstance(data.get("purpose"), str) else None,
        "tags": _coerce_list(data.get("tags")),
        "people": _coerce_list(data.get("people")),
        "organizations": _coerce_list(data.get("organizations")),
        "addresses": _coerce_list(data.get("addresses")),
        "amounts": data.get("amounts") if isinstance(data.get("amounts"), list) else [],
        "identifiers": data.get("identifiers") if isinstance(data.get("identifiers"), list) else [],
        "date_candidates": _coerce_date_candidates(data.get("date_candidates")),
        "year_hint_filename": year_hint_filename,
        "year_hint_text": year_hint_text,
    }
    facts_json = json.dumps(facts, ensure_ascii=False, sort_keys=True)

    return FactsResult(
        status="scanned",
        summary_long=(summary_long or "").strip()[:4000] or None,
        facts_json=facts_json,
        confidence=conf,
        model_used=model,
    )


def extract_facts_item(item: ScanItem, *, config: AnalysisConfig) -> FactsResult:
    path = item.path
    if item.status not in {"pending", "skipped", "error"}:
        return FactsResult(status=item.status, reason=item.reason)

    year_hint_filename = _extract_year_hint_from_path(path)

    def skipped(reason: str) -> FactsResult:
        return FactsResult(status="skipped", reason=reason)

    if item.kind == "pdf":
        text, reason, meta = extract_pdf_text_with_meta(path, ocr_mode=config.ocr_mode)
        if not text:
            res = skipped(reason or "No extractable PDF text")
            if meta:
                res = replace(
                    res,
                    extract_method=meta.method,
                    extract_time_s=meta.extract_time_s,
                    ocr_time_s=meta.ocr_time_s,
                    ocr_mode=meta.ocr_mode,
                )
            return res
        year_hint_text = _extract_year_hint_from_text(text)
        evidence_pack, evidence = _build_evidence_pack(text, max_chars=3500)
        excerpt = evidence_pack or _content_excerpt_for_llm(text, max_chars=14000)
        model = _text_model_candidates(config)[0] if _text_model_candidates(config) else config.text_model
        llm_total = 0.0
        used_level = "fast"
        t0 = time.perf_counter()
        res = _extract_facts_from_text(
            model=model,
            content=excerpt,
            filename=path.name,
            mtime_iso=item.mtime_iso,
            base_url=config.ollama_base_url,
            year_hint_filename=year_hint_filename,
            year_hint_text=year_hint_text,
            output_language=config.output_language,
            detail_level="fast",
        )
        llm_total += time.perf_counter() - t0

        def needs_deep(r: FactsResult) -> bool:
            if r.status == "skipped" and isinstance(r.reason, str):
                if "Unparseable output" in r.reason:
                    return True
                if "Low confidence" in r.reason:
                    return True
            if r.status != "scanned":
                return False
            if r.confidence is not None and r.confidence < 0.55:
                return True
            if not r.summary_long or len(r.summary_long.strip()) < 160:
                return True
            if not r.facts_json:
                return True
            try:
                obj = json.loads(r.facts_json)
            except Exception:
                return True
            if not isinstance(obj, dict):
                return True
            if not (isinstance(obj.get("purpose"), str) and obj.get("purpose", "").strip()):
                return True
            # OCR docs often need a second pass to recover entities/amounts.
            if meta and meta.method == "ocr":
                return True
            return False

        if needs_deep(res):
            used_level = "deep"
            deep_pack, deep_evidence = _build_evidence_pack(text, max_chars=6500, max_snippets=10)
            deep_excerpt = deep_pack or _content_excerpt_for_llm(text, max_chars=14000)
            t1 = time.perf_counter()
            deep = _extract_facts_from_text(
                model=model,
                content=deep_excerpt,
                filename=path.name,
                mtime_iso=item.mtime_iso,
                base_url=config.ollama_base_url,
                year_hint_filename=year_hint_filename,
                year_hint_text=year_hint_text,
                output_language=config.output_language,
                detail_level="deep",
            )
            llm_total += time.perf_counter() - t1
            # Prefer deep output when it improves on the fast pass.
            if deep.status == "scanned" or (res.status != "scanned" and deep.status != "error"):
                res = deep
                evidence = deep_evidence or evidence

        if meta:
            res = replace(
                res,
                extract_method=meta.method,
                extract_time_s=meta.extract_time_s,
                ocr_time_s=meta.ocr_time_s,
                ocr_mode=meta.ocr_mode,
            )
        res = replace(res, llm_time_s=llm_total)
        if res.facts_json and evidence:
            try:
                obj = json.loads(res.facts_json)
                if isinstance(obj, dict):
                    obj["evidence"] = evidence
                    obj["evidence_source"] = meta.method if meta else "text"
                    obj["scan_level"] = used_level
                    res = replace(res, facts_json=json.dumps(obj, ensure_ascii=False, sort_keys=True))
            except Exception:
                pass
        return res

    if item.kind == "image":
        if config.output_language == "it":
            caption_prompt = "Describe this image in one sentence in Italian."
        else:
            caption_prompt = "Describe this image in one sentence in English."
        caption = ""
        vision_model_used: str | None = None
        last_vision_error: str | None = None
        for vm in _vision_model_candidates(config):
            try:
                cap = generate_with_image_file(
                    model=vm,
                    prompt=caption_prompt,
                    image_path=str(path),
                    base_url=config.ollama_base_url,
                    timeout_s=180.0,
                )
            except Exception as exc:  # noqa: BLE001
                last_vision_error = f"{type(exc).__name__}"
                continue
            if cap.error:
                last_vision_error = cap.error
                continue
            caption = cap.response.strip()
            if caption:
                vision_model_used = vm
                break
        if not caption:
            msg = "Empty caption" if not last_vision_error else f"Vision error: {last_vision_error}"
            return skipped(msg)

        model = _text_model_candidates(config)[0] if _text_model_candidates(config) else config.text_model
        t0 = time.perf_counter()
        res = _extract_facts_from_text(
            model=model,
            content=f"IMAGE_CAPTION: {caption}",
            filename=path.name,
            mtime_iso=item.mtime_iso,
            base_url=config.ollama_base_url,
            year_hint_filename=year_hint_filename,
            year_hint_text=None,
            output_language=config.output_language,
        )
        llm_elapsed = time.perf_counter() - t0
        used = model
        if vision_model_used:
            used = f"{model} (vision: {vision_model_used})"
        return replace(res, llm_time_s=llm_elapsed, model_used=used)

    return skipped("Unsupported file type")


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
        text, reason, meta = extract_pdf_text_with_meta(path, ocr_mode=config.ocr_mode)
        if not text:
            return skipped(reason or "No extractable PDF text")
        content_year_hint = _extract_year_hint_from_text(text)
        effective_year_hint = filename_year_hint or content_year_hint
        category_hint = _category_hint_from_signals(path=path, text=text)
        t0 = time.perf_counter()
        res = _try_text_models(
            cfg=config,
            content=text,
            filename=path.name,
            mtime_iso=item.mtime_iso,
            reference_year_hint=effective_year_hint,
            category_hint=category_hint,
        )
        llm_elapsed = time.perf_counter() - t0
        if meta:
            res = replace(
                res,
                extract_method=meta.method,
                extract_time_s=meta.extract_time_s,
                ocr_time_s=meta.ocr_time_s,
                ocr_mode=meta.ocr_mode,
            )
        res = replace(res, llm_time_s=llm_elapsed)
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
        if config.output_language == "it":
            caption_prompt = "Describe this image in one sentence in Italian."
        else:
            caption_prompt = "Describe this image in one sentence in English."
        caption = ""
        vision_model_used: str | None = None
        last_vision_error: str | None = None
        for vm in _vision_model_candidates(config):
            try:
                cap = generate_with_image_file(
                    model=vm,
                    prompt=caption_prompt,
                    image_path=str(path),
                    base_url=config.ollama_base_url,
                    timeout_s=180.0,
                )
            except Exception as exc:  # noqa: BLE001 (MVP: best-effort)
                last_vision_error = f"{type(exc).__name__}"
                continue
            if cap.error:
                last_vision_error = cap.error
                continue
            caption = cap.response.strip()
            if caption:
                vision_model_used = vm
                break
        if not caption:
            msg = "Empty caption" if not last_vision_error else f"Vision error: {last_vision_error}"
            return skipped_with_year(msg, effective_year_hint)
        res = _try_text_models(
            cfg=config,
            content=f"IMAGE_CAPTION: {caption}",
            filename=path.name,
            mtime_iso=item.mtime_iso,
            reference_year_hint=effective_year_hint,
            category_hint=category_hint,
        )
        if vision_model_used and res.model_used:
            res = replace(res, model_used=f"{res.model_used} (vision: {vision_model_used})")
        if res.status == "skipped":
            return replace(
                res,
                category="unknown",
                reference_year=res.reference_year or effective_year_hint,
                proposed_name=path.name,
            )
        return res

    return skipped_with_year("Unsupported file type", filename_year_hint)
