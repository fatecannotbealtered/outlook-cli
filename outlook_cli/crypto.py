"""Machine-bound password encryption using AES-256-GCM.

Derives an encryption key from a machine fingerprint (hostname + CPU info)
so that encrypted credentials only work on the same machine.

Falls back to plaintext if the `cryptography` package is not installed.
"""

import hashlib
import os
import platform
import re
import threading

# Prefix added to encrypted values so we can detect them on load
ENCRYPTED_PREFIX = "enc:v1:"

_fernet = None
_fernet_lock = threading.Lock()


def _machine_id() -> bytes:
    """Build a machine fingerprint from hardware/system identifiers.

    Cross-platform: Windows, macOS, Linux.
    """
    parts = []

    # Hostname
    parts.append(platform.node())

    # Processor identifier
    parts.append(platform.processor())

    # Machine architecture
    parts.append(platform.machine())

    # On Windows: add machine GUID from registry
    if os.name == "nt":
        try:
            import winreg

            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Cryptography",
            )
            guid, _ = winreg.QueryValueEx(key, "MachineGuid")
            parts.append(str(guid))
            winreg.CloseKey(key)
        except Exception:
            pass

    # On Linux: try /etc/machine-id
    if os.name == "posix":
        for path in ["/etc/machine-id", "/var/lib/dbus/machine-id"]:
            try:
                with open(path, "r") as f:
                    parts.append(f.read().strip())
                break
            except (OSError, IOError):
                pass

    # On macOS: try IOPlatformUUID via ioreg
    if platform.system() == "Darwin":
        try:
            import subprocess

            result = subprocess.run(
                ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            match = re.search(r'"IOPlatformUUID"\s*=\s*"([^"]+)"', result.stdout)
            if match:
                parts.append(match.group(1))
        except Exception:
            pass

    raw = "|".join(parts)
    return raw.encode("utf-8")


def _get_fernet():
    """Get or create a Fernet instance derived from machine ID."""
    global _fernet
    if _fernet is not None:
        return _fernet

    with _fernet_lock:
        # Double-check after acquiring lock
        if _fernet is not None:
            return _fernet

        try:
            from cryptography.fernet import Fernet
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
        except ImportError:
            return None

        machine_id = _machine_id()

        # Derive a unique salt from the machine ID itself
        salt = hashlib.sha256(machine_id + b"outlook-cli-salt-v1").digest()[:16]

        # Derive a 32-byte key using PBKDF2
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            iterations=600_000,  # OWASP 2023 recommendation for PBKDF2-SHA256
            salt=salt,
        )
        key_bytes = kdf.derive(machine_id)
        import base64

        key = base64.urlsafe_b64encode(key_bytes)

        _fernet = Fernet(key)
        return _fernet


def is_available() -> bool:
    """Check if encryption is available (cryptography package installed)."""
    return _get_fernet() is not None


def encrypt(plaintext: str) -> str:
    """Encrypt a string. Returns ENCRYPTED_PREFIX + ciphertext.

    Falls back to returning plaintext if cryptography is not available.
    """
    f = _get_fernet()
    if f is None:
        import sys

        print(
            "Warning: cryptography package not installed, storing password as plaintext. "
            "Install it with: pip install cryptography",
            file=sys.stderr,
        )
        return plaintext

    token = f.encrypt(plaintext.encode("utf-8")).decode("ascii")
    return ENCRYPTED_PREFIX + token


def decrypt(value: str) -> str:
    """Decrypt a value that was encrypted with encrypt().

    If the value doesn't have the encrypted prefix, returns it as-is
    (backward compatible with plaintext configs).

    Raises DecryptionError if decryption fails on encrypted data.
    """
    if not value or not value.startswith(ENCRYPTED_PREFIX):
        return value

    f = _get_fernet()
    if f is None:
        raise DecryptionError(
            "Cannot decrypt credentials: cryptography package not installed. "
            "Install it with: pip install cryptography"
        )

    token = value[len(ENCRYPTED_PREFIX) :]
    try:
        return f.decrypt(token.encode("ascii")).decode("utf-8")
    except Exception as e:
        raise DecryptionError(
            f"Failed to decrypt credentials (data may be from a different machine "
            f"or corrupted). Re-run 'outlook-cli setup login' to re-configure. "
            f"Detail: {e}"
        ) from e


def is_encrypted(value: str) -> bool:
    """Check if a value looks like an encrypted token."""
    return bool(value) and value.startswith(ENCRYPTED_PREFIX)


class DecryptionError(Exception):
    """Raised when credential decryption fails."""

    pass
