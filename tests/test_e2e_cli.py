"""End-to-end CLI tests (no Exchange connection required).

Tests CLI structure, help output, error handling, and permission system
by invoking the CLI as a subprocess.
"""

import json
import os
import subprocess
import sys


def run_cli(*args, env_overrides=None):
    """Run outlook-cli and return (exit_code, stdout, stderr)."""
    env = os.environ.copy()
    # Clear any real credentials
    env.pop("OUTLOOK_EMAIL", None)
    env.pop("OUTLOOK_PASSWORD", None)
    env.pop("OUTLOOK_SERVER", None)
    env.pop("OUTLOOK_PERMISSIONS", None)
    env.pop("OUTLOOK_SHARED_MAILBOX", None)
    # Force UTF-8 output for Windows
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    if env_overrides:
        env.update(env_overrides)

    result = subprocess.run(
        [sys.executable, "-m", "outlook_cli.main", *args],
        capture_output=True,
        timeout=30,
        env=env,
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )
    stdout = result.stdout.decode("utf-8", errors="replace")
    stderr = result.stderr.decode("utf-8", errors="replace")
    return result.returncode, stdout, stderr


def parse_json_doc(text):
    """Parse a JSON document from stdout or stderr."""
    start = text.find("{")
    assert start >= 0, "expected JSON output"
    return json.loads(text[start:].strip())


def data_doc(stdout):
    return parse_json_doc(stdout)["data"]


def error_code(stdout):
    return parse_json_doc(stdout)["error"]["code"]


def confirm_token_for(*args, env_overrides=None):
    code, stdout, stderr = run_cli(*args, "--dry-run", env_overrides=env_overrides)
    assert code == 0, stderr
    return data_doc(stdout)["confirm_token"]


class TestCLIHelp:
    """Test that all commands are registered and help works."""

    def test_top_level_help(self):
        code, stdout, _ = run_cli("--help")
        assert code == 0
        assert "Outlook Exchange CLI" in stdout
        assert "mail" in stdout
        assert "cal" in stdout
        assert "folders" in stdout
        assert "rules" in stdout
        assert "tools" in stdout
        assert "setup" in stdout
        assert "changelog" in stdout
        assert "update" in stdout
        assert "--dry-run" in stdout
        assert "--confirm" in stdout

    def test_version(self):
        code, stdout, _ = run_cli("--version")
        assert code == 0
        assert "outlook-cli" in stdout

    def test_mail_help(self):
        code, stdout, _ = run_cli("mail", "--help")
        assert code == 0
        for cmd in [
            "list",
            "search",
            "read",
            "send",
            "reply",
            "forward",
            "delete",
            "move",
            "mark",
            "flag",
            "drafts",
        ]:
            assert cmd in stdout, f"mail {cmd} not in help"

    def test_cal_help(self):
        code, stdout, _ = run_cli("cal", "--help")
        assert code == 0
        assert "list" in stdout
        assert "create" in stdout

    def test_folders_help(self):
        code, stdout, _ = run_cli("folders", "--help")
        assert code == 0

    def test_rules_help(self):
        code, stdout, _ = run_cli("rules", "--help")
        assert code == 0

    def test_tools_help(self):
        code, stdout, _ = run_cli("tools", "--help")
        assert code == 0
        assert "contacts" in stdout
        assert "free-busy" in stdout
        assert "oof" in stdout
        assert "respond" in stdout

    def test_setup_help(self):
        code, stdout, _ = run_cli("setup", "--help")
        assert code == 0
        assert "login" in stdout
        assert "status" in stdout
        assert "doctor" in stdout

    def test_mail_send_help(self):
        code, stdout, _ = run_cli("mail", "send", "--help")
        assert code == 0
        assert "--html" in stdout
        assert "--attachments" in stdout
        assert "--bcc" in stdout
        assert "--preview" not in stdout
        assert "--send" not in stdout

    def test_mail_draft_edit_help(self):
        code, stdout, _ = run_cli("mail", "draft-edit", "--help")
        assert code == 0
        assert "--html" in stdout
        assert "--attachments" in stdout
        assert "--bcc" in stdout

    def test_mail_reply_help(self):
        code, stdout, _ = run_cli("mail", "reply", "--help")
        assert code == 0
        assert "--html" in stdout
        assert "--attachments" in stdout

    def test_mail_reply_all_help(self):
        code, stdout, _ = run_cli("mail", "reply-all", "--help")
        assert code == 0
        assert "--html" in stdout
        assert "--attachments" in stdout

    def test_mail_forward_help(self):
        code, stdout, _ = run_cli("mail", "forward", "--help")
        assert code == 0
        assert "--html" in stdout
        assert "--attachments" in stdout

    def test_tools_respond_help(self):
        code, stdout, _ = run_cli("tools", "respond", "--help")
        assert code == 0
        assert "--mail-id" in stdout
        assert "--id" in stdout
        assert "--action" in stdout


