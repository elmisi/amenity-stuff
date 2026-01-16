from __future__ import annotations

from pathlib import Path


def _parse(v: str) -> tuple[int, int, int]:
    parts = v.strip().split(".")
    if len(parts) != 3:
        raise SystemExit(f"Invalid version in VERSION: {v!r} (expected MAJOR.MINOR.PATCH)")
    return int(parts[0]), int(parts[1]), int(parts[2])


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    version_path = root / "VERSION"
    pyproject_path = root / "pyproject.toml"

    cur = version_path.read_text(encoding="utf-8").strip()
    major, minor, patch = _parse(cur)
    nxt = f"{major}.{minor}.{patch + 1}"

    version_path.write_text(nxt + "\n", encoding="utf-8")

    text = pyproject_path.read_text(encoding="utf-8")
    text2 = text.replace(f'version = "{cur}"', f'version = "{nxt}"')
    if text2 == text:
        raise SystemExit("Could not update pyproject.toml (version string not found)")
    pyproject_path.write_text(text2, encoding="utf-8")
    print(nxt)


if __name__ == "__main__":
    main()

