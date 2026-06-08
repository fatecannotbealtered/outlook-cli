"""Tests for audit module."""

import json
import os
from datetime import datetime
from unittest import mock

import pytest

from outlook_cli import audit


@pytest.fixture(autouse=True)
def isolate_audit(tmp_path):
    """Isolate audit to a temp directory."""
    audit._test_dir = str(tmp_path / "audit")
    yield tmp_path / "audit"
    audit._test_dir = ""


def test_audit_dir(isolate_audit):
    d = audit.audit_dir()
    assert str(d) == str(isolate_audit)


def test_log_creates_file(isolate_audit):
    audit.log("mail send", ["--to", "a@b.com", "--dry-run"], 0, 1500)
    files = audit.files()
    assert len(files) == 1
    assert files[0].endswith(".jsonl")


def test_log_entry_format(isolate_audit):
    audit.log("mail list", ["--limit", "10"], 0, 500, account="a@example.com")
    files = audit.files()
    with open(files[0], "r", encoding="utf-8") as f:
        entry = json.loads(f.readline())
    assert "ts" in entry
    assert entry["ts"].endswith("Z")
    assert entry["cmd"] == "mail list"
    assert entry["args"] == ["--limit", "10"]
    assert entry["account"] == "a@example.com"
    assert entry["exit"] == 0
    assert entry["ms"] == 500


def test_log_strips_password(isolate_audit):
    audit.log("setup login", ["--email", "a@b.com", "--password", "secret123"], 0, 200)
    files = audit.files()
    with open(files[0], "r", encoding="utf-8") as f:
        entry = json.loads(f.readline())
    args = entry["args"]
    assert "secret123" not in args
    assert "--email" in args
    assert "a@b.com" in args
    # Flag is kept, value is stripped (two-arg form)
    assert "--password" in args


def test_log_strips_password_equals(isolate_audit):
    """--password=value form is sanitized."""
    audit.log("setup login", ["--email", "a@b.com", "--password=mysecret"], 0, 200)
    files = audit.files()
    with open(files[0], "r", encoding="utf-8") as f:
        entry = json.loads(f.readline())
    args = entry["args"]
    assert "mysecret" not in str(args)
    assert "--password=***" in args


def test_log_strips_token(isolate_audit):
    audit.log("cmd", ["--token", "abc123", "--other", "val"], 0, 100)
    files = audit.files()
    with open(files[0], "r", encoding="utf-8") as f:
        entry = json.loads(f.readline())
    assert "abc123" not in entry["args"]
    assert "--token" in entry["args"]  # flag kept, value stripped
    assert "--other" in entry["args"]
    assert "val" in entry["args"]


def test_log_strips_confirm_token(isolate_audit):
    audit.log("mail send", ["--confirm", "ct_secret", "--subject", "hi"], 0, 100)
    files = audit.files()
    with open(files[0], "r", encoding="utf-8") as f:
        entry = json.loads(f.readline())
    assert "ct_secret" not in entry["args"]
    assert "--confirm" in entry["args"]


def test_no_audit_env(tmp_path):
    """OUTLOOK_NO_AUDIT=1 disables auditing."""
    audit._test_dir = str(tmp_path / "audit")
    with mock.patch.dict(os.environ, {"OUTLOOK_NO_AUDIT": "1"}):
        audit.log("mail list", [], 0, 100)
    assert audit.files() == []


def test_multiple_entries(isolate_audit):
    audit.log("mail list", [], 0, 100)
    audit.log("mail read", ["--id", "123"], 0, 200)
    audit.log("mail delete", ["--id", "456"], 0, 300)
    files = audit.files()
    assert len(files) == 1  # same month
    with open(files[0], "r", encoding="utf-8") as f:
        lines = f.readlines()
    assert len(lines) == 3


def test_sanitize_args_empty():
    assert audit._sanitize_args([]) == []


def test_sanitize_args_normal():
    args = ["--limit", "10", "--folder", "inbox"]
    assert audit._sanitize_args(args) == args


def test_cleanup_removes_old_files(isolate_audit):
    """_cleanup removes files older than retention period."""
    d = isolate_audit
    d.mkdir(parents=True, exist_ok=True)

    # Create a fake old file
    old_file = d / "audit-2020-01.jsonl"
    old_file.write_text('{"ts":"2020-01-01"}\n', encoding="utf-8")

    # Create a current file
    current_month = datetime.now().strftime("%Y-%m")
    current_file = d / f"audit-{current_month}.jsonl"
    current_file.write_text('{"ts":"now"}\n', encoding="utf-8")

    with mock.patch.dict(os.environ, {"OUTLOOK_AUDIT_RETENTION_MONTHS": "3"}):
        audit._cleanup(d)

    assert not old_file.exists()
    assert current_file.exists()


def test_retention_months_default():
    with mock.patch.dict(os.environ, {}, clear=True):
        # Remove OUTLOOK_AUDIT_RETENTION_MONTHS if present
        os.environ.pop("OUTLOOK_AUDIT_RETENTION_MONTHS", None)
        assert audit._retention_months() == 3


def test_retention_months_custom():
    with mock.patch.dict(os.environ, {"OUTLOOK_AUDIT_RETENTION_MONTHS": "12"}):
        assert audit._retention_months() == 12


def test_retention_months_zero():
    """0 means keep forever."""
    with mock.patch.dict(os.environ, {"OUTLOOK_AUDIT_RETENTION_MONTHS": "0"}):
        assert audit._retention_months() == 0


def test_retention_months_invalid():
    with mock.patch.dict(os.environ, {"OUTLOOK_AUDIT_RETENTION_MONTHS": "abc"}):
        assert audit._retention_months() == 3


def test_files_empty_dir(isolate_audit):
    assert audit.files() == []
