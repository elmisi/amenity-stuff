from __future__ import annotations

from dataclasses import dataclass

from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Footer, Header, Select, Static, TextArea

from .taxonomy import DEFAULT_TAXONOMY_LINES, parse_taxonomy_lines


@dataclass(frozen=True)
class SettingsResult:
    output_language: str
    taxonomy_lines: tuple[str, ...]


class SettingsScreen(ModalScreen[SettingsResult]):
    CSS = """
    SettingsScreen { layout: vertical; }
    #intro { height: auto; }
    #form { height: 1fr; }
    #lang_row { height: auto; }
    #taxonomy_label { height: auto; padding: 1 0 0 0; }
    #taxonomy { height: 1fr; border: round $accent; }
    #errors { height: auto; color: $error; }
    #help { height: auto; color: $text-muted; }
    """

    BINDINGS = [
        ("q", "cancel", "Cancel"),
        ("escape", "cancel", "Cancel"),
        ("ctrl+s", "save", "Save"),
        ("r", "reset_defaults", "Reset defaults"),
    ]

    def __init__(self, *, output_language: str, taxonomy_lines: tuple[str, ...]) -> None:
        super().__init__()
        self._output_language = output_language
        self._taxonomy_lines = taxonomy_lines

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Static("Settings (Ctrl+S save • Esc cancel • r reset)", id="intro")

        with Container(id="form"):
            with Horizontal(id="lang_row"):
                yield Static("Output language:", id="lang_label")
                yield Select(
                    [
                        ("Auto (match document)", "auto"),
                        ("Italian", "it"),
                        ("English", "en"),
                    ],
                    value=self._output_language if self._output_language in {"auto", "it", "en"} else "auto",
                    id="lang",
                )
            yield Static("Taxonomy (one category per line): name | description | examples", id="taxonomy_label")
            yield TextArea("\n".join(self._taxonomy_lines).strip() + "\n", id="taxonomy")
            yield Static("", id="errors")

        yield Static(
            "Tip: focus Output language and press Enter to open; use arrows. "
            "In the taxonomy box you can edit text directly.",
            id="help",
        )
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#taxonomy", TextArea).focus()

    def action_cancel(self) -> None:
        self.dismiss(SettingsResult(output_language=self._output_language, taxonomy_lines=self._taxonomy_lines))

    def action_save(self) -> None:
        self._save()

    def action_reset_defaults(self) -> None:
        self.query_one("#taxonomy", TextArea).text = "\n".join(DEFAULT_TAXONOMY_LINES).strip() + "\n"
        self.query_one("#errors", Static).update("")

    def _save(self) -> None:
        lang = self.query_one("#lang", Select).value or "auto"
        text = self.query_one("#taxonomy", TextArea).text
        lines = tuple(ln.rstrip("\n") for ln in text.splitlines() if ln.strip())
        _, errors = parse_taxonomy_lines(lines)
        if errors:
            self.query_one("#errors", Static).update("\n".join(errors[:6]))
            return
        self.dismiss(SettingsResult(output_language=str(lang), taxonomy_lines=lines))
