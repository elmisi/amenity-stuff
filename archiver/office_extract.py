from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from typing import Optional, Tuple
import zipfile


@dataclass(frozen=True)
class OfficeExtractMeta:
    method: str
    extract_time_s: float


def extract_office_text_with_meta(
    path: Path,
    *,
    max_chars: int = 15000,
) -> Tuple[Optional[str], Optional[str], Optional[OfficeExtractMeta]]:
    """Extract text from common Office formats.

    Supported (best-effort):
    - .docx: ZIP/XML parsing (no extra deps)
    - .xlsx: ZIP/XML parsing (no extra deps)
    - .doc, .xls: requires LibreOffice (soffice) or antiword (doc only)
    """
    ext = path.suffix.lower().lstrip(".")
    t0 = time.perf_counter()

    if ext == "docx":
        text = _extract_docx_text(path, max_chars=max_chars)
        if not text:
            return None, "No extractable DOCX text", None
        return text, "docx", OfficeExtractMeta(method="docx", extract_time_s=time.perf_counter() - t0)

    if ext == "xlsx":
        text = _extract_xlsx_text(path, max_chars=max_chars)
        if not text:
            return None, "No extractable XLSX text", None
        return text, "xlsx", OfficeExtractMeta(method="xlsx", extract_time_s=time.perf_counter() - t0)

    if ext == "doc":
        text = _extract_doc_text_antiword(path, max_chars=max_chars)
        if text:
            return text, "antiword", OfficeExtractMeta(method="antiword", extract_time_s=time.perf_counter() - t0)
        text = _extract_via_libreoffice_txt(path, max_chars=max_chars)
        if text:
            return text, "libreoffice", OfficeExtractMeta(method="libreoffice", extract_time_s=time.perf_counter() - t0)
        return None, "No extractable DOC text (install libreoffice or antiword)", None

    if ext == "xls":
        text = _extract_via_libreoffice_txt(path, max_chars=max_chars)
        if text:
            return text, "libreoffice", OfficeExtractMeta(method="libreoffice", extract_time_s=time.perf_counter() - t0)
        return None, "No extractable XLS text (install libreoffice)", None

    return None, "Unsupported office type", None


