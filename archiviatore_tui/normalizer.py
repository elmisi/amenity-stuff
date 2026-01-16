from __future__ import annotations

import json
import re
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .ollama_client import generate
from .scanner import ScanItem
from .taxonomy import Taxonomy, taxonomy_to_prompt_block
from .utils_filename import sanitize_name
from .utils_json import extract_json_any


@dataclass(frozen=True)
class NormalizationResult:
    by_path: dict[str, dict]
    model_used: str
    error: Optional[str] = None


def _extract_json(text: str) -> Optional[object]:
    return extract_json_any(text)


def _sanitize_name(name: str) -> str:
    return sanitize_name(name)


def _name_separator(kind: str) -> str:
    return {"space": " ", "underscore": "_", "dash": "-"}.get(kind, " ")


def _normalize_separators(name: str, *, sep: str) -> str:
    desired = _name_separator(sep)
    stem = Path(name).stem
    ext = Path(name).suffix
    raw = [t for t in re.split(r"[\s_\-]+", stem.strip()) if t]
    if desired == " ":
        return _sanitize_name(" ".join(raw)) + ext
    return _sanitize_name(desired.join(raw)) + ext


def _ensure_extension(proposed_name: str, original_filename: str) -> str:
    original_ext = Path(original_filename).suffix
    if not original_ext:
        return proposed_name
    if proposed_name.lower().endswith(original_ext.lower()):
        return proposed_name
    return proposed_name.rstrip(".") + original_ext


