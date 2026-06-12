"""Shared test fixtures.

The fake secret store keeps every in-process test away from the real OS
keyring (subprocess e2e tests only exercise --dry-run paths and never save).
"""

import pytest

from outlook_cli import secret_store


@pytest.fixture(autouse=True)
def fake_secret_store(monkeypatch):
    """Replace the OS keyring with an in-memory dict for all tests."""
    vault: dict[str, str] = {}

    def fake_set(secret: str) -> bool:
        vault[secret_store.ACCOUNT] = secret
        return True

    def fake_get() -> str | None:
        return vault.get(secret_store.ACCOUNT)

    def fake_delete() -> None:
        vault.pop(secret_store.ACCOUNT, None)

    monkeypatch.setattr(secret_store, "set_password", fake_set)
    monkeypatch.setattr(secret_store, "get_password", fake_get)
    monkeypatch.setattr(secret_store, "delete_password", fake_delete)
    yield vault
