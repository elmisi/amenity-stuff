from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import DirectoryTree, Footer, Header, Static


@dataclass(frozen=True)
class SetupResult:
    source_root: Path
    archive_root: Path


class SetupScreen(ModalScreen[SetupResult]):
    CSS = """
    SetupScreen { layout: vertical; }
    #summary { height: auto; }
    #summary Static { height: auto; }
    #picker { height: 1fr; }
    #help { height: auto; color: $text-muted; }
    """

    BINDINGS = [
        ("q", "cancel", "Cancel"),
        ("1", "select_source", "Select source"),
        ("2", "select_archive", "Select archive"),
        ("g", "go", "Continue"),
    ]

    def __init__(self, *, source_root: Path, archive_root: Path) -> None:
        super().__init__()
        self._source_root = source_root
        self._archive_root = archive_root
        self._target: str = "archive"

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="summary"):
            yield Static(self._render_summary(), id="summary_text")
        yield DirectoryTree(path=Path.home(), id="picker")
        yield Static(self._render_help(), id="help")
        yield Footer()

    def on_mount(self) -> None:
        self._update_summary()
        self.query_one("#picker", DirectoryTree).focus()

    def action_cancel(self) -> None:
        self.dismiss(SetupResult(source_root=self._source_root, archive_root=self._archive_root))

    def action_select_source(self) -> None:
        self._target = "source"
        self._update_summary()

    def action_select_archive(self) -> None:
        self._target = "archive"
        self._update_summary()

    def action_go(self) -> None:
        self.dismiss(SetupResult(source_root=self._source_root, archive_root=self._archive_root))

    def on_directory_tree_directory_selected(self, event: DirectoryTree.DirectorySelected) -> None:
        if self._target == "source":
            self._source_root = event.path
        else:
            self._archive_root = event.path
        self._update_summary()

    def _update_summary(self) -> None:
        self.query_one("#summary_text", Static).update(self._render_summary())
        self.query_one("#help", Static).update(self._render_help())

    def _render_summary(self) -> str:
        tgt = "SOURCE" if self._target == "source" else "ARCHIVE"
        return (
            "Folder selection\n\n"
            f"Source: {self._source_root}\n"
            f"Archive: {self._archive_root}\n\n"
            f"Active target: {tgt}"
        )

    def _render_help(self) -> str:
        return "Enter on a folder: set active target • 1/2 switch target • g continue • q cancel"
