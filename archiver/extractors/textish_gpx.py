"""GPX (GPS Exchange Format) text extraction.

Extracts waypoints, tracks, and routes from GPX files.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional
import xml.etree.ElementTree as ET


def extract_gpx_text(path: Path, *, max_chars: int = 15000) -> Optional[str]:
    """Extract text content from a GPX file.

    Extracts:
    - Metadata (name, description, author, time)
    - Waypoints (name, description, coordinates)
    - Tracks (name, number of points, date range)
    - Routes (name, points)
    """
    try:
        tree = ET.parse(path)
        root = tree.getroot()
    except Exception:
        return None

    # Handle GPX namespace
    ns = {"gpx": "http://www.topografix.com/GPX/1/1"}
    # Try without namespace if needed
    if root.tag.startswith("{"):
        ns_uri = root.tag.split("}")[0] + "}"
        ns = {"gpx": ns_uri.strip("{}")}
    else:
        ns = {}

    def find(element, tag):
        """Find element with or without namespace."""
        if ns:
            result = element.find(f"gpx:{tag}", ns)
            if result is None:
                result = element.find(tag)
        else:
            result = element.find(tag)
        return result

    def findall(element, tag):
        """Find all elements with or without namespace."""
        if ns:
            result = element.findall(f"gpx:{tag}", ns)
            if not result:
                result = element.findall(tag)
        else:
            result = element.findall(tag)
        return result

    def get_text(element, tag):
        """Get text content of a child element."""
        child = find(element, tag)
        return child.text.strip() if child is not None and child.text else None

    lines: list[str] = []

    # Metadata
    metadata = find(root, "metadata")
    if metadata is not None:
        name = get_text(metadata, "name")
        desc = get_text(metadata, "desc")
        time = get_text(metadata, "time")
        if name:
            lines.append(f"GPX Name: {name}")
        if desc:
            lines.append(f"Description: {desc}")
        if time:
            lines.append(f"Date: {time[:10] if len(time) >= 10 else time}")

    # Waypoints
    waypoints = findall(root, "wpt")
    if waypoints:
        lines.append(f"\nWaypoints ({len(waypoints)}):")
        for wpt in waypoints[:20]:  # Limit to 20
            lat = wpt.get("lat", "")
            lon = wpt.get("lon", "")
            name = get_text(wpt, "name") or "unnamed"
            desc = get_text(wpt, "desc")
            wpt_line = f"  - {name}"
            if lat and lon:
                wpt_line += f" ({lat}, {lon})"
            if desc:
                wpt_line += f": {desc[:100]}"
            lines.append(wpt_line)
        if len(waypoints) > 20:
            lines.append(f"  ... and {len(waypoints) - 20} more")

    # Tracks
    tracks = findall(root, "trk")
    if tracks:
        lines.append(f"\nTracks ({len(tracks)}):")
        for trk in tracks[:10]:
            name = get_text(trk, "name") or "unnamed track"
            # Count track points
            segments = findall(trk, "trkseg")
            total_points = sum(len(findall(seg, "trkpt")) for seg in segments)
            # Try to get time range
            times = []
            for seg in segments:
                for pt in findall(seg, "trkpt"):
                    t = get_text(pt, "time")
                    if t:
                        times.append(t)
            time_info = ""
            if times:
                start = times[0][:10] if len(times[0]) >= 10 else times[0]
                end = times[-1][:10] if len(times[-1]) >= 10 else times[-1]
                if start == end:
                    time_info = f", date: {start}"
                else:
                    time_info = f", from {start} to {end}"
            lines.append(f"  - {name}: {total_points} points{time_info}")

    # Routes
    routes = findall(root, "rte")
    if routes:
        lines.append(f"\nRoutes ({len(routes)}):")
        for rte in routes[:10]:
            name = get_text(rte, "name") or "unnamed route"
            points = findall(rte, "rtept")
            lines.append(f"  - {name}: {len(points)} points")

    if not lines:
        return None

    text = "\n".join(lines)
    return text[:max_chars] if len(text) > max_chars else text