class TestGlobalFlags:
    """Test global flag behavior."""

    def test_json_flag_in_help(self):
        code, stdout, _ = run_cli("--help")
        assert "--json" in stdout

    def test_quiet_flag_in_help(self):
        code, stdout, _ = run_cli("--help")
        assert "--quiet" in stdout

    def test_dry_run_flag_in_help(self):
        code, stdout, _ = run_cli("--help")
        assert "--dry-run" in stdout

    def test_account_flag_in_help(self):
        code, stdout, _ = run_cli("--help")
        assert code == 0
        assert "--account" in stdout

    def test_format_flag_in_help(self):
        code, stdout, _ = run_cli("--help")
        assert code == 0
        assert "--format" in stdout

    def test_fields_flag_in_help(self):
        code, stdout, _ = run_cli("--help")
        assert code == 0
        assert "--fields" in stdout

    def test_confirm_flag_in_help(self):
        code, stdout, _ = run_cli("--help")
        assert code == 0
        assert "--confirm" in stdout

    def test_update_help(self):
        code, stdout, _ = run_cli("update", "--help")
        assert code == 0
        assert "--check" in stdout
        assert "--manager" in stdout


class TestSelfDescription:
    """Test agent-facing self-description commands."""

    def test_reference(self):
        code, stdout, _ = run_cli("reference", "--compact")
        assert code == 0
        data = data_doc(stdout)
        assert data["tool"] == "outlook-cli"
        assert data["schema_version"] == "2.0"
        assert data["risk_tier"] == "T1"
        assert data["release_readiness"]["level"] == "beta"
        assert data["release_readiness"]["live_smoke_status"] == "missing"
        assert data["security"]["untrusted_marker"] == "_untrusted"
        assert "commands" in data
        assert any(cmd["path"] == "update" for cmd in data["commands"])
        assert any(cmd["path"] == "changelog" for cmd in data["commands"])
        mail_group = next(cmd for cmd in data["commands"] if cmd["path"] == "mail")
        mail_list = next(cmd for cmd in mail_group["children"] if cmd["path"] == "mail list")
        assert mail_list["pagination"]["supported"] is True

    def test_context(self):
        code, stdout, _ = run_cli("context", "--compact")
        assert code == 0
        data = data_doc(stdout)
        assert data["version"]
        assert "configured" in data
        assert "credentials" in data
        assert "skill" in data

    def test_doctor(self):
        code, stdout, _ = run_cli("doctor", "--compact")
        assert code == 0
        checks = data_doc(stdout)["checks"]
        assert any(c["check"] == "version" for c in checks)
        readiness = next(c for c in checks if c["check"] == "release_readiness")
        assert readiness["status"] == "warn"
        assert readiness["details"]["level"] == "beta"

    def test_changelog(self):
        code, stdout, _ = run_cli("changelog", "--since", "1.1.0", "--compact")
        assert code == 0
        data = data_doc(stdout)
        assert data["current_version"] == "1.1.0"
        assert data["entries"][0]["version"] == "Unreleased"


