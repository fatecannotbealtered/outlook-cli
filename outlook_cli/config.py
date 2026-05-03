"""Configuration management for outlook-cli.

Config file: ~/.outlook-cli/config.json
Environment variable overrides: OUTLOOK_EMAIL, OUTLOOK_PASSWORD,
OUTLOOK_SERVER, OUTLOOK_TIMEZONE, OUTLOOK_PERMISSIONS
"""

import json
import os
import sys
from pathlib import Path

CONFIG_DIR_NAME = ".outlook-cli"
CONFIG_FILE_NAME = "config.json"

# Permission levels (ascending)
PERMISSION_LEVELS = {"read-only": 0, "write": 1, "full": 2}

# Commands that require "full" permission (send/reply/forward are irreversible)
FULL_COMMANDS = frozenset({
    "mail send", "mail reply", "mail reply-all", "mail forward",
    "mail draft-send",
})

# Commands that require "write" permission
WRITE_COMMANDS = frozenset({
    "mail move", "mail mark", "mail flag", "mail categorize",
    "mail restore", "mail batch", "mail delete", "mail draft-edit",
    "mail draft-delete",
    "cal create", "cal update", "cal delete",
    "folders create", "folders rename", "folders move",
    "folders empty", "folders delete",
    "rules create", "rules update", "rules delete", "rules toggle",
    "tools oof set", "tools oof disable", "tools respond",
})


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
    from .crypto import decrypt

    cfg = {}
    path = config_path()
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass

    # Decrypt password from file
    pwd = cfg.get("password", "")
    if pwd:
        cfg["password"] = decrypt(pwd)

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

    return cfg


def save(cfg: dict) -> None:
    """Save config to file with secure permissions.

    Password is encrypted with machine-bound AES-256-GCM if the
    cryptography package is available. Otherwise stored as plaintext.
    """
    from .crypto import encrypt, is_encrypted

    d = config_dir()
    d.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass

    path = config_path()
    # Don't save env-only fields to file
    save_cfg = {k: v for k, v in cfg.items() if k != "permissions_mode"}

    # Encrypt password before saving (skip if already encrypted)
    pwd = save_cfg.get("password", "")
    if pwd and not is_encrypted(pwd):
        save_cfg["password"] = encrypt(pwd)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(save_cfg, f, ensure_ascii=False, indent=2)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


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

    Exits with code 5 (FORBIDDEN) if not allowed.
    """
    mode = get_permission_mode()
    level = PERMISSION_LEVELS.get(mode, 0)

    if cmd_path in FULL_COMMANDS:
        if level < PERMISSION_LEVELS["full"]:
            _deny(cmd_path, mode, "full")
    elif cmd_path in WRITE_COMMANDS:
        if level < PERMISSION_LEVELS["write"]:
            _deny(cmd_path, mode, "write")
    # read-only commands always allowed


def _deny(cmd_path: str, current: str, required: str) -> None:
    from .output import error_json
    error_json(
        f"权限不足：当前模式 '{current}'，命令 '{cmd_path}' 需要 '{required}' 或更高",
        code="FORBIDDEN",
        hint=f"编辑 {config_path()} 将 permissions.mode 改为 '{required}'",
    )
    sys.exit(5)
