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
    "--preview",
    "--send",
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


def operation_digest(args: list[str] | None = None) -> str:
    payload = json.dumps(args or operation_args(), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def issue_token(args: list[str] | None = None, ttl_seconds: int = TOKEN_TTL_SECONDS) -> tuple[str, str]:
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
    expires_epoch = int(expires_at.timestamp())
    digest = operation_digest(args)
    msg = f"{expires_epoch}.{digest}".encode("utf-8")
    sig = hmac.new(_load_secret(), msg, hashlib.sha256).digest()
    token = f"{TOKEN_PREFIX}_{expires_epoch}_{_b64(sig)}"
    return token, expires_at.isoformat().replace("+00:00", "Z")


def validate_token(token: str, args: list[str] | None = None) -> tuple[bool, str]:
    try:
        prefix, exp_raw, sig_raw = token.split("_", 2)
        if prefix != TOKEN_PREFIX:
            return False, "invalid token prefix"
        expires_epoch = int(exp_raw)
        if datetime.now(timezone.utc).timestamp() > expires_epoch:
            return False, "confirm token expired"
        digest = operation_digest(args)
        msg = f"{expires_epoch}.{digest}".encode("utf-8")
        expected = hmac.new(_load_secret(), msg, hashlib.sha256).digest()
        actual = _unb64(sig_raw)
        if not hmac.compare_digest(expected, actual):
            return False, "confirm token does not match this operation"
        return True, ""
    except Exception as exc:
        return False, f"invalid confirm token: {exc}"


def preview_payload(action: str, detail: dict[str, Any] | None = None) -> dict[str, Any]:
    token, expires_at = issue_token()
    return {
        "preview": {
            "changes": [
                {
                    "action": action,
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
