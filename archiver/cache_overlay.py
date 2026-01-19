from __future__ import annotations

from dataclasses import replace
from typing import Iterable

from .cache import CacheStore
from .scanner import ScanItem


def overlay_scan_items_with_cache(items: Iterable[ScanItem], cache: CacheStore) -> list[ScanItem]:
    """Overlay cached analysis onto freshly scanned filesystem items.

    This is a refactor-only helper that preserves the previous behavior in `ArchiverApp._run_scan`.
    """
    result: list[ScanItem] = list(items)
    for idx, it in enumerate(list(result)):
        cached = cache.get_matching(it)
        if not cached:
            continue
        cached_status = {
            "analysis": "scanning",
            "extracting": "scanning",
            "extracted": "scanned",
            "ready": "classified",
            "normalizing": "classifying",
            "normalized": "classified",
        }.get(cached.status, cached.status)
        result[idx] = replace(
            it,
            status=cached_status,
            reason=cached.reason,
            category=cached.category,
            reference_year=cached.reference_year,
            proposed_name=cached.proposed_name,
            summary=cached.summary,
            confidence=cached.confidence if isinstance(cached.confidence, (int, float)) else None,
            analysis_time_s=cached.analysis_time_s if isinstance(cached.analysis_time_s, (int, float)) else None,
            model_used=cached.model_used if isinstance(cached.model_used, str) else None,
            summary_long=cached.summary_long if isinstance(cached.summary_long, str) else None,
            facts_json=cached.facts_json if isinstance(cached.facts_json, str) else None,
            llm_raw_output=cached.llm_raw_output if isinstance(cached.llm_raw_output, str) else None,
            extract_method=cached.extract_method if isinstance(cached.extract_method, str) else None,
            extract_time_s=cached.extract_time_s if isinstance(cached.extract_time_s, (int, float)) else None,
            llm_time_s=cached.llm_time_s if isinstance(cached.llm_time_s, (int, float)) else None,
            ocr_time_s=cached.ocr_time_s if isinstance(cached.ocr_time_s, (int, float)) else None,
            ocr_mode=cached.ocr_mode if isinstance(cached.ocr_mode, str) else None,
            facts_time_s=cached.facts_time_s if isinstance(cached.facts_time_s, (int, float)) else None,
            facts_llm_time_s=cached.facts_llm_time_s if isinstance(cached.facts_llm_time_s, (int, float)) else None,
            facts_model_used=cached.facts_model_used if isinstance(cached.facts_model_used, str) else None,
            classify_time_s=cached.classify_time_s if isinstance(cached.classify_time_s, (int, float)) else None,
            classify_llm_time_s=cached.classify_llm_time_s
            if isinstance(cached.classify_llm_time_s, (int, float))
            else None,
            classify_model_used=cached.classify_model_used if isinstance(cached.classify_model_used, str) else None,
        )
    return result

