"""Single-command update contract (CLI-SPEC §14).

Drives the `update` command in-process so we can inject staged failures and
assert the failure/interruption envelope without a live release:

- a bare `update` executes without a confirm token;
- integrity failure is non-retryable E_INTEGRITY (exit 1);
- a Skill-sync failure after a successful swap is partial success
  (ok:false, binary_replaced:true, retryable);
- replace-stage local failures map to E_IO / E_FORBIDDEN;
- SIGINT during the update still emits a terminal JSON envelope (E_INTERRUPTED).
"""

import json
from unittest import mock

from click.testing import CliRunner

from outlook_cli import output, updater
from outlook_cli.main import update_cmd
from outlook_cli.update_binary import IntegrityError, ReplaceError


def _invoke(args, *, obj=None):
    output.init(format_mode="json")
    runner = CliRunner()
    base = {"dry_run": False, "confirm": None, "quiet": True}
    if obj:
        base.update(obj)
    return runner.invoke(update_cmd, args, obj=base, catch_exceptions=False)


def _doc(result):
    # CliRunner merges stdout (the JSON envelope) and stderr (a human line), so
    # decode only the first JSON object and ignore any trailing stderr text.
    text = result.output
    start = text.find("{")
    assert start >= 0, f"no JSON in output: {text!r}"
    obj, _end = json.JSONDecoder().raw_decode(text[start:])
    return obj


def _not_on_target(monkeypatch):
    """Force the idempotency probe to report an available newer release."""
    monkeypatch.setattr("outlook_cli.main._already_on_target", lambda *_a, **_k: False)


def test_bare_update_executes_without_confirm_token(monkeypatch):
    _not_on_target(monkeypatch)
    monkeypatch.setattr(
        updater,
        "execute_update",
        lambda *a, **k: {
            "previous_version": "1.0.0",
            "current_version": "2.0.0",
            "install_method": "github-binary",
            "stage": "skill_sync",
            "binary_replaced": True,
            "signature_status": "verified",
            "skill_sync_status": "synced",
            "updated": True,
        },
    )
    # No --confirm anywhere; bare update must run and succeed.
    result = _invoke([])
    assert result.exit_code == 0, result.output
    data = _doc(result)["data"]
    assert data["binary_replaced"] is True
    assert data["current_version"] == "2.0.0"


def test_dry_run_issues_no_confirm_token(monkeypatch):
    result = _invoke([], obj={"dry_run": True})
    assert result.exit_code == 0, result.output
    data = _doc(result)["data"]
    assert "confirm_token" not in data
    assert "expires_at" not in data
    assert data["install_method"] == "github-binary"


def test_integrity_failure_is_non_retryable(monkeypatch):
    _not_on_target(monkeypatch)
    monkeypatch.setattr(updater.subprocess, "run", mock.Mock())  # must never be called
    with mock.patch(
        "outlook_cli.update_binary.perform_binary_update",
        side_effect=IntegrityError("signature verification failed"),
    ):
        result = _invoke(["--manager", "manual"])
    assert result.exit_code == 1
    doc = _doc(result)
    assert doc["error"]["code"] == "E_INTEGRITY"
    assert doc["error"]["retryable"] is False
    details = doc["error"]["details"]
    assert details["binary_replaced"] is False
    assert details["current_version"]
    assert "stage" in details


def test_replace_io_failure_is_e_io(monkeypatch):
    _not_on_target(monkeypatch)
    with mock.patch(
        "outlook_cli.update_binary.perform_binary_update",
        side_effect=ReplaceError("disk full", "E_IO"),
    ):
        result = _invoke(["--manager", "manual"])
    assert result.exit_code == 1
    doc = _doc(result)
    assert doc["error"]["code"] == "E_IO"
    assert doc["error"]["details"]["stage"] == "replace"
    assert doc["error"]["details"]["binary_replaced"] is False


def test_replace_permission_failure_is_e_forbidden(monkeypatch):
    _not_on_target(monkeypatch)
    with mock.patch(
        "outlook_cli.update_binary.perform_binary_update",
        side_effect=ReplaceError("permission denied", "E_FORBIDDEN"),
    ):
        result = _invoke(["--manager", "manual"])
    assert result.exit_code == 4
    doc = _doc(result)
    assert doc["error"]["code"] == "E_FORBIDDEN"
    assert doc["error"]["details"]["stage"] == "replace"


