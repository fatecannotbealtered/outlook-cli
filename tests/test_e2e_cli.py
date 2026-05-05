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
        assert "--preview" in stdout
        assert "--send" in stdout

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
        assert "--account" in stdout


class TestPermissionEnforcement:
    """Test that permission system blocks unauthorized commands."""

    def _env_with_mode(self, mode):
        return {"OUTLOOK_PERMISSIONS": mode}

    def test_read_only_blocks_send(self):
        code, _, stderr = run_cli(
            "--json",
            "mail",
            "send",
            "--to",
            "test@test.com",
            "--subject",
            "Hi",
            "--body",
            "Hello",
            "--preview",
            env_overrides=self._env_with_mode("read-only"),
        )
        assert code == 5
        assert "FORBIDDEN" in stderr or "权限不足" in stderr

    def test_read_only_blocks_reply(self):
        code, _, stderr = run_cli(
            "--json",
            "mail",
            "reply",
            "--id",
            "fake-id",
            "--body",
            "Hi",
            "--preview",
            env_overrides=self._env_with_mode("read-only"),
        )
        assert code == 5
        assert "FORBIDDEN" in stderr or "权限不足" in stderr

    def test_read_only_blocks_delete(self):
        code, _, stderr = run_cli(
            "--json",
            "mail",
            "delete",
            "--id",
            "fake-id",
            env_overrides=self._env_with_mode("read-only"),
        )
        assert code == 5
        assert "FORBIDDEN" in stderr or "权限不足" in stderr

    def test_read_only_blocks_cal_create(self):
        code, _, stderr = run_cli(
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
        assert code == 5

    def test_write_allows_move(self):
        """Write permission allows move (will fail on connection, not permission)."""
        code, _, stderr = run_cli(
            "--json",
            "mail",
            "move",
            "--id",
            "fake-id",
            "--folder",
            "Archive",
            env_overrides=self._env_with_mode("write"),
        )
        # Should NOT be exit 5 (permission denied)
        # It will be exit 3 (config error) or 7 (connection error) - that's OK
        assert code != 5

    def test_write_blocks_send(self):
        code, _, stderr = run_cli(
            "--json",
            "mail",
            "send",
            "--to",
            "test@test.com",
            "--subject",
            "Hi",
            "--body",
            "Hello",
            "--preview",
            env_overrides=self._env_with_mode("write"),
        )
        assert code == 5

    def test_full_allows_send_preview(self):
        """Full permission allows send (will fail on connection, not permission)."""
        code, _, stderr = run_cli(
            "--json",
            "mail",
            "send",
            "--to",
            "test@test.com",
            "--subject",
            "Hi",
            "--body",
            "Hello",
            "--preview",
            env_overrides=self._env_with_mode("full"),
        )
        # Should NOT be exit 5 (permission denied)
        assert code != 5


class TestSendSafety:
    """Test that send commands require --preview or --send."""

    def _env_full(self):
        return {"OUTLOOK_PERMISSIONS": "full"}

    def test_send_without_flag_rejected(self):
        code, _, stderr = run_cli(
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
        assert code == 2
        assert (
            "VALIDATION_ERROR" in stderr or "--preview" in stderr or "--send" in stderr
        )

    def test_reply_without_flag_rejected(self):
        code, _, stderr = run_cli(
            "--json",
            "mail",
            "reply",
            "--id",
            "fake-id",
            "--body",
            "Hi",
            env_overrides=self._env_full(),
        )
        assert code == 2

    def test_forward_without_flag_rejected(self):
        code, _, stderr = run_cli(
            "--json",
            "mail",
            "forward",
            "--id",
            "fake-id",
            "--to",
            "test@test.com",
            env_overrides=self._env_full(),
        )
        assert code == 2

    def test_draft_send_without_flag_rejected(self):
        code, _, stderr = run_cli(
            "--json",
            "mail",
            "draft-send",
            "--id",
            "fake-id",
            env_overrides=self._env_full(),
        )
        assert code == 2


class TestRespondValidation:
    """Test tools respond validation."""

    def _env_write(self):
        return {"OUTLOOK_PERMISSIONS": "write"}

    def test_respond_requires_preview_or_send(self):
        code, _, stderr = run_cli(
            "--json",
            "tools",
            "respond",
            "--action",
            "accept",
            env_overrides=self._env_write(),
        )
        assert code == 2
        assert "preview" in stderr.lower() or "send" in stderr.lower()

    def test_respond_requires_id_or_mail_id(self):
        code, _, stderr = run_cli(
            "--json",
            "tools",
            "respond",
            "--action",
            "accept",
            "--send",
            env_overrides=self._env_write(),
        )
        assert code == 2
        assert "--id" in stderr or "--mail-id" in stderr


class TestErrorFormat:
    """Test that errors are properly formatted JSON."""

    def test_config_error_is_json(self):
        code, _, stderr = run_cli(
            "--json",
            "mail",
            "list",
            env_overrides={"OUTLOOK_EMAIL": "", "OUTLOOK_PASSWORD": ""},
        )
        assert code == 3
        # stderr should contain JSON error
        lines = [ln for ln in stderr.strip().split("\n") if ln.strip()]
        json_found = False
        for line in lines:
            try:
                data = json.loads(line)
                if "error" in data and "errorCode" in data:
                    json_found = True
                    break
            except json.JSONDecodeError:
                continue
        assert json_found, f"No JSON error found in stderr: {stderr}"


class TestMissingArgs:
    """Test that missing required args produce helpful errors."""

    def test_send_missing_to(self):
        code, _, _ = run_cli(
            "mail", "send", "--subject", "Hi", "--body", "Hello", "--preview"
        )
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
