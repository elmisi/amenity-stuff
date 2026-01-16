from __future__ import annotations

import asyncio
import time
from dataclasses import replace

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal
from textual.widgets import DataTable, Footer, Header, Static
from textual.worker import get_current_worker

from .analyzer import analyze_item
from .cache import CacheStore
from .config import AppConfig, save_config
from .confirm_screen import ConfirmResult, ConfirmScreen
from .discovery import DiscoveryResult, discover_providers
from .normalizer import normalize_items
from .scanner import ScanItem, scan_files
from .settings import Settings
from .settings_screen import SettingsResult, SettingsScreen
from .setup_screen import SetupResult, SetupScreen
from .taxonomy import parse_taxonomy_lines
from .ui_status import app_title, notes_line, provider_summary, status_cell
from .model_selection import pick_model_candidates
from .task_builders import build_analysis_config
from .ui_details import render_details
from .task_state import TaskState


class ArchiverApp(App):
    CSS = """
    Screen { layout: vertical; }
    #top { height: 2; }
    #notes { height: auto; color: $text-muted; }
    #files { height: 1fr; }
    #details_box { height: 9; border: round $accent; background: $panel; }
    #details_text { padding: 0 2; }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("ctrl+c", "quit", "Quit"),
        ("s", "scan", "Scan"),
        ("a", "analyze_row", "Analyze row"),
        ("A", "analyze_pending", "Analyze pending"),
        ("N", "normalize_ready", "Normalize ready"),
        ("p", "stop_analysis", "Stop analysis"),
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
        self._analysis_task = TaskState()
        self._cache: CacheStore | None = None
        self._scan_task = TaskState()
        self._provider_line: str = ""

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="top"):
            with Horizontal():
                yield Static(app_title(), id="title")
                yield Static(f"Source: {self.settings.source_root}", id="src")
                yield Static(f"Archive: {self.settings.archive_root}", id="arc")
                yield Static(f"Max: {self.settings.max_files}", id="max")
                yield Static(f"Lang: {self.settings.output_language}", id="lang")
            yield Static("Ready.", id="notes")

        files = DataTable(id="files")
        files.add_column("St", key="status", width=6)
        files.add_column("Type", key="kind")
        files.add_column("File", key="file")
        files.add_column("Category", key="category")
        files.add_column("Year", key="year")
        files.cursor_type = "row"
        yield files

        with Container(id="details_box"):
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
            filename_separator=self.settings.filename_separator,
            ocr_mode=self.settings.ocr_mode,
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
                filename_separator=self.settings.filename_separator,
                ocr_mode=self.settings.ocr_mode,
            )
        )

    async def _post_setup(self) -> None:
        await self._run_discovery()
        await self._run_scan()
        self.query_one("#files", DataTable).focus()
        self._update_details_from_cursor()

    async def action_scan(self) -> None:
        await self._run_scan()

    async def action_analyze_row(self) -> None:
        await self._run_analyze_row(force=True)

    async def action_analyze_pending(self) -> None:
        await self._run_analyze_pending()

    async def action_normalize_ready(self) -> None:
        await self._run_normalize_ready()

    async def action_stop_analysis(self) -> None:
        if not self._analysis_task.running or self._analysis_task.worker is None:
            return
        self._analysis_task.request_cancel()
        self._render_notes()

    async def action_reset_row(self) -> None:
        if self._analysis_task.running or self._scan_task.running:
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
            summary_long=None,
            facts_json=None,
            confidence=None,
            analysis_time_s=None,
            model_used=None,
            extract_method=None,
            extract_time_s=None,
            llm_time_s=None,
            ocr_time_s=None,
            ocr_mode=None,
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
        if self._analysis_task.running or self._scan_task.running:
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
                summary_long=None,
                facts_json=None,
                confidence=None,
                analysis_time_s=None,
                model_used=None,
                extract_method=None,
                extract_time_s=None,
                llm_time_s=None,
                ocr_time_s=None,
                ocr_mode=None,
            )
            for it in self._scan_items
        ]
        self._render_files()
        self._update_details_from_cursor()
        self._render_notes()

    async def action_settings(self) -> None:
        if self._analysis_task.running:
            return
        if self._scan_task.running:
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
                filename_separator=self.settings.filename_separator,
                ocr_mode=self.settings.ocr_mode,
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
            filename_separator=result.filename_separator,
            ocr_mode=result.ocr_mode,
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
        self._provider_line = provider_summary(self._discovery, self.settings, model_picker=pick_model_candidates)
        self.query_one("#title", Static).update(app_title(provider_line=self._provider_line))
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
            )

        worker = self.run_worker(do_scan, thread=True, exclusive=True)
        self._scan_task.start(worker)
        self._render_notes()
        self._scan_items = await worker.wait()
        self._scan_task.finish()
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
                    summary_long=cached.summary_long if isinstance(cached.summary_long, str) else None,
                    facts_json=cached.facts_json if isinstance(cached.facts_json, str) else None,
                    extract_method=cached.extract_method if isinstance(cached.extract_method, str) else None,
                    extract_time_s=cached.extract_time_s if isinstance(cached.extract_time_s, (int, float)) else None,
                    llm_time_s=cached.llm_time_s if isinstance(cached.llm_time_s, (int, float)) else None,
                    ocr_time_s=cached.ocr_time_s if isinstance(cached.ocr_time_s, (int, float)) else None,
                    ocr_mode=cached.ocr_mode if isinstance(cached.ocr_mode, str) else None,
                )
        self._render_files()
        self._render_notes()
        self._update_details_from_cursor()

    async def _run_analyze_pending(self) -> None:
        if self._analysis_task.running:
            return
        if self._scan_task.running:
            return
        self._analysis_task.cancel_requested = False
        self._analysis_task.running = True
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
            files.update_cell(path_str, "status", status_cell("analysis"))
            if files.cursor_row == idx:
                self._update_details(idx)

        def apply_result(path_str: str, new_item: ScanItem) -> None:
            idx = self._scan_index_by_path.get(path_str)
            if idx is None:
                return
            self._scan_items[idx] = new_item
            files.update_cell(path_str, "status", status_cell(new_item.status))
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
                    files.update_cell(key, "status", status_cell("pending"))
            self._analysis_task.running = False
            self._render_notes()

        def do_analyze_background() -> None:
            taxonomy, _ = parse_taxonomy_lines(self.settings.taxonomy_lines)
            cfg = build_analysis_config(settings=self.settings, discovery=self._discovery, taxonomy=taxonomy)
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
                    summary_long=res.summary_long,
                    facts_json=res.facts_json,
                    extract_method=res.extract_method,
                    extract_time_s=res.extract_time_s,
                    llm_time_s=res.llm_time_s,
                    ocr_time_s=res.ocr_time_s,
                    ocr_mode=res.ocr_mode,
                )
                self.call_from_thread(apply_result, path_str, updated)
            self.call_from_thread(finish, worker.is_cancelled)

        worker = self.run_worker(do_analyze_background, thread=True, exclusive=True)
        self._analysis_task.worker = worker

    async def _run_normalize_ready(self) -> None:
        if self._analysis_task.running or self._scan_task.running:
            return
        if not self._discovery:
            return
        taxonomy, _ = parse_taxonomy_lines(self.settings.taxonomy_lines)
        text_models, _ = pick_model_candidates(self._discovery)
        if self.settings.text_model and self.settings.text_model != "auto":
            text_models = (self.settings.text_model, *tuple(m for m in text_models if m != self.settings.text_model))
        model = text_models[0] if text_models else "qwen2.5:7b-instruct"

        targets = [it for it in self._scan_items if it.status in {"ready", "normalized"}]
        if not targets:
            return

        self._analysis_task.cancel_requested = False
        self._analysis_task.running = True
        self._render_notes()

        files = self.query_one("#files", DataTable)

        def mark_normalizing(path_str: str) -> None:
            idx = self._scan_index_by_path.get(path_str)
            if idx is None:
                return
            it = self._scan_items[idx]
            if it.status not in {"ready", "normalized"}:
                return
            self._scan_items[idx] = replace(it, status="normalizing", reason=None)
            files.update_cell(path_str, "status", status_cell("normalizing"))
            if files.cursor_row == idx:
                self._update_details(idx)

        def apply_norm(path_str: str, updated: ScanItem) -> None:
            idx = self._scan_index_by_path.get(path_str)
            if idx is None:
                return
            self._scan_items[idx] = updated
            files.update_cell(path_str, "status", status_cell(updated.status))
            files.update_cell(path_str, "category", updated.category or "")
            files.update_cell(path_str, "year", updated.reference_year or "")
            if files.cursor_row == idx:
                self._update_details(idx)
            if self._cache:
                self._cache.upsert(updated)
                self._cache.save()

        def finish(cancelled: bool) -> None:
            if cancelled:
                for idx, it in enumerate(list(self._scan_items)):
                    if it.status != "normalizing":
                        continue
                    updated = replace(it, status="ready", reason="Normalization stopped")
                    self._scan_items[idx] = updated
                    key = str(updated.path)
                    files.update_cell(key, "status", status_cell("ready"))
            self._analysis_task.running = False
            self._render_notes()

        def do_normalize_background() -> None:
            worker = get_current_worker()
            for it in targets:
                if worker.is_cancelled:
                    break
                self.call_from_thread(mark_normalizing, str(it.path))
            if worker.is_cancelled:
                self.call_from_thread(finish, True)
                return
            res = normalize_items(
                items=targets,
                model=model,
                base_url="http://localhost:11434",
                taxonomy=taxonomy,
                output_language=self.settings.output_language,
                filename_separator=self.settings.filename_separator,
            )
            if res.error:
                for it in targets:
                    if worker.is_cancelled:
                        break
                    key = str(it.path)
                    idx = self._scan_index_by_path.get(key)
                    if idx is None:
                        continue
                    cur = self._scan_items[idx]
                    if cur.status == "normalizing":
                        self.call_from_thread(
                            apply_norm,
                            key,
                            replace(cur, status="ready", reason=f"Normalization error: {res.error}"),
                        )
                self.call_from_thread(finish, worker.is_cancelled)
                return

            for it in targets:
                if worker.is_cancelled:
                    break
                key = str(it.path)
                upd = res.by_path.get(key)
                if not upd:
                    continue
                idx = self._scan_index_by_path.get(key)
                if idx is None:
                    continue
                cur = self._scan_items[idx]
                updated = replace(
                    cur,
                    status="normalized",
                    category=upd.get("category") or cur.category,
                    reference_year=upd.get("reference_year") or cur.reference_year,
                    proposed_name=upd.get("proposed_name") or cur.proposed_name,
                    summary=upd.get("summary") or cur.summary,
                    model_used=str(upd.get("model_used") or cur.model_used or ""),
                    reason=None,
                )
                self.call_from_thread(apply_norm, key, updated)
            self.call_from_thread(finish, worker.is_cancelled)

        worker = self.run_worker(do_normalize_background, thread=True, exclusive=True)
        self._analysis_task.worker = worker

    async def _run_analyze_row(self, *, force: bool) -> None:
        if self._analysis_task.running or self._scan_task.running:
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
            summary_long=None,
            facts_json=None,
            confidence=None,
            analysis_time_s=None,
            model_used=None,
            extract_method=None,
            extract_time_s=None,
            llm_time_s=None,
            ocr_time_s=None,
            ocr_mode=None,
        )
        self._scan_items[row_index] = reset
        path_str = str(reset.path)
        mark_item = replace(reset, status="analysis", reason=None)
        self._scan_items[row_index] = mark_item
        files.update_cell(path_str, "status", status_cell("analysis"))
        self._update_details(row_index)
        self._render_notes()

        def do_one() -> None:
            taxonomy, _ = parse_taxonomy_lines(self.settings.taxonomy_lines)
            cfg = build_analysis_config(settings=self.settings, discovery=self._discovery, taxonomy=taxonomy)
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
                summary_long=res.summary_long,
                facts_json=res.facts_json,
                extract_method=res.extract_method,
                extract_time_s=res.extract_time_s,
                llm_time_s=res.llm_time_s,
                ocr_time_s=res.ocr_time_s,
                ocr_mode=res.ocr_mode,
            )

            def apply() -> None:
                idx = self._scan_index_by_path.get(path_str)
                if idx is None:
                    return
                self._scan_items[idx] = updated
                files.update_cell(path_str, "status", status_cell(updated.status))
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
            files.add_row(status_cell(item.status), item.kind, rel, cat, year, key=key)

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
        details_widget = self.query_one("#details_text", Static)
        width = details_widget.size.width or (self.size.width - 4)
        details_widget.update(
            # Let the widget clip to the fixed panel height; avoid adding our own “…” line.
            render_details(item, settings=self.settings, max_width=max(40, width))
        )

    def _render_notes(self) -> None:
        pending = sum(1 for i in self._scan_items if i.status == "pending")
        analysis = sum(1 for i in self._scan_items if i.status == "analysis")
        ready = sum(1 for i in self._scan_items if i.status == "ready")
        normalizing = sum(1 for i in self._scan_items if i.status == "normalizing")
        normalized = sum(1 for i in self._scan_items if i.status == "normalized")
        skipped = sum(1 for i in self._scan_items if i.status == "skipped")
        err = sum(1 for i in self._scan_items if i.status == "error")
        total = len(self._scan_items)

        state = "idle"
        if self._analysis_task.running:
            if self._analysis_task.cancel_requested:
                state = "stopping…"
            elif normalizing:
                state = "normalizing…"
            elif analysis:
                state = "analyzing…"
            else:
                state = "running…"
        if self._scan_task.running:
            state = "scanning…"

        self.query_one("#notes", Static).update(
            notes_line(
                scan_items_total=total,
                pending=pending,
                analyzing=analysis,
                ready=ready,
                normalizing=normalizing,
                normalized=normalized,
                skipped=skipped,
                error=err,
                task_state=state,
            )
        )
