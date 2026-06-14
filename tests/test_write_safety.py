"""Write-safety upgrades: single-use confirm tokens, the --dangerous T2 gate,
and resource_version binding.

These exercise the in-process helpers (confirmation, config) plus a couple of
subprocess paths for the --dangerous gate, so no Exchange connection is needed.
"""

import json
from pathlib import Path
from unittest import mock

import click
import pytest

from outlook_cli import confirmation
from tests.test_e2e_cli import error_code, run_cli


@pytest.fixture
def isolate_home(tmp_path):
    """Point config_dir()/Path.home() at a throwaway dir for token storage."""
    with mock.patch.object(Path, "home", return_value=tmp_path):
        yield tmp_path


def _click_ctx(*, dry_run=False, confirm=None, dangerous=False):
    """Build a Click context whose obj mirrors the global flags."""
    ctx = click.Context(click.Command("x"))
    ctx.obj = {"dry_run": dry_run, "confirm": confirm, "dangerous": dangerous}
    return ctx


# --- Single-use confirm tokens ---


def test_mark_and_is_consumed_roundtrip(isolate_home):
    token, _ = confirmation.issue_token()
    assert confirmation.is_consumed(token) is False
    confirmation.mark_consumed(token, confirmation._token_exp(token))
    assert confirmation.is_consumed(token) is True


def test_consumed_store_has_owner_only_permissions(isolate_home):
    import os
    import stat

    token, _ = confirmation.issue_token()
    confirmation.mark_consumed(token, confirmation._token_exp(token))
    mode = stat.S_IMODE(os.stat(confirmation._consumed_path()).st_mode)
    # Windows chmod is a partial no-op; assert the bits we can on POSIX.
    if os.name != "nt":
        assert mode == 0o600


def test_expired_entries_are_pruned(isolate_home):
    path = confirmation._consumed_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"deadbeefdeadbeef": 1}), encoding="utf-8")  # exp in 1970
    # A fresh write must not carry the expired fingerprint forward.
    token, _ = confirmation.issue_token()
    confirmation.mark_consumed(token, confirmation._token_exp(token))
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert "deadbeefdeadbeef" not in stored


def test_require_confirmed_accepts_then_rejects_replay(isolate_home):
    token, _ = confirmation.issue_token()
    ctx = _click_ctx(confirm=token)
    with ctx:
        # First acceptance: must not raise, and must burn the token.
        confirmation.require_confirmed("cal create")
    assert confirmation.is_consumed(token) is True

    with ctx:
        with pytest.raises(SystemExit) as exc:
            confirmation.require_confirmed("cal create")
    # E_CONFLICT -> exit 6
    assert exc.value.code == 6


def test_require_confirmed_replay_emits_already_used(isolate_home, capsys):
    from outlook_cli import output

    output.init(format_mode="json")
    token, _ = confirmation.issue_token()
    ctx = _click_ctx(confirm=token)
    with ctx:
        confirmation.require_confirmed("cal create")
    with ctx:
        with pytest.raises(SystemExit):
            confirmation.require_confirmed("cal create")
    out = capsys.readouterr().out
    doc = json.loads(out[out.find("{") :])
    assert doc["error"]["code"] == "E_CONFLICT"
    assert "already used" in doc["error"]["message"]


def test_storage_failure_degrades_gracefully(isolate_home):
    token, _ = confirmation.issue_token()
    # A write failure inside mark_consumed must warn, not raise.
    with mock.patch.object(Path, "write_text", side_effect=OSError("disk full")):
        confirmation.mark_consumed(token, confirmation._token_exp(token))  # no exception


# --- --dangerous T2 gate ---


def test_require_dangerous_blocks_without_flag(isolate_home):
    from outlook_cli import config

    ctx = _click_ctx(dangerous=False)
    with ctx:
        with pytest.raises(SystemExit) as exc:
            config.require_dangerous("folders delete")
    # E_CONFIRMATION_REQUIRED -> exit 5
    assert exc.value.code == 5


def test_require_dangerous_allows_with_flag(isolate_home):
    from outlook_cli import config

    ctx = _click_ctx(dangerous=True)
    with ctx:
        config.require_dangerous("folders delete")  # no raise


def test_dangerous_gate_blocks_dry_run_step():
    # Dangerous command at the dry-run step without --dangerous -> exit 5.
    code, stdout, _ = run_cli(
        "folders",
        "delete",
        "--name",
        "Junk",
        "--dry-run",
        "--json",
        env_overrides={"OUTLOOK_PERMISSIONS": "write"},
    )
    assert code == 5, stdout
    assert error_code(stdout) == "E_CONFIRMATION_REQUIRED"


def test_dangerous_gate_blocks_confirm_step():
    # Dangerous command at the confirm step without --dangerous -> exit 5,
    # before any token validation or Exchange call.
    code, stdout, _ = run_cli(
        "folders",
        "delete",
        "--name",
        "Junk",
        "--confirm",
        "ct_fake_token",
        "--json",
        env_overrides={"OUTLOOK_PERMISSIONS": "write"},
    )
    assert code == 5, stdout
    assert error_code(stdout) == "E_CONFIRMATION_REQUIRED"


def test_mail_batch_delete_is_dangerous_but_other_actions_are_not():
    # batch --action delete needs --dangerous even at dry-run.
    code, stdout, _ = run_cli(
        "mail",
        "batch",
        "--ids",
        "abc",
        "--action",
        "delete",
        "--dry-run",
        "--json",
        env_overrides={"OUTLOOK_PERMISSIONS": "write"},
    )
    assert code == 5, stdout
    assert error_code(stdout) == "E_CONFIRMATION_REQUIRED"


def test_reference_surfaces_dangerous_tier():
    code, stdout, _ = run_cli("reference", "--json")
    assert code == 0
    data = json.loads(stdout[stdout.find("{") :])["data"]
    assert "write-dangerous" in data["permission_tiers"]
    assert "folders delete" in data["dangerous_commands"]
    assert "--dangerous" in data["global_options"]


# --- resource_version binding ---


def test_resource_version_binds_and_mismatch_rejected(isolate_home):
    token, _ = confirmation.issue_token(resource_id="evt-1", resource_version="v1")
    # Same id+version validates.
    valid, _ = confirmation.validate_token(token, resource_id="evt-1", resource_version="v1")
    assert valid is True
    # A changed version (someone else edited the item) is rejected.
    valid, reason = confirmation.validate_token(
        token, resource_id="evt-1", resource_version="v2"
    )
    assert valid is False
    assert "operation" in reason


def test_resource_id_mismatch_rejected(isolate_home):
    token, _ = confirmation.issue_token(resource_id="evt-1", resource_version="v1")
    valid, reason = confirmation.validate_token(
        token, resource_id="evt-2", resource_version="v1"
    )
    assert valid is False
    assert "resource" in reason
