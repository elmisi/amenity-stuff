from __future__ import annotations

import textwrap
from pathlib import Path
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from .scanner import ScanItem
    from .settings import Settings


def _format_bytes(size_bytes: int) -> str:
    try:
        size = float(size_bytes)
    except Exception:
        return ""
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    unit = units[0]
    for u in units[1:]:
        if size < 1024.0:
            break
        size /= 1024.0
        unit = u
    if unit == "B":
        return f"{int(size)} {unit}"
    return f"{size:.1f} {unit}"


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


def _wrap_field(*, label: str, value: str, width: int) -> list[str]:
    clean = " ".join((value or "").strip().split())
    prefix = f"{label}: "
    if not clean:
        return [prefix.rstrip()]
    wrapped = textwrap.wrap(
        clean,
        width=max(20, width - len(prefix)),
        break_long_words=False,
        break_on_hyphens=False,
    )
    if not wrapped:
        return [prefix.rstrip()]
    lines = [prefix + wrapped[0]]
    indent = " " * len(prefix)
    for w in wrapped[1:]:
        lines.append(indent + w)
    return lines


def render_details(item: "ScanItem", *, settings: "Settings", max_width: int | None = None, max_lines: int | None = None) -> str:
    abs_path = str(item.path)
    if max_width:
        abs_path = _shorten_middle(abs_path, max_width)

    size = _format_bytes(int(item.size_bytes) if isinstance(item.size_bytes, int) else 0)
    meta_line = " • ".join(
        [
            f"Type: {item.kind}",
            f"Size: {size}",
            f"Status: {item.status}",
            f"Category: {item.category or ''}",
            f"Year: {item.reference_year or ''}",
        ]
    )

    extra_bits: list[str] = []
    if isinstance(item.facts_time_s, (int, float)):
        extra_bits.append(f"Facts: {item.facts_time_s:.1f}s")
    if isinstance(item.classify_time_s, (int, float)):
        extra_bits.append(f"Classify: {item.classify_time_s:.1f}s")
    if not extra_bits and isinstance(item.analysis_time_s, (int, float)):
        extra_bits.append(f"Elab: {item.analysis_time_s:.1f}s")
    if isinstance(item.extract_time_s, (int, float)) and item.extract_method:
        ext = f"Extract: {item.extract_method} {item.extract_time_s:.1f}s"
        if item.extract_method == "ocr" and item.ocr_mode:
            ext += f" ({item.ocr_mode})"
        extra_bits.append(ext)
    if isinstance(item.facts_llm_time_s, (int, float)):
        extra_bits.append(f"LLM(facts): {item.facts_llm_time_s:.1f}s")
    if isinstance(item.classify_llm_time_s, (int, float)):
        extra_bits.append(f"LLM(class): {item.classify_llm_time_s:.1f}s")
    if not (item.facts_llm_time_s or item.classify_llm_time_s) and isinstance(item.llm_time_s, (int, float)):
        extra_bits.append(f"LLM: {item.llm_time_s:.1f}s")
    if item.classify_model_used:
        extra_bits.append(f"Model(class): {item.classify_model_used}")
    if item.facts_model_used and not item.classify_model_used:
        extra_bits.append(f"Model(facts): {item.facts_model_used}")
    if item.model_used and not (item.facts_model_used or item.classify_model_used):
        extra_bits.append(f"Model: {item.model_used}")
    perf_line = " • ".join(extra_bits) if extra_bits else ""

    width = max_width or 0
    lines: list[str] = []
    lines.append(f"File: {abs_path}")
    lines.append(meta_line)
    if perf_line:
        lines.append(perf_line)
    lines.append(f"Proposed name: {item.proposed_name or ''}")
    if item.moved_to:
        lines.append(f"Moved to: {item.moved_to}")

    if width >= 20:
        lines = [lines[0]] + [_shorten_end(l, width) if len(l) > width else l for l in lines[1:]]

    if width < 20:
        width = 120

    purpose = ""
    try:
        if isinstance(item.facts_json, str) and item.facts_json.strip():
            facts = json.loads(item.facts_json)
            if isinstance(facts, dict) and isinstance(facts.get("purpose"), str):
                purpose = facts.get("purpose", "").strip()
    except Exception:
        purpose = ""

    if purpose:
        lines.extend(_wrap_field(label="Purpose", value=purpose, width=width))

    # Display only the richer summary in the details panel (the short summary is kept in data/caches).
    lines.extend(_wrap_field(label="Summary", value=(item.summary_long or ""), width=width))

    if item.reason:
        lines.extend(_wrap_field(label="Reason", value=item.reason, width=width))

    text = "\n".join([l for l in lines if l.strip() != ""]).strip()
    if max_lines and max_lines > 0:
        split = text.splitlines()
        if len(split) > max_lines:
            split = split[: max_lines - 1] + ["…"]
        text = "\n".join(split)
    return text
