from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import shutil
import subprocess
import time
from typing import Iterable, Optional, Tuple


@dataclass(frozen=True)
class TextExtractMeta:
    method: str
    extract_time_s: float


def extract_text_file_with_meta(
    path: Path,
    *,
    max_chars: int = 15000,
) -> Tuple[Optional[str], Optional[str], Optional[TextExtractMeta]]:
    """Extract text from lightweight text-ish formats with minimal deps.

    Supported:
    - .txt, .md: read as UTF-8 (errors=ignore)
    - .json: parse + flatten to key/value lines (fallback to raw)
    - .rtf: prefer `unrtf` if available, fallback to naive stripping
    - .svg: parse XML and collect <text>/<title>/<desc> plus raw text nodes
    - .kmz: read embedded .kml (zip) and extract placemarks (best-effort)
    """
    ext = path.suffix.lower().lstrip(".")
    t0 = time.perf_counter()

    if ext in {"txt", "md"}:
        text = _read_text(path, max_chars=max_chars)
        if not text:
            return None, "Empty file", None
        return text, ext, TextExtractMeta(method=ext, extract_time_s=time.perf_counter() - t0)

    if ext == "json":
        raw = _read_text(path, max_chars=max_chars * 4) or ""
        text = _flatten_json_text(raw, max_chars=max_chars) or raw.strip()[:max_chars]
        if not text:
            return None, "Empty JSON", None
        return text, "json", TextExtractMeta(method="json", extract_time_s=time.perf_counter() - t0)

    if ext == "rtf":
        text = _extract_rtf_text(path, max_chars=max_chars)
        if not text:
            return None, "No extractable RTF text (install unrtf for best results)", None
        return text, "rtf", TextExtractMeta(method="rtf", extract_time_s=time.perf_counter() - t0)

    if ext == "svg":
        text = _extract_svg_text(path, max_chars=max_chars)
        if not text:
            return None, "No extractable SVG text", None
        return text, "svg", TextExtractMeta(method="svg", extract_time_s=time.perf_counter() - t0)

    if ext == "kmz":
        text = _extract_kmz_text(path, max_chars=max_chars)
        if not text:
            return None, "No extractable KMZ/KML text", None
        return text, "kmz", TextExtractMeta(method="kmz", extract_time_s=time.perf_counter() - t0)

    return None, "Unsupported text type", None


