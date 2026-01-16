from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Footer, Header, OptionList, Static, TextArea

from .archive_picker_screen import ArchivePickerResult, ArchivePickerScreen
from .taxonomy import DEFAULT_TAXONOMY_LINES, parse_taxonomy_lines


@dataclass(frozen=True)
class SettingsResult:
    output_language: str
    taxonomy_lines: tuple[str, ...]
    text_model: str
    vision_model: str
    filename_separator: str
    archive_root: Path


class SettingsScreen(ModalScreen[SettingsResult]):
    CSS = """
    SettingsScreen { layout: vertical; }
    #intro { height: auto; color: $text-muted; }
    #options { height: auto; border: round $accent; background: $panel; }
    #taxonomy_label { height: auto; padding: 1 0 0 0; }
    #taxonomy { height: 1fr; border: round $accent; }
    #errors { height: auto; color: $error; }
    """

    BINDINGS = [
        ("ctrl+s", "save", "Save"),
        ("escape", "cancel", "Cancel"),
        ("q", "cancel", "Cancel"),
        ("o", "focus_options", "Options"),
        ("t", "focus_taxonomy", "Taxonomy"),
        ("r", "reset_taxonomy", "Reset taxonomy"),
    ]

    def __init__(
        self,
        *,
        output_language: str,
        taxonomy_lines: tuple[str, ...],
        text_model: str,
        vision_model: str,
        filename_separator: str,
        archive_root: Path,
        available_models: tuple[str, ...],
    ) -> None:
        super().__init__()
        self._output_language = output_language if output_language in {"auto", "it", "en"} else "auto"
        self._taxonomy_lines = taxonomy_lines or DEFAULT_TAXONOMY_LINES
        self._text_model = text_model or "auto"
        self._vision_model = vision_model or "auto"
        self._archive_root = archive_root
        self._available_models = available_models
        self._filename_separator = filename_separator if filename_separator in {"space", "underscore", "dash"} else "space"

        self._text_options = ("auto",) + tuple(self._filter_text_models(available_models))
        self._vision_options = ("auto",) + tuple(self._filter_vision_models(available_models))
        self._lang_options = ("auto", "it", "en")
        self._sep_options = ("space", "underscore", "dash")

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Static(
            "Settings: ↑/↓ select • Enter/←/→ change • t taxonomy • Ctrl+S save • Esc cancel",
            id="intro",
        )
        yield OptionList(*self._render_options(), id="options")
        yield Static("Taxonomy (one category per line): name | description | examples", id="taxonomy_label")
        yield TextArea("\n".join(self._taxonomy_lines).strip() + "\n", id="taxonomy", tab_behavior="indent")
        yield Static("", id="errors")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#options", OptionList).focus()

    def action_focus_options(self) -> None:
        self.query_one("#options", OptionList).focus()

    def action_focus_taxonomy(self) -> None:
        self.query_one("#taxonomy", TextArea).focus()

    def action_reset_taxonomy(self) -> None:
        self.query_one("#taxonomy", TextArea).text = "\n".join(DEFAULT_TAXONOMY_LINES).strip() + "\n"
        self.query_one("#errors", Static).update("")

    def action_cancel(self) -> None:
        self.dismiss(
            SettingsResult(
                output_language=self._output_language,
                taxonomy_lines=self._taxonomy_lines,
                text_model=self._text_model,
                vision_model=self._vision_model,
                filename_separator=self._filename_separator,
                archive_root=self._archive_root,
            )
        )

    def action_save(self) -> None:
        self._save()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self._activate_option(event.option_index)

    def on_key(self, event) -> None:  # type: ignore[override]
        if self.focused and self.focused.id == "options":
            if event.key in {"enter"}:
                ol = self.query_one("#options", OptionList)
                self._activate_option(ol.highlighted)
                event.stop()
            elif event.key in {"left", "right"}:
                ol = self.query_one("#options", OptionList)
                self._cycle_option(ol.highlighted, forward=(event.key == "right"))
                event.stop()
        elif self.focused and self.focused.id == "taxonomy":
            if event.key in {"escape"}:
                self.action_focus_options()
                event.stop()

    def _activate_option(self, idx: int) -> None:
        if idx in {0, 1, 2, 4}:
            self._cycle_option(idx, forward=True)
            return
        if idx == 3:
            self.app.push_screen(
                ArchivePickerScreen(archive_root=self._archive_root),
                callback=self._on_archive_picked,
                wait_for_dismiss=False,
            )
            return
        if idx == 5:
            self.action_focus_taxonomy()
            return

    def _cycle_option(self, idx: int, *, forward: bool) -> None:
        if idx == 0:
            self._text_model = self._cycle_value(self._text_model, self._text_options, forward=forward)
        elif idx == 1:
            self._vision_model = self._cycle_value(self._vision_model, self._vision_options, forward=forward)
        elif idx == 2:
            self._output_language = self._cycle_value(self._output_language, self._lang_options, forward=forward)
        elif idx == 4:
            self._filename_separator = self._cycle_value(self._filename_separator, self._sep_options, forward=forward)
        else:
            return
        self._refresh_options()

    def _on_archive_picked(self, result: ArchivePickerResult) -> None:
        self._archive_root = result.archive_root
        self._refresh_options()

    def _refresh_options(self) -> None:
        ol = self.query_one("#options", OptionList)
        highlighted = ol.highlighted
        ol.clear_options()
        ol.add_options(self._render_options())
        if highlighted is not None:
            ol.highlighted = highlighted

    def _render_options(self) -> list[str]:
        return [
            f"Text model: {self._text_model}",
            f"Vision model: {self._vision_model}",
            f"Output language: {self._output_language}",
            f"Archive folder: {self._archive_root}",
            f"Filename separator: {self._filename_separator}",
            "Edit taxonomy (press Enter)",
        ]

    def _save(self) -> None:
        text = self.query_one("#taxonomy", TextArea).text
        lines = tuple(ln.rstrip("\n") for ln in text.splitlines() if ln.strip())
        _, errors = parse_taxonomy_lines(lines)
        if errors:
            self.query_one("#errors", Static).update("\n".join(errors[:6]))
            return
        self.dismiss(
            SettingsResult(
                output_language=self._output_language,
                taxonomy_lines=lines,
                text_model=self._text_model,
                vision_model=self._vision_model,
                filename_separator=self._filename_separator,
                archive_root=self._archive_root,
            )
        )

    @staticmethod
    def _cycle_value(current: str, values: tuple[str, ...], *, forward: bool) -> str:
        if current not in values:
            return values[0]
        i = values.index(current)
        if forward:
            return values[(i + 1) % len(values)]
        return values[(i - 1) % len(values)]

    @staticmethod
    def _filter_vision_models(models: tuple[str, ...]) -> list[str]:
        out: list[str] = []
        for m in models:
            ml = m.lower()
            if any(v in ml for v in ("vision", "llava", "moondream", "minicpm", "bakllava")):
                out.append(m)
        return out

    @staticmethod
    def _filter_text_models(models: tuple[str, ...]) -> list[str]:
        out: list[str] = []
        for m in models:
            ml = m.lower()
            if any(v in ml for v in ("vision", "llava", "moondream", "minicpm", "bakllava")):
                continue
            out.append(m)
        return out
