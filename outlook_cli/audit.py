"""Write-operation audit logging.

JSONL format, monthly file rotation, lazy cleanup.
Mirrors jira-cli's internal/audit/audit.go pattern.
"""

import json
import os
import time
from datetime import datetime
from pathlib import Path

# Test isolation
_test_dir: str = ""

# Sensitive flags to strip from logged args
_SENSITIVE_FLAGS = {"--password", "-p", "--token", "-t"}


def audit_dir() -> Path:
    """Return ~/.outlook-cli/audit/"""
    if _test_dir:
        return Path(_test_dir)
    return Path.home() / ".outlook-cli" / "audit"


def log(cmd_path: str, args: list, exit_code: int, duration_ms: int) -> None:
    """Write one audit entry. No-op if OUTLOOK_NO_AUDIT=1."""
    if os.environ.get("OUTLOOK_NO_AUDIT", "") == "1":
        return

    d = audit_dir()
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        return

    _cleanup(d)

    entry = {
        "ts": datetime.now().astimezone().isoformat(),
        "cmd": cmd_path,
        "args": _sanitize_args(args),
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
    """Remove sensitive flag values."""
    out = []
    skip = False
    for a in args:
        if skip:
            skip = False
            continue
        if a.lower() in _SENSITIVE_FLAGS:
            skip = True
            continue
        out.append(a)
    return out


def _cleanup(d: Path) -> None:
    """Remove audit files older than retention period."""
    months = _retention_months()
    if months == 0:
        return

    cutoff = datetime.now().strftime("%Y-%m")  # simplified
    # Calculate cutoff date
    from datetime import timedelta
    cutoff_dt = datetime.now() - timedelta(days=months * 30)
    cutoff = cutoff_dt.strftime("%Y-%m")

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