def _extract_doc_text_antiword(path: Path, *, max_chars: int) -> Optional[str]:
    if not shutil.which("antiword"):
        return None
    try:
        proc = subprocess.run(
            ["antiword", str(path)],
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    text = (proc.stdout or "").strip()
    return text[:max_chars] if text else None


def _extract_via_libreoffice_txt(path: Path, *, max_chars: int) -> Optional[str]:
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        return None
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            proc = subprocess.run(
                [soffice, "--headless", "--nologo", "--nolockcheck", "--convert-to", "txt:Text", "--outdir", tmpdir, str(path)],
                text=True,
                capture_output=True,
                timeout=90,
                check=False,
            )
            if proc.returncode != 0:
                return None
            out = Path(tmpdir)
            txt_candidates = sorted(out.glob("*.txt"))
            if not txt_candidates:
                return None
            text = txt_candidates[0].read_text(encoding="utf-8", errors="ignore").strip()
            return text[:max_chars] if text else None
    except Exception:
        return None


def _extract_docx_text(path: Path, *, max_chars: int) -> Optional[str]:
    try:
        with zipfile.ZipFile(path) as zf:
            xml = zf.read("word/document.xml").decode("utf-8", errors="ignore")
    except Exception:
        return None

    try:
        from xml.etree import ElementTree as ET

        root = ET.fromstring(xml)
    except Exception:
        # Fallback: extremely naive strip (still better than nothing)
        import re

        text = re.sub(r"<[^>]+>", " ", xml)
        text = " ".join(text.split())
        return text[:max_chars] if text else None

    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    parts: list[str] = []
    for para in root.findall(".//w:p", ns):
        texts: list[str] = []
        for node in para.findall(".//w:t", ns):
            if node.text:
                texts.append(node.text)
        if texts:
            parts.append("".join(texts).strip())
        if sum(len(p) for p in parts) >= max_chars:
            break
    out = "\n".join(p for p in parts if p).strip()
    return out[:max_chars] if out else None


def _extract_xlsx_text(path: Path, *, max_chars: int) -> Optional[str]:
    try:
        with zipfile.ZipFile(path) as zf:
            namelist = set(zf.namelist())
            shared_strings: list[str] = []
            if "xl/sharedStrings.xml" in namelist:
                shared_strings = _xlsx_shared_strings(zf.read("xl/sharedStrings.xml"))

            workbook_sheets = _xlsx_workbook_sheets(zf.read("xl/workbook.xml")) if "xl/workbook.xml" in namelist else []
            worksheet_paths = sorted([n for n in namelist if n.startswith("xl/worksheets/sheet") and n.endswith(".xml")])

            parts: list[str] = []
            if workbook_sheets:
                parts.append("Sheets: " + ", ".join(workbook_sheets))

            # Extract strings from up to a few sheets (best-effort, token efficient).
            cells_seen = 0
            for ws_path in worksheet_paths[:6]:
                try:
                    sheet_texts, consumed = _xlsx_sheet_texts(zf.read(ws_path), shared_strings, budget_cells=1200 - cells_seen)
                except Exception:
                    continue
                cells_seen += consumed
                if sheet_texts:
                    parts.append("\n".join(sheet_texts))
                if sum(len(p) for p in parts) >= max_chars or cells_seen >= 1200:
                    break

            out = "\n".join(p for p in parts if p).strip()
            return out[:max_chars] if out else None
    except Exception:
        return None


def _xlsx_shared_strings(xml_bytes: bytes) -> list[str]:
    from xml.etree import ElementTree as ET

    try:
        root = ET.fromstring(xml_bytes)
    except Exception:
        return []
    # sharedStrings doesn't use a stable namespace prefix; match by localname.
    strings: list[str] = []
    for si in root.findall(".//{*}si"):
        texts: list[str] = []
        for t in si.findall(".//{*}t"):
            if t.text:
                texts.append(t.text)
        s = "".join(texts).strip()
        strings.append(s)
    return strings


def _xlsx_workbook_sheets(xml_bytes: bytes) -> list[str]:
    from xml.etree import ElementTree as ET

    try:
        root = ET.fromstring(xml_bytes)
    except Exception:
        return []
    names: list[str] = []
    for sheet in root.findall(".//{*}sheet"):
        name = sheet.attrib.get("name")
        if name:
            names.append(name.strip())
    return names


def _xlsx_sheet_texts(xml_bytes: bytes, shared_strings: list[str], *, budget_cells: int) -> tuple[list[str], int]:
    from xml.etree import ElementTree as ET

    try:
        root = ET.fromstring(xml_bytes)
    except Exception:
        return [], 0

    parts: list[str] = []
    cells = 0

    def add_value(value: str) -> None:
        v = (value or "").strip()
        if not v:
            return
        # Avoid ultra-long values (images/encoded blobs)
        if len(v) > 400:
            v = v[:400] + "…"
        parts.append(v)

    for c in root.findall(".//{*}c"):
        if cells >= budget_cells:
            break
        cells += 1
        c_type = c.attrib.get("t") or ""
        if c_type == "s":
            v = c.find("{*}v")
            if v is None or not v.text:
                continue
            try:
                idx = int(v.text)
            except Exception:
                continue
            if 0 <= idx < len(shared_strings):
                add_value(shared_strings[idx])
            continue
        if c_type == "inlineStr":
            t = c.find(".//{*}t")
            if t is not None and t.text:
                add_value(t.text)
            continue
        # Numbers / booleans can be useful (totals, years) but are often noisy.
        v = c.find("{*}v")
        if v is not None and v.text:
            txt = v.text.strip()
            if any(ch.isalpha() for ch in txt):
                add_value(txt)
            else:
                # Keep only short numeric tokens (years, amounts)
                if len(txt) <= 12:
                    add_value(txt)

    # Deduplicate while preserving order
    seen: set[str] = set()
    deduped: list[str] = []
    for p in parts:
        if p in seen:
            continue
        seen.add(p)
        deduped.append(p)
    return deduped, cells

