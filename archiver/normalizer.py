from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from .ollama_client import generate
from .scanner import ScanItem
from .taxonomy import Taxonomy, taxonomy_to_prompt_block
from .utils_filename import (
    ensure_extension,
    name_separator,
    normalize_separators,
    propose_name_from_summary_and_facts,
    sanitize_name,
)
from .utils_json import extract_json_any
from .utils_parsing import (
    GENERIC_NAME_TOKENS,
    STOPWORDS,
    is_year,
    name_token_count,
    short_entity,
    split_tokens,
    tokenize_for_match,
)
from .prompts import build_normalize_batch_prompt


@dataclass(frozen=True)
class NormalizationResult:
    by_path: dict[str, dict]
    model_used: str
    error: Optional[str] = None


def _extract_json(text: str) -> Optional[object]:
    return extract_json_any(text)


def _chunk(items: list[ScanItem], size: int) -> list[list[ScanItem]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


# The following functions/constants have been moved to shared utilities:
# - _sanitize_name -> utils_filename.sanitize_name
# - _name_separator -> utils_filename.name_separator
# - _normalize_separators -> utils_filename.normalize_separators
# - _ensure_extension -> utils_filename.ensure_extension
# - _GENERIC_NAME_TOKENS -> utils_parsing.GENERIC_NAME_TOKENS
# - _STOPWORDS -> utils_parsing.STOPWORDS
# - _LEGAL_SUFFIXES_RE -> utils_parsing.LEGAL_SUFFIXES_RE
# - _short_entity -> utils_parsing.short_entity
# - _tokenize_for_match -> utils_parsing.tokenize_for_match


def _category_repair_from_taxonomy(
    *,
    taxonomy: Taxonomy,
    summary_long: Optional[str],
    facts_obj: dict,
) -> Optional[str]:
    """Attempt to map content to a taxonomy category without an LLM.

    Uses user taxonomy examples/description as the weak supervision signal.
    Returns None if ambiguous / insufficient evidence.
    """

    # Build a small searchable text from already-extracted signals.
    fields: list[str] = []
    for key in ("doc_type",):
        v = facts_obj.get(key)
        if isinstance(v, str) and v.strip():
            fields.append(v)
    tags = facts_obj.get("tags")
    if isinstance(tags, list):
        fields.extend(str(t) for t in tags if isinstance(t, str))
    people = facts_obj.get("people")
    if isinstance(people, list) and people:
        # Avoid biasing toward personal for every named document; still useful for disambiguation.
        fields.append("people")
    orgs = facts_obj.get("organizations")
    if isinstance(orgs, list) and orgs:
        fields.append("organization")
    if isinstance(summary_long, str) and summary_long.strip():
        fields.append(summary_long)
    haystack = " ".join(fields)

    if not haystack.strip():
        return None

    tokens = set(tokenize_for_match(haystack))
    haystack_l = haystack.lower()

    scored: list[tuple[float, str]] = []
    for cat in taxonomy.categories:
        if cat.name == "unknown":
            continue
        kw_phrases: list[str] = []
        if cat.name:
            kw_phrases.append(cat.name)
        if cat.description:
            kw_phrases.append(cat.description)
        if cat.examples:
            kw_phrases.extend(cat.examples)

        score = 0.0
        for phrase in kw_phrases:
            if not phrase:
                continue
            p = phrase.strip().lower()
            if not p:
                continue
            # Phrase match is strong (e.g., "carta d'identità", "utility bill").
            if len(p) >= 6 and p in haystack_l:
                score += 3.0
                continue
            # Token match is weaker.
            for tok in tokenize_for_match(p):
                if tok in tokens:
                    score += 1.0

        if score > 0:
            scored.append((score, cat.name))

    if not scored:
        return None

    scored.sort(reverse=True)
    best_score, best_cat = scored[0]
    second_score = scored[1][0] if len(scored) > 1 else 0.0
    # Require a minimum signal and avoid ties.
    if best_score < 3.0:
        return None
    if best_score - second_score < 1.0:
        return None
    return best_cat


# Additional functions moved to shared utilities:
# - _MONTHS -> utils_parsing.MONTHS
# - _extract_date_token -> utils_parsing.extract_date_token
# - _extract_amount_token -> utils_parsing.extract_amount_token
# - _name_token_count -> utils_parsing.name_token_count
# - _split_tokens -> utils_parsing.split_tokens


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


def _propose_name_from_facts_json(
    *,
    summary_long: Optional[str],
    facts_json: Optional[str],
    reference_year: Optional[str],
    original_filename: str,
    filename_separator: str,
) -> Optional[str]:
    """Wrapper that parses facts_json before calling the shared implementation."""
    facts = _parse_facts_json(facts_json)
    return propose_name_from_summary_and_facts(
        summary_long=summary_long,
        facts=facts,
        reference_year=reference_year,
        original_filename=original_filename,
        filename_separator=filename_separator,
    )


def normalize_items(
    *,
    items: list[ScanItem],
    model: str,
    base_url: str,
    taxonomy: Taxonomy,
    output_language: str,
    filename_separator: str,
    chunk_size: int = 25,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> NormalizationResult:
    allowed = taxonomy.allowed_names
    taxonomy_block = taxonomy_to_prompt_block(taxonomy)

    sep_label = filename_separator
    sep_desc = {
        "space": "spaces",
        "underscore": "underscores",
        "dash": "dashes",
    }.get(filename_separator, "spaces")

    by_path: dict[str, dict] = {}
    for batch in _chunk(items, chunk_size):
        if should_cancel and should_cancel():
            return NormalizationResult(by_path=by_path, model_used=model, error="Cancelled")
        payload = []
        by_input_path = {str(it.path): it for it in batch}

        def apply_row(row: dict, *, path: str) -> None:
            src = by_input_path.get(path)
            cat = row.get("category")
            if not isinstance(cat, str) or cat not in allowed:
                cat = "unknown"
            if cat == "unknown" and src:
                repaired = _category_repair_from_taxonomy(
                    taxonomy=taxonomy,
                    summary_long=src.summary_long,
                    facts_obj=_parse_facts_json(src.facts_json),
                )
                if repaired in allowed:
                    cat = repaired
            year = row.get("reference_year")
            if not isinstance(year, str) or not re.fullmatch(r"(19\\d{2}|20\\d{2})", year.strip()):
                year = None
            name = row.get("proposed_name")
            if not isinstance(name, str) or not name.strip():
                name = Path(path).name
            name = ensure_extension(sanitize_name(name.strip()), Path(path).name)
            name = normalize_separators(name, sep=sep_label)

            cur_facts = _parse_facts_json(src.facts_json) if src else {}

            derived_year = _best_year_from_facts(cur_facts, summary_long=src.summary_long, proposed_name=name) if src else None

            # If year is missing, derive it from facts/hints/summary.
            if not year and derived_year:
                year = derived_year
            # If the model picked a year that isn't evidenced, prefer the derived one.
            if year and derived_year and year != derived_year and src:
                evidence = f"{src.summary_long or ''} {name}"
                has_year = bool(re.search(rf"(?<!\d){re.escape(year)}(?!\d)", evidence))
                has_derived = bool(re.search(rf"(?<!\d){re.escape(derived_year)}(?!\d)", evidence))
                if (not has_year and has_derived) or (int(year) < 1950 and int(derived_year) >= 1950):
                    year = derived_year

            # If the model output is generic, rebuild deterministically from summary_long + facts_json.
            if src and src.summary_long:
                orgs = cur_facts.get("organizations") if isinstance(cur_facts.get("organizations"), list) else []
                org_hint = short_entity(str(orgs[0])) if orgs else ""
                low_signal = len(Path(name).stem) < 18 or name_token_count(name) < 4
                missing_entity = bool(org_hint) and (org_hint.lower().split()[0] not in name.lower())
                if low_signal or missing_entity:
                    better = _propose_name_from_facts_json(
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

        for it in batch:
            facts_obj = _parse_facts_json(it.facts_json)
            # Keep purpose in scan cache, but do not use it during classification/naming.
            if isinstance(facts_obj, dict) and "purpose" in facts_obj:
                facts_obj = dict(facts_obj)
                facts_obj.pop("purpose", None)
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

        prompt = build_normalize_batch_prompt(
            allowed_categories=list(allowed),
            taxonomy_block=taxonomy_block,
            separator_description=sep_desc,
            payload_json=json.dumps(payload, ensure_ascii=False),
            output_language=output_language,
        )

        if should_cancel and should_cancel():
            return NormalizationResult(by_path=by_path, model_used=model, error="Cancelled")
        gen = generate(model=model, prompt=prompt, base_url=base_url, timeout_s=180.0)
        if gen.error:
            return NormalizationResult(by_path=by_path, model_used=model, error=gen.error)
        data = _extract_json(gen.response)
        if not isinstance(data, list):
            return NormalizationResult(by_path=by_path, model_used=model, error="Unparseable output (JSON list)")

        # Some models may fail to echo back the full absolute path. For single-item normalization we
        # can safely apply the first output row to the only input item.
        fallback_row: Optional[dict] = None
        for row in data:
            if not isinstance(row, dict):
                continue
            path = row.get("path")
            if not isinstance(path, str) or not path:
                if len(batch) == 1 and fallback_row is None:
                    fallback_row = row
                continue
            src = by_input_path.get(path)
            # Ignore mismatched paths for multi-item batches; for per-file this is handled below.
            if not src:
                if len(batch) == 1 and fallback_row is None:
                    fallback_row = row
                continue
            apply_row(row, path=path)

        if len(batch) == 1 and not by_path and fallback_row is not None:
            only_path = str(batch[0].path)
            apply_row(fallback_row, path=only_path)

    return NormalizationResult(by_path=by_path, model_used=model)