def test_skill_sync_failure_is_partial_success(monkeypatch):
    _not_on_target(monkeypatch)
    completed = mock.Mock(returncode=1, stdout="", stderr="npx not found")
    with (
        mock.patch(
            "outlook_cli.update_binary.perform_binary_update",
            return_value={
                "status": "installed",
                "signature_status": "verified",
                "current_version": "2.0.0",
            },
        ),
        mock.patch.object(updater.subprocess, "run", return_value=completed),
    ):
        result = _invoke(["--manager", "manual"])
    # Partial success: not exit 0 (it is not a clean success), but the envelope
    # tells the agent the binary is already new and gives skill_sync_command.
    doc = _doc(result)
    assert doc["ok"] is False
    details = doc["error"]["details"]
    assert details["binary_replaced"] is True
    assert details["skill_sync_status"] == "failed"
    assert details["current_version"] == "2.0.0"
    assert details["skill_sync_command"]
    assert doc["error"]["retryable"] is True


def test_download_failure_is_retryable_network(monkeypatch):
    _not_on_target(monkeypatch)
    with mock.patch(
        "outlook_cli.update_binary.perform_binary_update",
        side_effect=OSError("connection reset"),
    ):
        result = _invoke(["--manager", "manual"])
    assert result.exit_code == 7
    doc = _doc(result)
    assert doc["error"]["code"] == "E_NETWORK"
    assert doc["error"]["retryable"] is True
    assert doc["error"]["details"]["binary_replaced"] is False


def test_interrupt_emits_terminal_envelope(monkeypatch):
    _not_on_target(monkeypatch)
    with mock.patch(
        "outlook_cli.updater.execute_update",
        side_effect=KeyboardInterrupt(),
    ):
        result = _invoke([])
    assert result.exit_code == 130
    doc = _doc(result)
    assert doc["error"]["code"] == "E_INTERRUPTED"
    assert doc["error"]["retryable"] is True
    details = doc["error"]["details"]
    assert details["binary_replaced"] is False
    assert details["current_version"]


def test_interrupt_after_swap_reports_new_version_and_partial(monkeypatch):
    # An interrupt that lands AFTER the binary swap must not claim "no change,
    # still on old": it must report binary_replaced=true, the NEW version, and a
    # skill_sync_command (CLI-SPEC §14 hard rule #1: never misstate the version).
    from outlook_cli import updater

    def _interrupt_after_swap(manager, target_version, quiet=False, progress=None):
        # Simulate the swap committing before the interrupt fires.
        progress.stage = "skill_sync"
        progress.binary_replaced = True
        progress.current_version = "2.0.0"
        raise KeyboardInterrupt()

    _not_on_target(monkeypatch)
    monkeypatch.setattr(updater, "execute_update", _interrupt_after_swap)
    result = _invoke([])
    assert result.exit_code == 130
    doc = _doc(result)
    assert doc["error"]["code"] == "E_INTERRUPTED"
    assert doc["error"]["retryable"] is True
    details = doc["error"]["details"]
    assert details["binary_replaced"] is True
    assert details["current_version"] == "2.0.0"
    assert details["skill_sync_status"] == "failed"
    assert details["skill_sync_command"]


def test_interrupt_during_verify_is_interrupted_not_integrity(monkeypatch):
    # A SIGINT landing in the verify stage must be E_INTERRUPTED (retryable, exit
    # 130), reported at the verify stage with the old version intact — never
    # misclassified as a non-retryable E_INTEGRITY.
    from outlook_cli import update_binary

    def _interrupt_in_verify(target, on_stage=None):
        on_stage("discover")
        on_stage("download")
        on_stage("verify_signature")
        raise KeyboardInterrupt()

    _not_on_target(monkeypatch)
    monkeypatch.setattr(update_binary, "perform_binary_update", _interrupt_in_verify)
    result = _invoke(["--manager", "manual"])
    assert result.exit_code == 130
    doc = _doc(result)
    assert doc["error"]["code"] == "E_INTERRUPTED"
    assert doc["error"]["retryable"] is True
    details = doc["error"]["details"]
    assert details["stage"] == "verify_signature"
    assert details["binary_replaced"] is False
    assert details["current_version"] == updater.__version__


def test_skill_sync_npx_missing_surfaces_partial_not_server_error(monkeypatch):
    # FileNotFoundError from `npx` must surface as partial success (ok:false,
    # binary_replaced:true, retryable), NOT a catch-all E_SERVER exit.
    _not_on_target(monkeypatch)
    with (
        mock.patch(
            "outlook_cli.update_binary.perform_binary_update",
            return_value={
                "status": "installed",
                "signature_status": "verified",
                "current_version": "2.0.0",
            },
        ),
        mock.patch.object(updater.subprocess, "run", side_effect=FileNotFoundError("npx")),
    ):
        result = _invoke(["--manager", "manual"])
    doc = _doc(result)
    assert doc["ok"] is False
    assert doc["error"]["code"] != "E_SERVER"
    details = doc["error"]["details"]
    assert details["binary_replaced"] is True
    assert details["skill_sync_status"] == "failed"
    assert details["current_version"] == "2.0.0"
    assert doc["error"]["retryable"] is True


