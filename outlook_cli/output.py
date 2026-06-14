"""Agent-safe output helpers.

Default command output is a single JSON document on stdout. Progress and
diagnostics are written to stderr, and write commands are guarded elsewhere by
the dry-run/confirm flow.
"""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any

SCHEMA_VERSION = "1.0"
FORMAT_JSON = "json"
FORMAT_TEXT = "text"
FORMAT_RAW = "raw"

_quiet = False
_format = FORMAT_JSON
_compact = False
_fields: tuple[str, ...] = ()
_started_at = time.monotonic()


ERROR_HINTS = {
    "E_CONFIG": "Run 'outlook-cli setup login --dry-run' first, then confirm the returned token.",
    "E_AUTH": "Check Outlook credentials and authentication settings.",
    "E_FORBIDDEN": "Check permissions in ~/.outlook-cli/config.json.",
    "E_NOT_FOUND": "Verify the resource ID from a fresh list/search result.",
    "E_VALIDATION": "Check command arguments.",
    "E_USAGE": "Check command arguments.",
    "E_CONFIRMATION_REQUIRED": (
        "Run the same write command with --dry-run, then retry with --confirm <token>."
    ),
    "E_CONFLICT": "State or token changed. Re-run --dry-run and use the new confirm_token.",
    "E_SERVER": "Exchange server error. Retry later if the operation is transient.",
    "E_NETWORK": "Check network, VPN, proxy, and OUTLOOK_SERVER.",
    "E_RATE_LIMITED": "Too many requests. Back off before retrying.",
    "E_TIMEOUT": "The operation timed out. Back off before retrying.",
    "E_UNKNOWN": "Inspect error.details for more context.",
}

# Backward-compatible names used by the existing command modules and tests.
LEGACY_ERROR_MAP = {
    "CONFIG_ERROR": "E_CONFIG",
    "AUTH_REQUIRED": "E_AUTH",
    "FORBIDDEN": "E_FORBIDDEN",
    "NOT_FOUND": "E_NOT_FOUND",
    "VALIDATION_ERROR": "E_VALIDATION",
    "SERVER_ERROR": "E_SERVER",
    "NETWORK_ERROR": "E_NETWORK",
    "RATE_LIMITED": "E_RATE_LIMITED",
    "TIMEOUT": "E_TIMEOUT",
    "UNKNOWN_ERROR": "E_UNKNOWN",
}

ERROR_CODES = {legacy: ERROR_HINTS[semantic] for legacy, semantic in LEGACY_ERROR_MAP.items()}
ERROR_CODES.update(ERROR_HINTS)

EXIT_CODE_BY_ERROR = {
    "E_USAGE": 2,
    "E_VALIDATION": 2,
    "E_NOT_FOUND": 3,
    "E_AUTH": 4,
    "E_FORBIDDEN": 4,
    "E_CONFIG": 4,
    "E_CONFIRMATION_REQUIRED": 5,
    "E_CONFLICT": 6,
    "E_NETWORK": 7,
    "E_RATE_LIMITED": 7,
    "E_SERVER": 7,
    "E_TIMEOUT": 8,
}

RETRYABLE_ERRORS = {"E_NETWORK", "E_RATE_LIMITED", "E_SERVER", "E_TIMEOUT"}


def _is_no_color() -> bool:
    """Check NO_COLOR at runtime."""
    return os.environ.get("NO_COLOR", "") != "" or not sys.stdout.isatty()


def _ansi(code: str) -> str:
    """Return ANSI escape code if color is enabled, else empty string."""
    if _is_no_color():
        return ""
    return f"\033[{code}"


def _semantic_code(code: str) -> str:
    return LEGACY_ERROR_MAP.get(code, code if code.startswith("E_") else "E_UNKNOWN")


def exit_code_for(code: str, fallback: int = 1) -> int:
    return EXIT_CODE_BY_ERROR.get(_semantic_code(code), fallback)


def init(
    format_mode: str | None = None,
    quiet: bool = False,
    compact: bool = False,
    fields: str | list[str] | tuple[str, ...] | None = None,
    json_mode: bool | None = None,
) -> None:
    """Set global output mode. Called once at startup.

    json_mode is retained for compatibility with older unit tests and callers.
    """
    global _format, _quiet, _compact, _fields, _started_at

    _started_at = time.monotonic()
    if json_mode is not None:
        format_mode = FORMAT_JSON if json_mode else FORMAT_TEXT
    _format = format_mode or FORMAT_JSON
    _quiet = quiet
    _compact = compact

    if fields is None or fields == "":
        _fields = ()
    elif isinstance(fields, str):
        _fields = tuple(f.strip() for f in fields.split(",") if f.strip())
    else:
        _fields = tuple(str(f).strip() for f in fields if str(f).strip())


def output_format() -> str:
    return _format


def is_json() -> bool:
    return _format == FORMAT_JSON


