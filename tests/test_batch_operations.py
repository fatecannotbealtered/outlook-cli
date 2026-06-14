"""Batch-operations contract tests (CLI-SPEC §15) for mail + calendar.

Covers the new batch capabilities added this round:
  * mail batch categorize/flag/unflag/complete/restore
  * mail draft-send batch (account.bulk_send)
  * cal batch create/update/delete (native exchangelib bulk_*)

The aggregation contract is what matters here: plural inputs, dry-run summary,
single confirm token (single-use replay -> E_CONFLICT), the --dangerous gate on
bulk delete, per-item items[]/summary with no whole-batch rollback, and
--continue-on-error. These drive the command callbacks in-process with fakes so
no Exchange connection is needed; a few subprocess paths exercise the global
flag plumbing (validation, dangerous gate).
"""

import json
import types
from pathlib import Path
from unittest import mock

import pytest
from click.testing import CliRunner

from outlook_cli import confirmation, output
from outlook_cli.commands import cal, mail
from tests.test_e2e_cli import error_code, run_cli


@pytest.fixture
def isolate_home(tmp_path):
    """Point Path.home() at a throwaway dir so confirm-token storage is isolated."""
    with mock.patch.object(Path, "home", return_value=tmp_path):
        yield tmp_path


def _json_data(result):
    out = result.output
    return json.loads(out[out.find("{") :])["data"]


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeItem:
    """A mail/calendar item that records the mutations applied to it."""

    def __init__(self, item_id, *, raise_on_save=None):
        self.id = item_id
        self.subject = f"Subj {item_id}"
        self.categories = []
        self.flag = None
        self.is_read = False
        self.required_attendees = None
        self.optional_attendees = None
        self._raise_on_save = raise_on_save
        self.moved_to = None
        self.trashed = False

    def save(self, update_fields=None):
        if self._raise_on_save:
            raise self._raise_on_save

    def move(self, target):
        self.moved_to = target

    def move_to_trash(self):
        self.trashed = True


class FakeAccount:
    def __init__(self):
        self.inbox = "INBOX"
        self.calendar = "CALENDAR"
        self.bulk_send_calls = []
        self.bulk_create_calls = []
        self.bulk_update_calls = []
        self.bulk_delete_calls = []
        self._send_results = None
        self._create_results = None
        self._update_results = None
        self._delete_results = None

    def bulk_send(self, items):
        self.bulk_send_calls.append(list(items))
        # Default: every send succeeds.
        if self._send_results is None:
            return [True] * len(items)
        # Pop the next slice matching this call size.
        n = len(items)
        head, self._send_results = self._send_results[:n], self._send_results[n:]
        return head

    def bulk_create(self, folder=None, items=None, send_meeting_invitations=None):
        self.bulk_create_calls.append(
            {"items": list(items), "send_meeting_invitations": send_meeting_invitations}
        )
        return self._create_results

    def bulk_update(self, items=None, send_meeting_invitations_or_cancellations=None):
        self.bulk_update_calls.append(
            {"items": list(items), "send": send_meeting_invitations_or_cancellations}
        )
        return self._update_results

    def bulk_delete(self, ids=None, delete_type=None, send_meeting_cancellations=None):
        self.bulk_delete_calls.append(
            {
                "ids": list(ids),
                "delete_type": delete_type,
                "send_meeting_cancellations": send_meeting_cancellations,
            }
        )
        return self._delete_results


def _invoke(cmd, args, *, obj, monkeypatch_setup=None):
    output.init(format_mode="json")
    runner = CliRunner()
    return runner.invoke(cmd, args, obj=obj, catch_exceptions=False)


# ===========================================================================
# mail batch
# ===========================================================================


def _patch_mail(monkeypatch, account, items_by_id):
    monkeypatch.setattr("outlook_cli.config.check_permission", lambda *_a, **_k: None)
    monkeypatch.setattr(mail, "get_account", lambda *a, **k: account)
    monkeypatch.setattr(mail, "find_mail_by_id", lambda acc, mid: items_by_id.get(mid))
    monkeypatch.setattr("outlook_cli.confirmation.require_confirmed", lambda *a, **k: None)


