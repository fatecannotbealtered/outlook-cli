"""Dry-run and confirm-token support for mutating commands."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

TOKEN_PREFIX = "ct"
TOKEN_TTL_SECONDS = 15 * 60

_VALUE_OPTIONS = {"--format", "--fields", "--confirm"}
_OUTPUT_FLAGS = {
    "--json",
    "--quiet",
    "--compact",
    "--dry-run",
    "--force",
}


def _secret_path() -> Path:
    from .config import config_dir

    return config_dir() / "confirm.secret"


def _load_secret() -> bytes:
    path = _secret_path()
    if path.exists():
        return path.read_bytes()

    path.parent.mkdir(parents=True, exist_ok=True)
    secret = secrets.token_bytes(32)
    path.write_bytes(secret)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return secret


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _canonical_args(args: list[str]) -> list[str]:
    result: list[str] = []
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in _OUTPUT_FLAGS:
            i += 1
            continue
        if any(arg.startswith(f"{opt}=") for opt in _VALUE_OPTIONS):
            i += 1
            continue
        if arg in _VALUE_OPTIONS:
            i += 2
            continue
        result.append(arg)
        i += 1
    return result


def operation_args() -> list[str]:
    return _canonical_args(sys.argv[1:])


def _args_digest(args: list[str]) -> str:
    payload = json.dumps(args, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _operation_context(
    args: list[str] | None = None,
    resource_id: str | None = None,
    resource_version: str | None = None,
) -> dict[str, Any]:
    """Build the signed operation scope for confirm tokens."""
    from . import __version__
    from .config import get_permission_mode, load

    cfg = load()
    account = (cfg.get("shared_mailbox") or cfg.get("email") or "").strip()
    auth_account = (cfg.get("email") or "").strip()
    scope = {
        "tool": "outlook-cli",
        "tool_version": __version__,
        "args_sha256": _args_digest(args or operation_args()),
        "account": account,
        "auth_account": auth_account,
        "permission": get_permission_mode(cfg),
    }
    if resource_id is not None:
        scope["resource_id"] = str(resource_id)
    if resource_version is not None:
        scope["resource_version"] = str(resource_version)
    return scope


def _redacted_args(args: list[str]) -> list[str]:
    redacted: list[str] = []
    secret_next = False
    secret_flags = {"--password", "--secret", "--token", "--access-token"}
    for arg in args:
        if secret_next:
            redacted.append("<redacted>")
            secret_next = False
            continue
        if any(arg.startswith(f"{flag}=") for flag in secret_flags):
            redacted.append(f"{arg.split('=', 1)[0]}=<redacted>")
            continue
        redacted.append(arg)
        if arg in secret_flags:
            secret_next = True
    return redacted


def operation_digest(
    args: list[str] | None = None,
    resource_id: str | None = None,
    resource_version: str | None = None,
) -> str:
    payload = json.dumps(
        _operation_context(args, resource_id, resource_version),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def issue_token(
    args: list[str] | None = None,
    ttl_seconds: int = TOKEN_TTL_SECONDS,
    resource_id: str | None = None,
    resource_version: str | None = None,
) -> tuple[str, str]:
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
    expires_epoch = int(expires_at.timestamp())
    payload = {
        "exp": expires_epoch,
        "scope": _operation_context(args, resource_id, resource_version),
    }
    payload_bytes = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    sig = hmac.new(_load_secret(), payload_bytes, hashlib.sha256).digest()
    token = f"{TOKEN_PREFIX}_{_b64(payload_bytes)}_{_b64(sig)}"
    return (
        token,
        expires_at.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    )


def validate_token(
    token: str,
    args: list[str] | None = None,
    resource_id: str | None = None,
    resource_version: str | None = None,
) -> tuple[bool, str]:
    try:
        prefix, payload_raw, sig_raw = token.split("_", 2)
        if prefix != TOKEN_PREFIX:
            return False, "invalid token prefix"
        payload_bytes = _unb64(payload_raw)
        expected_sig = hmac.new(_load_secret(), payload_bytes, hashlib.sha256).digest()
        actual_sig = _unb64(sig_raw)
        if not hmac.compare_digest(expected_sig, actual_sig):
            return False, "confirm token signature mismatch"
        payload = json.loads(payload_bytes.decode("utf-8"))
        expires_epoch = int(payload.get("exp", 0))
        if datetime.now(timezone.utc).timestamp() > expires_epoch:
            return False, "confirm token expired"
        actual_scope = payload.get("scope") or {}
        expected_scope = _operation_context(args, resource_id, resource_version)
        for key in (
            "tool",
            "tool_version",
            "args_sha256",
            "account",
            "auth_account",
            "permission",
        ):
            if actual_scope.get(key) != expected_scope.get(key):
                return False, f"confirm token does not match operation {key}"
        if resource_id is not None and actual_scope.get("resource_id") != str(resource_id):
            return False, "confirm token does not match resource"
        if resource_version is not None and actual_scope.get("resource_version") != str(
            resource_version
        ):
            return False, "confirm token does not match this operation"
        return True, ""
    except Exception as exc:
        return False, f"invalid confirm token: {exc}"


def preview_payload(
    action: str,
    detail: dict[str, Any] | None = None,
    *,
    resource_id: str | None = None,
    resource_version: str | None = None,
) -> dict[str, Any]:
    token, expires_at = issue_token(
        resource_id=resource_id,
        resource_version=resource_version,
    )
    return {
        "preview": {
            "changes": [
                {
                    "action": action,
                    "resource_id": resource_id or "",
                    "resource_version": resource_version or "",
                    "detail": detail or {},
                }
            ]
        },
        "confirm_token": token,
        "expires_at": expires_at,
    }


def command_preview_payload(command: str) -> dict[str, Any]:
    args = operation_args()
    token, expires_at = issue_token(args)
    return {
        "preview": {
            "changes": [
                {
                    "action": command,
                    "detail": {
                        "command": command,
                        "args": _redacted_args(args),
                    },
                }
            ]
        },
        "confirm_token": token,
        "expires_at": expires_at,
    }


def require_confirmed(
    command: str,
    *,
    resource_id: str | None = None,
    resource_version: str | None = None,
) -> None:
    """Validate the current --confirm token before a mutation."""
    import click

    from . import output

    ctx = click.get_current_context(silent=True)
    obj = ctx.obj if ctx and ctx.obj else {}
    if obj.get("dry_run"):
        return
    token = obj.get("confirm")
    if not token:
        output.handle_error(
            f"Command '{command}' requires --dry-run followed by --confirm <token>",
            "E_CONFIRMATION_REQUIRED",
            details={"command": command},
        )
    valid, reason = validate_token(
        token,
        resource_id=resource_id,
        resource_version=resource_version,
    )
    if not valid:
        output.handle_error(
            "Confirm token is invalid for this operation",
            "E_CONFLICT",
            details={"command": command, "reason": reason},
        )
