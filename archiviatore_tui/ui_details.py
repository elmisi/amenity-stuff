from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from .scanner import ScanItem
    from .settings import Settings


def render_details(item: "ScanItem", *, settings: "Settings") -> str:
    abs_path = str(item.path)
    source_root = str(settings.source_root.expanduser().resolve())
    try:
        _ = str(item.path.relative_to(source_root))
    except Exception:
        pass

    type_state_cat_year = " • ".join(
        [
            f"Type: {item.kind}",
            f"Status: {item.status}",
            f"Category: {item.category or ''}",
            f"Year: {item.reference_year or ''}",
        ]
    )

    extra_bits: list[str] = []
    if isinstance(item.analysis_time_s, (int, float)):
        extra_bits.append(f"Elab: {item.analysis_time_s:.1f}s")
    if isinstance(item.extract_time_s, (int, float)) and item.extract_method:
        ext = f"Extract: {item.extract_method} {item.extract_time_s:.1f}s"
        if item.extract_method == "ocr" and isinstance(item.ocr_time_s, (int, float)):
            ext += f" (OCR {item.ocr_time_s:.1f}s{', ' + item.ocr_mode if item.ocr_mode else ''})"
        extra_bits.append(ext)
    if isinstance(item.llm_time_s, (int, float)):
        extra_bits.append(f"LLM: {item.llm_time_s:.1f}s")
    if item.model_used:
        extra_bits.append(f"Model: {item.model_used}")
    if extra_bits:
        type_state_cat_year = type_state_cat_year + " • " + " • ".join(extra_bits)

    summary = (item.summary or "").strip()
    if summary:
        summary_line = f"Summary: {summary}"
    else:
        summary_line = "Summary:"

    return "\n".join(
        [
            f"File: {abs_path}",
            type_state_cat_year,
            f"Proposed name: {item.proposed_name or ''}",
            summary_line,
            f"Summary long: {(item.summary_long or '').strip()}",
            f"Facts: {(item.facts_json or '').strip()}",
            f"Reason: {item.reason or ''}",
        ]
    ).strip()

