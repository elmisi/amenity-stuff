from __future__ import annotations

import asyncio
import time
from dataclasses import replace
from importlib import metadata

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.widgets import DataTable, Footer, Header, Static
from textual.worker import get_current_worker

from .analyzer import AnalysisConfig, analyze_item
from .cache import CacheStore
from .config import AppConfig, save_config
from .confirm_screen import ConfirmResult, ConfirmScreen
from .discovery import DiscoveryResult, discover_providers
from .scanner import ScanItem, scan_files
from .settings import Settings
from .settings_screen import SettingsResult, SettingsScreen
from .setup_screen import SetupResult, SetupScreen
from .taxonomy import parse_taxonomy_lines


class ArchiverApp(App):
    CSS = """
    Screen { layout: vertical; }
    #top { height: 2; }
    #notes { height: auto; color: $text-muted; }
    #files { height: 1fr; }
    #details_box { height: 9; border: round $accent; background: $panel; }
    #details_text { padding: 1 2; }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("ctrl+c", "quit", "Quit"),
        ("s", "scan_toggle", "Scan"),
        ("a", "analyze_row", "Analyze row"),
        ("A", "analyze_pending", "Analyze pending"),
        ("r", "reset_row", "Reset row"),
        ("R", "reset_all", "Reset all"),
        ("f2", "settings", "Settings"),
    ]

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings
        self._discovery: DiscoveryResult | None = None
        self._scan_items: list[ScanItem] = []
        self._scan_index_by_path: dict[str, int] = {}
        self._analysis_running: bool = False
        self._analysis_worker = None
        self._analysis_cancel_requested: bool = False
        self._cache: CacheStore | None = None
        self._scan_running: bool = False
        self._scan_worker = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="top"):
            with Horizontal():
                yield Static(_app_title(), id="title")
                yield Static(f"Source: {self.settings.source_root}", id="src")
                yield Static(f"Archive: {self.settings.archive_root}", id="arc")
                yield Static(f"Max: {self.settings.max_files}", id="max")
                yield Static(f"Lang: {self.settings.output_language}", id="lang")
            yield Static("Ready.", id="notes")

        files = DataTable(id="files")
        files.add_column("Status", key="status", width=10)
        files.add_column("Type", key="kind")
        files.add_column("File", key="file")
        files.add_column("Category", key="category")
        files.add_column("Year", key="year")
        files.cursor_type = "row"
        yield files

        with Container(id="details_box"):
            with VerticalScroll():
                yield Static("", id="details_text")

        yield Footer()

    async def on_mount(self) -> None:
        initial_source = self.settings.source_root.expanduser().resolve()
        initial_archive = self.settings.archive_root.expanduser().resolve()
        if self.settings.skip_initial_setup:
            self._apply_setup(setup=SetupResult(source_root=initial_source, archive_root=initial_archive))
            asyncio.create_task(self._post_setup())
            return
        self.push_screen(
            SetupScreen(source_root=initial_source, archive_root=initial_archive),
            callback=self._on_setup_done,
            wait_for_dismiss=False,
        )

    def _on_setup_done(self, setup: SetupResult) -> None:
        self._apply_setup(setup=setup)
        asyncio.create_task(self._post_setup())

    def _apply_setup(self, *, setup: SetupResult) -> None:
        self.settings = Settings(
            source_root=setup.source_root,
            archive_root=setup.archive_root,
            max_files=self.settings.max_files,
            localai_base_url=self.settings.localai_base_url,
            recursive=self.settings.recursive,
            include_extensions=self.settings.include_extensions,
            exclude_dirnames=self.settings.exclude_dirnames,
            output_language=self.settings.output_language,
            taxonomy_lines=self.settings.taxonomy_lines,
            text_model=self.settings.text_model,
            vision_model=self.settings.vision_model,
            skip_initial_setup=self.settings.skip_initial_setup,
        )
        self.query_one("#src", Static).update(f"Source: {self.settings.source_root}")
        self.query_one("#arc", Static).update(f"Archive: {self.settings.archive_root}")
        self._cache = CacheStore(self.settings.source_root)
        self._cache.load()
        self._save_app_config()

    def _save_app_config(self) -> None:
        save_config(
            AppConfig(
                last_archive_root=str(self.settings.archive_root),
                last_source_root=str(self.settings.source_root),
                output_language=self.settings.output_language,
                taxonomy_lines=self.settings.taxonomy_lines,
                text_model=self.settings.text_model,
                vision_model=self.settings.vision_model,
            )
        )

    async def _post_setup(self) -> None:
        await self._run_discovery()
        await self._run_scan()
        self.query_one("#files", DataTable).focus()
        self._update_details_from_cursor()

    async def action_scan_toggle(self) -> None:
        await self._run_scan_toggle()

    async def action_analyze_row(self) -> None:
        await self._run_analyze_row(force=True)

    async def action_analyze_pending(self) -> None:
        await self._run_analyze_pending()

    async def action_reset_row(self) -> None:
        if self._analysis_running or self._scan_running:
            return
        files = self.query_one("#files", DataTable)
        row_index = files.cursor_row
        if row_index < 0 or row_index >= len(self._scan_items):
            return
        item = self._scan_items[row_index]
        reset = replace(
            item,
            status="pending",
            reason=None,
            category=None,
            reference_year=None,
            proposed_name=None,
            summary=None,
            confidence=None,
            analysis_time_s=None,
            model_used=None,
        )
        self._scan_items[row_index] = reset
        if self._cache:
            self._cache.invalidate(item)
            self._cache.save()
        self._render_files()
        self.query_one("#files", DataTable).move_cursor(row=row_index, column=0, scroll=True)
        self._update_details_from_cursor()
        self._render_notes()

    async def action_reset_all(self) -> None:
        if self._analysis_running or self._scan_running:
            return
        self.push_screen(
            ConfirmScreen(message="Reset ALL files and clear cache?"),
            callback=self._on_reset_all_confirmed,
            wait_for_dismiss=False,
        )

    def _on_reset_all_confirmed(self, result: ConfirmResult) -> None:
        if not result.confirmed:
            return
        self._reset_all_impl()

    def _reset_all_impl(self) -> None:
        if self._cache:
            self._cache.clear()
            self._cache.save()
        self._scan_items = [
            replace(
                it,
                status="pending",
                reason=None,
                category=None,
                reference_year=None,
                proposed_name=None,
                summary=None,
                confidence=None,
                analysis_time_s=None,
                model_used=None,
            )
            for it in self._scan_items
        ]
        self._render_files()
        self._update_details_from_cursor()
        self._render_notes()

    async def action_settings(self) -> None:
        if self._analysis_running:
            return
        if self._scan_running:
            return
        available_models: tuple[str, ...] = ()
        if self._discovery:
            for p in self._discovery.providers:
                if p.name == "ollama" and p.available and p.models:
                    available_models = p.models
                    break
        self.push_screen(
            SettingsScreen(
                output_language=self.settings.output_language,
                taxonomy_lines=self.settings.taxonomy_lines,
                text_model=self.settings.text_model,
                vision_model=self.settings.vision_model,
                archive_root=self.settings.archive_root,
                available_models=available_models,
            ),
            callback=self._on_settings_done,
            wait_for_dismiss=False,
        )

    def _on_settings_done(self, result: SettingsResult) -> None:
        self.settings = replace(
            self.settings,
            output_language=result.output_language,
            taxonomy_lines=result.taxonomy_lines,
            text_model=result.text_model,
            vision_model=result.vision_model,
            archive_root=result.archive_root,
        )
        self.query_one("#lang", Static).update(f"Lang: {self.settings.output_language}")
        self.query_one("#arc", Static).update(f"Archive: {self.settings.archive_root}")
        self._save_app_config()
        self._render_notes()

    async def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id != "files":
            return
        self._update_details(event.cursor_row)

    async def on_data_table_cell_highlighted(self, event: DataTable.CellHighlighted) -> None:
        if event.data_table.id != "files":
            return
        self._update_details(event.coordinate.row)

    async def _run_discovery(self) -> None:
        notes_widget = self.query_one("#notes", Static)
        notes_widget.update("Detecting local providers…")

        def do_discover() -> DiscoveryResult:
            return discover_providers(localai_base_url=self.settings.localai_base_url)

        worker = self.run_worker(do_discover, thread=True)
        self._discovery = await worker.wait()
        self._render_notes()

    async def _run_scan(self) -> None:
        notes_widget = self.query_one("#notes", Static)
        notes_widget.update("Scanning files…")

        files = self.query_one("#files", DataTable)
        files.clear()

        def do_scan() -> list[ScanItem]:
            return scan_files(
                self.settings.source_root,
                recursive=self.settings.recursive,
                max_files=self.settings.max_files,
                include_extensions=self.settings.include_extensions,
                exclude_dirnames=self.settings.exclude_dirnames,
                should_cancel=lambda: bool(get_current_worker().is_cancelled),
            )

        worker = self.run_worker(do_scan, thread=True, exclusive=True)
        self._scan_worker = worker
        self._scan_running = True
        self._render_notes()
        self._scan_items = await worker.wait()
        self._scan_running = False
        self._scan_worker = None
        if self._cache:
            for idx, it in enumerate(list(self._scan_items)):
                cached = self._cache.get_matching(it)
                if not cached:
                    continue
                self._scan_items[idx] = replace(
                    it,
                    status=cached.status,
                    reason=cached.reason,
                    category=cached.category,
                    reference_year=cached.reference_year,
                    proposed_name=cached.proposed_name,
                    summary=cached.summary,
                    confidence=cached.confidence if isinstance(cached.confidence, (int, float)) else None,
                    analysis_time_s=cached.analysis_time_s
                    if isinstance(cached.analysis_time_s, (int, float))
                    else None,
                    model_used=cached.model_used if isinstance(cached.model_used, str) else None,
                )
        self._render_files()
        self._render_notes()
        self._update_details_from_cursor()

    async def _run_scan_toggle(self) -> None:
        if self._scan_running and self._scan_worker is not None:
            try:
                self._scan_worker.cancel()
            except Exception:
                pass
            return
        if self._analysis_running:
            return
        await self._run_scan()

    async def _run_analyze_pending(self) -> None:
        if self._analysis_running:
            return
        if self._scan_running:
            return
        self._analysis_cancel_requested = False
        self._analysis_running = True
        self._render_notes()

        files = self.query_one("#files", DataTable)

        def mark_analysis(path_str: str) -> None:
            idx = self._scan_index_by_path.get(path_str)
            if idx is None:
                return
            it = self._scan_items[idx]
            if it.status != "pending":
                return
            self._scan_items[idx] = replace(it, status="analysis", reason=None)
            files.update_cell(path_str, "status", _status_cell("analysis"))
            if files.cursor_row == idx:
                self._update_details(idx)

        def apply_result(path_str: str, new_item: ScanItem) -> None:
            idx = self._scan_index_by_path.get(path_str)
            if idx is None:
                return
            self._scan_items[idx] = new_item
            files.update_cell(path_str, "status", _status_cell(new_item.status))
            files.update_cell(path_str, "category", new_item.category or "")
            files.update_cell(path_str, "year", new_item.reference_year or "")
            if files.cursor_row == idx:
                self._update_details(idx)
            if self._cache:
                self._cache.upsert(new_item)
                self._cache.save()

        def finish(cancelled: bool) -> None:
            if cancelled:
                for idx, it in enumerate(list(self._scan_items)):
                    if it.status != "analysis":
                        continue
                    updated = replace(it, status="pending", reason="Analysis stopped")
                    self._scan_items[idx] = updated
                    key = str(updated.path)
                    files.update_cell(key, "status", _status_cell("pending"))
            self._analysis_running = False
            self._render_notes()

        def do_analyze_background() -> None:
            taxonomy, _ = parse_taxonomy_lines(self.settings.taxonomy_lines)
            text_models, vision_models = _pick_model_candidates(self._discovery)
            if self.settings.text_model and self.settings.text_model != "auto":
                text_models = (self.settings.text_model, *tuple(m for m in text_models if m != self.settings.text_model))
            if self.settings.vision_model and self.settings.vision_model != "auto":
                vision_models = (
                    self.settings.vision_model,
                    *tuple(m for m in vision_models if m != self.settings.vision_model),
                )
            cfg = AnalysisConfig(
                output_language=self.settings.output_language,
                taxonomy=taxonomy,
                text_models=text_models,
                vision_models=vision_models,
            )
            worker = get_current_worker()
            for it in list(self._scan_items):
                if worker.is_cancelled:
                    break
                if it.status != "pending":
                    continue
                path_str = str(it.path)
                self.call_from_thread(mark_analysis, path_str)
                t0 = time.perf_counter()
                res = analyze_item(it, config=cfg)
                elapsed = time.perf_counter() - t0
                updated = replace(
                    it,
                    status=res.status,
                    reason=res.reason,
                    category=res.category,
                    reference_year=res.reference_year,
                    proposed_name=res.proposed_name,
                    summary=res.summary,
                    confidence=res.confidence,
                    analysis_time_s=elapsed,
                    model_used=res.model_used,
                )
                self.call_from_thread(apply_result, path_str, updated)
            self.call_from_thread(finish, worker.is_cancelled)

        self._analysis_worker = self.run_worker(do_analyze_background, thread=True, exclusive=True)

    async def _run_analyze_row(self, *, force: bool) -> None:
        if self._analysis_running or self._scan_running:
            return
        files = self.query_one("#files", DataTable)
        row_index = files.cursor_row
        if row_index < 0 or row_index >= len(self._scan_items):
            return
        it = self._scan_items[row_index]
        if self._cache:
            self._cache.invalidate(it)
            self._cache.save()
        reset = replace(
            it,
            status="pending" if force else it.status,
            reason=None,
            category=None,
            reference_year=None,
            proposed_name=None,
            summary=None,
            confidence=None,
            analysis_time_s=None,
            model_used=None,
        )
        self._scan_items[row_index] = reset
        path_str = str(reset.path)
        mark_item = replace(reset, status="analysis", reason=None)
        self._scan_items[row_index] = mark_item
        files.update_cell(path_str, "status", _status_cell("analysis"))
        self._update_details(row_index)
        self._render_notes()

        def do_one() -> None:
            taxonomy, _ = parse_taxonomy_lines(self.settings.taxonomy_lines)
            text_models, vision_models = _pick_model_candidates(self._discovery)
            if self.settings.text_model and self.settings.text_model != "auto":
                text_models = (self.settings.text_model, *tuple(m for m in text_models if m != self.settings.text_model))
            if self.settings.vision_model and self.settings.vision_model != "auto":
                vision_models = (
                    self.settings.vision_model,
                    *tuple(m for m in vision_models if m != self.settings.vision_model),
                )
            cfg = AnalysisConfig(
                output_language=self.settings.output_language,
                taxonomy=taxonomy,
                text_models=text_models,
                vision_models=vision_models,
            )
            t0 = time.perf_counter()
            res = analyze_item(reset, config=cfg)
            elapsed = time.perf_counter() - t0
            updated = replace(
                reset,
                status=res.status,
                reason=res.reason,
                category=res.category,
                reference_year=res.reference_year,
                proposed_name=res.proposed_name,
                summary=res.summary,
                confidence=res.confidence,
                analysis_time_s=elapsed,
                model_used=res.model_used,
            )

            def apply() -> None:
                idx = self._scan_index_by_path.get(path_str)
                if idx is None:
                    return
                self._scan_items[idx] = updated
                files.update_cell(path_str, "status", _status_cell(updated.status))
                files.update_cell(path_str, "category", updated.category or "")
                files.update_cell(path_str, "year", updated.reference_year or "")
                self._update_details(idx)
                if self._cache:
                    self._cache.upsert(updated)
                    self._cache.save()
                self._render_notes()

            self.call_from_thread(apply)

        self.run_worker(do_one, thread=True, exclusive=True)

    def _render_files(self) -> None:
        files = self.query_one("#files", DataTable)
        prev_row = files.cursor_row
        files.clear()
        self._scan_index_by_path.clear()

        for idx, item in enumerate(self._scan_items):
            rel = str(item.path)
            try:
                rel = str(item.path.relative_to(self.settings.source_root.expanduser().resolve()))
            except Exception:
                pass
            cat = item.category or ""
            year = item.reference_year or ""
            key = str(item.path)
            self._scan_index_by_path[key] = idx
            files.add_row(_status_cell(item.status), item.kind, rel, cat, year, key=key)

        if files.row_count:
            if prev_row < 0 or prev_row >= files.row_count:
                files.move_cursor(row=0, column=0, scroll=False)
            else:
                files.move_cursor(row=prev_row, column=0, scroll=False)

    def _update_details_from_cursor(self) -> None:
        table = self.query_one("#files", DataTable)
        if table.row_count == 0:
            self.query_one("#details_text", Static).update("")
            return
        self._update_details(table.cursor_row)

    def _update_details(self, row_index: int) -> None:
        if row_index < 0 or row_index >= len(self._scan_items):
            return
        item = self._scan_items[row_index]
        abs_path = str(item.path)
        rel_path = abs_path
        source_root = str(self.settings.source_root.expanduser().resolve())
        try:
            rel_path = str(item.path.relative_to(source_root))
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
        if item.model_used:
            extra_bits.append(f"Model: {item.model_used}")
        if extra_bits:
            type_state_cat_year = type_state_cat_year + " • " + " • ".join(extra_bits)
        summary = (item.summary or "").strip()
        if summary:
            summary_line = f"Summary: {summary}"
        else:
            summary_line = "Summary:"
        text = "\n".join(
            [
                f"File: {abs_path}",
                type_state_cat_year,
                f"Proposed name: {item.proposed_name or ''}",
                summary_line,
                f"Reason: {item.reason or ''}",
            ]
        ).strip()
        self.query_one("#details_text", Static).update(text)

    def _render_notes(self) -> None:
        provider = "provider: ?"
        models_part = ""
        if self._discovery:
            for p in self._discovery.providers:
                if p.name == "ollama":
                    provider = f"provider: ollama ({'OK' if p.available else 'missing'})"
                    if p.available and p.models:
                        models_part = f"models: {len(p.models)}"
                    break

        pending = sum(1 for i in self._scan_items if i.status == "pending")
        analysis = sum(1 for i in self._scan_items if i.status == "analysis")
        ready = sum(1 for i in self._scan_items if i.status == "ready")
        skipped = sum(1 for i in self._scan_items if i.status == "skipped")
        err = sum(1 for i in self._scan_items if i.status == "error")
        total = len(self._scan_items)

        state = "idle"
        if self._analysis_running:
            state = "stopping…" if self._analysis_cancel_requested else "running…"
        if self._scan_running:
            state = "scanning…"

        bits = [
            provider,
            models_part,
            f"files: {total} (·{pending} …{analysis} ✓{ready} ↷{skipped} ×{err})" if total else "files: 0",
            f"analysis: {state}",
        ]
        self.query_one("#notes", Static).update(" • ".join([b for b in bits if b]))


def _status_cell(status: str) -> str:
    marker = {
        "pending": "·",
        "analysis": "…",
        "ready": "✓",
        "skipped": "↷",
        "error": "×",
    }.get(status, "?")
    return f"{marker} {status}"

def _app_title() -> str:
    try:
        ver = metadata.version("amenity-stuff")
    except Exception:
        ver = "dev"
    return f"amenity-stuff v{ver}"


def _pick_model_candidates(discovery: DiscoveryResult | None) -> tuple[tuple[str, ...], tuple[str, ...]]:
    models: list[str] = []
    if discovery:
        for p in discovery.providers:
            if p.name == "ollama" and p.available and p.models:
                models = list(p.models)
                break

    if not models:
        return (), ()

    lower = [m.lower() for m in models]

    def has(sub: str) -> list[str]:
        return [m for m in models if sub in m.lower()]

    known_text_prefer = [
        "qwen2.5:7b-instruct",
        "qwen2.5:14b-instruct",
        "llama3.1:8b-instruct",
        "llama3.2:3b-instruct",
        "mistral:7b-instruct",
        "gemma2:9b-instruct",
        "phi3:medium",
    ]
    text_candidates: list[str] = [m for m in known_text_prefer if m in models]
    for m in models:
        ml = m.lower()
        if m in text_candidates:
            continue
        if any(v in ml for v in ("vision", "llava", "moondream", "minicpm", "bakllava")):
            continue
        if "instruct" in ml or "chat" in ml:
            text_candidates.append(m)

    # Vision candidates.
    known_vision_prefer = [
        "moondream:latest",
        "llama3.2-vision:latest",
        "llava:latest",
        "bakllava:latest",
        "minicpm-v:latest",
    ]
    vision_candidates: list[str] = [m for m in known_vision_prefer if m in models]
    for m in models:
        ml = m.lower()
        if m in vision_candidates:
            continue
        if any(v in ml for v in ("vision", "llava", "moondream", "minicpm", "bakllava")):
            vision_candidates.append(m)

    return tuple(text_candidates[:4]), tuple(vision_candidates[:3])
