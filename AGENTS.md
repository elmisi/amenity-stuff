# Agent Guidelines (amenity-stuff)

This repo is a Textual (Python) TUI that scans a source folder, extracts content (PDF / images), calls a local LLM (Ollama) for structured classification, and (later) will apply rename/move operations into an archive.

These guidelines document the conventions used so far and should be followed for future development.

## General Principles
- Prefer small, focused changes; avoid incidental formatting churn.
- Fix root causes rather than layering workarounds.
- Keep the project general-purpose; avoid dataset-specific rules unless they can be expressed as user-configurable heuristics.
- Maintain an interactive TUI: never block the Textual event loop with I/O, OCR, or LLM calls.

## Code Structure
- Keep UI concerns separate from analysis logic:
  - UI rendering/formatting helpers live in dedicated `ui_*.py` modules.
  - Analysis / extraction / OCR / LLM prompt+parse live outside the UI layer.
- Prefer “data in / data out” functions for logic that doesn’t need `App` context (easier to test and refactor).
- Use dataclasses (or TypedDicts) for structured results and configuration to reduce “loose dict” usage.

## Textual / TUI Conventions
- Use workers/threads for long-running operations (scan, extraction, OCR, LLM).
- UI updates should be scheduled from the main thread (e.g. via `call_from_thread` or safe message passing), not performed directly inside worker threads.
- Prefer a single source of truth for per-file state; the table is a view of that state.
- Keyboard shortcuts should be discoverable:
  - Document them in `README.md`.
  - Keep bindings stable; when they change, update docs in the same PR/commit series.

## Refactoring Rules (Behavior-Preserving)
When refactoring, do not change functionality unless explicitly requested:
- Avoid altering prompts, heuristics, defaults, or UX flows.
- Move code in small steps:
  1) extract helper with identical logic,
  2) replace call sites,
  3) delete dead code.
- Keep function signatures stable unless there is a clear simplification.
- Ensure imports remain acyclic and modules have single, clear responsibility.

## Naming & Typing
- Use descriptive names (`analysis_config`, `extract_result`, `task_state`) over abbreviations.
- Prefer `pathlib.Path` for filesystem paths.
- Add type hints on public functions and key internal helpers; keep types pragmatic (don’t over-annotate).

## Performance & Safety
- Measure before optimizing: record timing breakdowns (extract/OCR/LLM) in results and show them in the details panel.
- Protect the user’s data:
  - Default to local-first behavior.
  - When adding providers/models, clearly document where content is sent.
- OCR is optional and may be slow; keep it configurable (mode/time budgets) and fail gracefully.

## Configuration & Cache
- Persist user configuration in `~/.config/amenity-stuff/config.json`.
- Cache analysis results per-source under `<source>/.amenity-stuff/` keyed by `(path, size, mtime)`.
- Cache invalidation should be explicit and user-driven (reset row / reset all / force reanalysis).

## Commits
- Commit logically grouped changes with clear messages (e.g. `tui: refactor settings screen`).
- Keep refactors separate from behavior changes when possible.

