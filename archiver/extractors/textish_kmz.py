from __future__ import annotations

import re
from pathlib import Path
from typing import Optional


def extract_kmz_text(path: Path, *, max_chars: int) -> Optional[str]:
    import zipfile

    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            kml_candidates = [n for n in names if n.lower().endswith(".kml")]
            if not kml_candidates:
                return None
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

    for el in root.findall(".//{*}Document/{*}name"):
        if el.text and el.text.strip():
            add(f"Document: {el.text.strip()}")
            break

    placemarks = root.findall(".//{*}Placemark")
    add(f"Placemarks: {len(placemarks)}")

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

