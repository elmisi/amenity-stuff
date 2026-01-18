from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import shutil
import time
from typing import Optional, Tuple

from .cache import CacheStore
from .scanner import ScanItem
from .settings import Settings


def archive_dest_for_item(item: ScanItem, *, settings: Settings) -> Tuple[Path, str]:
    """Return (dest_path_abs, dest_rel_path_str) for an item."""
    category = (item.category or "").strip() or "unknown"
    year = (item.reference_year or "").strip() or settings.undated_folder_name
    if item.status == "classified" and item.proposed_name:
        filename = item.proposed_name
    else:
        filename = item.path.name
    dest_rel = Path(category) / year / filename
    return settings.archive_root / dest_rel, str(dest_rel)


def unique_destination(dest_path: Path) -> Path:
    """Avoid overwriting existing files by appending ' (n)' before the extension."""
    if not dest_path.exists():
        return dest_path
    parent = dest_path.parent
    stem = dest_path.stem
    suffix = dest_path.suffix
    n = 2
    while True:
        cand = parent / f"{stem} ({n}){suffix}"
        if not cand.exists():
            return cand
        n += 1


def move_file_best_effort(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    # shutil.move handles cross-device moves (copy+delete).
    shutil.move(str(src), str(dst))


def append_move_log(*, archive_root: Path, record: dict) -> None:
    base = archive_root / ".amenity-stuff"
    base.mkdir(parents=True, exist_ok=True)
    log_path = base / "moves.jsonl"
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def apply_archive_move(
    item: ScanItem,
    *,
    settings: Settings,
    source_cache: Optional[CacheStore],
    archive_cache: Optional[CacheStore],
    now_iso: str,
) -> Tuple[ScanItem, str]:
    """Move a file into the archive and update caches. Returns (updated_item_in_source, dest_rel_path)."""
    dest_path, dest_rel = archive_dest_for_item(item, settings=settings)
    dest_path = unique_destination(dest_path)
    dest_rel_final = str(dest_path.relative_to(settings.archive_root))

    t0 = time.perf_counter()
    move_file_best_effort(item.path, dest_path)
    elapsed = time.perf_counter() - t0

    try:
        stat = dest_path.stat()
        size_bytes = stat.st_size
        mtime_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(stat.st_mtime))
    except Exception:
        size_bytes = item.size_bytes
        mtime_iso = item.mtime_iso

    actual_name = dest_path.name

    moved_source = replace(
        item,
        status="moved",
        moved_to=str(dest_path),
        analysis_time_s=elapsed,
        proposed_name=actual_name if (item.status == "classified" and item.proposed_name) else item.proposed_name,
    )

    if source_cache:
        source_cache.upsert(moved_source)
        source_cache.save()

    if archive_cache:
        archived_item = replace(
            item,
            path=dest_path,
            size_bytes=size_bytes,
            mtime_iso=mtime_iso,
            moved_to=None,
            proposed_name=actual_name if (item.status == "classified" and item.proposed_name) else item.proposed_name,
        )
        archive_cache.upsert(archived_item)
        archive_cache.save()

    append_move_log(
        archive_root=settings.archive_root,
        record={
            "ts": now_iso,
            "from": str(item.path),
            "to": str(dest_path),
            "status": item.status,
            "category": item.category,
            "year": item.reference_year,
            "proposed_name": archived_filename_for_log(item, actual_name),
        },
    )

    return moved_source, dest_rel_final


def archived_filename_for_log(item: ScanItem, actual_name: str) -> str:
    if item.status == "classified":
        return actual_name
    return item.path.name

