"""Command-level coverage for leaves the FCC guard found untested:
`setup login`, `tools free-busy`, `tools rooms-free-busy`.
"""

from tests.test_e2e_cli import data_doc, error_code, run_cli


class TestSetupLogin:
    def test_missing_email_is_validation_error(self):
        code, stdout, _ = run_cli("--json", "setup", "login")
        assert code == 2
        assert error_code(stdout) == "E_VALIDATION"

    def test_missing_password_is_validation_error(self):
        code, stdout, _ = run_cli("--json", "setup", "login", "--email", "user@example.com")
        assert code == 2
        assert error_code(stdout) == "E_VALIDATION"

    def test_dry_run_returns_confirm_token(self):
        code, stdout, stderr = run_cli(
            "--json",
            "setup",
            "login",
            "--email",
            "user@example.com",
            "--password",
            "secret",
            "--skip-test",
            "--dry-run",
        )
        assert code == 0, stderr
        data = data_doc(stdout)
        assert data["confirm_token"].startswith("ct_")
        # The dry-run preview must never echo the password.
        assert "secret" not in stdout

    def test_write_requires_confirm_token(self):
        code, stdout, _ = run_cli(
            "--json",
            "setup",
            "login",
            "--email",
            "user@example.com",
            "--password",
            "secret",
            "--skip-test",
        )
        assert code == 5
        assert error_code(stdout) == "E_CONFIRMATION_REQUIRED"


class TestToolsFreeBusy:
    def test_free_busy_missing_options_is_usage_error(self):
        code, stdout, _ = run_cli("--json", "tools", "free-busy")
        assert code == 2
        assert error_code(stdout) == "E_USAGE"

    def test_free_busy_without_credentials_is_config_error(self):
        code, stdout, _ = run_cli(
            "--json",
            "tools",
            "free-busy",
            "--email",
            "user@example.com",
            "--start",
            "2026-06-12",
            env_overrides={"OUTLOOK_EMAIL": "", "OUTLOOK_PASSWORD": ""},
        )
        assert code == 4
        assert error_code(stdout) == "E_CONFIG"

    def test_rooms_free_busy_without_credentials_is_config_error(self):
        code, stdout, _ = run_cli(
            "--json",
            "tools",
            "rooms-free-busy",
            "--start",
            "2026-06-12 09:00",
            "--end",
            "2026-06-12 18:00",
            env_overrides={"OUTLOOK_EMAIL": "", "OUTLOOK_PASSWORD": ""},
        )
        assert code == 4
        assert error_code(stdout) == "E_CONFIG"
