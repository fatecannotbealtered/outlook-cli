"""Tests for output module."""

import json

import pytest

from outlook_cli import output, updater


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


def test_new_update_error_codes_have_hints():
    for code in ("E_IO", "E_INTERRUPTED"):
        assert code in output.ERROR_HINTS, f"Missing hint for {code}"


def test_new_update_error_codes_map_to_exits():
    # CLI-SPEC §6: E_IO -> 1, E_INTERRUPTED -> 130.
    assert output.exit_code_for("E_IO") == 1
    assert output.exit_code_for("E_INTERRUPTED") == 130
    assert output.exit_code_for("E_INTEGRITY") == 1


def test_integrity_is_non_retryable_by_default():
    env = output.error_envelope("bad sig", "E_INTEGRITY")
    assert env["error"]["retryable"] is False


def test_interrupted_is_retryable_by_default():
    env = output.error_envelope("cancelled", "E_INTERRUPTED")
    assert env["error"]["retryable"] is True


def test_io_is_non_retryable_by_default():
    env = output.error_envelope("disk full", "E_IO")
    assert env["error"]["retryable"] is False


# --- handle_api_error: exception-type classification (replaces substring sniffing) ---


class _FakeServerBusy(Exception):
    """Stands in for exchangelib.errors.ErrorServerBusy by class name."""


class ErrorServerBusy(Exception):
    pass


class ErrorItemNotFound(Exception):
    pass


class ReadTimeout(Exception):
    pass


def _api_error_exit(exc):
    with pytest.raises(SystemExit) as ei:
        output.init(json_mode=True, quiet=True)
        output.handle_api_error(exc)
    return ei.value.code


def test_handle_api_error_maps_by_type_rate_limited(capsys):
    code = _api_error_exit(ErrorServerBusy("server too busy, please retry"))
    out = capsys.readouterr().out
    parsed = json.loads(out[out.find("{") :])
    assert parsed["error"]["code"] == "E_RATE_LIMITED"
    assert parsed["error"]["retryable"] is True
    assert code == 7


def test_handle_api_error_maps_by_type_not_found(capsys):
    _api_error_exit(ErrorItemNotFound("the item does not exist"))
    out = capsys.readouterr().out
    parsed = json.loads(out[out.find("{") :])
    assert parsed["error"]["code"] == "E_NOT_FOUND"


def test_handle_api_error_maps_by_type_timeout(capsys):
    _api_error_exit(ReadTimeout("read timed out"))
    out = capsys.readouterr().out
    parsed = json.loads(out[out.find("{") :])
    assert parsed["error"]["code"] == "E_TIMEOUT"


def test_handle_api_error_falls_back_to_rate_limit_substring(capsys):
    # An unmapped exception type whose message indicates throttling still classifies.
    _api_error_exit(RuntimeError("HTTP 429 Too Many Requests"))
    out = capsys.readouterr().out
    parsed = json.loads(out[out.find("{") :])
    assert parsed["error"]["code"] == "E_RATE_LIMITED"


# --- error/success envelopes honor the global --compact flag ---


def test_error_json_honors_compact(capsys):
    output.init(json_mode=True, quiet=True, compact=True)
    output.error_json("boom", "E_VALIDATION")
    out = capsys.readouterr().out.strip()
    assert ",\n" not in out and ": " not in out.split('"message"')[0]
    assert json.loads(out)["error"]["code"] == "E_VALIDATION"


def test_error_json_pretty_by_default(capsys):
    output.init(json_mode=True, quiet=True, compact=False)
    output.error_json("boom", "E_VALIDATION")
    out = capsys.readouterr().out
    assert "\n  " in out  # indented (pretty) output
    assert json.loads(out[out.find("{") :])["error"]["code"] == "E_VALIDATION"


# --- meta.notices piggyback: cached update notice rides on every command ---


def _cached_notice():
    return [
        {
            "type": "update_available",
            "update_available": True,
            "severity": "info",
            "current_version": "1.0.0",
            "latest_version": "1.0.1",
            "source": "cache",
        }
    ]


def test_meta_notices_present_when_cache_has_update(monkeypatch, capsys):
    # An arbitrary (non-update) command's envelope carries the cached notice
    # under meta.notices when the local cache holds an available update.
    monkeypatch.setattr(updater, "read_cached_update_notices", _cached_notice)
    output.init(json_mode=True, quiet=False)
    output.print_json({"any": "payload"})
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["meta"]["notices"][0]["type"] == "update_available"
    assert parsed["meta"]["notices"][0]["severity"] == "info"


def test_meta_notices_absent_when_cache_empty(monkeypatch, capsys):
    # No cached update -> meta.notices is omitted entirely (omitempty).
    monkeypatch.setattr(updater, "read_cached_update_notices", lambda: [])
    output.init(json_mode=True, quiet=False)
    output.print_json({"any": "payload"})
    parsed = json.loads(capsys.readouterr().out)
    assert "notices" not in parsed["meta"]


def test_meta_notices_makes_no_network_call(monkeypatch, capsys):
    # The piggyback path reads only the local cache; it must never hit the
    # network. Wire the real reader (returns [] under pytest) and assert the
    # http seam is never touched.
    def _boom(*args, **kwargs):
        raise AssertionError("piggyback path made a network call")

    monkeypatch.setattr(updater.urllib.request, "urlopen", _boom)
    output.init(json_mode=True, quiet=False)
    output.print_json({"any": "payload"})
    parsed = json.loads(capsys.readouterr().out)
    assert "notices" not in parsed["meta"]