class TestPermissionEnforcement:
    """Test that permission system blocks unauthorized commands."""

    def _env_with_mode(self, mode):
        return {"OUTLOOK_PERMISSIONS": mode}

    def test_read_only_blocks_send(self):
        code, stdout, _ = run_cli(
            "--json",
            "mail",
            "send",
            "--to",
            "test@test.com",
            "--subject",
            "Hi",
            "--body",
            "Hello",
            "--dry-run",
            env_overrides=self._env_with_mode("read-only"),
        )
        assert code == 4
        assert error_code(stdout) == "E_FORBIDDEN"

    def test_read_only_blocks_reply(self):
        code, stdout, _ = run_cli(
            "--json",
            "mail",
            "reply",
            "--id",
            "fake-id",
            "--body",
            "Hi",
            "--dry-run",
            env_overrides=self._env_with_mode("read-only"),
        )
        assert code == 4
        assert error_code(stdout) == "E_FORBIDDEN"

    def test_read_only_blocks_delete(self):
        code, stdout, _ = run_cli(
            "--json",
            "mail",
            "delete",
            "--id",
            "fake-id",
            env_overrides=self._env_with_mode("read-only"),
        )
        assert code == 4
        assert error_code(stdout) == "E_FORBIDDEN"

    def test_read_only_blocks_cal_create(self):
        code, stdout, _ = run_cli(
            "--json",
            "cal",
            "create",
            "--subject",
            "Test",
            "--start",
            "2026-05-01 10:00",
            "--end",
            "2026-05-01 11:00",
            env_overrides=self._env_with_mode("read-only"),
        )
        assert code == 4
        assert error_code(stdout) == "E_FORBIDDEN"

    def test_write_requires_confirm_for_move(self):
        """Write permission still requires dry-run/confirm."""
        code, stdout, _ = run_cli(
            "--json",
            "mail",
            "move",
            "--id",
            "fake-id",
            "--folder",
            "Archive",
            env_overrides=self._env_with_mode("write"),
        )
        assert code == 5
        assert error_code(stdout) == "E_CONFIRMATION_REQUIRED"

    def test_resource_write_dry_run_requires_credentials(self):
        code, stdout, _ = run_cli(
            "--json",
            "mail",
            "move",
            "--id",
            "fake-id",
            "--folder",
            "Archive",
            "--dry-run",
            env_overrides=self._env_with_mode("write"),
        )
        assert code == 4
        assert error_code(stdout) == "E_CONFIG"

    def test_write_blocks_send(self):
        code, stdout, _ = run_cli(
            "--json",
            "mail",
            "send",
            "--to",
            "test@test.com",
            "--subject",
            "Hi",
            "--body",
            "Hello",
            "--dry-run",
            env_overrides=self._env_with_mode("write"),
        )
        assert code == 4
        assert error_code(stdout) == "E_FORBIDDEN"

    def test_full_allows_send_dry_run(self):
        """Full permission allows a send dry-run."""
        code, stdout, stderr = run_cli(
            "--json",
            "mail",
            "send",
            "--to",
            "test@test.com",
            "--subject",
            "Hi",
            "--body",
            "Hello",
            "--dry-run",
            env_overrides=self._env_with_mode("full"),
        )
        assert code == 0
        assert stderr == ""
        assert data_doc(stdout)["confirm_token"].startswith("ct_")


class TestUpdateCommand:
    """Test self-update command contract without executing package managers."""

    def test_update_check_manual(self):
        code, stdout, _ = run_cli("update", "--check", "--manager", "manual", "--compact")
        assert code == 0
        data = data_doc(stdout)
        assert data["install_method"] == "manual"
        assert data["supported"] is False

    def test_update_requires_confirm(self):
        code, stdout, _ = run_cli("update", "--manager", "npm", "--target-version", "latest")
        assert code == 5
        assert error_code(stdout) == "E_CONFIRMATION_REQUIRED"

    def test_update_dry_run_returns_plan_and_token(self):
        code, stdout, _ = run_cli(
            "update",
            "--manager",
            "npm",
            "--target-version",
            "latest",
            "--dry-run",
            "--compact",
        )
        assert code == 0
        data = data_doc(stdout)
        assert data["confirm_token"].startswith("ct_")
        assert data["command"] == [
            "npm",
            "install",
            "-g",
            "@fatecannotbealtered-/outlook-cli@latest",
        ]

    def test_update_invalid_token_is_conflict(self):
        code, stdout, _ = run_cli("update", "--manager", "manual", "--confirm", "ct_bad")
        assert code == 6
        assert error_code(stdout) == "E_CONFLICT"

    def test_setup_login_token_does_not_expose_password(self):
        code, stdout, _ = run_cli(
            "setup",
            "login",
            "--email",
            "a@example.com",
            "--password",
            "super-secret",
            "--skip-test",
            "--dry-run",
            "--compact",
        )
        assert code == 0
        assert "super-secret" not in stdout

    def test_rules_no_permanent_delete_option(self):
        code, stdout, _ = run_cli("rules", "create", "--help")
        assert code == 0
        assert "--permanent-delete" not in stdout


