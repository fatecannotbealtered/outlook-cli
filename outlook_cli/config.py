"""Configuration management for outlook-cli.

Config file: ~/.outlook-cli/config.json
Environment variable overrides: OUTLOOK_EMAIL, OUTLOOK_PASSWORD,
OUTLOOK_SERVER, OUTLOOK_TIMEZONE, OUTLOOK_PERMISSIONS
"""

import json
import os
import sys
import tempfile
from pathlib import Path

CONFIG_DIR_NAME = ".outlook-cli"
CONFIG_FILE_NAME = "config.json"

# Permission levels (ascending)
PERMISSION_LEVELS = {"read-only": 0, "write": 1, "full": 2}

# Commands that require "full" permission (send/reply/forward are irreversible)
FULL_COMMANDS = frozenset(
    {
        "mail send",
        "mail reply",
        "mail reply-all",
        "mail forward",
        "mail draft-send",
    }
)

# Commands that require "write" permission
WRITE_COMMANDS = frozenset(
    {
        "mail move",
        "mail mark",
        "mail flag",
        "mail categorize",
        "mail restore",
        "mail batch",
        "mail delete",
        "mail draft-edit",
        "mail draft-delete",
        "cal create",
        "cal update",
        "cal delete",
        "folders create",
        "folders rename",
        "folders move",
        "folders empty",
        "folders delete",
        "rules create",
        "rules update",
        "rules delete",
        "rules toggle",
        "tools oof set",
        "tools oof disable",
        "tools respond",
    }
)

# Commands that only write local files/config and do not require elevated
# Outlook mailbox permissions, but still must use dry-run/confirm.
LOCAL_WRITE_COMMANDS = frozenset(
    {
        "mail export",
        "mail download-attachment",
        "setup login",
    }
)


def config_dir() -> Path:
    """Return ~/.outlook-cli/"""
    return Path.home() / CONFIG_DIR_NAME


def config_path() -> Path:
    """Return ~/.outlook-cli/config.json"""
    return config_dir() / CONFIG_FILE_NAME


def load() -> dict:
    """Load config from file. Environment variables override file values.

    Password is decrypted if stored in encrypted form.
    Returns empty dict if no config exists (graceful degradation).
    """
    from .crypto import DecryptionError, decrypt

    cfg = {}
    path = config_path()
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except json.JSONDecodeError as e:
            print(
                f"Warning: config file is corrupted ({e}). "
                f"Run 'outlook-cli setup login' to re-configure.",
                file=sys.stderr,
            )
            return {}
        except OSError as e:
            print(f"Warning: cannot read config file: {e}", file=sys.stderr)
            return {}

    # Decrypt password from file
    pwd = cfg.get("password", "")
    if pwd:
        try:
            cfg["password"] = decrypt(pwd)
        except DecryptionError as e:
            print(f"Warning: {e}", file=sys.stderr)
            cfg["password"] = ""

    # Environment variable overrides
    # OUTLOOK_PASSWORD is supported for CI/CD and integration tests.
    # Normal usage: credentials stored encrypted in config file via `setup login`.
    env_map = {
        "OUTLOOK_EMAIL": "email",
        "OUTLOOK_PASSWORD": "password",
        "OUTLOOK_SERVER": "server",
        "OUTLOOK_TIMEZONE": "timezone",
        "OUTLOOK_PERMISSIONS": "permissions_mode",
        "OUTLOOK_SHARED_MAILBOX": "shared_mailbox",
    }
    for env_key, cfg_key in env_map.items():
        val = os.environ.get(env_key, "").strip()
        if val:
            cfg[cfg_key] = val

    # Validate permission mode if set
    perm = cfg.get("permissions_mode") or (
        cfg.get("permissions", {}).get("mode", "")
        if isinstance(cfg.get("permissions"), dict)
        else ""
    )
    if perm and perm not in PERMISSION_LEVELS:
        print(
            f"Warning: invalid permission mode '{perm}', falling back to 'read-only'. "
            f"Valid values: {', '.join(PERMISSION_LEVELS.keys())}",
            file=sys.stderr,
        )
        cfg.pop("permissions_mode", None)
        if isinstance(cfg.get("permissions"), dict):
            cfg["permissions"]["mode"] = "read-only"

    return cfg


