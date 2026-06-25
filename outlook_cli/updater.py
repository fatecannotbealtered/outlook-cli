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
        "command": ["outlook-cli", "update"],
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


def grade_update_severity(current: str, latest: str) -> str:
    """Grade an available update from the embedded CHANGELOG delta.

    `warning` when the delta since the running version contains a `security`
    entry, or the latest crosses a major version; otherwise `info`."""
    from .changelog import _version_key, entries_since

    if _version_key(latest)[0] > _version_key(current)[0]:
        return "warning"
    for entry in entries_since(current):
        if entry["version"].lower() == "unreleased":
            continue
        if entry["changes"].get("security"):
            return "warning"
    return "info"


def update_notices_from_status(status: dict[str, Any], source: str) -> list[dict[str, Any]]:
    """Convert update status data into Agent-facing notices."""
    if not status.get("update_available"):
        return []
    current = str(status.get("current_version") or __version__)
    latest = str(status.get("latest_version") or status.get("target_version") or "")
    severity = grade_update_severity(current, latest)
    default_command = "outlook-cli update --compact"
    command = status.get("command") or []
    if isinstance(command, list):
        recommended = shlex.join(str(part) for part in command) if command else default_command
    else:
        recommended = str(command) or default_command
    return [
        {
            "type": "update_available",
            "severity": severity,
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
        "command": ["outlook-cli", "update"],
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


class UpdateProgress:
    """Live post-failure state of a staged update.

    Updated by `execute_update` as each stage begins and once the binary swap
    commits, so a SIGINT/SIGTERM handler interrupting mid-flight can report the
    TRUE stage, version, and whether the binary was already replaced — instead
    of hardcoding `download`/old-version and risking a misstated version
    (CLI-SPEC §14 hard rule #1)."""

    def __init__(self) -> None:
        self.stage: str = "discover"
        self.binary_replaced: bool = False
        self.current_version: str = __version__


def execute_update(
    manager: str,
    target_version: str,
    quiet: bool = False,
    progress: UpdateProgress | None = None,
) -> dict[str, Any]:
    """Run the staged self-update: discover -> download -> verify_signature ->
    verify_checksum -> replace -> skill_sync, then sync the Skill directory.

    On success returns a result dict carrying the stage invariant fields
    (`stage`, `current_version`, `binary_replaced`, `skill_sync_status`).

    `progress`, when given, is updated as each stage begins and once the binary
    swap commits, so a SIGINT handler can report the TRUE post-failure state
    (which stage, which version, binary replaced or not) instead of guessing.

    Raises StageError on every failure, classified by the agent's next action:
    integrity failures are non-retryable E_INTEGRITY; replace-stage local
    failures are E_IO / E_FORBIDDEN (binary not replaced); a Skill-sync failure
    AFTER a successful binary swap is a PARTIAL SUCCESS (binary_replaced=True,
    retryable) so the agent knows it is already on the new binary."""
    from .update_binary import IntegrityError, ReplaceError, perform_binary_update

    previous_version = __version__
    skill_command = skill_sync_command()
    skill_command_str = shlex.join(skill_command)
    if progress is None:
        progress = UpdateProgress()

    def _on_stage(name: str) -> None:
        progress.stage = name

    # --- Stages BEFORE the swap: any failure leaves the old binary intact. ---
    try:
        result = perform_binary_update(target_version, on_stage=_on_stage)
    except IntegrityError as exc:
        # Could be discover (missing asset/tag) or verify (signature/checksum).
        # Either way it is a non-retryable integrity refusal: old version stays.
        raise StageError(
            str(exc),
            stage="verify_signature",
            code="E_INTEGRITY",
            current_version=previous_version,
            binary_replaced=False,
            skill_sync_status="not_run",
            retryable=False,
        ) from exc
    except ReplaceError as exc:
        # Local commit failure: temp/extract/write/rename/permission/disk.
        # The atomic swap never committed, so the old binary is still installed.
        raise StageError(
            str(exc),
            stage="replace",
            code=exc.error_code,
            current_version=previous_version,
            binary_replaced=False,
            skill_sync_status="not_run",
            retryable=False,
            details={"command": "update", "fix": "see message; fix the environment, then re-run"},
        ) from exc
    except (OSError, urllib.error.URLError, TimeoutError) as exc:
        # Transport failure during discover/download: transient, old version.
        raise StageError(
            "Downloading release failed",
            stage="download",
            code="E_NETWORK",
            current_version=previous_version,
            binary_replaced=False,
            skill_sync_status="not_run",
            retryable=True,
            details={"error": str(exc)},
        ) from exc

    # --- After the atomic swap: the binary is NEW; Skill sync is replayable. ---
    new_version = result["current_version"]
    progress.stage = "skill_sync"
    progress.binary_replaced = True
    progress.current_version = new_version
    try:
        skill_result = subprocess.run(skill_command, capture_output=True, text=True, timeout=300)
    except FileNotFoundError as exc:
        # `npx` is not installed: the binary is already on the new version, only
        # the Skill is stale. This is a PARTIAL SUCCESS, not E_SERVER — the agent
        # must run skill_sync_command, not loop on a server error.
        raise SkillSyncPartial(
            f"binary updated to {new_version}; Skill sync failed (npx not found) — "
            f"run `{skill_command_str}`, then changelog --since {previous_version}",
            previous_version=previous_version,
            current_version=new_version,
            skill_sync_command=skill_command_str,
            details={"command": skill_command, "error": str(exc)},
        ) from exc
    except subprocess.TimeoutExpired as exc:
        # Skill sync timed out post-swap: still a partial success, replayable.
        raise SkillSyncPartial(
            f"binary updated to {new_version}; Skill sync timed out — "
            f"run `{skill_command_str}`, then changelog --since {previous_version}",
            previous_version=previous_version,
            current_version=new_version,
            skill_sync_command=skill_command_str,
            details={"command": skill_command, "error": str(exc)},
        ) from exc
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
        # Partial success: the binary already updated; only the Skill is stale.
        raise SkillSyncPartial(
            f"binary updated to {new_version}; Skill sync failed — "
            f"run `{skill_command_str}`, then changelog --since {previous_version}",
            previous_version=previous_version,
            current_version=new_version,
            skill_sync_command=skill_command_str,
            details={
                "command": skill_command,
                "returncode": skill_result.returncode,
                "stdout": skill_result.stdout[-4000:],
                "stderr": skill_result.stderr[-4000:],
            },
        )

    return {
        "previous_version": previous_version,
        "current_version": new_version,
        "target_version": target_version,
        "install_method": "github-binary",
        "status": result["status"],
        "stage": "skill_sync",
        "binary_replaced": True,
        "signature_status": result["signature_status"],
        "signature_verified": result.get("signature_verified", True),
        "skill_sync_command": skill_command_str,
        "skill_sync_status": "synced",
        "updated": True,
        "next_step": f'run "outlook-cli changelog --since {previous_version}" to see what changed',
    }


class UpdateUnsupported(Exception):
    """Automatic update is unsupported for this install method."""


class UpdateFailed(Exception):
    """Package-manager update failed."""

    def __init__(self, message: str, details: dict[str, Any]):
        super().__init__(message)
        self.details = details


class StageError(Exception):
    """A staged-update failure that carries the full post-failure state.

    Every update failure envelope must report `stage`, `current_version`,
    `binary_replaced`, and `skill_sync_status` so an agent always knows which
    version it is running and what to do next."""

    def __init__(
        self,
        message: str,
        *,
        stage: str,
        code: str,
        current_version: str,
        binary_replaced: bool,
        skill_sync_status: str,
        retryable: bool,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.stage = stage
        self.code = code
        self.current_version = current_version
        self.binary_replaced = binary_replaced
        self.skill_sync_status = skill_sync_status
        self.retryable = retryable
        self.details = dict(details or {})

    def envelope_details(self) -> dict[str, Any]:
        """Stage-invariant fields every failure envelope must carry."""
        return {
            **self.details,
            "stage": self.stage,
            "current_version": self.current_version,
            "binary_replaced": self.binary_replaced,
            "skill_sync_status": self.skill_sync_status,
        }


class SkillSyncPartial(Exception):
    """Binary replaced successfully but the Skill sync failed afterwards.

    This is a PARTIAL SUCCESS, not a hard failure: the agent is already on the
    new binary and only needs to run `skill_sync_command`, then read the
    changelog. Surfaced as ok:false, binary_replaced:true, retryable:true."""

    def __init__(
        self,
        message: str,
        *,
        previous_version: str,
        current_version: str,
        skill_sync_command: str,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.previous_version = previous_version
        self.current_version = current_version
        self.skill_sync_command = skill_sync_command
        self.details = dict(details or {})

    def data(self) -> dict[str, Any]:
        """Partial-success `data` payload (lives in data, not error.details)."""
        return {
            "previous_version": self.previous_version,
            "current_version": self.current_version,
            "target_version": "",
            "install_method": "github-binary",
            "stage": "skill_sync",
            "binary_replaced": True,
            "skill_sync_status": "failed",
            "skill_sync_command": self.skill_sync_command,
            "updated": True,
            "next_step": (
                f"run `{self.skill_sync_command}`, then "
                f'"outlook-cli changelog --since {self.previous_version}"'
            ),
            **self.details,
        }