def test_idempotent_no_op_when_already_on_target():
    # target-version equals the running version -> no-op success, no swap.
    result = _invoke(["--target-version", updater.__version__])
    assert result.exit_code == 0, result.output
    data = _doc(result)["data"]
    assert data["noop"] is True
    assert data["updated"] is False
    assert data["binary_replaced"] is False


# --- Package-manager drive tests (pip / npm) ---

def test_pip_install_drives_package_manager(monkeypatch):
    # A bare `update --manager pip` DRIVES pip install -U, then syncs the Skill.
    # signature_status stays "not_checked" (pip provenance owns integrity).
    _not_on_target(monkeypatch)
    calls = []
    ok_proc = mock.Mock(returncode=0, stdout="", stderr="")

    def _fake_pm(*a, **k):
        calls.append(a[0])
        return ok_proc

    monkeypatch.setattr(updater, "_run_package_manager_install", _fake_pm)
    # Stub skill sync too
    monkeypatch.setattr(updater.subprocess, "run", mock.Mock(return_value=ok_proc))

    result = _invoke(["--manager", "pip", "--target-version", "2.0.0"])
    assert result.exit_code == 0, result.output
    assert any("pip" in str(c) for c in calls), f"pip not in calls: {calls}"
    data = _doc(result)["data"]
    assert data["binary_replaced"] is True
    assert data["install_method"] == "pip"
    assert data["signature_status"] == "not_checked"
    assert data["skill_sync_status"] == "synced"


def test_npm_install_drives_package_manager(monkeypatch):
    # A bare `update --manager npm` DRIVES npm install -g, then syncs the Skill.
    _not_on_target(monkeypatch)
    calls = []
    ok_proc = mock.Mock(returncode=0, stdout="", stderr="")

    def _fake_pm(*a, **k):
        calls.append(a[0])
        return ok_proc

    monkeypatch.setattr(updater, "_run_package_manager_install", _fake_pm)
    monkeypatch.setattr(updater.subprocess, "run", mock.Mock(return_value=ok_proc))

    result = _invoke(["--manager", "npm", "--target-version", "2.0.0"])
    assert result.exit_code == 0, result.output
    assert any("npm" in str(c) for c in calls), f"npm not in calls: {calls}"
    data = _doc(result)["data"]
    assert data["binary_replaced"] is True
    assert data["install_method"] == "npm"
    assert data["signature_status"] == "not_checked"
    assert data["skill_sync_status"] == "synced"


def test_package_manager_dry_run_does_not_execute(monkeypatch):
    # --dry-run on a package-manager install is a read-only preview: must NOT
    # invoke the manager, must report the plan without confirm_token/expires_at.
    _not_on_target(monkeypatch)
    called = []
    monkeypatch.setattr(updater, "_run_package_manager_install", lambda *a, **k: called.append(a))
    result = _invoke(["--manager", "pip", "--target-version", "2.0.0"], obj={"dry_run": True})
    assert result.exit_code == 0, result.output
    assert not called, "dry-run must not invoke the package manager"
    data = _doc(result)["data"]
    assert "confirm_token" not in data
    assert "expires_at" not in data
    assert data["install_method"] == "github-binary"  # plan_update always shows github-binary


def test_package_manager_failure_reports_e_io(monkeypatch):
    # When pip/npm exits non-zero: E_IO, binary_replaced:false, command surfaced.
    _not_on_target(monkeypatch)
    fail_proc = mock.Mock(returncode=1, stdout="", stderr="No matching distribution found")
    monkeypatch.setattr(updater, "_run_package_manager_install", lambda *a, **k: fail_proc)

    result = _invoke(["--manager", "pip", "--target-version", "2.0.0"])
    assert result.exit_code == 1, result.output
    doc = _doc(result)
    assert doc["error"]["code"] == "E_IO"
    assert doc["error"]["details"]["binary_replaced"] is False
    assert "pip" in doc["error"]["details"].get("command", "")


def test_package_manager_skill_sync_failure_is_partial_success(monkeypatch):
    # pip installs OK but Skill sync fails: binary_replaced=true, retryable.
    _not_on_target(monkeypatch)
    ok_proc = mock.Mock(returncode=0, stdout="", stderr="")
    fail_proc = mock.Mock(returncode=1, stdout="", stderr="npx not found")
    monkeypatch.setattr(updater, "_run_package_manager_install", lambda *a, **k: ok_proc)
    monkeypatch.setattr(updater.subprocess, "run", mock.Mock(return_value=fail_proc))

    result = _invoke(["--manager", "pip", "--target-version", "2.0.0"])
    doc = _doc(result)
    assert doc["ok"] is False
    details = doc["error"]["details"]
    assert details["binary_replaced"] is True
    assert details["skill_sync_status"] == "failed"
    assert doc["error"]["retryable"] is True