def is_text() -> bool:
    return _format == FORMAT_TEXT


def is_raw() -> bool:
    return _format == FORMAT_RAW


def is_quiet() -> bool:
    return _quiet


def is_compact() -> bool:
    return _compact


def selected_fields() -> tuple[str, ...]:
    return _fields


def _select_path(data: Any, path: str) -> Any:
    current = data
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None
    return current


def _assign_path(target: dict, path: str, value: Any) -> None:
    parts = path.split(".")
    cur = target
    for part in parts[:-1]:
        cur = cur.setdefault(part, {})
    cur[parts[-1]] = value


def apply_fields(data: Any) -> Any:
    """Apply --fields to envelope data.

    Supports top-level names and dotted paths. Unknown fields are omitted.
    """
    if not _fields or not isinstance(data, dict):
        return data

    selected: dict[str, Any] = {}
    for field in _fields:
        value = _select_path(data, field)
        if value is not None:
            _assign_path(selected, field, value)
    return selected


def success_envelope(data: Any, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    if meta is None:
        meta = {"duration_ms": int((time.monotonic() - _started_at) * 1000)}
    return {
        "ok": True,
        "schema_version": SCHEMA_VERSION,
        "data": apply_fields(data),
        "meta": meta,
    }


def error_envelope(
    msg: str,
    code: str = "E_UNKNOWN",
    details: dict[str, Any] | None = None,
    retryable: bool | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    semantic = _semantic_code(code)
    if retryable is None:
        retryable = semantic in RETRYABLE_ERRORS
    if meta is None:
        meta = {"duration_ms": int((time.monotonic() - _started_at) * 1000)}
    return {
        "ok": False,
        "schema_version": SCHEMA_VERSION,
        "error": {
            "code": semantic,
            "message": msg,
            "details": details or {},
            "retryable": retryable,
        },
        "meta": meta,
    }


def _dump_json(payload: Any, *, file=None, compact: bool | None = None) -> None:
    if compact is None:
        compact = _compact
    text = json.dumps(
        payload,
        ensure_ascii=False,
        default=str,
        separators=(",", ":") if compact else None,
        indent=None if compact else 2,
    )
    print(text, file=file or sys.stdout)


def print_json(data: Any, meta: dict[str, Any] | None = None) -> None:
    """Print a success envelope to stdout."""
    if is_raw():
        if isinstance(data, (bytes, bytearray)):
            sys.stdout.buffer.write(data)
        else:
            print(data if isinstance(data, str) else json.dumps(data, default=str))
        return
    if is_text():
        print(data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, default=str))
        return
    _dump_json(success_envelope(data, meta=meta))


def print_flat_json(data: dict, meta: dict[str, Any] | None = None) -> None:
    """Print a JSON success envelope to stdout, honoring the global --compact flag.

    Whitespace must not differ between this and the normal success path, so the
    same command produces the same shape on success regardless of which printer
    it uses.
    """
    if is_json():
        _dump_json(success_envelope(data, meta=meta))
    else:
        print_json(data, meta=meta)


def print_ndjson(items) -> None:
    """Print NDJSON items without wrapping them into one large document."""
    for item in items:
        _dump_json(item, compact=True)


def error_json(
    msg: str,
    code: str = "E_UNKNOWN",
    hint: str = "",
    details: dict[str, Any] | None = None,
    retryable: bool | None = None,
) -> None:
    """Print the structured error envelope to stdout (the JSON contract channel).

    Agents always parse stdout and check `ok` first; stderr only carries a short
    human-readable explanation as side-channel context.
    """
    semantic = _semantic_code(code)
    error_details = dict(details or {})
    if hint:
        error_details.setdefault("hint", hint)
    elif semantic in ERROR_HINTS:
        error_details.setdefault("hint", ERROR_HINTS[semantic])
    # Honor the global --compact flag (default pretty) so the error envelope's
    # whitespace matches the success envelope for the same invocation.
    _dump_json(error_envelope(msg, semantic, details=error_details, retryable=retryable))
    if not _quiet:
        print(f"{semantic}: {msg}", file=sys.stderr)


# --- Human-readable output ---


def success(msg: str) -> None:
    """Green status line. Suppressed by --quiet and non-text formats."""
    if _quiet or not is_text():
        return
    print(f"{_ansi('32m')}  {msg}{_ansi('0m')}")


def info(msg: str) -> None:
    """Blue status line. Suppressed by --quiet and non-text formats."""
    if _quiet or not is_text():
        return
    print(f"{_ansi('34m')}  {msg}{_ansi('0m')}")


def warn(msg: str) -> None:
    """Yellow warning to stderr."""
    print(f"{_ansi('33m')}  {msg}{_ansi('0m')}", file=sys.stderr)


def error(msg: str) -> None:
    """Red error to stderr. Errors are never suppressed by --quiet."""
    print(f"{_ansi('31m')}  {msg}{_ansi('0m')}", file=sys.stderr)


def bold(msg: str) -> None:
    if _quiet or not is_text():
        return
    print(f"{_ansi('1m')}{msg}{_ansi('0m')}")


def gray(msg: str) -> None:
    if _quiet or not is_text():
        return
    print(f"{_ansi('90m')}{msg}{_ansi('0m')}")


def format_cyan(s: str) -> str:
    return f"{_ansi('36m')}{s}{_ansi('0m')}"


def format_green(s: str) -> str:
    return f"{_ansi('32m')}{s}{_ansi('0m')}"


def format_red(s: str) -> str:
    return f"{_ansi('31m')}{s}{_ansi('0m')}"


# --- Error handling ---


def handle_error(
    msg: str,
    code: str = "E_UNKNOWN",
    exit_code: int | None = None,
    details: dict[str, Any] | None = None,
    retryable: bool | None = None,
) -> None:
    """Print error in the appropriate format and exit."""
    semantic = _semantic_code(code)
    resolved_exit = exit_code_for(semantic, fallback=exit_code or 1)
    if is_json():
        error_json(msg, semantic, details=details, retryable=retryable)
    else:
        error(msg)
    sys.exit(resolved_exit)


# Map exchangelib / requests exception class names to error codes. Matching on
# the exception TYPE (incl. its MRO) is more reliable than sniffing the message
# text, which can misclassify (e.g. a body that happens to contain "not found").
# Keyed by class name so this module stays decoupled from exchangelib's import
# surface and version-specific class availability.
_API_ERROR_TYPE_CODES = {
    "ErrorServerBusy": "E_RATE_LIMITED",
    "RateLimitError": "E_RATE_LIMITED",
    "ErrorTooManyObjectsOpened": "E_RATE_LIMITED",
    "ErrorItemNotFound": "E_NOT_FOUND",
    "ErrorFolderNotFound": "E_NOT_FOUND",
    "ErrorNonExistentMailbox": "E_NOT_FOUND",
    "UnauthorizedError": "E_AUTH",
    "ErrorAccessDenied": "E_FORBIDDEN",
    "ErrorTimeoutExpired": "E_TIMEOUT",
    "Timeout": "E_TIMEOUT",
    "ReadTimeout": "E_TIMEOUT",
    "ConnectTimeout": "E_TIMEOUT",
    "ConnectionError": "E_NETWORK",
    "TransportError": "E_NETWORK",
}


def _api_error_code_from_type(exc: Exception) -> str | None:
    """Return an error code by matching the exception type (and its bases)."""
    for base in type(exc).__mro__:
        code = _API_ERROR_TYPE_CODES.get(base.__name__)
        if code is not None:
            return code
    return None


def handle_api_error(exc: Exception, exit_code: int | None = None) -> None:
    """Handle Exchange/API errors, classifying by exception type first."""
    msg = str(exc)
    code = _api_error_code_from_type(exc)
    if code is None:
        # Fallback substring sniffing for exceptions we don't map by type.
        lower_msg = msg.lower()
        if "auth" in lower_msg or "401" in msg or "unauthorized" in lower_msg:
            code = "E_AUTH"
        elif "not found" in lower_msg or "404" in msg:
            code = "E_NOT_FOUND"
        elif "forbidden" in lower_msg or "403" in msg:
            code = "E_FORBIDDEN"
        elif "throttl" in lower_msg or "429" in msg or "too many request" in lower_msg:
            code = "E_RATE_LIMITED"
        elif "timeout" in lower_msg or "timed out" in lower_msg:
            code = "E_TIMEOUT"
        elif (
            "connect" in lower_msg
            and "disconnect" not in lower_msg
            and "reconnect" not in lower_msg
        ):
            code = "E_NETWORK"
        else:
            code = "E_SERVER"
    handle_error(msg, code, exit_code=exit_code)


def dry_run_output(
    action: str,
    detail: dict[str, Any],
    *,
    resource_id: str | None = None,
    resource_version: str | None = None,
) -> None:
    """Output a dry-run preview.

    If the global confirm machinery is active it will already have returned a
    token before command execution. This function remains for command-local
    previews and for backwards compatibility.
    """
    from .confirmation import preview_payload

    payload = preview_payload(
        action,
        detail,
        resource_id=resource_id,
        resource_version=resource_version,
    )
    if is_json():
        print_json(payload)
    elif not _quiet:
        gray(f"  [DRY RUN] {action}")
        for k, v in detail.items():
            gray(f"    {k}: {v}")
        gray(f"    confirm_token: {payload['confirm_token']}")
        gray(f"    expires_at: {payload['expires_at']}")


def duration_meta(start_time: float) -> dict[str, int]:
    return {"duration_ms": int((time.time() - start_time) * 1000)}
