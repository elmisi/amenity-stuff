from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import DirectoryTree, Footer, Header, Static


@dataclass(frozen=True)
class ArchivePickerResult:
    archive_root: Path


class DirectoriesOnlyTree(DirectoryTree):
    def filter_paths(self, paths):  # type: ignore[override]
        return [p for p in paths if p.is_dir()]


class ArchivePickerScreen(ModalScreen[ArchivePickerResult]):
    CSS = """
    ArchivePickerScreen { layout: vertical; }
    #summary { height: auto; }
    #picker { height: 1fr; }
    #help { height: auto; color: $text-muted; }
    """

    BINDINGS = [
        ("q", "cancel", "Cancel"),
        ("escape", "cancel", "Cancel"),
        ("g", "go", "Use this folder"),
    ]

    def __init__(self, *, archive_root: Path) -> None:
        super().__init__()
        self._archive_root = archive_root

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Container(id="summary"):
            yield Static(self._render_summary(), id="summary_text")
        yield DirectoriesOnlyTree(path=Path.home(), id="picker")
        yield Static("Enter: select folder • g confirm • Esc/q cancel", id="help")
        yield Footer()

    def on_mount(self) -> None:
        self._update_summary()
        self.query_one("#picker", DirectoryTree).focus()

    def action_cancel(self) -> None:
        self.dismiss(ArchivePickerResult(archive_root=self._archive_root))

    def action_go(self) -> None:
        self.dismiss(ArchivePickerResult(archive_root=self._archive_root))

    def on_directory_tree_directory_selected(self, event: DirectoryTree.DirectorySelected) -> None:
        self._archive_root = event.path
        self._update_summary()

    def _update_summary(self) -> None:
        self.query_one("#summary_text", Static).update(self._render_summary())

    def _render_summary(self) -> str:
        return f"Pick archive folder:\n\n{self._archive_root}"