def _chunk(items: list[ScanItem], size: int) -> list[list[ScanItem]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


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

_STOPWORDS = {
    "a",
    "an",
    "the",
    "and",
    "or",
    "of",
    "to",
    "in",
    "on",
    "for",
    "with",
    "da",
    "di",
    "del",
    "della",
    "dei",
    "delle",
    "in",
    "per",
    "con",
    "su",
    "un",
    "una",
    "il",
    "lo",
    "la",
    "i",
    "gli",
    "le",
}

_LEGAL_SUFFIXES_RE = re.compile(
    r"\b(s\.?p\.?a\.?|s\.?r\.?l\.?|srl|spa|inc\.?|llc|ltd\.?|gmbh|s\.?a\.?s\.?)\b",
    re.IGNORECASE,
)


def _short_entity(entity: str) -> str:
    e = re.sub(r"[^\w\sÀ-ÖØ-öø-ÿ]", " ", (entity or "")).strip()
    e = _LEGAL_SUFFIXES_RE.sub("", e).strip()
    e = re.sub(r"\s+", " ", e)
    parts = [p for p in e.split() if len(p) >= 2]
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
    t = text or ""
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
    t = text or ""
    m = re.search(r"(€)\s*([0-9]{1,3}(?:[.,][0-9]{3})*[.,][0-9]{2})", t)
    if m:
        amount = m.group(2).replace(".", "").replace(",", ".")
        return f"{amount} EUR"
    m = re.search(r"([0-9]{1,3}(?:[.,][0-9]{3})*[.,][0-9]{2})\s*(€|eur|euro)", t, flags=re.IGNORECASE)
    if m:
        amount = m.group(1).replace(".", "").replace(",", ".")
        return f"{amount} EUR"
    return None


def _name_token_count(name: str) -> int:
    return len(re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9]+", Path(name).stem))


def _split_tokens(text: str) -> list[str]:
    raw = [t for t in re.split(r"[\s_\-]+", (text or "").strip()) if t]
    out: list[str] = []
    for t in raw:
        t2 = re.sub(r"[\\/:*?\"<>|]", " ", t).strip()
        if t2:
            out.append(t2)
    return out


def _parse_facts_json(value: Optional[str]) -> dict:
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        data = json.loads(value)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _best_year_from_facts(facts: dict, *, summary_long: Optional[str], proposed_name: Optional[str]) -> Optional[str]:
    # 1) explicit candidates from phase 1
    candidates = facts.get("date_candidates")
    best: tuple[float, str] | None = None
    if isinstance(candidates, list):
        for c in candidates:
            if not isinstance(c, dict):
                continue
            y = c.get("year")
            if not isinstance(y, str) or not re.fullmatch(r"(19\d{2}|20\d{2})", y.strip()):
                continue
            conf = c.get("confidence")
            score = float(conf) if isinstance(conf, (int, float)) else 0.0
            typ = c.get("type")
            if isinstance(typ, str) and typ.strip().lower() == "reference":
                score += 0.2
            if best is None or score > best[0]:
                best = (score, y.strip())
    if best is not None:
        return best[1]

    # 2) year hints collected in phase 1
    for key in ("year_hint_text", "year_hint_filename"):
        v = facts.get(key)
        if isinstance(v, str) and re.fullmatch(r"(19\d{2}|20\d{2})", v.strip()):
            return v.strip()

    # 3) extract from summary_long or proposed_name if present
    for text in (summary_long or "", proposed_name or ""):
        m = re.search(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)", text)
        if m:
            return m.group(1)

    return None


def _propose_name_from_summary_and_facts(
    *,
    summary_long: Optional[str],
    facts_json: Optional[str],
    reference_year: Optional[str],
    original_filename: str,
    filename_separator: str,
) -> Optional[str]:
    summary_long = (summary_long or "").strip()
    if not summary_long:
        return None
    facts = _parse_facts_json(facts_json)
    doc_type = facts.get("doc_type") if isinstance(facts.get("doc_type"), str) else ""
    purpose = facts.get("purpose") if isinstance(facts.get("purpose"), str) else ""
    tags = facts.get("tags") if isinstance(facts.get("tags"), list) else []
    kind = (doc_type or (str(tags[0]) if tags else "")).strip()
    kind = re.sub(r"\b(document|documento|file|testo|immagine|image|text)\b", "", kind, flags=re.IGNORECASE).strip()
    if not kind and purpose:
        kind = purpose.strip()

    orgs = facts.get("organizations") if isinstance(facts.get("organizations"), list) else []
    people = facts.get("people") if isinstance(facts.get("people"), list) else []
    entity = _short_entity(str(orgs[0])) if orgs else (_short_entity(str(people[0])) if people else "")

    date_tok = _extract_date_token(summary_long) or reference_year
    amt = _extract_amount_token(summary_long)

    pieces: list[str] = []
    pieces.extend(_split_tokens(kind)[:4])
    if purpose and purpose != kind:
        # Allow purpose to contribute a little extra signal (kept short to avoid overly long names).
        pieces.extend(_split_tokens(purpose)[:3])
    pieces.extend(_split_tokens(entity)[:3])
    if isinstance(date_tok, str) and date_tok.strip():
        # Keep date as a single token so we don't de-duplicate month/day (e.g. 04 04).
        pieces.append(date_tok.strip())
    if amt:
        pieces.extend(_split_tokens(amt)[:2])

    cleaned: list[str] = []
    seen: set[str] = set()
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
    name = _name_separator(filename_separator).join(cleaned) + ext
    name = _ensure_extension(_sanitize_name(name), original_filename)
    return _normalize_separators(name, sep=filename_separator)


def normalize_items(
    *,
    items: list[ScanItem],
    model: str,
    base_url: str,
    taxonomy: Taxonomy,
    output_language: str,
    filename_separator: str,
    chunk_size: int = 25,
) -> NormalizationResult:
    allowed = taxonomy.allowed_names
    taxonomy_block = taxonomy_to_prompt_block(taxonomy)

    if output_language == "it":
        language_line = "Output language: Italian (but keep proper names as-is)"
    elif output_language == "en":
        language_line = "Output language: English (but keep proper names as-is)"
    else:
        language_line = "Output language: match each document language; if unclear: English"

    sep_label = filename_separator
    sep_desc = {
        "space": "spaces",
        "underscore": "underscores",
        "dash": "dashes",
    }.get(filename_separator, "spaces")

    by_path: dict[str, dict] = {}
    for batch in _chunk(items, chunk_size):
        payload = []
        by_input_path = {str(it.path): it for it in batch}
        for it in batch:
            facts_obj = _parse_facts_json(it.facts_json)
            payload.append(
                {
                    "path": str(it.path),
                    "kind": it.kind,
                    "summary_long": it.summary_long,
                    "facts": facts_obj,
                    "current": {
                        "category": it.category,
                        "reference_year": it.reference_year,
                        "proposed_name": it.proposed_name,
                    },
                }
            )

        prompt = f"""
You are a document archiving assistant. Reply with VALID JSON only.

Task:
- Given a batch of documents described by extracted facts (not the raw file content),
  classify and rename with maximum output quality.
- You MAY change category and reference_year if a better choice is supported by the facts.
- Produce consistent, uniform naming across the batch by using coherent templates per document cluster.
  Example: similar utility bills should share the same naming pattern (same ordering, same fields).

Constraints:
- category MUST be one of: {list(allowed)}
- proposed_name MUST be descriptive, 6-14 words when possible.
- Include key entities (organization/person) and a date/period if available in the facts or summary.
- Use the document "purpose" (facts.purpose) as a generic, cross-domain hint: what the document is for / why it exists.
- Copy proper names as-is; do NOT guess spellings. If uncertain, omit the entity.
- Use {sep_desc} between words (no mixed separators). Do NOT put separators inside a word.
- Do NOT include generic words like "document", "file", "text", "image".
- Do NOT include category/year in the name unless there is no other useful info.
- {language_line}

Taxonomy:
{taxonomy_block}

Input (JSON list):
{json.dumps(payload, ensure_ascii=False)}

Output JSON schema (JSON list, same length as input, preserve 'path'):
[
  {{
    "path": string,
    "category": string,
    "reference_year": string|null,
    "proposed_name": string,
    "summary": string,
    "confidence": number|null
  }}
]
"""

        gen = generate(model=model, prompt=prompt, base_url=base_url, timeout_s=180.0)
        if gen.error:
            return NormalizationResult(by_path=by_path, model_used=model, error=gen.error)
        data = _extract_json(gen.response)
        if not isinstance(data, list):
            return NormalizationResult(by_path=by_path, model_used=model, error="Unparseable output (JSON list)")

        for row in data:
            if not isinstance(row, dict):
                continue
            path = row.get("path")
            if not isinstance(path, str) or not path:
                continue
            src = by_input_path.get(path)
            cat = row.get("category")
            if not isinstance(cat, str) or cat not in allowed:
                cat = "unknown"
            year = row.get("reference_year")
            if not isinstance(year, str) or not re.fullmatch(r"(19\\d{2}|20\\d{2})", year.strip()):
                year = None
            name = row.get("proposed_name")
            if not isinstance(name, str) or not name.strip():
                name = Path(path).name
            name = _ensure_extension(_sanitize_name(name.strip()), Path(path).name)
            name = _normalize_separators(name, sep=sep_label)

            cur_facts = _parse_facts_json(src.facts_json) if src else {}

            # If year is missing, derive it from facts/hints/summary.
            if not year and src:
                year = _best_year_from_facts(cur_facts, summary_long=src.summary_long, proposed_name=name)

            # If the model output is generic, rebuild deterministically from summary_long + facts_json.
            if src and src.summary_long:
                orgs = cur_facts.get("organizations") if isinstance(cur_facts.get("organizations"), list) else []
                org_hint = _short_entity(str(orgs[0])) if orgs else ""
                low_signal = len(Path(name).stem) < 18 or _name_token_count(name) < 4
                missing_entity = bool(org_hint) and (org_hint.lower().split()[0] not in name.lower())
                if low_signal or missing_entity:
                    better = _propose_name_from_summary_and_facts(
                        summary_long=src.summary_long,
                        facts_json=src.facts_json,
                        reference_year=year,
                        original_filename=Path(path).name,
                        filename_separator=sep_label,
                    )
                    if better:
                        name = better

            summary = row.get("summary")
            if not isinstance(summary, str):
                summary = ""
            conf = row.get("confidence")
            conf_out = float(conf) if isinstance(conf, (int, float)) else None

            by_path[path] = {
                "category": cat,
                "reference_year": year,
                "proposed_name": name,
                "summary": summary.strip()[:200] or None,
                "confidence": conf_out,
                "model_used": model,
            }

    return NormalizationResult(by_path=by_path, model_used=model)
