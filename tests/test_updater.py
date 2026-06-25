"""Tests for binary self-update planning and the fail-closed signature gate."""

import os
from unittest import mock

import pytest

from outlook_cli import changelog, update_binary, updater
from outlook_cli.update_binary import IntegrityError, replace_executable


def test_detect_install_method_honors_explicit_request():
    assert updater.detect_install_method("npm") == "npm"
    assert updater.detect_install_method("pip") == "pip"
    assert updater.detect_install_method("manual") == "manual"


def test_detect_install_method_honors_env_override(monkeypatch):
    monkeypatch.setenv("OUTLOOK_CLI_UPDATE_MANAGER", "npm")
    assert updater.detect_install_method("auto") == "npm"
    monkeypatch.setenv("OUTLOOK_CLI_UPDATE_MANAGER", "MANUAL")
    assert updater.detect_install_method("auto") == "manual"


def test_detect_install_method_frozen_without_package_json_is_manual(monkeypatch, tmp_path):
    monkeypatch.delenv("OUTLOOK_CLI_UPDATE_MANAGER", raising=False)
    monkeypatch.setattr(updater.sys, "frozen", True, raising=False)
    fake_exe = tmp_path / "bin" / "outlook-cli"
    fake_exe.parent.mkdir(parents=True)
    fake_exe.write_bytes(b"x")
    monkeypatch.setattr(updater.sys, "executable", str(fake_exe))
    # No package.json two levels up -> manual.
    assert updater.detect_install_method("auto") == "manual"


def test_detect_install_method_frozen_with_package_json_is_npm(monkeypatch, tmp_path):
    monkeypatch.delenv("OUTLOOK_CLI_UPDATE_MANAGER", raising=False)
    monkeypatch.setattr(updater.sys, "frozen", True, raising=False)
    exe = tmp_path / "node_modules" / ".bin" / "outlook-cli"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"x")
    (exe.parent.parent / "package.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(updater.sys, "executable", str(exe))
    assert updater.detect_install_method("auto") == "npm"


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


def test_execute_update_skill_sync_npx_missing_is_partial_success():
    # npx not installed -> subprocess.run raises FileNotFoundError. This must
    # NOT escape as a catch-all E_SERVER: the binary is already swapped, so it
    # is a partial success that tells the agent to run skill_sync_command.
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
        mock.patch.object(
            updater.subprocess, "run", side_effect=FileNotFoundError("npx")
        ),
    ):
        with pytest.raises(updater.SkillSyncPartial) as excinfo:
            updater.execute_update("auto", "latest", quiet=True)
    err = excinfo.value
    assert err.current_version == "2.0.1"
    data = err.data()
    assert data["binary_replaced"] is True
    assert data["skill_sync_status"] == "failed"
    assert data["skill_sync_command"]


def test_execute_update_skill_sync_timeout_is_partial_success():
    # A Skill-sync timeout post-swap is partial success, not a hard E_SERVER.
    import subprocess

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
        mock.patch.object(
            updater.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(cmd="npx", timeout=300),
        ),
    ):
        with pytest.raises(updater.SkillSyncPartial) as excinfo:
            updater.execute_update("auto", "latest", quiet=True)
    assert excinfo.value.current_version == "2.0.1"
    assert excinfo.value.data()["binary_replaced"] is True


def test_execute_update_progress_records_binary_replaced_before_skill_sync():
    # After the swap commits, progress must report binary_replaced + the new
    # version so an interrupt handler can report the truthful post-swap state.
    progress = updater.UpdateProgress()
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
        updater.execute_update("auto", "latest", quiet=True, progress=progress)
    assert progress.binary_replaced is True
    assert progress.current_version == "2.0.1"
    assert progress.stage == "skill_sync"


def test_execute_update_progress_tracks_stage_before_swap():
    # Before the swap, progress reflects the stage that failed and keeps the old
    # version + binary_replaced=False (so an interrupt never misstates version).
    progress = updater.UpdateProgress()

    def _fail(target, on_stage=None):
        on_stage("verify_signature")
        raise IntegrityError("bad signature")

    with mock.patch.object(update_binary, "perform_binary_update", side_effect=_fail):
        with pytest.raises(updater.StageError):
            updater.execute_update("auto", "latest", quiet=True, progress=progress)
    assert progress.stage == "verify_signature"
    assert progress.binary_replaced is False
    assert progress.current_version == updater.__version__


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


# --- in-place rename-trick binary swap (no .cmd helper / restart on any OS) ---


def test_replace_executable_swaps_in_place_and_returns_installed(tmp_path):
    target = tmp_path / "outlook-cli"
    target.write_bytes(b"OLD")

    status = replace_executable(target, b"NEW")

    assert status == "installed"
    assert target.read_bytes() == b"NEW"
    # No helper script, no pending .new, no leftover .old.
    leftovers = [p.name for p in tmp_path.iterdir() if p != target]
    assert leftovers == [], leftovers


