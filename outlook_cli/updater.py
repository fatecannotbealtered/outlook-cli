"""Self-update planning and execution."""

from __future__ import annotations

import json
import os
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
NPM_LATEST_URL = "https://registry.npmjs.org/@fatecannotbealtered-%2Foutlook-cli/latest"
PYPI_URL = "https://pypi.org/pypi/outlook-cli/json"


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


def _read_json_url(url: str, timeout: float = 5.0) -> dict[str, Any]:
    req = urllib.request.Request(
        url, headers={"User-Agent": f"outlook-cli/{__version__}"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def latest_version(manager: str) -> tuple[str | None, str | None]:
    """Return (latest_version, error_message)."""
    try:
        if manager == "npm":
            data = _read_json_url(NPM_LATEST_URL)
            return str(data.get("version") or ""), None
        if manager == "pip":
            data = _read_json_url(PYPI_URL)
            return str(data.get("info", {}).get("version") or ""), None
        return None, "manual installs do not expose a package registry"
    except (OSError, urllib.error.URLError, TimeoutError) as exc:
        return None, str(exc)
    except Exception as exc:
        return None, str(exc)


def check_update(manager: str) -> dict[str, Any]:
    """Build a read-only update status payload."""
    latest, err = latest_version(manager)
    command = update_command(manager)
    return {
        "current_version": __version__,
        "latest_version": latest or "",
        "update_available": bool(latest and latest != __version__),
        "install_method": manager,
        "supported": manager in {"npm", "pip"},
        "command": command,
        "error": err or "",
    }


def plan_update(manager: str, target_version: str) -> dict[str, Any]:
    """Build a deterministic dry-run plan without touching the network."""
    command = update_command(manager, target_version)
    supported = bool(command)
    return {
        "current_version": __version__,
        "target_version": target_version,
        "install_method": manager,
        "supported": supported,
        "command": command,
        "changes": [
            {
                "action": "update",
                "detail": {
                    "install_method": manager,
                    "target_version": target_version,
                    "command": command,
                },
            }
        ],
        "manual_url": "https://github.com/fatecannotbealtered/outlook-cli/releases",
    }


def execute_update(
    manager: str, target_version: str, quiet: bool = False
) -> dict[str, Any]:
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

    return {
        "previous_version": __version__,
        "current_version": resolved_version,
        "target_version": target_version,
        "install_method": manager,
        "command": command,
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
