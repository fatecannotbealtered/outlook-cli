"""Tests for binary self-update planning and the fail-closed signature gate."""

from unittest import mock

import pytest

from outlook_cli import changelog, update_binary, updater
from outlook_cli.update_binary import IntegrityError


def test_plan_update_is_binary_and_supported():
    plan = updater.plan_update("auto", "latest")
    assert plan["supported"] is True
    assert plan["install_method"] == "github-binary"
    assert plan["changes"][0]["action"] == "download_verify_replace_binary"
    assert plan["signature_status"] == "not_checked"


def test_check_update_resolves_from_github_releases():
    with mock.patch.object(updater, "latest_version", return_value=("9.9.9", None)):
        data = updater.check_update()
    assert data["install_method"] == "github-binary"
    assert data["latest_version"] == "9.9.9"
    assert data["update_available"] is True
    assert data["signature_status"] == "not_checked"


def test_execute_update_runs_binary_pipeline_and_syncs_skill():
    completed = mock.Mock(returncode=0, stdout="", stderr="")
    with (
        mock.patch.object(
            update_binary,
            "perform_binary_update",
            return_value={
                "status": "installed",
                "signature_status": "verified",
                "current_version": "2.0.1",
            },
        ),
        mock.patch.object(updater.subprocess, "run", return_value=completed),
    ):
        result = updater.execute_update("auto", "latest", quiet=True)

    assert result["previous_version"] == updater.__version__
    assert result["current_version"] == "2.0.1"
    assert result["install_method"] == "github-binary"
    assert result["signature_status"] == "verified"
    assert result["skill_sync_status"] == "synced"
    assert result["binary_replaced"] is True
    assert result["stage"] == "skill_sync"


def test_execute_update_integrity_failure_is_non_retryable_stage_error():
    # A supply-chain failure must surface as a non-retryable StageError tagged
    # E_INTEGRITY, with the stage invariant intact (old version, not replaced).
    with mock.patch.object(
        update_binary, "perform_binary_update", side_effect=IntegrityError("bad signature")
    ):
        with pytest.raises(updater.StageError) as excinfo:
            updater.execute_update("auto", "latest", quiet=True)
    err = excinfo.value
    assert err.code == "E_INTEGRITY"
    assert err.retryable is False
    assert err.binary_replaced is False
    assert err.current_version == updater.__version__
    details = err.envelope_details()
    assert details["stage"] in {"discover", "download", "verify_signature", "verify_checksum"}
    assert details["binary_replaced"] is False
    assert details["current_version"] == updater.__version__


def test_execute_update_replace_io_failure_is_e_io():
    # A local replace failure must be E_IO (not network), binary not replaced.
    with mock.patch.object(
        update_binary,
        "perform_binary_update",
        side_effect=update_binary.ReplaceError("disk full", "E_IO"),
    ):
        with pytest.raises(updater.StageError) as excinfo:
            updater.execute_update("auto", "latest", quiet=True)
    err = excinfo.value
    assert err.code == "E_IO"
    assert err.stage == "replace"
    assert err.binary_replaced is False
    assert err.retryable is False


def test_execute_update_replace_permission_failure_is_e_forbidden():
    with mock.patch.object(
        update_binary,
        "perform_binary_update",
        side_effect=update_binary.ReplaceError("permission denied", "E_FORBIDDEN"),
    ):
        with pytest.raises(updater.StageError) as excinfo:
            updater.execute_update("auto", "latest", quiet=True)
    assert excinfo.value.code == "E_FORBIDDEN"
    assert excinfo.value.stage == "replace"


def test_execute_update_download_failure_is_retryable_network():
    with mock.patch.object(
        update_binary, "perform_binary_update", side_effect=OSError("connection reset")
    ):
        with pytest.raises(updater.StageError) as excinfo:
            updater.execute_update("auto", "latest", quiet=True)
    err = excinfo.value
    assert err.code == "E_NETWORK"
    assert err.stage == "download"
    assert err.retryable is True
    assert err.binary_replaced is False


