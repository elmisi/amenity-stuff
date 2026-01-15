from __future__ import annotations

import argparse
from pathlib import Path

from .app import ArchiverApp
from .settings import Settings


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="archiviatore_tui")
    parser.add_argument(
        "--source",
        type=Path,
        default=Path("."),
        help="Cartella sorgente da analizzare (default: .)",
    )
    parser.add_argument(
        "--archive",
        type=Path,
        default=Path("./ARCHIVIO"),
        help="Root archivio destinazione (default: ./ARCHIVIO)",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=100,
        help="Numero massimo di file da considerare per batch (default: 100)",
    )
    parser.add_argument(
        "--localai-base-url",
        type=str,
        default=None,
        help="(deprecated) riservato per provider futuri",
    )
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    settings = Settings(
        source_root=args.source,
        archive_root=args.archive,
        max_files=args.max_files,
        localai_base_url=args.localai_base_url,
    )
    ArchiverApp(settings).run()


if __name__ == "__main__":
    main()