def save(cfg: dict) -> None:
    """Save config to file with secure permissions.

    Password is encrypted with machine-bound AES if the
    cryptography package is available. Otherwise stored as plaintext.
    Uses atomic write (temp file + rename) to prevent corruption.
    """
    from .crypto import encrypt, is_encrypted

    d = config_dir()
    d.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass  # Windows: chmod is no-op; ACLs not enforced here

    path = config_path()
    # Don't save env-only fields to file
    save_cfg = {k: v for k, v in cfg.items() if k != "permissions_mode"}

    # Encrypt password before saving (skip if already encrypted)
    pwd = save_cfg.get("password", "")
    if pwd and not is_encrypted(pwd):
        save_cfg["password"] = encrypt(pwd)

    # Atomic write: write to temp file, then rename
    tmp_fd = None
    tmp_path = None
    try:
        tmp_fd, tmp_path = tempfile.mkstemp(dir=str(d), suffix=".tmp")
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(save_cfg, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        tmp_fd = None  # fdopen takes ownership
        os.replace(tmp_path, path)
        tmp_path = None  # successfully renamed
    finally:
        if tmp_fd is not None:
            try:
                os.close(tmp_fd)
            except OSError:
                pass
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    try:
        os.chmod(path, 0o600)
    except OSError:
        pass  # Windows: chmod is no-op


def is_configured() -> bool:
    """Quick check if credentials exist."""
    cfg = load()
    return bool(cfg.get("email") and cfg.get("password"))


def get_permission_mode(cfg: dict = None) -> str:
    """Get the effective permission mode.

    Priority: env var OUTLOOK_PERMISSIONS > config file > default "read-only"
    """
    if cfg is None:
        cfg = load()

    # Check env-only override first
    if cfg.get("permissions_mode"):
        return cfg["permissions_mode"]

    # Check config file
    permissions = cfg.get("permissions", {})
    if isinstance(permissions, dict):
        return permissions.get("mode", "read-only")

    return "read-only"


def check_permission(cmd_path: str) -> None:
    """Check if the current permission level allows this command.

    Exits with code 4 (E_FORBIDDEN) if not allowed. Mutating commands then
    require the dry-run/confirm-token flow.
    """
    mode = get_permission_mode()
    level = PERMISSION_LEVELS.get(mode, 0)
    is_mutating = False

    if cmd_path in FULL_COMMANDS:
        is_mutating = True
        if level < PERMISSION_LEVELS["full"]:
            _deny(cmd_path, mode, "full")
    elif cmd_path in WRITE_COMMANDS:
        is_mutating = True
        if level < PERMISSION_LEVELS["write"]:
            _deny(cmd_path, mode, "write")
    elif cmd_path in LOCAL_WRITE_COMMANDS:
        is_mutating = True
    # read-only commands always allowed
    if is_mutating:
        _require_confirm(cmd_path)


def _deny(cmd_path: str, current: str, required: str) -> None:
    from . import output

    output.handle_error(
        f"Insufficient permission: mode is '{current}', "
        f"command '{cmd_path}' requires '{required}' or higher",
        code="E_FORBIDDEN",
        details={
            "command": cmd_path,
            "current": current,
            "required": required,
            "hint": f"Edit {config_path()} and set permissions.mode to '{required}'",
        },
    )


def _require_confirm(cmd_path: str) -> None:
    """Enforce dry-run -> confirm for mutating operations."""
    import click

    from . import output
    from .confirmation import command_preview_payload, validate_token

    ctx = click.get_current_context(silent=True)
    obj = ctx.obj if ctx and ctx.obj else {}

    if obj.get("dry_run") or "--preview" in sys.argv:
        output.print_json(command_preview_payload(cmd_path))
        sys.exit(0)

    token = obj.get("confirm")
    if not token:
        output.handle_error(
            f"Command '{cmd_path}' requires --dry-run followed by --confirm <token>",
            "E_CONFIRMATION_REQUIRED",
            details={"command": cmd_path},
        )

    valid, reason = validate_token(token)
    if not valid:
        output.handle_error(
            "Confirm token is invalid for this operation",
            "E_CONFLICT",
            details={"command": cmd_path, "reason": reason},
        )
