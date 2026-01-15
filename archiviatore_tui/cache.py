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
        if entry.status in {"analysis", "pending"}:
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