def test_execute_update_skill_sync_failure_is_partial_success():
    # Binary replaced, Skill sync failed -> partial success, NOT a hard error:
    # binary_replaced True, retryable, with skill_sync_command for the agent.
    completed = mock.Mock(returncode=1, stdout="boom", stderr="npx missing")
    with (
        mock.patch.object(
            update_binary,
            "perform_binary_update",
            return_value={
                "status": "installed",
                "signature_status": "verified",
                "current_version": "2.0.1",
            },
        ),
        mock.patch.object(updater.subprocess, "run", return_value=completed),
    ):
        with pytest.raises(updater.SkillSyncPartial) as excinfo:
            updater.execute_update("auto", "latest", quiet=True)
    err = excinfo.value
    assert err.current_version == "2.0.1"
    data = err.data()
    assert data["binary_replaced"] is True
    assert data["skill_sync_status"] == "failed"
    assert data["skill_sync_command"]


def test_perform_binary_update_refuses_unsigned_release():
    # No checksums.txt.sigstore.json asset -> refused (no skip path).
    release = {
        "tag_name": "v9.9.9",
        "assets": [
            {"name": "outlook-cli-9.9.9-linux-amd64.tar.gz", "browser_download_url": "https://x/a"},
            {"name": "checksums.txt", "browser_download_url": "https://x/c"},
        ],
    }
    with (
        mock.patch.object(update_binary, "fetch_release", return_value=release),
        mock.patch.object(update_binary, "_platform", return_value=("linux", "amd64")),
        mock.patch("sys.executable", "/tmp/outlook-cli"),
    ):
        with pytest.raises(IntegrityError, match="unsigned release"):
            update_binary.perform_binary_update("latest")


def test_signer_identity_pins_exact_tag():
    ident = update_binary.signer_identity("1.2.3")
    assert ident == (
        "https://github.com/fatecannotbealtered/outlook-cli/"
        ".github/workflows/release.yml@refs/tags/v1.2.3"
    )


def test_verify_checksum_detects_mismatch():
    archive = b"hello"
    checksums = "0000  outlook-cli-1-linux-amd64.tar.gz\n"
    with pytest.raises(IntegrityError, match="checksum mismatch"):
        update_binary.verify_checksum(archive, checksums, "outlook-cli-1-linux-amd64.tar.gz")


# --- severity grading from the embedded CHANGELOG delta (CLI-SPEC §14) ---


def _entry(version, **categories):
    changes = {
        name: [] for name in ("added", "changed", "deprecated", "fixed", "removed", "security")
    }
    changes.update(categories)
    return {"version": version, "date": "", "changes": changes}


def test_severity_warning_when_delta_has_security_entry(monkeypatch):
    monkeypatch.setattr(
        changelog, "entries_since", lambda since=None: [_entry("1.0.1", security=["CVE fix"])]
    )
    assert updater.grade_update_severity("1.0.0", "1.0.1") == "warning"


def test_severity_warning_on_major_bump(monkeypatch):
    monkeypatch.setattr(changelog, "entries_since", lambda since=None: [_entry("2.0.0")])
    assert updater.grade_update_severity("1.5.0", "2.0.0") == "warning"


def test_severity_info_for_plain_patch(monkeypatch):
    monkeypatch.setattr(
        changelog, "entries_since", lambda since=None: [_entry("1.0.1", fixed=["small fix"])]
    )
    assert updater.grade_update_severity("1.0.0", "1.0.1") == "info"


def test_notices_carry_graded_severity(monkeypatch):
    monkeypatch.setattr(
        changelog, "entries_since", lambda since=None: [_entry("1.0.1", security=["CVE fix"])]
    )
    status = {
        "update_available": True,
        "current_version": "1.0.0",
        "latest_version": "1.0.1",
        "install_method": "github-binary",
        "command": ["outlook-cli", "update"],
    }
    notices = updater.update_notices_from_status(status, "update_check")
    assert notices[0]["severity"] == "warning"
