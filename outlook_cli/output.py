"""Dual-mode output system (JSON / human-readable).

Mirrors jira-cli's output patterns:
- --json: machine-readable JSON to stdout, errors to stderr
- --quiet: suppress non-error stdout
- NO_COLOR: disable ANSI colors
- Semantic error codes with actionable hints
"""

import json
import os
import sys

# Global state (set by main.py)
_quiet = False
_json_mode = False


def _is_no_color() -> bool:
    """Check NO_COLOR at runtime (supports env changes after import)."""
    return os.environ.get("NO_COLOR", "") != "" or not sys.stdout.isatty()


def _ansi(code: str) -> str:
    """Return ANSI escape code if color is enabled, else empty string."""
    if _is_no_color():
        return ""
    return f"\033[{code}"


# Error code taxonomy (same as jira-cli)
ERROR_CODES = {
    "CONFIG_ERROR": "Run 'outlook-cli setup login' to configure credentials",
    "AUTH_REQUIRED": "Check OUTLOOK_EMAIL and OUTLOOK_PASSWORD env vars",
    "FORBIDDEN": "Check permissions in ~/.outlook-cli/config.json",
    "NOT_FOUND": "Verify the resource ID (from list/search results). The ID may have changed if the item was moved or deleted.",
    "VALIDATION_ERROR": "Check command arguments",
    "SERVER_ERROR": "Exchange server error, try again later",
    "NETWORK_ERROR": "Check network and OUTLOOK_SERVER config",
    "RATE_LIMITED": "Too many requests, retry after a delay",
}


def init(json_mode: bool, quiet: bool) -> None:
    """Set global output mode. Called once at startup."""
    global _json_mode, _quiet
    _json_mode = json_mode
    _quiet = quiet


def is_json() -> bool:
    return _json_mode


def is_quiet() -> bool:
    return _quiet


# --- JSON output ---


def print_json(data) -> None:
    """Print indented JSON to stdout (human-readable)."""
    print(json.dumps(data, ensure_ascii=False, default=str, indent=2))


def print_flat_json(data: dict) -> None:
    """Print compact JSON to stdout (token-efficient for AI agents)."""
    print(json.dumps(data, ensure_ascii=False, default=str))


def error_json(msg: str, code: str = "UNKNOWN_ERROR", hint: str = "") -> None:
    """Print structured error JSON to stderr."""
    if not hint:
        hint = ERROR_CODES.get(code, "")
    payload = {"error": msg, "errorCode": code}
    if hint:
        payload["hint"] = hint
    print(json.dumps(payload, ensure_ascii=False), file=sys.stderr)


# --- Human-readable output ---


def success(msg: str) -> None:
    """Green checkmark. Suppressed by --quiet."""
    if _quiet or _json_mode:
        return
    print(f"{_ansi('32m')}  {msg}{_ansi('0m')}")


def info(msg: str) -> None:
    """Blue info. Suppressed by --quiet."""
    if _quiet or _json_mode:
        return
    print(f"{_ansi('34m')}  {msg}{_ansi('0m')}")


def warn(msg: str) -> None:
    """Yellow warning to stderr. Always shown."""
    print(f"{_ansi('33m')}  {msg}{_ansi('0m')}", file=sys.stderr)


def error(msg: str) -> None:
    """Red error to stderr. Always shown."""
    print(f"{_ansi('31m')}  {msg}{_ansi('0m')}", file=sys.stderr)


def bold(msg: str) -> None:
    if _quiet or _json_mode:
        return
    print(f"{_ansi('1m')}{msg}{_ansi('0m')}")


def gray(msg: str) -> None:
    if _quiet or _json_mode:
        return
    print(f"{_ansi('90m')}{msg}{_ansi('0m')}")


def format_cyan(s: str) -> str:
    return f"{_ansi('36m')}{s}{_ansi('0m')}"


def format_green(s: str) -> str:
    return f"{_ansi('32m')}{s}{_ansi('0m')}"


def format_red(s: str) -> str:
    return f"{_ansi('31m')}{s}{_ansi('0m')}"


# --- Error handling ---


def handle_error(msg: str, code: str = "UNKNOWN_ERROR", exit_code: int = 1) -> None:
    """Print error in the appropriate format and exit."""
    if _json_mode:
        error_json(msg, code)
    else:
        error(msg)
    sys.exit(exit_code)


def handle_api_error(exc: Exception, exit_code: int = 7) -> None:
    """Handle Exchange/API errors."""
    msg = str(exc)
    code = "SERVER_ERROR"
    lower_msg = msg.lower()
    if "auth" in lower_msg or "401" in msg:
        code = "AUTH_REQUIRED"
        exit_code = 3
    elif "not found" in lower_msg or "404" in msg:
        code = "NOT_FOUND"
        exit_code = 4
    elif "forbidden" in lower_msg or "403" in msg:
        code = "FORBIDDEN"
        exit_code = 5
    elif "timeout" in lower_msg:
        code = "NETWORK_ERROR"
        exit_code = 7
    elif (
        "connect" in lower_msg
        and "disconnect" not in lower_msg
        and "reconnect" not in lower_msg
    ):
        code = "NETWORK_ERROR"
        exit_code = 7
    handle_error(msg, code, exit_code)


def dry_run_output(action: str, detail: dict) -> None:
    """Output dry-run preview. No-op in JSON or quiet mode."""
    if _json_mode:
        print_json({"dry_run": True, "action": action, "detail": detail})
    elif not _quiet:
        gray(f"  [DRY RUN] {action}")
        for k, v in detail.items():
            gray(f"    {k}: {v}")
