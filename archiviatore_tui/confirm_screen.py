from __future__ import annotations

from dataclasses import dataclass

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Footer, Header, Static


@dataclass(frozen=True)
class ConfirmResult:
    confirmed: bool


class ConfirmScreen(ModalScreen[ConfirmResult]):
    CSS = """
    ConfirmScreen { layout: vertical; }
    #dialog { height: auto; border: round $accent; background: $panel; padding: 1 2; margin: 1 2; }
    #hint { height: auto; color: $text-muted; }
    """

    BINDINGS = [
        ("y", "yes", "Yes"),
        ("n", "no", "No"),
        ("enter", "yes", "Yes"),
        ("escape", "no", "No"),
        ("q", "no", "No"),
    ]

    def __init__(self, *, message: str) -> None:
        super().__init__()
        self._message = message

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Container(id="dialog"):
            yield Static(self._message)
            yield Static("y/Enter confirm • n/Esc cancel", id="hint")
        yield Footer()

    def action_yes(self) -> None:
        self.dismiss(ConfirmResult(confirmed=True))

    def action_no(self) -> None:
        self.dismiss(ConfirmResult(confirmed=False))

