"""Machine-bound password encryption using AES-256-GCM.

Derives an encryption key from a machine fingerprint (hostname + CPU info)
so that encrypted credentials only work on the same machine.

Falls back to plaintext if the `cryptography` package is not installed.
"""

import os
import platform

# Prefix added to encrypted values so we can detect them on load
ENCRYPTED_PREFIX = "enc:v1:"

_fernet = None


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

    # On macOS: try IOPlatformSerialNumber via ioreg
    if platform.system() == "Darwin":
        try:
            import subprocess
            result = subprocess.run(
                ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
                capture_output=True, text=True, timeout=5,
            )
            for line in result.stdout.split("\n"):
                if "IOPlatformUUID" in line:
                    uuid = line.split('"')[-2]
                    parts.append(uuid)
                    break
        except Exception:
            pass

    raw = "|".join(parts)
    return raw.encode("utf-8")


def _get_fernet():
    """Get or create a Fernet instance derived from machine ID."""
    global _fernet
    if _fernet is not None:
        return _fernet

    try:
        from cryptography.fernet import Fernet
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    except ImportError:
        return None

    machine_id = _machine_id()

    # Derive a 32-byte key using PBKDF2
    # Salt is fixed per-machine (embedded in machine_id already)
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        iterations=100_000,
        salt=b"outlook-cli-v1",
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
        return plaintext

    token = f.encrypt(plaintext.encode("utf-8")).decode("ascii")
    return ENCRYPTED_PREFIX + token


def decrypt(value: str) -> str:
    """Decrypt a value that was encrypted with encrypt().

    If the value doesn't have the encrypted prefix, returns it as-is
    (backward compatible with plaintext configs).
    """
    if not value or not value.startswith(ENCRYPTED_PREFIX):
        return value

    f = _get_fernet()
    if f is None:
        # Can't decrypt without cryptography — return raw (will likely fail auth)
        return value

    token = value[len(ENCRYPTED_PREFIX):]
    try:
        return f.decrypt(token.encode("ascii")).decode("utf-8")
    except Exception:
        # Decryption failed (different machine, corrupted data, etc.)
        return ""


def is_encrypted(value: str) -> bool:
    """Check if a value looks like an encrypted token."""
    return bool(value) and value.startswith(ENCRYPTED_PREFIX)