def test_mail_batch_categorize_success_aggregates(monkeypatch):
    account = FakeAccount()
    items = {"1": FakeItem("1"), "2": FakeItem("2")}
    _patch_mail(monkeypatch, account, items)

    result = _invoke(
        mail.mail_batch,
        ["--ids", "1,2", "--action", "categorize", "--categories", "Red,Urgent"],
        obj={"dry_run": False, "confirm": "ct_x"},
    )
    assert result.exit_code == 0, result.output
    data = _json_data(result)
    assert data["summary"] == {"total": 2, "succeeded": 2, "failed": 0}
    assert [i["target"] for i in data["items"]] == ["1", "2"]
    assert all(i["ok"] is True for i in data["items"])
    # Categories were added (add-only, like a label).
    assert items["1"].categories == ["Red", "Urgent"]


def test_mail_batch_flag_unflag_complete(monkeypatch):
    account = FakeAccount()
    items = {"1": FakeItem("1")}
    _patch_mail(monkeypatch, account, items)
    for action, expected in [("flag", 2), ("complete", 1), ("unflag", None)]:
        result = _invoke(
            mail.mail_batch,
            ["--ids", "1", "--action", action],
            obj={"dry_run": False, "confirm": "ct_x"},
        )
        assert result.exit_code == 0, result.output
        assert items["1"].flag == expected


def test_mail_batch_partial_failure_does_not_block_others(monkeypatch):
    account = FakeAccount()
    # id "2" is missing -> E_NOT_FOUND; "3" raises on save -> mapped error.
    items = {
        "1": FakeItem("1"),
        "3": FakeItem("3", raise_on_save=RuntimeError("boom")),
    }
    _patch_mail(monkeypatch, account, items)

    result = _invoke(
        mail.mail_batch,
        ["--ids", "1,2,3", "--action", "mark-read"],
        obj={"dry_run": False, "confirm": "ct_x"},
    )
    assert result.exit_code == 0, result.output
    data = _json_data(result)
    by_target = {i["target"]: i for i in data["items"]}
    assert by_target["1"]["ok"] is True
    assert by_target["2"]["error"]["code"] == "E_NOT_FOUND"
    assert by_target["3"]["ok"] is False
    assert data["summary"] == {"total": 3, "succeeded": 1, "failed": 2}


def test_mail_batch_no_continue_on_error_skips_remainder(monkeypatch):
    account = FakeAccount()
    items = {"1": FakeItem("1")}  # "2" missing -> stops the run
    _patch_mail(monkeypatch, account, items)

    result = _invoke(
        mail.mail_batch,
        ["--ids", "2,1", "--action", "mark-read", "--no-continue-on-error"],
        obj={"dry_run": False, "confirm": "ct_x"},
    )
    assert result.exit_code == 0, result.output
    data = _json_data(result)
    by_target = {i["target"]: i for i in data["items"]}
    assert by_target["2"]["error"]["code"] == "E_NOT_FOUND"
    # "1" is reported but skipped (ok is null), not applied.
    assert by_target["1"]["ok"] is None
    assert data["summary"]["skipped"] == 1


def test_mail_batch_dedupes_and_preserves_order(monkeypatch):
    account = FakeAccount()
    items = {"1": FakeItem("1"), "2": FakeItem("2")}
    _patch_mail(monkeypatch, account, items)
    result = _invoke(
        mail.mail_batch,
        ["--ids", "2", "--ids", "1,2", "--action", "mark-read"],
        obj={"dry_run": False, "confirm": "ct_x"},
    )
    data = _json_data(result)
    assert [i["target"] for i in data["items"]] == ["2", "1"]


def test_mail_batch_categorize_requires_categories():
    code, stdout, _ = run_cli(
        "mail",
        "batch",
        "--ids",
        "1",
        "--action",
        "categorize",
        "--dry-run",
        "--json",
        env_overrides={"OUTLOOK_PERMISSIONS": "write"},
    )
    assert code == 2, stdout
    assert error_code(stdout) == "E_VALIDATION"


def test_mail_batch_empty_ids_is_validation_error():
    code, stdout, _ = run_cli(
        "mail",
        "batch",
        "--ids",
        ",",
        "--action",
        "mark-read",
        "--dry-run",
        "--json",
        env_overrides={"OUTLOOK_PERMISSIONS": "write"},
    )
    assert code == 2, stdout
    assert error_code(stdout) == "E_VALIDATION"


