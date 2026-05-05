"""Tests for the permission system."""

import os
from unittest import mock

import pytest

from outlook_cli import config


@pytest.fixture(autouse=True)
def clean_env():
    """Remove permission env var during tests."""
    with mock.patch.dict(os.environ, {}, clear=False):
        os.environ.pop("OUTLOOK_PERMISSIONS", None)
        yield


# --- check_permission tests ---


def test_read_only_allows_read_commands():
    """read-only mode allows read commands."""
    with mock.patch.object(config, "get_permission_mode", return_value="read-only"):
        # Should not raise
        config.check_permission("mail list")
        config.check_permission("mail search")
        config.check_permission("mail read")
        config.check_permission("cal list")
        config.check_permission("folders list")
        config.check_permission("rules list")
        config.check_permission("tools contacts")


def test_read_only_blocks_write_commands():
    """read-only mode blocks write commands."""
    with mock.patch.object(config, "get_permission_mode", return_value="read-only"):
        with pytest.raises(SystemExit) as exc_info:
            config.check_permission("mail move")
        assert exc_info.value.code == 5


def test_read_only_blocks_full_commands():
    """read-only mode blocks full commands."""
    with mock.patch.object(config, "get_permission_mode", return_value="read-only"):
        with pytest.raises(SystemExit) as exc_info:
            config.check_permission("mail send")
        assert exc_info.value.code == 5


def test_write_allows_read_and_write():
    """write mode allows read and write commands."""
    with mock.patch.object(config, "get_permission_mode", return_value="write"):
        config.check_permission("mail list")  # read
        config.check_permission("mail move")  # write
        config.check_permission("mail delete")  # write
        config.check_permission("cal create")  # write
        config.check_permission("rules create")  # write


def test_write_blocks_full_commands():
    """write mode blocks full commands (send/reply/forward)."""
    with mock.patch.object(config, "get_permission_mode", return_value="write"):
        for cmd in [
            "mail send",
            "mail reply",
            "mail reply-all",
            "mail forward",
            "mail draft-send",
        ]:
            with pytest.raises(SystemExit) as exc_info:
                config.check_permission(cmd)
            assert exc_info.value.code == 5


def test_full_allows_all():
    """full mode allows everything."""
    with mock.patch.object(config, "get_permission_mode", return_value="full"):
        config.check_permission("mail list")
        config.check_permission("mail move")
        config.check_permission("mail send")
        config.check_permission("mail reply")
        config.check_permission("mail forward")
        config.check_permission("cal create")
        config.check_permission("rules delete")
        config.check_permission("tools oof set")


def test_unknown_command_read_only():
    """Unknown commands are treated as read-only (always allowed)."""
    with mock.patch.object(config, "get_permission_mode", return_value="read-only"):
        config.check_permission("unknown command")


# --- Permission level constants ---


def test_permission_levels_ascending():
    assert config.PERMISSION_LEVELS["read-only"] < config.PERMISSION_LEVELS["write"]
    assert config.PERMISSION_LEVELS["write"] < config.PERMISSION_LEVELS["full"]


# --- Command classification ---


def test_send_commands_require_full():
    send_cmds = [
        "mail send",
        "mail reply",
        "mail reply-all",
        "mail forward",
        "mail draft-send",
    ]
    for cmd in send_cmds:
        assert cmd in config.FULL_COMMANDS, f"{cmd} should be in FULL_COMMANDS"


def test_write_commands_completeness():
    expected = {
        "mail move",
        "mail mark",
        "mail flag",
        "mail categorize",
        "mail restore",
        "mail batch",
        "mail delete",
        "mail draft-edit",
        "mail draft-delete",
        "cal create",
        "cal update",
        "cal delete",
        "folders create",
        "folders rename",
        "folders move",
        "folders empty",
        "folders delete",
        "rules create",
        "rules update",
        "rules delete",
        "rules toggle",
        "tools oof set",
        "tools oof disable",
        "tools respond",
    }
    assert expected == config.WRITE_COMMANDS


def test_full_and_write_no_overlap():
    overlap = config.FULL_COMMANDS & config.WRITE_COMMANDS
    assert overlap == set(), f"Overlap: {overlap}"


# --- Deny output ---


def test_deny_exits_5(capsys):
    with pytest.raises(SystemExit) as exc_info:
        config._deny("mail send", "read-only", "full")
    assert exc_info.value.code == 5


def test_deny_includes_hint(capsys):
    with pytest.raises(SystemExit):
        config._deny("mail send", "read-only", "full")
    captured = capsys.readouterr()
    assert "read-only" in captured.err
    assert "full" in captured.err