def _read_text(path: Path, *, max_chars: int) -> Optional[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        try:
            data = path.read_bytes()
        except Exception:
            return None
        text = data.decode("utf-8", errors="ignore")
    text = text.strip()
    return text[:max_chars] if text else None


def _flatten_json_text(raw: str, *, max_chars: int) -> Optional[str]:
    try:
        data = json.loads(raw)
    except Exception:
        return None

    lines: list[str] = []
    budget_items = 1200

    def emit(path_parts: Iterable[str], value: object) -> None:
        if len(lines) >= budget_items:
            return
        key = ".".join(path_parts)
        if isinstance(value, bool):
            v = "true" if value else "false"
        else:
            v = str(value)
        v = " ".join(v.split())
        if not v:
            return
        if len(v) > 400:
            v = v[:400] + "…"
        if key:
            lines.append(f"{key}: {v}")
        else:
            lines.append(v)

    def walk(node: object, path_parts: list[str]) -> None:
        if len(lines) >= budget_items:
            return
        if node is None:
            return
        if isinstance(node, (str, int, float, bool)):
            emit(path_parts, node)
            return
        if isinstance(node, dict):
            for k, v in node.items():
                if len(lines) >= budget_items:
                    break
                if not isinstance(k, str):
                    continue
                walk(v, [*path_parts, k])
            return
        if isinstance(node, list):
            for idx, v in enumerate(node[:200]):
                if len(lines) >= budget_items:
                    break
                walk(v, [*path_parts, str(idx)])
            return

    walk(data, [])
    out = "\n".join(lines).strip()
    if not out:
        return None
    return out[:max_chars]


def _extract_rtf_text(path: Path, *, max_chars: int) -> Optional[str]:
    if shutil.which("unrtf"):
        try:
            proc = subprocess.run(
                ["unrtf", "--text", str(path)],
                text=True,
                capture_output=True,
                timeout=30,
                check=False,
            )
        except Exception:
            proc = None
        if proc and proc.returncode == 0:
            text = (proc.stdout or "").strip()
            return text[:max_chars] if text else None

    raw = _read_text(path, max_chars=max_chars * 6)
    if not raw:
        return None

    # Naive fallback: remove control words/braces while trying to keep visible text.
    # This is imperfect but avoids extra dependencies.
    s = raw
    s = re.sub(r"\\'[0-9a-fA-F]{2}", " ", s)  # hex escapes
    s = re.sub(r"\\[a-zA-Z]+-?\d* ?", " ", s)  # control words
    s = s.replace("{", " ").replace("}", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s[:max_chars] if s else None


def _extract_svg_text(path: Path, *, max_chars: int) -> Optional[str]:
    raw = _read_text(path, max_chars=max_chars * 4)
    if not raw:
        return None
    try:
        from xml.etree import ElementTree as ET

        root = ET.fromstring(raw)
    except Exception:
        # Fallback: strip tags
        text = re.sub(r"<[^>]+>", " ", raw)
        text = " ".join(text.split())
        return text[:max_chars] if text else None

    parts: list[str] = []

    def add(value: str) -> None:
        v = " ".join((value or "").strip().split())
        if not v:
            return
        parts.append(v)

    # Prefer human-visible elements first.
    for tag in ["title", "desc", "text"]:
        for el in root.findall(f".//{{*}}{tag}"):
            if el.text:
                add(el.text)
            if sum(len(p) for p in parts) >= max_chars:
                break

    # Collect remaining text nodes (best-effort).
    if sum(len(p) for p in parts) < max_chars:
        for el in root.iter():
            if el.text and el.tag and not str(el.tag).endswith(("style", "script")):
                add(el.text)
            if sum(len(p) for p in parts) >= max_chars:
                break

    out = "\n".join(parts).strip()
    return out[:max_chars] if out else None


def _extract_kmz_text(path: Path, *, max_chars: int) -> Optional[str]:
    import zipfile

    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            kml_candidates = [n for n in names if n.lower().endswith(".kml")]
            if not kml_candidates:
                return None
            # Prefer doc.kml if present (common in KMZ exports)
            chosen = None
            for n in kml_candidates:
                if n.lower().endswith("doc.kml"):
                    chosen = n
                    break
            if not chosen:
                chosen = sorted(kml_candidates)[0]
            xml = zf.read(chosen).decode("utf-8", errors="ignore")
    except Exception:
        return None

    try:
        from xml.etree import ElementTree as ET

        root = ET.fromstring(xml)
    except Exception:
        import re

        text = re.sub(r"<[^>]+>", " ", xml)
        text = " ".join(text.split())
        return text[:max_chars] if text else None

    parts: list[str] = []

    def add(line: str) -> None:
        if not line:
            return
        v = " ".join(line.split()).strip()
        if not v:
            return
        parts.append(v)

    # Document name
    for el in root.findall(".//{*}Document/{*}name"):
        if el.text and el.text.strip():
            add(f"Document: {el.text.strip()}")
            break

    placemarks = root.findall(".//{*}Placemark")
    add(f"Placemarks: {len(placemarks)}")

    # Extract a limited number of placemarks to keep it cheap.
    for pm in placemarks[:40]:
        name = ""
        desc = ""
        coords = ""
        n = pm.find("{*}name")
        if n is not None and n.text:
            name = n.text.strip()
        d = pm.find("{*}description")
        if d is not None and d.text:
            desc = d.text.strip()
        c = pm.find(".//{*}coordinates")
        if c is not None and c.text:
            coords = " ".join(c.text.split())[:120]

        if name:
            add(f"- {name}")
        if desc:
            # Descriptions can contain HTML; keep it short.
            desc_clean = desc
            desc_clean = desc_clean.replace("<br>", " ").replace("<br/>", " ").replace("<br />", " ")
            desc_clean = re.sub(r"<[^>]+>", " ", desc_clean)
            desc_clean = " ".join(desc_clean.split())
            if len(desc_clean) > 240:
                desc_clean = desc_clean[:240] + "…"
            add(f"  {desc_clean}")
        if coords:
            add(f"  coords: {coords}")

        if sum(len(p) for p in parts) >= max_chars:
            break

    out = "\n".join(parts).strip()
    return out[:max_chars] if out else None
