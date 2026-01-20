"""CSV text extraction.

Extracts tabular data from CSV files in a readable format.
"""
from __future__ import annotations

import csv
from io import StringIO
from pathlib import Path
from typing import Optional


def extract_csv_text(path: Path, *, max_chars: int = 15000, max_rows: int = 100) -> Optional[str]:
    """Extract text content from a CSV file.

    Returns:
    - Header row (column names)
    - First N data rows
    - Row count summary
    """
    try:
        # Try UTF-8 first, then latin-1 as fallback
        try:
            raw = path.read_text(encoding="utf-8", errors="ignore")
        except UnicodeDecodeError:
            raw = path.read_text(encoding="latin-1", errors="ignore")
    except Exception:
        return None

    if not raw.strip():
        return None

    # Detect delimiter
    sample = raw[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        delimiter = dialect.delimiter
    except csv.Error:
        # Default to comma
        delimiter = ","

    # Parse CSV
    try:
        reader = csv.reader(StringIO(raw), delimiter=delimiter)
        rows = list(reader)
    except Exception:
        return None

    if not rows:
        return None

    lines: list[str] = []
    total_rows = len(rows)

    # Header
    header = rows[0] if rows else []
    if header:
        lines.append(f"Columns ({len(header)}): {', '.join(header)}")
        lines.append("")

    # Data rows
    data_rows = rows[1:] if len(rows) > 1 else rows
    shown_rows = data_rows[:max_rows]

    for i, row in enumerate(shown_rows):
        if header and len(row) == len(header):
            # Format as key: value pairs
            pairs = [f"{header[j]}: {row[j]}" for j in range(len(row)) if row[j].strip()]
            lines.append(f"Row {i+1}: {'; '.join(pairs)}")
        else:
            # Format as comma-separated values
            lines.append(f"Row {i+1}: {', '.join(row)}")

    # Summary
    if len(data_rows) > max_rows:
        lines.append(f"\n... and {len(data_rows) - max_rows} more rows")
    lines.append(f"\nTotal: {total_rows} rows, {len(header)} columns")

    text = "\n".join(lines)
    return text[:max_chars] if len(text) > max_chars else text
