from __future__ import annotations

import argparse
from pathlib import Path

from .app import ArchiverApp
from .config import load_config
from .settings import Settings


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="amenity-stuff")
    parser.add_argument(
        "--source",
        type=Path,
        default=Path("."),
        help="Source folder to analyze (default: .)",
    )
    parser.add_argument(
        "--archive",
        type=Path,
        default=Path("./ARCHIVIO"),
        help="Archive root destination (default: ./ARCHIVIO)",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=100,
        help="Max files per batch (default: 100)",
    )
    parser.add_argument(
        "--localai-base-url",
        type=str,
        default=None,
        help="(deprecated) reserved for future providers",
    )
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    cfg = load_config()
    default_source = args.source
    default_archive = args.archive
    if default_archive == Path("./ARCHIVIO") and cfg.last_archive_root:
        default_archive = Path(cfg.last_archive_root)
    settings = Settings(
        source_root=default_source,
        archive_root=default_archive,
        max_files=args.max_files,
        localai_base_url=args.localai_base_url,
    )
    # Disable mouse tracking so the terminal can do native text selection (copy with mouse).
    ArchiverApp(settings).run(mouse=False)


if __name__ == "__main__":
    main()