def test_mail_batch_delete_requires_dangerous():
    code, stdout, _ = run_cli(
        "mail",
        "batch",
        "--ids",
        "1,2",
        "--action",
        "delete",
        "--dry-run",
        "--json",
        env_overrides={"OUTLOOK_PERMISSIONS": "write"},
    )
    assert code == 5, stdout
    assert error_code(stdout) == "E_CONFIRMATION_REQUIRED"


# ===========================================================================
# mail draft-send (batch via account.bulk_send)
# ===========================================================================


def test_mail_draft_send_batch_success(monkeypatch):
    account = FakeAccount()
    items = {"d1": FakeItem("d1"), "d2": FakeItem("d2")}
    _patch_mail(monkeypatch, account, items)

    result = _invoke(
        mail.mail_draft_send,
        ["--ids", "d1,d2"],
        obj={"dry_run": False, "confirm": "ct_x"},
    )
    assert result.exit_code == 0, result.output
    data = _json_data(result)
    assert data["summary"] == {"total": 2, "succeeded": 2, "failed": 0}
    # A single native bulk_send carried both drafts.
    assert len(account.bulk_send_calls) == 1
    assert len(account.bulk_send_calls[0]) == 2


def test_mail_draft_send_single_id_is_batch_of_one(monkeypatch):
    account = FakeAccount()
    items = {"d1": FakeItem("d1")}
    _patch_mail(monkeypatch, account, items)
    result = _invoke(
        mail.mail_draft_send,
        ["--id", "d1"],
        obj={"dry_run": False, "confirm": "ct_x"},
    )
    assert result.exit_code == 0, result.output
    data = _json_data(result)
    assert data["summary"] == {"total": 1, "succeeded": 1, "failed": 0}


def test_mail_draft_send_partial_failure(monkeypatch):
    account = FakeAccount()
    account._send_results = [True, RuntimeError("smtp down")]
    items = {"d1": FakeItem("d1"), "d2": FakeItem("d2")}
    _patch_mail(monkeypatch, account, items)

    result = _invoke(
        mail.mail_draft_send,
        ["--ids", "d1,d2"],
        obj={"dry_run": False, "confirm": "ct_x"},
    )
    assert result.exit_code == 0, result.output
    data = _json_data(result)
    by_target = {i["target"]: i for i in data["items"]}
    assert by_target["d1"]["ok"] is True
    assert by_target["d2"]["ok"] is False
    assert data["summary"] == {"total": 2, "succeeded": 1, "failed": 1}


def test_mail_draft_send_missing_draft_reported(monkeypatch):
    account = FakeAccount()
    items = {"d1": FakeItem("d1")}  # d2 missing
    _patch_mail(monkeypatch, account, items)
    result = _invoke(
        mail.mail_draft_send,
        ["--ids", "d1,d2"],
        obj={"dry_run": False, "confirm": "ct_x"},
    )
    data = _json_data(result)
    by_target = {i["target"]: i for i in data["items"]}
    assert by_target["d2"]["error"]["code"] == "E_NOT_FOUND"


# ===========================================================================
# cal batch
# ===========================================================================


def _patch_cal(monkeypatch, account, events_by_id=None):
    monkeypatch.setattr("outlook_cli.config.check_permission", lambda *_a, **_k: None)
    monkeypatch.setattr(cal, "get_account", lambda *a, **k: account)
    from datetime import timezone

    monkeypatch.setattr(cal, "get_tz", lambda: timezone.utc)
    monkeypatch.setattr("outlook_cli.confirmation.require_confirmed", lambda *a, **k: None)
    if events_by_id is not None:
        monkeypatch.setattr(cal, "_get_event", lambda acc, eid, ck="": events_by_id.get(eid))


def _bulk_create_result(new_id):
    return types.SimpleNamespace(id=types.SimpleNamespace(id=new_id))


