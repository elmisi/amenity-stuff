from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from .scanner import ScanItem


@dataclass(frozen=True)
class CacheEntry:
    rel_path: str
    size_bytes: int
    mtime_iso: str
    status: str
    reason: Optional[str] = None
    category: Optional[str] = None
    reference_year: Optional[str] = None
    proposed_name: Optional[str] = None
    summary: Optional[str] = None
    confidence: Optional[float] = None
    analysis_time_s: Optional[float] = None
    model_used: Optional[str] = None
    summary_long: Optional[str] = None
    facts_json: Optional[str] = None
    extract_method: Optional[str] = None
    extract_time_s: Optional[float] = None
    llm_time_s: Optional[float] = None
    ocr_time_s: Optional[float] = None
    ocr_mode: Optional[str] = None
    facts_time_s: Optional[float] = None
    facts_llm_time_s: Optional[float] = None
    facts_model_used: Optional[str] = None
    classify_time_s: Optional[float] = None
    classify_llm_time_s: Optional[float] = None
    classify_model_used: Optional[str] = None


class CacheStore:
    def __init__(self, source_root: Path) -> None:
        self.source_root = source_root
        self._path = self.source_root / ".amenity-stuff" / "cache.json"
        self._data: dict[str, CacheEntry] = {}

    def load(self) -> None:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except Exception:
            self._data = {}
            return
        if not isinstance(raw, dict):
            self._data = {}
            return
        data: dict[str, CacheEntry] = {}
        for rel_path, entry in raw.items():
            if not isinstance(rel_path, str) or not isinstance(entry, dict):
                continue
            try:
                data[rel_path] = CacheEntry(
                    rel_path=rel_path,
                    size_bytes=int(entry.get("size_bytes", 0)),
                    mtime_iso=str(entry.get("mtime_iso", "")),
                    status=str(entry.get("status", "")),
                    reason=entry.get("reason"),
                    category=entry.get("category"),
                    reference_year=entry.get("reference_year"),
                    proposed_name=entry.get("proposed_name"),
                    summary=entry.get("summary"),
                    confidence=entry.get("confidence"),
                    analysis_time_s=entry.get("analysis_time_s"),
                    model_used=entry.get("model_used"),
                    summary_long=entry.get("summary_long"),
                    facts_json=entry.get("facts_json"),
                    extract_method=entry.get("extract_method"),
                    extract_time_s=entry.get("extract_time_s"),
                    llm_time_s=entry.get("llm_time_s"),
                    ocr_time_s=entry.get("ocr_time_s"),
                    ocr_mode=entry.get("ocr_mode"),
                    facts_time_s=entry.get("facts_time_s"),
                    facts_llm_time_s=entry.get("facts_llm_time_s"),
                    facts_model_used=entry.get("facts_model_used"),
                    classify_time_s=entry.get("classify_time_s"),
                    classify_llm_time_s=entry.get("classify_llm_time_s"),
                    classify_model_used=entry.get("classify_model_used"),
                )
            except Exception:
                continue
        self._data = data

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        payload = {k: asdict(v) for k, v in self._data.items()}
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self._path)

    def get_matching(self, item: ScanItem) -> Optional[CacheEntry]:
        rel = self._rel_path(item.path)
        entry = self._data.get(rel)
        if not entry:
            return None
        if entry.size_bytes != item.size_bytes:
            return None
        if entry.mtime_iso != item.mtime_iso:
            return None
        if entry.status in {"pending", "analysis", "extracting", "scanning", "classifying", "normalizing"}:
            return None
        return entry

    def upsert(self, item: ScanItem) -> None:
        rel = self._rel_path(item.path)
        self._data[rel] = CacheEntry(
            rel_path=rel,
            size_bytes=item.size_bytes,
            mtime_iso=item.mtime_iso,
            status=item.status,
            reason=item.reason,
            category=item.category,
            reference_year=item.reference_year,
            proposed_name=item.proposed_name,
            summary=item.summary,
            confidence=item.confidence,
            analysis_time_s=item.analysis_time_s,
            model_used=item.model_used,
            summary_long=item.summary_long,
            facts_json=item.facts_json,
            extract_method=item.extract_method,
            extract_time_s=item.extract_time_s,
            llm_time_s=item.llm_time_s,
            ocr_time_s=item.ocr_time_s,
            ocr_mode=item.ocr_mode,
            facts_time_s=item.facts_time_s,
            facts_llm_time_s=item.facts_llm_time_s,
            facts_model_used=item.facts_model_used,
            classify_time_s=item.classify_time_s,
            classify_llm_time_s=item.classify_llm_time_s,
            classify_model_used=item.classify_model_used,
        )

    def invalidate(self, item: ScanItem) -> None:
        rel = self._rel_path(item.path)
        self._data.pop(rel, None)

    def clear(self) -> None:
        self._data.clear()

    def _rel_path(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.source_root))
        except Exception:
            return str(path)
