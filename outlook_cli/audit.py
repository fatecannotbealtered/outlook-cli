"""Write-operation audit logging.

JSONL format, monthly file rotation, lazy cleanup.
Mirrors jira-cli's internal/audit/audit.go pattern.
"""

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

# Test isolation
_test_dir: str = ""

# Sensitive flags to strip from logged args
_SENSITIVE_FLAGS = {
    "--password",
    "-p",
    "--token",
    "-t",
    "--access-token",
    "--confirm",
    "--secret",
    "--authorization",
    "--cookie",
}


def audit_dir() -> Path:
    """Return ~/.outlook-cli/audit/"""
    if _test_dir:
        return Path(_test_dir)
    return Path.home() / ".outlook-cli" / "audit"


def log(
    cmd_path: str,
    args: list,
    exit_code: int,
    duration_ms: int,
    account: str = "",
) -> None:
    """Write one audit entry. No-op if OUTLOOK_NO_AUDIT=1."""
    if os.environ.get("OUTLOOK_NO_AUDIT", "") == "1":
        return

    d = audit_dir()
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        return

    _maybe_cleanup(d)

    entry = {
        "ts": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "cmd": cmd_path,
        "args": _sanitize_args(args),
        "account": account,
        "exit": exit_code,
        "ms": duration_ms,
    }

    try:
        data = json.dumps(entry, ensure_ascii=False) + "\n"
    except (TypeError, ValueError):
        return

    filename = f"audit-{time.strftime('%Y-%m')}.jsonl"
    path = d / filename

    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(data)
    except OSError:
        pass


def files() -> list:
    """Return sorted list of audit JSONL files. For testing."""
    d = audit_dir()
    if not d.exists():
        return []
    return sorted(str(p) for p in d.glob("audit-*.jsonl"))


def _sanitize_args(args: list) -> list:
    """Remove sensitive flag values. Handles both '--flag value' and '--flag=value'."""
    out = []
    skip = False
    for a in args:
        if skip:
            skip = False
            continue
        # Handle --flag=value form
        if "=" in a:
            flag_part = a.split("=", 1)[0]
            if flag_part.lower() in _SENSITIVE_FLAGS:
                out.append(f"{flag_part}=***")
                continue
        # Handle --flag value form
        if a.lower() in _SENSITIVE_FLAGS:
            skip = True
            out.append(a)
            continue
        out.append(a)
    return out


# Track last cleanup to avoid running it on every log() call
_last_cleanup_month: str = ""


def _maybe_cleanup(d: Path) -> None:
    """Remove expired audit files, at most once per month."""
    global _last_cleanup_month
    current_month = time.strftime("%Y-%m")
    if _last_cleanup_month == current_month:
        return
    _last_cleanup_month = current_month
    _cleanup(d)


def _cleanup(d: Path) -> None:
    """Remove audit files older than retention period."""
    months = _retention_months()
    if months == 0:
        return

    # Calculate cutoff by subtracting months
    now = datetime.now()
    cutoff_year = now.year
    cutoff_month = now.month - months
    while cutoff_month <= 0:
        cutoff_month += 12
        cutoff_year -= 1
    cutoff = f"{cutoff_year:04d}-{cutoff_month:02d}"

    try:
        for p in d.glob("audit-*.jsonl"):
            name = p.stem  # "audit-2026-01"
            ym = name.replace("audit-", "")
            if ym < cutoff:
                try:
                    p.unlink()
                except OSError:
                    pass
    except OSError:
        pass


def _retention_months() -> int:
    """Get retention months from env. Default 3. 0 = keep forever."""
    s = os.environ.get("OUTLOOK_AUDIT_RETENTION_MONTHS", "")
    if not s:
        return 3
    try:
        n = int(s)
        return max(n, 0)
    except ValueError:
        return 3
