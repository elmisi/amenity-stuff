from __future__ import annotations

from importlib import metadata

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
        try:
            ver = metadata.version("amenity-stuff")
        except Exception:
            ver = "dev"

        yield Header(show_clock=False)
        with Container(id="dialog"):
            yield Static(
                "\n".join(
                    [
                        f"amenity-stuff v{ver}",
                        "Author: elmisi",
                        "",
                        "Purpose:",
                        "Local-first TUI that scans a folder and prepares a clean archive plan by extracting facts,",
                        "classifying files into a user taxonomy, and proposing better filenames.",
                        "",
                        "Workflow:",
                        "1) Reload: load files from the source folder.",
                        "2) Scan: extract text/OCR + call the local LLM to produce structured facts and a rich summary.",
                        "3) Classify: use scanned facts to assign category/year and propose a coherent filename.",
                        "4) Review: inspect per-file details in the bottom panel (no files are moved yet).",
                        "",
                        "Shortcuts:",
                        "F1      Show this help screen",
                        "F2      Open settings (models, language, taxonomy, archive folder)",
                        "Ctrl+R  Reload directory and refresh the file list",
                        "Enter   Open selected file with the system default application",
                        "",
                        "s       Scan the selected row (force re-scan)",
                        "S       Scan all pending files",
                        "x       Stop an ongoing scan/classify task",
                        "",
                        "c       Classify the selected scanned row (force re-classify)",
                        "C       Classify all scanned (not-yet-classified) files",
                        "",
                        "u       Unclassify the selected row (keep scan results)",
                        "U       Unclassify all classified files (keeps scan results)",
                        "",
                        "r       Reset the selected row back to pending (clears cached result)",
                        "R       Reset all rows back to pending (clears cache)",
                        "q       Quit",
                    ]
                )
            , markup=False)
            yield Static("Enter / Esc / q to close", id="hint")
        yield Footer()

    def action_close(self) -> None:
        self.dismiss(None)
