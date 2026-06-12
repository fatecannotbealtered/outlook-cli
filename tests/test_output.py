"""Tests for output module."""

import json

import pytest

from outlook_cli import output


@pytest.fixture(autouse=True)
def reset_output():
    """Reset output state before each test."""
    output.init(json_mode=False, quiet=False)
    yield
    output.init(json_mode=False, quiet=False)


def test_init_sets_mode():
    output.init(json_mode=True, quiet=True)
    assert output.is_json() is True
    assert output.is_quiet() is True

    output.init(json_mode=False, quiet=False)
    assert output.is_json() is False
    assert output.is_quiet() is False


def test_print_json(capsys):
    output.init(json_mode=True, quiet=False)
    output.print_json({"key": "value"})
    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert parsed["ok"] is True
    assert parsed["schema_version"] == "1.0"
    assert parsed["data"]["key"] == "value"
    assert "duration_ms" in parsed["meta"]


def test_print_json_unicode(capsys):
    output.init(json_mode=True, quiet=False)
    output.print_json({"msg": "你好"})
    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert parsed["data"]["msg"] == "你好"


def test_print_flat_json(capsys):
    output.init(json_mode=True, quiet=False)
    output.print_flat_json({"count": 5})
    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert parsed["data"]["count"] == 5


def test_error_json(capsys):
    output.init(json_mode=True, quiet=False)
    output.error_json("not found", code="NOT_FOUND", hint="check ID")
    captured = capsys.readouterr()
    # The failure envelope is the single JSON document on stdout
    parsed = json.loads(captured.out)
    assert parsed["ok"] is False
    assert parsed["error"]["message"] == "not found"
    assert parsed["error"]["code"] == "E_NOT_FOUND"
    assert parsed["error"]["details"]["hint"] == "check ID"
    # stderr only carries the human-readable side-channel line
    assert "E_NOT_FOUND" in captured.err


def test_error_json_default_hint(capsys):
    """error_json fills in default hint from ERROR_CODES."""
    output.error_json("forbidden", code="FORBIDDEN")
    parsed = json.loads(capsys.readouterr().out)
    hint = parsed["error"]["details"]["hint"]
    assert "permissions" in hint.lower() or "config" in hint.lower()


def test_success_suppressed_in_quiet(capsys):
    output.init(json_mode=False, quiet=True)
    output.success("should not appear")
    captured = capsys.readouterr()
    assert "should not appear" not in captured.out


def test_success_suppressed_in_json(capsys):
    output.init(json_mode=True, quiet=False)
    output.success("should not appear")
    captured = capsys.readouterr()
    assert "should not appear" not in captured.out


def test_info_suppressed_in_quiet(capsys):
    output.init(json_mode=False, quiet=True)
    output.info("should not appear")
    captured = capsys.readouterr()
    assert "should not appear" not in captured.out


def test_warn_always_shown(capsys):
    output.init(json_mode=False, quiet=True)
    output.warn("warning text")
    captured = capsys.readouterr()
    assert "warning text" in captured.err


def test_error_always_shown(capsys):
    output.init(json_mode=False, quiet=True)
    output.error("error text")
    captured = capsys.readouterr()
    assert "error text" in captured.err


def test_handle_error_exits():
    with pytest.raises(SystemExit) as exc_info:
        output.handle_error("fatal", "CONFIG_ERROR", exit_code=3)
    assert exc_info.value.code == 4


def test_handle_error_json_mode(capsys):
    output.init(json_mode=True, quiet=False)
    with pytest.raises(SystemExit):
        output.handle_error("fatal", "CONFIG_ERROR", exit_code=3)
    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert parsed["error"]["code"] == "E_CONFIG"


def test_handle_api_error_auth(capsys):
    output.init(json_mode=True, quiet=False)
    with pytest.raises(SystemExit) as exc_info:
        output.handle_api_error(Exception("401 Unauthorized"))
    assert exc_info.value.code == 4


def test_handle_api_error_not_found(capsys):
    output.init(json_mode=True, quiet=False)
    with pytest.raises(SystemExit) as exc_info:
        output.handle_api_error(Exception("Item not found"))
    assert exc_info.value.code == 3


def test_handle_api_error_timeout(capsys):
    output.init(json_mode=True, quiet=False)
    with pytest.raises(SystemExit) as exc_info:
        output.handle_api_error(Exception("Connection timeout"))
    assert exc_info.value.code == 8


def test_dry_run_output(capsys):
    output.init(json_mode=False, quiet=False)
    output.dry_run_output("send email", {"to": "a@b.com"})
    captured = capsys.readouterr()
    assert "DRY RUN" in captured.out


def test_dry_run_suppressed_quiet(capsys):
    output.init(json_mode=False, quiet=True)
    output.dry_run_output("send email", {"to": "a@b.com"})
    captured = capsys.readouterr()
    assert "DRY RUN" not in captured.out


def test_error_codes_complete():
    """Ensure all expected error codes have hints."""
    expected_codes = [
        "CONFIG_ERROR",
        "AUTH_REQUIRED",
        "FORBIDDEN",
        "NOT_FOUND",
        "VALIDATION_ERROR",
        "SERVER_ERROR",
        "NETWORK_ERROR",
        "E_CONFIG",
        "E_AUTH",
        "E_FORBIDDEN",
        "E_NOT_FOUND",
        "E_VALIDATION",
        "E_CONFIRMATION_REQUIRED",
        "E_CONFLICT",
    ]
    for code in expected_codes:
        assert code in output.ERROR_CODES, f"Missing error code: {code}"
