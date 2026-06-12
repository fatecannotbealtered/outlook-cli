"""Tests for the crypto module (password encryption/decryption)."""

import json
from unittest.mock import patch

import pytest

from outlook_cli import crypto


class TestEncryptDecrypt:
    """Core encrypt/decrypt round-trip."""

    def test_round_trip(self):
        """Encrypting then decrypting returns the original value."""
        original = "my-secret-password-123!"
        encrypted = crypto.encrypt(original)
        assert encrypted.startswith(crypto.ENCRYPTED_PREFIX)
        assert crypto.decrypt(encrypted) == original

    def test_different_values_different_ciphertext(self):
        """Two different inputs produce different encrypted outputs."""
        e1 = crypto.encrypt("password1")
        e2 = crypto.encrypt("password2")
        assert e1 != e2

    def test_encrypt_is_deterministic_on_same_machine(self):
        """Same plaintext on same machine should decrypt correctly."""
        val = "test-password"
        e1 = crypto.encrypt(val)
        e2 = crypto.encrypt(val)
        # Fernet uses random IV, so ciphertext differs
        assert crypto.decrypt(e1) == crypto.decrypt(e2) == val

    def test_empty_string(self):
        """Empty string encrypts and decrypts back."""
        encrypted = crypto.encrypt("")
        decrypted = crypto.decrypt(encrypted)
        assert decrypted == ""

    def test_unicode_password(self):
        """Unicode passwords work correctly."""
        original = "密码-test-🔒"
        encrypted = crypto.encrypt(original)
        assert crypto.decrypt(encrypted) == original

    def test_long_password(self):
        """Long passwords work correctly."""
        original = "a" * 1000
        encrypted = crypto.encrypt(original)
        assert crypto.decrypt(encrypted) == original


class TestIsEncrypted:
    """Test the is_encrypted helper."""

    def test_encrypted_value(self):
        assert crypto.is_encrypted(crypto.encrypt("test")) is True

    def test_plaintext_value(self):
        assert crypto.is_encrypted("plain-password") is False

    def test_empty_string(self):
        assert crypto.is_encrypted("") is False


class TestDecryptBackwardCompat:
    """Test that plaintext values pass through unchanged."""

    def test_plaintext_passthrough(self):
        """Decryption of non-encrypted value returns it as-is."""
        assert crypto.decrypt("plain-password") == "plain-password"

    def test_empty_passthrough(self):
        assert crypto.decrypt("") == ""


class TestDecryptWrongMachine:
    """Simulate decryption with wrong key (different machine)."""

    def test_wrong_key_raises_error(self):
        """Decrypting with a wrong Fernet key raises DecryptionError."""
        encrypted = crypto.encrypt("my-password")
        # Simulate wrong machine by forcing a different Fernet
        original_fernet = crypto._fernet
        try:
            crypto._fernet = None
            # Patch _machine_id to return different value
            with patch.object(crypto, "_machine_id", return_value=b"wrong-machine-id"):
                with pytest.raises(crypto.DecryptionError, match="Failed to decrypt"):
                    crypto.decrypt(encrypted)
        finally:
            crypto._fernet = original_fernet


class TestConfigIntegration:
    """Test that config save/load properly encrypts/decrypts."""

    def test_save_encrypts_password(self, tmp_path, monkeypatch):
        """Without a keyring backend, save falls back to encrypting the password field."""
        monkeypatch.setattr("outlook_cli.config.config_dir", lambda: tmp_path)
        monkeypatch.setattr("outlook_cli.config.config_path", lambda: tmp_path / "config.json")
        from outlook_cli import secret_store

        monkeypatch.setattr(secret_store, "set_password", lambda _s: False)

        from outlook_cli.config import save

        save({"email": "test@test.com", "password": "secret123", "server": ""})

        # Read raw file — password should be encrypted
        with open(tmp_path / "config.json") as f:
            raw = json.load(f)
        assert raw["password"].startswith(crypto.ENCRYPTED_PREFIX)

    def test_load_decrypts_password(self, tmp_path, monkeypatch):
        """Config load should decrypt the password field."""
        monkeypatch.setattr("outlook_cli.config.config_dir", lambda: tmp_path)
        monkeypatch.setattr("outlook_cli.config.config_path", lambda: tmp_path / "config.json")

        from outlook_cli.config import load, save

        save({"email": "test@test.com", "password": "secret123", "server": ""})

        cfg = load()
        assert cfg["password"] == "secret123"

    def test_load_handles_plaintext_legacy(self, tmp_path, monkeypatch):
        """Config load should handle old plaintext passwords (backward compat)."""
        monkeypatch.setattr("outlook_cli.config.config_dir", lambda: tmp_path)
        monkeypatch.setattr("outlook_cli.config.config_path", lambda: tmp_path / "config.json")

        # Write a legacy plaintext config
        config_file = tmp_path / "config.json"
        with open(config_file, "w") as f:
            json.dump({"email": "test@test.com", "password": "plain-text-pwd"}, f)

        from outlook_cli.config import load

        cfg = load()
        assert cfg["password"] == "plain-text-pwd"

    def test_env_password_not_double_encrypted(self, tmp_path, monkeypatch):
        """Password from env var should not be encrypted on next save cycle (file fallback)."""
        monkeypatch.setattr("outlook_cli.config.config_dir", lambda: tmp_path)
        monkeypatch.setattr("outlook_cli.config.config_path", lambda: tmp_path / "config.json")
        from outlook_cli import secret_store

        monkeypatch.setattr(secret_store, "set_password", lambda _s: False)

        from outlook_cli.config import load, save

        # First save with encrypted password
        save({"email": "test@test.com", "password": "secret123"})

        # Load (decrypted)
        cfg = load()
        assert cfg["password"] == "secret123"

        # Save again — should not double-encrypt
        save(cfg)
        cfg2 = load()
        assert cfg2["password"] == "secret123"

        # Raw file should still be encrypted
        with open(tmp_path / "config.json") as f:
            raw = json.load(f)
        assert raw["password"].startswith(crypto.ENCRYPTED_PREFIX)