def test_replace_executable_leaves_no_cmd_helper(tmp_path):
    target = tmp_path / "outlook-cli.exe"
    target.write_bytes(b"OLD")

    replace_executable(target, b"NEW")

    assert not list(tmp_path.glob("*.cmd"))
    assert not list(tmp_path.glob("*.new"))
    assert target.read_bytes() == b"NEW"


def test_replace_executable_rolls_back_when_final_rename_fails(tmp_path):
    target = tmp_path / "outlook-cli"
    target.write_bytes(b"OLD")

    real_rename = os.rename
    calls = {"n": 0}

    def flaky_rename(src, dst):
        calls["n"] += 1
        # First rename (target -> .old) succeeds; second (.new -> target) fails;
        # the rollback rename (.old -> target) must succeed.
        if calls["n"] == 2:
            raise OSError("simulated rename failure")
        return real_rename(src, dst)

    with mock.patch.object(update_binary.os, "rename", side_effect=flaky_rename):
        with pytest.raises(OSError, match="simulated rename failure"):
            replace_executable(target, b"NEW")

    # Original binary restored in place; new content not committed.
    assert target.read_bytes() == b"OLD"


def test_replace_executable_resolves_symlink_to_real_file(tmp_path):
    # A self-update reached through a symlink must replace the REAL binary
    # behind the link, not clobber the link itself (regression: the port
    # initially dropped jira's EvalSymlinks symlink resolution).
    real = tmp_path / "outlook-cli-real"
    real.write_bytes(b"OLD")
    link = tmp_path / "outlook-cli"
    try:
        os.symlink(real, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported on this platform/filesystem")

    status = replace_executable(link, b"NEW")

    assert status == "installed"
    # The real file behind the link received the new bytes.
    assert real.read_bytes() == b"NEW"
    # The link is preserved as a link still pointing at the real file.
    assert link.is_symlink()
    assert os.path.realpath(link) == os.path.realpath(real)


def test_replace_executable_cleans_staged_new_when_final_rename_fails(tmp_path):
    # A failed final swap must not leave a half-applied `.<name>.new` behind:
    # the staged artifact is never trusted, so it is discarded on rollback.
    target = tmp_path / "outlook-cli"
    target.write_bytes(b"OLD")

    real_rename = os.rename
    calls = {"n": 0}

    def flaky_rename(src, dst):
        calls["n"] += 1
        if calls["n"] == 2:  # .new -> target fails; rollback restores OLD
            raise OSError("simulated rename failure")
        return real_rename(src, dst)

    with mock.patch.object(update_binary.os, "rename", side_effect=flaky_rename):
        with pytest.raises(OSError, match="simulated rename failure"):
            replace_executable(target, b"NEW")

    assert target.read_bytes() == b"OLD"
    assert not list(tmp_path.glob("*.new")), "half-written .new left behind"


def test_replace_executable_cleans_staged_new_on_interrupt(tmp_path):
    # An interrupt (SIGINT -> KeyboardInterrupt, a BaseException) before the swap
    # commits must also leave no `.new` behind.
    target = tmp_path / "outlook-cli"
    target.write_bytes(b"OLD")

    real_rename = os.rename

    def interrupt_first_rename(src, dst):
        raise KeyboardInterrupt()

    with mock.patch.object(update_binary.os, "rename", side_effect=interrupt_first_rename):
        with pytest.raises(KeyboardInterrupt):
            replace_executable(target, b"NEW")

    assert target.read_bytes() == b"OLD"
    assert not list(tmp_path.glob("*.new")), "half-written .new left behind"
    # Sanity: os.rename was the trap point, original kept intact.
    assert real_rename is os.rename


def test_extract_binary_closes_tarfile_handle(tmp_path):
    # extractfile() returns a file object that must be closed to avoid a handle
    # leak; the returned bytes must still be correct.
    import io
    import tarfile

    buf = io.BytesIO()
    payload = b"BINARY-BYTES"
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        info = tarfile.TarInfo(name="outlook-cli")
        info.size = len(payload)
        tf.addfile(info, io.BytesIO(payload))

    real_extractfile = tarfile.TarFile.extractfile
    closed = {"flag": False}

    def tracking_extractfile(self, member):
        fh = real_extractfile(self, member)

        class _Tracker:
            def __init__(self, inner):
                self._inner = inner

            def read(self, *a):
                return self._inner.read(*a)

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                closed["flag"] = True
                return self._inner.__exit__(*exc)

            def close(self):
                closed["flag"] = True
                return self._inner.close()

        return _Tracker(fh)

    with mock.patch.object(tarfile.TarFile, "extractfile", tracking_extractfile):
        out = update_binary.extract_binary(buf.getvalue(), is_zip=False)

    assert out == payload
    assert closed["flag"] is True, "tarfile member handle not closed"


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
