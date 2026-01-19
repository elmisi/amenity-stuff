from __future__ import annotations

from dataclasses import dataclass

from .discovery import DiscoveryResult
from .scanner import ScanItem
from .task_state import TaskState


@dataclass(frozen=True)
class StatusCounts:
    total: int
    pending: int
    scanning: int
    scanned: int
    classifying: int
    classified: int
    moving: int
    moved: int
    skipped: int
    error: int


def count_statuses(items: list[ScanItem]) -> StatusCounts:
    pending = sum(1 for i in items if i.status == "pending")
    scanning = sum(1 for i in items if i.status == "scanning")
    scanned = sum(1 for i in items if i.status == "scanned")
    classifying = sum(1 for i in items if i.status == "classifying")
    classified = sum(1 for i in items if i.status == "classified")
    moving = sum(1 for i in items if i.status == "moving")
    moved = sum(1 for i in items if i.status == "moved")
    skipped = sum(1 for i in items if i.status == "skipped")
    error = sum(1 for i in items if i.status == "error")
    total = len(items)
    return StatusCounts(
        total=total,
        pending=pending,
        scanning=scanning,
        scanned=scanned,
        classifying=classifying,
        classified=classified,
        moving=moving,
        moved=moved,
        skipped=skipped,
        error=error,
    )


def derive_task_state(*, counts: StatusCounts, analysis: TaskState, scan: TaskState, archive: TaskState) -> str:
    state = "idle"
    if analysis.running:
        if analysis.cancel_requested:
            state = "stopping…"
        elif counts.classifying:
            state = "classifying…"
        elif counts.scanning:
            state = "scanning…"
        else:
            state = "running…"
    if scan.running:
        state = "scanning…"
    if archive.running:
        state = "archiving…"
    return state


def provider_problem(discovery: DiscoveryResult | None) -> tuple[str | None, str]:
    """Return (problem, severity) for the active local setup."""
    if not discovery:
        return ("Detecting providers…", "info")
    for p in discovery.providers:
        if p.name != "ollama":
            continue
        if not p.available:
            return ("Ollama is not available", "error")
        if not p.models:
            return ("No models found in Ollama", "error")
        return (None, "ok")
    return ("Ollama is not configured", "error")


def banner_for_state(
    *,
    state: str,
    scanning: int,
    classifying: int,
    moving: int,
    problem: str | None,
    severity: str,
) -> tuple[str, str]:
    if severity == "error":
        base = problem or "Error"
        return (f"ERROR: {base}", "bold white on red")
    if severity == "info" and state == "idle":
        return ("Status: idle (detecting providers…)", "bold black on grey70")
    if state == "idle":
        return ("Status: idle (no running task)", "bold black on grey70")
    if state.startswith("stopping"):
        return ("STOPPING…", "bold white on red")
    if state.startswith("scanning") and scanning:
        msg = "RUNNING: scanning pending files…"
        if problem:
            msg += f" • {problem}"
        return (msg, "bold white on blue")
    if state.startswith("classifying") and classifying:
        msg = "RUNNING: classifying scanned files…"
        if problem:
            msg += f" • {problem}"
        return (msg, "bold white on blue")
    if state.startswith("archiving") and moving:
        msg = "RUNNING: moving files to archive…"
        if problem:
            msg += f" • {problem}"
        return (msg, "bold white on blue")
    if state.startswith("archiving"):
        msg = "RUNNING: archiving…"
        if problem:
            msg += f" • {problem}"
        return (msg, "bold white on blue")
    if state.startswith("scanning"):
        msg = "RUNNING: scanning directory…"
        if problem:
            msg += f" • {problem}"
        return (msg, "bold white on blue")
    msg = "RUNNING…"
    if problem:
        msg += f" • {problem}"
    return (msg, "bold white on blue")

