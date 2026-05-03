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

# ANSI colors
_NO_COLOR = os.environ.get("NO_COLOR", "") != "" or not sys.stdout.isatty()
_GREEN = "" if _NO_COLOR else "\033[32m"
_RED = "" if _NO_COLOR else "\033[31m"
_YELLOW = "" if _NO_COLOR else "\033[33m"
_BLUE = "" if _NO_COLOR else "\033[34m"
_CYAN = "" if _NO_COLOR else "\033[36m"
_BOLD = "" if _NO_COLOR else "\033[1m"
_GRAY = "" if _NO_COLOR else "\033[90m"
_RESET = "" if _NO_COLOR else "\033[0m"

# Error code taxonomy (same as jira-cli)
ERROR_CODES = {
    "CONFIG_ERROR": "运行 'outlook-cli setup login' 配置凭据",
    "AUTH_REQUIRED": "检查 OUTLOOK_EMAIL 和 OUTLOOK_PASSWORD 环境变量",
    "FORBIDDEN": "检查权限配置 ~/.outlook-cli/config.json",
    "NOT_FOUND": "确认资源 ID 是否正确（来自 list/search 结果）",
    "VALIDATION_ERROR": "检查命令参数是否正确",
    "SERVER_ERROR": "Exchange 服务器错误，请稍后重试",
    "NETWORK_ERROR": "检查网络连接和 OUTLOOK_SERVER 配置",
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
    """Print indented JSON to stdout."""
    print(json.dumps(data, ensure_ascii=False, default=str, indent=2))


def print_flat_json(data: dict) -> None:
    """Print flat JSON to stdout (token-efficient for AI agents)."""
    print_json(data)


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
    if _quiet:
        return
    if _json_mode:
        return
    print(f"{_GREEN}  {msg}{_RESET}")


def info(msg: str) -> None:
    """Blue info. Suppressed by --quiet."""
    if _quiet:
        return
    if _json_mode:
        return
    print(f"{_BLUE}  {msg}{_RESET}")


def warn(msg: str) -> None:
    """Yellow warning to stderr. Always shown."""
    print(f"{_YELLOW}  {msg}{_RESET}", file=sys.stderr)


def error(msg: str) -> None:
    """Red error to stderr. Always shown."""
    print(f"{_RED}  {msg}{_RESET}", file=sys.stderr)


def bold(msg: str) -> None:
    if _quiet or _json_mode:
        return
    print(f"{_BOLD}{msg}{_RESET}")


def gray(msg: str) -> None:
    if _quiet or _json_mode:
        return
    print(f"{_GRAY}{msg}{_RESET}")


def format_cyan(s: str) -> str:
    return f"{_CYAN}{s}{_RESET}"


def format_green(s: str) -> str:
    return f"{_GREEN}{s}{_RESET}"


def format_red(s: str) -> str:
    return f"{_RED}{s}{_RESET}"


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
    if "auth" in msg.lower() or "401" in msg:
        code = "AUTH_REQUIRED"
        exit_code = 3
    elif "not found" in msg.lower() or "404" in msg:
        code = "NOT_FOUND"
        exit_code = 4
    elif "forbidden" in msg.lower() or "403" in msg:
        code = "FORBIDDEN"
        exit_code = 5
    elif "timeout" in msg.lower() or "connect" in msg.lower():
        code = "NETWORK_ERROR"
        exit_code = 7
    handle_error(msg, code, exit_code)


def dry_run_output(action: str, detail: dict) -> bool:
    """If --dry-run mode, output preview and return True."""
    if not _json_mode and not _quiet:
        gray(f"  [DRY RUN] {action}")
        for k, v in detail.items():
            gray(f"    {k}: {v}")
    return False  # Caller checks is_dry_run flag
