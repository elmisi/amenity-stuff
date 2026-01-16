from __future__ import annotations

import json
import re
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
    raw = [t for t in re.split(r"[\\s_\\-]+", stem.strip()) if t]
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
        for it in batch:
            payload.append(
                {
                    "path": str(it.path),
                    "kind": it.kind,
                    "category": it.category,
                    "reference_year": it.reference_year,
                    "summary_long": it.summary_long,
                    "facts_json": it.facts_json,
                }
            )

        prompt = f"""
You are a document archiving assistant. Reply with VALID JSON only.

Task:
- Given a batch of documents described by extracted facts (not the raw file content),
  improve classification and naming with maximum output quality.
- You MAY change category and reference_year if a better choice is supported by the facts.
- Produce consistent, uniform naming across the batch.

Constraints:
- category MUST be one of: {list(allowed)}
- proposed_name MUST be descriptive, 6-14 words when possible.
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
    "summary": string
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
            summary = row.get("summary")
            if not isinstance(summary, str):
                summary = ""

            by_path[path] = {
                "category": cat,
                "reference_year": year,
                "proposed_name": name,
                "summary": summary.strip()[:200] or None,
                "model_used": model,
            }

    return NormalizationResult(by_path=by_path, model_used=model)
