from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .scanner import ScanItem
from .ui_status import status_cell


@dataclass(frozen=True)
class FileTableRow:
    key: str
    status: str
    kind: str
    file: str
    category: str
    year: str


def build_file_table_rows(items: list[ScanItem], *, source_root: Path) -> tuple[list[FileTableRow], dict[str, int]]:
    src = source_root.expanduser().resolve()
    rows: list[FileTableRow] = []
    index_by_key: dict[str, int] = {}

    for idx, item in enumerate(items):
        rel = str(item.path)
        try:
            rel = str(item.path.relative_to(src))
        except Exception:
            pass
        key = str(item.path)
        index_by_key[key] = idx
        rows.append(
            FileTableRow(
                key=key,
                status=status_cell(item.status),
                kind=item.kind,
                file=rel,
                category=item.category or "",
                year=item.reference_year or "",
            )
        )

    return rows, index_by_key

