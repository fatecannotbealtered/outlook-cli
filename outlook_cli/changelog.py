"""Runtime CHANGELOG.md parser."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

from . import __version__

_HEADING_RE = re.compile(r"^## \[(?P<version>[^\]]+)\](?: - (?P<date>\d{4}-\d{2}-\d{2}))?\s*$")
_CATEGORY_RE = re.compile(r"^### (?P<category>[A-Za-z ]+)\s*$")
_BULLET_RE = re.compile(r"^- (?P<text>.*)$")
_CATEGORIES = {
    "added",
    "changed",
    "fixed",
    "deprecated",
    "removed",
    "security",
}


def changelog_path() -> Path:
    """Return the CHANGELOG.md path in source or PyInstaller runtime."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "CHANGELOG.md"  # type: ignore[attr-defined]
    candidates = [
        Path(__file__).resolve().parent.parent / "CHANGELOG.md",
        Path(sys.prefix) / "share" / "outlook-cli" / "CHANGELOG.md",
    ]
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


def read_text() -> str:
    path = changelog_path()
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def parse_entries(text: str | None = None) -> list[dict[str, Any]]:
    """Parse Keep a Changelog version entries."""
    lines = (text if text is not None else read_text()).splitlines()
    entries: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    category: str | None = None

    for line in lines:
        heading = _HEADING_RE.match(line)
        if heading:
            if current:
                entries.append(current)
            current = {
                "version": heading.group("version"),
                "date": heading.group("date") or "",
                "changes": {name: [] for name in sorted(_CATEGORIES)},
            }
            category = None
            continue

        if current is None:
            continue

        cat_match = _CATEGORY_RE.match(line)
        if cat_match:
            raw = cat_match.group("category").strip().lower().replace(" ", "_")
            category = raw if raw in _CATEGORIES else None
            continue

        bullet = _BULLET_RE.match(line)
        if bullet and category:
            current["changes"][category].append(bullet.group("text").strip())

    if current:
        entries.append(current)

    return [entry for entry in entries if any(entry["changes"].values())]


def _version_key(version: str) -> tuple[int, int, int, str]:
    parts = version.split("-", 1)
    nums = parts[0].split(".")
    padded = [int(p) if p.isdigit() else 0 for p in nums[:3]]
    while len(padded) < 3:
        padded.append(0)
    suffix = parts[1] if len(parts) > 1 else ""
    return padded[0], padded[1], padded[2], suffix


def entries_since(since: str | None = None) -> list[dict[str, Any]]:
    entries = parse_entries()
    if not since:
        return entries
    baseline = _version_key(since)
    return [
        entry
        for entry in entries
        if entry["version"].lower() == "unreleased" or _version_key(entry["version"]) > baseline
    ]


def payload(since: str | None = None) -> dict[str, Any]:
    return {
        "current_version": __version__,
        "since": since or "",
        "entries": entries_since(since),
    }
