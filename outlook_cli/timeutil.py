"""Time formatting helpers for the CLI contract."""

from __future__ import annotations

from datetime import date, datetime, time, timezone


def iso_utc(value) -> str:
    """Return an ISO 8601 UTC timestamp with a trailing Z."""
    if value is None:
        return ""
    if isinstance(value, date) and not isinstance(value, datetime):
        value = datetime.combine(value, time.min, tzinfo=timezone.utc)
    if not isinstance(value, datetime):
        return str(value)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    value = value.astimezone(timezone.utc).replace(microsecond=0)
    return value.isoformat().replace("+00:00", "Z")


def parse_datetime(value: str, field_name: str = "time") -> datetime:
    """Parse ISO 8601 or legacy YYYY-MM-DD HH:MM datetime input."""
    from . import output

    text = (value or "").strip()
    candidates = []
    if text.endswith("Z"):
        candidates.append(text[:-1] + "+00:00")
    candidates.append(text)
    for candidate in candidates:
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            pass
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    output.handle_error(
        f"{field_name} format error, use ISO 8601 UTC or YYYY-MM-DD HH:MM, got: {value}",
        "E_VALIDATION",
    )


def item_version(item) -> str:
    """Extract a stable Exchange item version when available."""
    item_id = getattr(item, "id", None)
    for obj in (item_id, item):
        version = getattr(obj, "changekey", None)
        if version:
            return str(version)
    last_modified = getattr(item, "last_modified_time", None)
    if last_modified:
        return iso_utc(last_modified)
    return ""