def test_cal_batch_create_success(monkeypatch, tmp_path):
    account = FakeAccount()
    account._create_results = [_bulk_create_result("evt-A"), _bulk_create_result("evt-B")]
    _patch_cal(monkeypatch, account)
    # Skip real CalendarItem construction (needs a live Account type).
    monkeypatch.setattr(cal, "_build_event", lambda acc, tz, spec: object())

    f = tmp_path / "events.json"
    f.write_text(
        json.dumps(
            [
                {"subject": "Sync", "start": "2026-07-01 10:00", "end": "2026-07-01 11:00"},
                {"subject": "Review", "start": "2026-07-02 14:00", "end": "2026-07-02 15:00"},
            ]
        ),
        encoding="utf-8",
    )
    result = _invoke(
        cal.cal_batch,
        ["--action", "create", "--file", str(f)],
        obj={"dry_run": False, "confirm": "ct_x"},
    )
    assert result.exit_code == 0, result.output
    data = _json_data(result)
    assert data["summary"] == {"total": 2, "succeeded": 2, "failed": 0}
    assert [i["target"] for i in data["items"]] == ["Sync", "Review"]
    assert data["items"][0]["id"] == "evt-A"
    # Default --send-notifications true -> invitations are sent.
    assert account.bulk_create_calls[0]["send_meeting_invitations"] == "SendToAllAndSaveCopy"


def test_cal_batch_create_no_notifications(monkeypatch, tmp_path):
    account = FakeAccount()
    account._create_results = [_bulk_create_result("evt-A")]
    _patch_cal(monkeypatch, account)
    monkeypatch.setattr(cal, "_build_event", lambda acc, tz, spec: object())

    f = tmp_path / "events.json"
    f.write_text(
        json.dumps([{"subject": "Solo", "start": "2026-07-01 10:00", "end": "2026-07-01 11:00"}]),
        encoding="utf-8",
    )
    result = _invoke(
        cal.cal_batch,
        ["--action", "create", "--file", str(f), "--no-send-notifications"],
        obj={"dry_run": False, "confirm": "ct_x"},
    )
    assert result.exit_code == 0, result.output
    assert account.bulk_create_calls[0]["send_meeting_invitations"] == "SendToNone"


def test_cal_batch_create_with_attendees_sends_invitations(monkeypatch, tmp_path):
    account = FakeAccount()
    account._create_results = [_bulk_create_result("evt-A")]
    _patch_cal(monkeypatch, account)
    monkeypatch.setattr(cal, "_build_event", lambda acc, tz, spec: object())

    f = tmp_path / "events.json"
    f.write_text(
        json.dumps(
            [
                {
                    "subject": "Sync",
                    "start": "2026-07-01 10:00",
                    "end": "2026-07-01 11:00",
                    "attendees": "a@co.com",
                }
            ]
        ),
        encoding="utf-8",
    )
    result = _invoke(
        cal.cal_batch,
        ["--action", "create", "--file", str(f)],
        obj={"dry_run": False, "confirm": "ct_x"},
    )
    assert result.exit_code == 0, result.output
    assert account.bulk_create_calls[0]["send_meeting_invitations"] == "SendToAllAndSaveCopy"


def test_cal_batch_create_build_error_is_per_item(monkeypatch, tmp_path):
    account = FakeAccount()
    account._create_results = [_bulk_create_result("evt-A")]
    _patch_cal(monkeypatch, account)

    def fake_build(acc, tz, spec):
        if spec["subject"] == "Bad":
            raise ValueError("end before start")
        return object()

    monkeypatch.setattr(cal, "_build_event", fake_build)

    f = tmp_path / "events.json"
    f.write_text(
        json.dumps(
            [
                {"subject": "Good", "start": "2026-07-01 10:00", "end": "2026-07-01 11:00"},
                {"subject": "Bad", "start": "2026-07-02 15:00", "end": "2026-07-02 14:00"},
            ]
        ),
        encoding="utf-8",
    )
    result = _invoke(
        cal.cal_batch,
        ["--action", "create", "--file", str(f)],
        obj={"dry_run": False, "confirm": "ct_x"},
    )
    data = _json_data(result)
    by_target = {i["target"]: i for i in data["items"]}
    assert by_target["Good"]["ok"] is True
    assert by_target["Bad"]["ok"] is False
    # The bad spec never reached bulk_create.
    assert len(account.bulk_create_calls[0]["items"]) == 1


