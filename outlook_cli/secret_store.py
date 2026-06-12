"""OS-keyring storage for the Exchange password (SEC-SPEC §4).

Exchange Basic auth needs a durable secret, so the password itself goes into
the OS keyring (Windows Credential Manager / macOS Keychain / Linux Secret
Service); config.json then holds zero secrets, only a storage marker. The
machine-bound AES encryption in crypto.py remains as the fallback when no
keyring backend is available. Every helper is best-effort: any keyring
failure returns a "not available" result instead of raising, so callers can
degrade explicitly.
"""

from __future__ import annotations

SERVICE = "outlook-cli"
ACCOUNT = "exchange-password"


def set_password(secret: str) -> bool:
    """Store the secret in the OS keyring. False = backend unavailable."""
    try:
        import keyring

        keyring.set_password(SERVICE, ACCOUNT, secret)
        # Read-back proves the backend actually persisted it (some null
        # backends accept writes silently).
        return keyring.get_password(SERVICE, ACCOUNT) == secret
    except Exception:
        return False


def get_password() -> str | None:
    """Fetch the secret from the OS keyring; None when absent/unavailable."""
    try:
        import keyring

        return keyring.get_password(SERVICE, ACCOUNT)
    except Exception:
        return None


def delete_password() -> None:
    """Best-effort removal of the keyring entry."""
    try:
        import keyring

        keyring.delete_password(SERVICE, ACCOUNT)
    except Exception:
        pass