class TestSendSafety:
    """Test that send commands require dry-run/confirm."""

    def _env_full(self):
        return {"OUTLOOK_PERMISSIONS": "full"}

    def test_send_without_flag_rejected(self):
        token = confirm_token_for(
            "--json",
            "mail",
            "send",
            "--to",
            "test@test.com",
            "--subject",
            "Hi",
            "--body",
            "Hello",
            env_overrides=self._env_full(),
        )
        code, stdout, _ = run_cli(
            "--json",
            "mail",
            "send",
            "--to",
            "test@test.com",
            "--subject",
            "Hi",
            "--body",
            "Hello",
            "--confirm",
            token,
            env_overrides=self._env_full(),
        )
        assert code == 4
        assert error_code(stdout) == "E_CONFIG"

    def test_reply_without_flag_rejected(self):
        code, stdout, _ = run_cli(
            "--json",
            "mail",
            "reply",
            "--id",
            "fake-id",
            "--body",
            "Hi",
            "--dry-run",
            env_overrides=self._env_full(),
        )
        assert code == 4
        assert error_code(stdout) == "E_CONFIG"

    def test_confirm_token_binds_args(self):
        token = confirm_token_for(
            "--json",
            "mail",
            "send",
            "--to",
            "test@test.com",
            "--subject",
            "Hi",
            "--body",
            "Hello",
            env_overrides=self._env_full(),
        )
        code, stdout, _ = run_cli(
            "--json",
            "mail",
            "send",
            "--to",
            "test@test.com",
            "--subject",
            "Changed",
            "--body",
            "Hello",
            "--confirm",
            token,
            env_overrides=self._env_full(),
        )
        assert code == 6
        assert error_code(stdout) == "E_CONFLICT"

    def test_forward_without_flag_rejected(self):
        code, stdout, _ = run_cli(
            "--json",
            "mail",
            "forward",
            "--id",
            "fake-id",
            "--to",
            "test@test.com",
            "--dry-run",
            env_overrides=self._env_full(),
        )
        assert code == 4
        assert error_code(stdout) == "E_CONFIG"

    def test_draft_send_without_flag_rejected(self):
        code, stdout, _ = run_cli(
            "--json",
            "mail",
            "draft-send",
            "--id",
            "fake-id",
            "--dry-run",
            env_overrides=self._env_full(),
        )
        assert code == 4
        assert error_code(stdout) == "E_CONFIG"


class TestRespondValidation:
    """Test tools respond validation."""

    def _env_write(self):
        return {"OUTLOOK_PERMISSIONS": "write"}

    def test_respond_requires_target(self):
        code, stdout, _ = run_cli(
            "--json",
            "tools",
            "respond",
            "--action",
            "accept",
            "--dry-run",
            env_overrides=self._env_write(),
        )
        assert code == 2
        assert error_code(stdout) == "E_VALIDATION"

    def test_respond_requires_id_or_mail_id(self):
        code, stdout, _ = run_cli(
            "--json",
            "tools",
            "respond",
            "--action",
            "accept",
            "--dry-run",
            env_overrides=self._env_write(),
        )
        assert code == 2
        assert error_code(stdout) == "E_VALIDATION"


class TestErrorFormat:
    """Test that errors are properly formatted JSON."""

    def test_config_error_is_json(self):
        code, stdout, _ = run_cli(
            "--json",
            "mail",
            "list",
            env_overrides={"OUTLOOK_EMAIL": "", "OUTLOOK_PASSWORD": ""},
        )
        assert code == 4
        # the failure envelope is the single JSON document on stdout
        doc = parse_json_doc(stdout)
        assert doc["ok"] is False
        assert doc["error"]["code"]


class TestMissingArgs:
    """Test that missing required args produce helpful errors."""

    def test_send_missing_to(self):
        code, _, _ = run_cli("mail", "send", "--subject", "Hi", "--body", "Hello", "--dry-run")
        assert code != 0

    def test_search_no_args(self):
        code, _, _ = run_cli("--json", "mail", "search")
        assert code != 0

    def test_cal_create_missing_subject(self):
        code, _, _ = run_cli(
            "cal",
            "create",
            "--start",
            "2026-05-01 10:00",
            "--end",
            "2026-05-01 11:00",
        )
        assert code != 0

    def test_batch_move_requires_folder(self):
        code, stdout, _ = run_cli(
            "--json",
            "mail",
            "batch",
            "--ids",
            "fake-id",
            "--action",
            "move",
            "--dry-run",
            env_overrides={"OUTLOOK_PERMISSIONS": "write"},
        )
        assert code == 2
        assert error_code(stdout) == "E_VALIDATION"