def test_cal_batch_update_success_and_not_found(monkeypatch, tmp_path):
    account = FakeAccount()
    account._update_results = [("evt-1", "ck-1")]  # one prepared item
    events = {"evt-1": FakeItem("evt-1")}
    _patch_cal(monkeypatch, account, events_by_id=events)

    f = tmp_path / "updates.json"
    f.write_text(
        json.dumps(
            [
                {"id": "evt-1", "location": "Room 1"},
                {"id": "evt-404", "location": "Nowhere"},
            ]
        ),
        encoding="utf-8",
    )
    result = _invoke(
        cal.cal_batch,
        ["--action", "update", "--file", str(f)],
        obj={"dry_run": False, "confirm": "ct_x"},
    )
    assert result.exit_code == 0, result.output
    data = _json_data(result)
    by_target = {i["target"]: i for i in data["items"]}
    assert by_target["evt-1"]["ok"] is True
    assert by_target["evt-404"]["error"]["code"] == "E_NOT_FOUND"
    assert data["summary"] == {"total": 2, "succeeded": 1, "failed": 1}


def test_cal_batch_delete_soft_deletes_and_sends_cancellations(monkeypatch):
    account = FakeAccount()
    account._delete_results = [True, True]
    e1 = FakeItem("evt-1")
    e1.required_attendees = ["a@co.com"]  # triggers cancellations
    events = {"evt-1": e1, "evt-2": FakeItem("evt-2")}
    _patch_cal(monkeypatch, account, events_by_id=events)

    result = _invoke(
        cal.cal_batch,
        ["--action", "delete", "--ids", "evt-1,evt-2", "--force"],
        obj={"dry_run": False, "confirm": "ct_x", "dangerous": True},
    )
    assert result.exit_code == 0, result.output
    data = _json_data(result)
    assert data["summary"] == {"total": 2, "succeeded": 2, "failed": 0}
    call = account.bulk_delete_calls[0]
    # Soft delete (recoverable) honors the soft-delete-only policy.
    from exchangelib.items import MOVE_TO_DELETED_ITEMS

    assert call["delete_type"] == MOVE_TO_DELETED_ITEMS
    assert call["send_meeting_cancellations"] == "SendToAllAndSaveCopy"


def test_cal_batch_delete_requires_dangerous():
    code, stdout, _ = run_cli(
        "cal",
        "batch",
        "--action",
        "delete",
        "--ids",
        "evt-1",
        "--dry-run",
        "--json",
        env_overrides={"OUTLOOK_PERMISSIONS": "write"},
    )
    assert code == 5, stdout
    assert error_code(stdout) == "E_CONFIRMATION_REQUIRED"


def test_cal_batch_create_requires_file():
    code, stdout, _ = run_cli(
        "cal",
        "batch",
        "--action",
        "create",
        "--dry-run",
        "--json",
        env_overrides={"OUTLOOK_PERMISSIONS": "write"},
    )
    assert code == 2, stdout
    assert error_code(stdout) == "E_VALIDATION"


def test_cal_batch_dry_run_summarizes_targets_with_token():
    code, stdout, _ = run_cli(
        "cal",
        "batch",
        "--action",
        "delete",
        "--ids",
        "evt-1,evt-2",
        "--dangerous",
        "--dry-run",
        "--json",
        env_overrides={"OUTLOOK_PERMISSIONS": "write"},
    )
    assert code == 0, stdout
    data = json.loads(stdout[stdout.find("{") :])["data"]
    assert data["confirm_token"]
    detail = data["preview"]["changes"][0]["detail"]
    assert detail["total"] == 2
    assert detail["targets"] == ["evt-1", "evt-2"]


# ===========================================================================
# Single-use confirm token (replay -> E_CONFLICT) for batch commands
# ===========================================================================


def test_batch_confirm_token_single_use_then_conflict(isolate_home):
    """A batch confirm token is consumed once; replay -> E_CONFLICT (exit 6)."""
    import click

    token, _ = confirmation.issue_token(resource_id="evt-1,evt-2")
    ctx = click.Context(click.Command("x"))
    ctx.obj = {"dry_run": False, "confirm": token}
    with ctx:
        confirmation.require_confirmed("cal batch", resource_id="evt-1,evt-2")
    assert confirmation.is_consumed(token) is True
    with ctx:
        with pytest.raises(SystemExit) as exc:
            confirmation.require_confirmed("cal batch", resource_id="evt-1,evt-2")
    assert exc.value.code == 6


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
