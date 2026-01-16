from __future__ import annotations

import asyncio
import time
from dataclasses import replace

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, VerticalScroll
from textual.widgets import DataTable, Footer, Header, Static
from textual.worker import get_current_worker

from .analyzer import AnalysisConfig, analyze_item
from .cache import CacheStore
from .config import AppConfig, save_config
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
        ("s", "rescan", "Rescan"),
        ("a", "analyze", "Analyze"),
        ("c", "cancel_analysis", "Stop analysis"),
        ("R", "reanalyze_row", "Reanalyze row"),
        ("A", "reanalyze_all", "Reanalyze all"),
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

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="top"):
            with Horizontal():
                yield Static(f"Source: {self.settings.source_root}", id="src")
                yield Static(f"Archive: {self.settings.archive_root}", id="arc")
                yield Static(f"Max files: {self.settings.max_files}", id="max")
                yield Static(f"Lang: {self.settings.output_language}", id="lang")
            yield Static("Ready.", id="notes")

        files = DataTable(id="files")
        files.add_column("Status", key="status", width=10)
        files.add_column("Type", key="kind")
        files.add_column("File", key="file")
        files.add_column("Category", key="category")
        files.add_column("Year", key="year")
        files.add_column("Reason", key="reason")
        files.cursor_type = "row"
        yield files

        with Container(id="details_box"):
            with VerticalScroll():
                yield Static("", id="details_text")

        yield Footer()

    async def on_mount(self) -> None:
        initial_source = self.settings.source_root.expanduser().resolve()
        initial_archive = self.settings.archive_root.expanduser().resolve()
        self.push_screen(
            SetupScreen(source_root=initial_source, archive_root=initial_archive),
            callback=self._on_setup_done,
            wait_for_dismiss=False,
        )

    def _on_setup_done(self, setup: SetupResult) -> None:
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
        )
        save_config(
            AppConfig(
                last_archive_root=str(self.settings.archive_root),
                last_source_root=str(self.settings.source_root),
                output_language=self.settings.output_language,
                taxonomy_lines=self.settings.taxonomy_lines,
            )
        )
        self.query_one("#src", Static).update(f"Source: {self.settings.source_root}")
        self.query_one("#arc", Static).update(f"Archive: {self.settings.archive_root}")
        self._cache = CacheStore(self.settings.source_root)
        self._cache.load()

        asyncio.create_task(self._post_setup())

    async def _post_setup(self) -> None:
        await self._run_discovery()
        await self._run_scan()
        self.query_one("#files", DataTable).focus()
        self._update_details_from_cursor()

    async def action_rescan(self) -> None:
        await self._run_scan()

    async def action_analyze(self) -> None:
        await self._run_analyze()

    async def action_cancel_analysis(self) -> None:
        if not self._analysis_running or self._analysis_worker is None:
            return
        self._analysis_cancel_requested = True
        try:
            self._analysis_worker.cancel()
        except Exception:
            pass
        self._render_notes()

    async def action_reanalyze_row(self) -> None:
        if self._analysis_running:
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

    async def action_reanalyze_all(self) -> None:
        if self._analysis_running:
            return
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
        self.push_screen(
            SettingsScreen(
                output_language=self.settings.output_language,
                taxonomy_lines=self.settings.taxonomy_lines,
            ),
            callback=self._on_settings_done,
            wait_for_dismiss=False,
        )

    def _on_settings_done(self, result: SettingsResult) -> None:
        self.settings = replace(
            self.settings,
            output_language=result.output_language,
            taxonomy_lines=result.taxonomy_lines,
        )
        self.query_one("#lang", Static).update(f"Lang: {self.settings.output_language}")
        save_config(
            AppConfig(
                last_archive_root=str(self.settings.archive_root),
                last_source_root=str(self.settings.source_root),
                output_language=self.settings.output_language,
                taxonomy_lines=self.settings.taxonomy_lines,
            )
        )
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
            )

        worker = self.run_worker(do_scan, thread=True)
        self._scan_items = await worker.wait()
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

    async def _run_analyze(self) -> None:
        if self._analysis_running:
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
            files.update_cell(path_str, "reason", "")
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
            files.update_cell(path_str, "reason", new_item.reason or "")
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
                    files.update_cell(key, "reason", updated.reason or "")
            self._analysis_running = False
            self._render_notes()

        def do_analyze_background() -> None:
            taxonomy, _ = parse_taxonomy_lines(self.settings.taxonomy_lines)
            text_models, vision_models = _pick_model_candidates(self._discovery)
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
            files.add_row(_status_cell(item.status), item.kind, rel, cat, year, item.reason or "", key=key)

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
        parts: list[str] = []
        if self._discovery:
            parts.extend(self._discovery.notes)
            if self._discovery.chosen_text:
                parts.append(f"Text provider (auto): {self._discovery.chosen_text}")
            if self._discovery.chosen_vision:
                parts.append(f"Vision provider (auto): {self._discovery.chosen_vision}")
        if self._analysis_running:
            if self._analysis_cancel_requested:
                parts.append("Analysis: stop requested…")
            else:
                parts.append("Analysis: running…")
        if self._scan_items:
            pending = sum(1 for i in self._scan_items if i.status == "pending")
            ready = sum(1 for i in self._scan_items if i.status == "ready")
            skipped = sum(1 for i in self._scan_items if i.status == "skipped")
            analysis = sum(1 for i in self._scan_items if i.status == "analysis")
            err = sum(1 for i in self._scan_items if i.status == "error")
            parts.append(
                f"Files: {len(self._scan_items)} (pending={pending}, analysis={analysis}, ready={ready}, skipped={skipped}, error={err})"
            )
        if not parts:
            parts = ["No notes."]
        self.query_one("#notes", Static).update(" ".join(parts))


def _status_cell(status: str) -> str:
    marker = {
        "pending": "·",
        "analysis": "…",
        "ready": "✓",
        "skipped": "↷",
        "error": "×",
    }.get(status, "?")
    return f"{marker} {status}"


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
