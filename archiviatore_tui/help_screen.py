from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Footer, Header, Static


class HelpScreen(ModalScreen[None]):
    CSS = """
    HelpScreen { layout: vertical; }
    #dialog { height: auto; border: round $accent; background: $panel; padding: 1 2; margin: 1 2; }
    #hint { height: auto; color: $text-muted; }
    """

    BINDINGS = [
        ("escape", "close", "Close"),
        ("enter", "close", "Close"),
        ("q", "close", "Close"),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Container(id="dialog"):
            yield Static(
                "\n".join(
                    [
                        "How it works (current):",
                        "- Ctrl+R reloads the source directory.",
                        "- Scan extracts facts (text/OCR + LLM) and stores them in the local cache.",
                        "- Classify uses scanned facts to assign category/year and propose a coherent filename.",
                        "- Enter opens the selected file with the system default application.",
                        "",
                        "Shortcuts:",
                        "Scan: s (file) • S (pending) • x (stop)",
                        "Classify: c (file) • C (scanned)",
                        "Reset: r (row) • R (all)",
                        "Settings: F2 • Quit: q",
                    ]
                )
            )
            yield Static("Enter / Esc / q to close", id="hint")
        yield Footer()

    def action_close(self) -> None:
        self.dismiss(None)

