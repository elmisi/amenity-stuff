from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from .scanner import ScanItem
    from .settings import Settings


def _shorten_middle(text: str, max_width: int) -> str:
    if max_width <= 10 or len(text) <= max_width:
        return text
    keep_left = max(4, int(max_width * 0.4))
    keep_right = max(4, max_width - keep_left - 1)
    return text[:keep_left] + "…" + text[-keep_right:]


def _shorten_end(text: str, max_width: int) -> str:
    if max_width <= 10 or len(text) <= max_width:
        return text
    return text[: max_width - 1] + "…"


def render_details(item: "ScanItem", *, settings: "Settings", max_width: int | None = None, max_lines: int | None = None) -> str:
    abs_path = str(item.path)
    if max_width:
        abs_path = _shorten_middle(abs_path, max_width)

    meta_line = " • ".join(
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
        if item.extract_method == "ocr" and item.ocr_mode:
            ext += f" ({item.ocr_mode})"
        extra_bits.append(ext)
    if isinstance(item.llm_time_s, (int, float)):
        extra_bits.append(f"LLM: {item.llm_time_s:.1f}s")
    if item.model_used:
        extra_bits.append(f"Model: {item.model_used}")
    perf_line = " • ".join(extra_bits) if extra_bits else ""

    summary = (item.summary or "").strip()
    if summary:
        summary_line = f"Summary: {summary}"
    else:
        summary_line = "Summary:"

    lines = [
        f"File: {abs_path}",
        meta_line,
        perf_line,
        f"Proposed name: {item.proposed_name or ''}",
        summary_line,
        f"Summary long: {(item.summary_long or '').strip()}",
        f"Reason: {item.reason or ''}",
    ]
    lines = [l for l in lines if l.strip() != ""]

    width = max_width or 0
    if width >= 20:
        lines = [lines[0]] + [_shorten_end(l, width) if len(l) > width else l for l in lines[1:]]
    text = "\n".join(lines).strip()
    if max_lines and max_lines > 0:
        split = text.splitlines()
        if len(split) > max_lines:
            split = split[: max_lines - 1] + ["…"]
        text = "\n".join(split)
    return text
