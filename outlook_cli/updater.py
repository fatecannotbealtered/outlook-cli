"""Self-update planning and execution."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from . import __version__

NPM_PACKAGE = "@fateforge/outlook-cli"
PYPI_PACKAGE = "outlook-cli"
SKILL_REPO = "fatecannotbealtered/outlook-cli"
NPM_LATEST_URL = "https://registry.npmjs.org/@fateforge%2Foutlook-cli/latest"
PYPI_URL = "https://pypi.org/pypi/outlook-cli/json"
GITHUB_RELEASES_URL = "https://github.com/fatecannotbealtered/outlook-cli/releases"
UPDATE_NOTICE_TTL_SECONDS = 24 * 60 * 60
NO_UPDATE_CHECK_ENV = "OUTLOOK_CLI_NO_UPDATE_CHECK"


def detect_install_method(requested: str = "auto") -> str:
    """Detect the safest update manager for this installation."""
    if requested != "auto":
        return requested

    override = os.environ.get("OUTLOOK_CLI_UPDATE_MANAGER", "").strip().lower()
    if override in {"npm", "pip", "manual"}:
        return override

    exe = Path(sys.executable).resolve()
    if getattr(sys, "frozen", False):
        package_json = exe.parent.parent / "package.json"
        if package_json.exists():
            return "npm"
        return "manual"

    try:
        from importlib import metadata

        metadata.version(PYPI_PACKAGE)
        return "pip"
    except Exception:
        return "manual"


def skill_sync_command() -> list[str]:
    """Build the command that syncs the whole Agent Skill directory."""
    return ["npx", "skills", "add", SKILL_REPO, "-y", "-g"]


def _read_json_url(url: str, timeout: float = 5.0) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": f"outlook-cli/{__version__}"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def latest_version(manager: str = "", timeout: float = 5.0) -> tuple[str | None, str | None]:
    """Return (latest_version, error_message) from the GitHub releases API.

    The binary self-update path is the single source of truth; the package
    registries are no longer consulted."""
    from .update_binary import GITHUB_API, REPO, normalize_version

    try:
        url = f"{GITHUB_API.rstrip('/')}/repos/{REPO}/releases/latest"
        data = _read_json_url(url, timeout=timeout)
        tag = normalize_version(str(data.get("tag_name") or ""))
        return (tag or None), None
    except (OSError, urllib.error.URLError, TimeoutError) as exc:
        return None, str(exc)
    except Exception as exc:
        return None, str(exc)


def check_update(manager: str = "", timeout: float = 5.0) -> dict[str, Any]:
    """Build a read-only update status payload."""
    latest, err = latest_version(manager, timeout=timeout)
    return {
        "current_version": __version__,
        "latest_version": latest or "",
        "update_available": bool(latest and latest != __version__),
        "install_method": "github-binary",
        "supported": True,
        "command": ["outlook-cli", "update", "--dry-run"],
        "release_url": GITHUB_RELEASES_URL,
        "signature_status": "not_checked",
        "skill_sync_command": skill_sync_command(),
        "skill_sync_status": "not_run",
        "error": err or "",
    }


def refresh_update_notices(manager: str, source: str, timeout: float = 2.0) -> list[dict[str, Any]]:
    """Actively check for notices for maintenance commands."""
    if update_notice_auto_disabled():
        return []
    try:
        status = check_update(manager, timeout=timeout)
    except Exception:
        return read_cached_update_notices()
    notices = update_notices_from_status(status, source)
    write_update_notice_cache(notices)
    return notices


def update_notices_from_status(status: dict[str, Any], source: str) -> list[dict[str, Any]]:
    """Convert update status data into Agent-facing notices."""
    if not status.get("update_available"):
        return []
    current = str(status.get("current_version") or __version__)
    latest = str(status.get("latest_version") or status.get("target_version") or "")
    default_command = "outlook-cli update --dry-run --compact"
    command = status.get("command") or []
    if isinstance(command, list):
        recommended = shlex.join(str(part) for part in command) if command else default_command
    else:
        recommended = str(command) or default_command
    return [
        {
            "type": "update_available",
            "severity": "info",
            "message": f"outlook-cli {latest} is available (current {current})",
            "current_version": current,
            "latest_version": latest,
            "update_available": True,
            "install_method": status.get("install_method", ""),
            "recommended_command": recommended,
            "release_url": status.get("release_url") or GITHUB_RELEASES_URL,
            "checked_at": _now_iso(),
            "source": source,
            "next_steps": [
                "run the recommended command",
                f"after update, run outlook-cli changelog --since {current} --compact",
                "refresh outlook-cli reference --compact before using new behavior",
            ],
        }
    ]


def read_cached_update_notices() -> list[dict[str, Any]]:
    """Read a non-stale update notice cache without touching the network."""
    if update_notice_auto_disabled():
        return []
    path = update_notice_cache_path()
    try:
        cache = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    checked_at = float(cache.get("checked_at_epoch") or 0)
    if checked_at <= 0 or (time_now() - checked_at) > UPDATE_NOTICE_TTL_SECONDS:
        return []
    notices = []
    for notice in cache.get("notices") or []:
        if notice.get("type") == "update_available" and notice.get("update_available"):
            cloned = dict(notice)
            cloned["source"] = "cache"
            notices.append(cloned)
    return notices


def write_update_notice_cache(notices: list[dict[str, Any]]) -> None:
    """Write or clear update notice cache."""
    if update_notice_auto_disabled():
        return
    path = update_notice_cache_path()
    if not notices:
        try:
            path.unlink()
        except OSError:
            pass
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        now = time_now()
        for notice in notices:
            notice["checked_at"] = _now_iso(now)
        path.write_text(
            json.dumps(
                {
                    "checked_at_epoch": now,
                    "checked_at": _now_iso(now),
                    "notices": notices,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    except OSError:
        return


def update_notice_cache_path() -> Path:
    from .config import config_dir

    return config_dir() / "update-check.json"


def update_notice_auto_disabled() -> bool:
    value = os.environ.get(NO_UPDATE_CHECK_ENV, "").strip().lower()
    if value in {"1", "true", "yes"}:
        return True
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def time_now() -> float:
    import time

    return time.time()


def _now_iso(epoch: float | None = None) -> str:
    import datetime as _dt

    if epoch is None:
        epoch = time_now()
    moment = _dt.datetime.fromtimestamp(epoch, tz=_dt.timezone.utc).replace(microsecond=0)
    return moment.isoformat().replace("+00:00", "Z")


def plan_update(manager: str, target_version: str) -> dict[str, Any]:
    """Build a deterministic dry-run plan without touching the network."""
    skill_command = skill_sync_command()
    return {
        "current_version": __version__,
        "target_version": target_version,
        "install_method": "github-binary",
        "supported": True,
        "command": ["outlook-cli", "update", "--confirm", "<confirm_token>"],
        "signature_status": "not_checked",
        "skill_sync_command": skill_command,
        "skill_sync_status": "not_run",
        "changes": [
            {
                "action": "download_verify_replace_binary",
                "detail": {
                    "target_version": target_version,
                    "verification": "Sigstore signature + archive SHA256",
                },
            },
            {
                "action": "sync_skill",
                "detail": {
                    "command": skill_command,
                },
            },
        ],
        "manual_url": "https://github.com/fatecannotbealtered/outlook-cli/releases",
    }


def execute_update(manager: str, target_version: str, quiet: bool = False) -> dict[str, Any]:
    """Download, verify (Sigstore signature + SHA256), and install the target
    release binary, then sync the Skill directory.

    Raises IntegrityError on any supply-chain failure (non-retryable) and
    UpdateFailed on transport or Skill-sync failures (retryable)."""
    from .update_binary import IntegrityError, perform_binary_update

    try:
        result = perform_binary_update(target_version)
    except IntegrityError:
        raise
    except (OSError, urllib.error.URLError, TimeoutError) as exc:
        raise UpdateFailed("Downloading release failed", {"error": str(exc)}) from exc

    skill_command = skill_sync_command()
    skill_result = subprocess.run(skill_command, capture_output=True, text=True, timeout=300)
    if not quiet:
        if skill_result.stdout:
            print(
                skill_result.stdout,
                file=sys.stderr,
                end="" if skill_result.stdout.endswith("\n") else "\n",
            )
        if skill_result.stderr:
            print(
                skill_result.stderr,
                file=sys.stderr,
                end="" if skill_result.stderr.endswith("\n") else "\n",
            )
    if skill_result.returncode != 0:
        raise UpdateFailed(
            "Skill sync command failed",
            {
                "command": skill_command,
                "returncode": skill_result.returncode,
                "stdout": skill_result.stdout[-4000:],
                "stderr": skill_result.stderr[-4000:],
            },
        )

    return {
        "previous_version": __version__,
        "current_version": result["current_version"],
        "target_version": target_version,
        "install_method": "github-binary",
        "status": result["status"],
        "signature_status": result["signature_status"],
        "signature_verified": result.get("signature_verified", True),
        "skill_sync_command": shlex.join(skill_command),
        "skill_sync_status": "synced",
        "updated": True,
        "next_step": f'run "outlook-cli changelog --since {__version__}" to see what changed',
    }


class UpdateUnsupported(Exception):
    """Automatic update is unsupported for this install method."""


class UpdateFailed(Exception):
    """Package-manager update failed."""

    def __init__(self, message: str, details: dict[str, Any]):
        super().__init__(message)
        self.details = details
