"""Self-update planning and execution."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from . import __version__

NPM_PACKAGE = "@fatecannotbealtered-/outlook-cli"
PYPI_PACKAGE = "outlook-cli"
SKILL_REPO = "fatecannotbealtered/outlook-cli"
NPM_LATEST_URL = "https://registry.npmjs.org/@fatecannotbealtered-%2Foutlook-cli/latest"
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


def update_command(manager: str, target_version: str = "latest") -> list[str]:
    """Build the command that performs the update."""
    if manager == "npm":
        target = target_version if target_version != "latest" else "latest"
        return ["npm", "install", "-g", f"{NPM_PACKAGE}@{target}"]
    if manager == "pip":
        if target_version == "latest":
            return [sys.executable, "-m", "pip", "install", "--upgrade", PYPI_PACKAGE]
        return [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--upgrade",
            f"{PYPI_PACKAGE}=={target_version}",
        ]
    return []


def skill_sync_command() -> list[str]:
    """Build the command that syncs the whole Agent Skill directory."""
    return ["npx", "skills", "add", SKILL_REPO, "-y", "-g"]


def signature_status(manager: str) -> str:
    """Describe where release integrity verification happens for this update path."""
    if manager == "npm":
        return "handled_by_npm_installer"
    if manager == "pip":
        return "handled_by_package_manager"
    return "manual_release_verification_required"


def _read_json_url(url: str, timeout: float = 5.0) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": f"outlook-cli/{__version__}"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def latest_version(manager: str, timeout: float = 5.0) -> tuple[str | None, str | None]:
    """Return (latest_version, error_message)."""
    try:
        if manager == "npm":
            data = _read_json_url(NPM_LATEST_URL, timeout=timeout)
            return str(data.get("version") or ""), None
        if manager == "pip":
            data = _read_json_url(PYPI_URL, timeout=timeout)
            return str(data.get("info", {}).get("version") or ""), None
        return None, "manual installs do not expose a package registry"
    except (OSError, urllib.error.URLError, TimeoutError) as exc:
        return None, str(exc)
    except Exception as exc:
        return None, str(exc)


def check_update(manager: str, timeout: float = 5.0) -> dict[str, Any]:
    """Build a read-only update status payload."""
    latest, err = latest_version(manager, timeout=timeout)
    command = update_command(manager)
    return {
        "current_version": __version__,
        "latest_version": latest or "",
        "update_available": bool(latest and latest != __version__),
        "install_method": manager,
        "supported": manager in {"npm", "pip"},
        "command": command,
        "release_url": release_url(manager),
        "signature_status": signature_status(manager),
        "skill_sync_command": skill_sync_command(),
        "skill_sync_status": "not_run",
        "error": err or "",
    }


def release_url(manager: str) -> str:
    """Return the human release/source page for an update method."""
    if manager == "npm":
        return "https://www.npmjs.com/package/@fatecannotbealtered-/outlook-cli"
    if manager == "pip":
        return "https://pypi.org/project/outlook-cli/"
    return GITHUB_RELEASES_URL


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
    command = status.get("command") or []
    if isinstance(command, list):
        recommended = shlex.join(str(part) for part in command) if command else "outlook-cli update --dry-run --compact"
    else:
        recommended = str(command) or "outlook-cli update --dry-run --compact"
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
                "after update, run outlook-cli changelog --since "
                f"{current} --compact",
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
    return _dt.datetime.fromtimestamp(epoch, tz=_dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def plan_update(manager: str, target_version: str) -> dict[str, Any]:
    """Build a deterministic dry-run plan without touching the network."""
    command = update_command(manager, target_version)
    skill_command = skill_sync_command()
    supported = bool(command)
    return {
        "current_version": __version__,
        "target_version": target_version,
        "install_method": manager,
        "supported": supported,
        "command": command,
        "signature_status": signature_status(manager),
        "skill_sync_command": skill_command,
        "skill_sync_status": "not_run",
        "changes": [
            {
                "action": "update",
                "detail": {
                    "install_method": manager,
                    "target_version": target_version,
                    "command": command,
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
    """Execute the package-manager update command."""
    command = update_command(manager, target_version)
    if not command:
        raise UpdateUnsupported(
            "This installation cannot be updated automatically. Download a release manually."
        )

    if shutil.which(command[0]) is None and not Path(command[0]).exists():
        raise UpdateUnsupported(f"Update manager not found: {command[0]}")

    resolved_version = target_version
    if target_version == "latest":
        latest, _ = latest_version(manager)
        if latest:
            resolved_version = latest

    result = subprocess.run(command, capture_output=True, text=True, timeout=300)
    if not quiet:
        if result.stdout:
            print(
                result.stdout,
                file=sys.stderr,
                end="" if result.stdout.endswith("\n") else "\n",
            )
        if result.stderr:
            print(
                result.stderr,
                file=sys.stderr,
                end="" if result.stderr.endswith("\n") else "\n",
            )

    if result.returncode != 0:
        raise UpdateFailed(
            "Update command failed",
            {
                "command": command,
                "returncode": result.returncode,
                "stdout": result.stdout[-4000:],
                "stderr": result.stderr[-4000:],
            },
        )

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
        "current_version": resolved_version,
        "target_version": target_version,
        "install_method": manager,
        "command": command,
        "signature_status": signature_status(manager),
        "skill_sync_command": skill_command,
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
