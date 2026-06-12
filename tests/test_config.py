"""Tests for config module."""

import json
import os
from pathlib import Path
from unittest import mock

import pytest

from outlook_cli import config


@pytest.fixture(autouse=True)
def isolate_config(tmp_path):
    """Isolate config to a temp directory for each test."""
    with mock.patch.object(config, "CONFIG_DIR_NAME", ".outlook-cli-test"):
        config_dir = tmp_path / ".outlook-cli-test"
        config_dir.mkdir(parents=True, exist_ok=True)
        with mock.patch.object(Path, "home", return_value=tmp_path):
            yield config_dir


def test_config_dir(isolate_config):
    assert config.config_dir().name == ".outlook-cli-test"


def test_config_path(isolate_config):
    path = config.config_path()
    assert path.name == "config.json"
    assert path.parent.name == ".outlook-cli-test"


def test_load_empty():
    """Load returns empty dict when no config file exists."""
    cfg = config.load()
    assert isinstance(cfg, dict)
    assert cfg.get("email") is None


def test_save_and_load(isolate_config):
    """Save and load round-trip."""
    cfg = {"email": "test@example.com", "password": "secret", "server": ""}
    config.save(cfg)

    loaded = config.load()
    assert loaded["email"] == "test@example.com"
    assert loaded["password"] == "secret"


def test_save_strips_env_only_fields(isolate_config):
    """permissions_mode should not be persisted to config file."""
    cfg = {"email": "test@example.com", "password": "pw", "permissions_mode": "write"}
    config.save(cfg)

    raw = json.loads(config.config_path().read_text(encoding="utf-8"))
    assert "permissions_mode" not in raw
    assert raw["email"] == "test@example.com"


def test_env_override(isolate_config):
    """Environment variables override file values."""
    cfg = {"email": "file@example.com", "password": "file_pw"}
    config.save(cfg)

    with mock.patch.dict(os.environ, {"OUTLOOK_EMAIL": "env@example.com"}):
        loaded = config.load()
        assert loaded["email"] == "env@example.com"
        assert loaded["password"] == "file_pw"


def test_is_configured_true(isolate_config):
    cfg = {"email": "a@b.com", "password": "pw"}
    config.save(cfg)
    assert config.is_configured() is True


def test_is_configured_false(isolate_config):
    assert config.is_configured() is False


def test_is_configured_missing_password(isolate_config):
    cfg = {"email": "a@b.com", "password": ""}
    config.save(cfg)
    assert config.is_configured() is False


def test_get_permission_mode_default():
    """Default permission mode is read-only."""
    assert config.get_permission_mode({}) == "read-only"


def test_get_permission_mode_from_config():
    cfg = {"permissions": {"mode": "full"}}
    assert config.get_permission_mode(cfg) == "full"


def test_get_permission_mode_from_env():
    cfg = {"permissions_mode": "write"}
    assert config.get_permission_mode(cfg) == "write"


def test_get_permission_mode_env_overrides_file():
    """permissions_mode (env) overrides permissions.mode (file)."""
    cfg = {"permissions": {"mode": "full"}, "permissions_mode": "read-only"}
    assert config.get_permission_mode(cfg) == "read-only"


def test_permission_levels():
    assert config.PERMISSION_LEVELS["read-only"] == 0
    assert config.PERMISSION_LEVELS["write"] == 1
    assert config.PERMISSION_LEVELS["full"] == 2


def test_full_commands_contain_send():
    assert "mail send" in config.FULL_COMMANDS
    assert "mail reply" in config.FULL_COMMANDS
    assert "mail forward" in config.FULL_COMMANDS


def test_write_commands_contain_move():
    assert "mail move" in config.WRITE_COMMANDS
    assert "mail delete" in config.WRITE_COMMANDS
    assert "cal create" in config.WRITE_COMMANDS


def test_save_creates_directory(tmp_path):
    """save() creates the config directory if it doesn't exist."""
    with mock.patch.object(Path, "home", return_value=tmp_path):
        cfg = {"email": "a@b.com", "password": "pw"}
        config.save(cfg)
        assert config.config_path().exists()


def test_save_corrupt_json(isolate_config):
    """load() gracefully handles corrupt JSON."""
    config.config_path().write_text("not json{{{", encoding="utf-8")
    cfg = config.load()
    assert cfg == {} or cfg.get("email") is None


class TestKeyringStorage:
    def test_save_uses_keyring_and_keeps_config_secret_free(self, fake_secret_store):
        config.save({"email": "u@example.com", "password": "s3cret"})
        raw = (config.config_path()).read_text(encoding="utf-8")
        assert "s3cret" not in raw
        assert '"password_storage": "keyring"' in raw
        assert "password" not in json.loads(raw) or "password_storage" in raw

        loaded = config.load()
        assert loaded["password"] == "s3cret"
        assert loaded["password_storage"] == "keyring"

    def test_save_falls_back_to_encrypted_file(self, monkeypatch):
        from outlook_cli import secret_store

        monkeypatch.setattr(secret_store, "set_password", lambda _s: False)
        config.save({"email": "u@example.com", "password": "fallback-pw"})
        raw = (config.config_path()).read_text(encoding="utf-8")
        assert "fallback-pw" not in raw
        assert '"password_storage": "encrypted-file"' in raw

        loaded = config.load()
        assert loaded["password"] == "fallback-pw"

    def test_missing_keyring_entry_degrades_to_empty_password(self, fake_secret_store):
        config.save({"email": "u@example.com", "password": "vanish"})
        fake_secret_store.clear()
        loaded = config.load()
        assert loaded["password"] == ""
