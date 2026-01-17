from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import os
from pathlib import Path
from typing import Callable, Iterable, Optional


@dataclass(frozen=True)
class ScanItem:
    path: Path
    kind: str
    size_bytes: int
    mtime_iso: str
    status: str = "pending"
    reason: Optional[str] = None
    category: Optional[str] = None
    reference_year: Optional[str] = None
    proposed_name: Optional[str] = None
    summary: Optional[str] = None
    confidence: Optional[float] = None
    analysis_time_s: Optional[float] = None  # last operation elapsed (best-effort)
    model_used: Optional[str] = None  # last model used (best-effort)
    summary_long: Optional[str] = None
    facts_json: Optional[str] = None
    llm_raw_output: Optional[str] = None
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


def _infer_kind(path: Path) -> Optional[str]:
    ext = path.suffix.lower().lstrip(".")
    if ext == "pdf":
        return "pdf"
    if ext in {"jpg", "jpeg", "png"}:
        return "image"
    if ext in {"doc", "docx", "xls", "xlsx"}:
        return ext
    if ext in {"json", "md", "txt", "rtf", "svg"}:
        return ext
    return None


def scan_files(
    source_root: Path,
    *,
    recursive: bool,
    include_extensions: Iterable[str],
    exclude_dirnames: Iterable[str],
    should_cancel: Optional[Callable[[], bool]] = None,
) -> list[ScanItem]:
    include = {ext.lower().lstrip(".") for ext in include_extensions}
    exclude_dirs = set(exclude_dirnames)
    items: list[ScanItem] = []

    source_root = source_root.expanduser().resolve()
    if not source_root.exists():
        return [
            ScanItem(
                path=source_root,
                kind="unknown",
                size_bytes=0,
                mtime_iso="",
                status="error",
                reason="source_root does not exist",
            )
        ]
    if not source_root.is_dir():
        return [
            ScanItem(
                path=source_root,
                kind=_infer_kind(source_root) or "unknown",
                size_bytes=source_root.stat().st_size if source_root.exists() else 0,
                mtime_iso=_mtime_iso(source_root) if source_root.exists() else "",
                status="error",
                reason="source_root is not a directory",
            )
        ]

    def consider_file(path: Path) -> None:
        if should_cancel and should_cancel():
            return
        ext = path.suffix.lower().lstrip(".")
        if ext not in include:
            return
        kind = _infer_kind(path)
        if not kind:
            return
        try:
            stat = path.stat()
            items.append(
                ScanItem(
                    path=path,
                    kind=kind,
                    size_bytes=stat.st_size,
                    mtime_iso=datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
                )
            )
        except OSError as exc:
            items.append(
                ScanItem(
                    path=path,
                    kind=kind,
                    size_bytes=0,
                    mtime_iso="",
                    status="error",
                    reason=f"stat failed: {type(exc).__name__}",
                )
            )

    if not recursive:
        for child in sorted(source_root.iterdir()):
            if should_cancel and should_cancel():
                break
            if child.is_file():
                consider_file(child)
        return items

    for dirpath, dirnames, filenames in os.walk(source_root):
        if should_cancel and should_cancel():
            break
        dirnames[:] = [d for d in dirnames if d not in exclude_dirs]
        for filename in filenames:
            if should_cancel and should_cancel():
                break
            consider_file(Path(dirpath) / filename)

    return items


def _mtime_iso(path: Path) -> str:
    try:
        stat = path.stat()
        return datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds")
    except OSError:
        return ""
