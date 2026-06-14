"""Exchange Web Services connection and shared utilities.

Migrated from the original utils.py with improved structure.
"""

import json
import os
import threading
import time
from collections import deque

# Lazy import of exchangelib to avoid import errors when not installed
_account = None
_account_lock = threading.Lock()

# Max folder depth for find_mail_by_id
_MAX_FOLDER_DEPTH = 20

# Credential-probe cache: keep the result on disk so `context` (and any caller)
# can report whether the credentials actually work without re-hitting Exchange
# on every invocation. TTL keeps it cheap; the timeout keeps it non-blocking.
_PROBE_CACHE_NAME = "credential-probe.json"
_PROBE_TTL_SECONDS = 300
_PROBE_TIMEOUT_SECONDS = 5


def get_account(shared_mailbox: str = None):
    """Get or create a cached Exchange account connection.

    Args:
        shared_mailbox: Email of shared mailbox to access via delegate.
            If None, checks Click context --account flag, then config/env.
    """
    global _account

    # Resolve shared mailbox: param > Click context > config/env
    if not shared_mailbox:
        try:
            import click

            ctx = click.get_current_context(silent=True)
            if ctx and ctx.obj:
                shared_mailbox = ctx.obj.get("account") or ""
        except Exception:
            pass

    from .config import load

    cfg = load()

    if not shared_mailbox:
        shared_mailbox = cfg.get("shared_mailbox", "").strip()

    # Return cached account if already connected
    if _account is not None:
        return _account

    with _account_lock:
        # Double-check after acquiring lock
        if _account is not None:
            return _account

        email = cfg.get("email", "").strip()
        password = cfg.get("password", "").strip()

        if not email or not password:
            from .output import handle_error as _handle

            _handle(
                "Credentials not configured. Run 'outlook-cli setup login'",
                "CONFIG_ERROR",
                exit_code=3,
            )

        try:
            from exchangelib import DELEGATE, Account, Configuration, Credentials
            from exchangelib.errors import AutoDiscoverFailed
        except ImportError:
            from .output import handle_error as _handle

            _handle(
                "exchangelib not installed. Run: pip install exchangelib",
                "CONFIG_ERROR",
                exit_code=3,
            )

        credentials = Credentials(email, password)
        server = cfg.get("server", "").strip()

        # Target email: shared mailbox or primary
        target_email = shared_mailbox or email

        try:
            if server:
                config = Configuration(server=server, credentials=credentials)
                _account = Account(target_email, config=config, access_type=DELEGATE)
            else:
                _account = Account(
                    target_email,
                    credentials=credentials,
                    autodiscover=True,
                    access_type=DELEGATE,
                )
        except AutoDiscoverFailed:
            from .output import handle_error as _handle

            _handle(
                "Autodiscover failed. Set OUTLOOK_SERVER env var",
                "NETWORK_ERROR",
                exit_code=7,
            )
        except Exception as e:
            from .output import handle_api_error

            handle_api_error(e)

        return _account


def get_tz():
    """Get timezone object. Prefers exchangelib.EWSTimeZone (has ms_id for EWS)."""
    from .config import load

    cfg = load()
    tz_name = cfg.get("timezone", "Asia/Shanghai")

    # Prefer EWSTimeZone: exchangelib needs tz.ms_id for Exchange API calls
    try:
        from exchangelib.ewsdatetime import EWSTimeZone

        return EWSTimeZone(tz_name)
    except Exception:
        pass
    # Fallback: zoneinfo (stdlib in 3.9+)
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(tz_name)
    except Exception:
        pass
    # Last resort: UTC
    try:
        from exchangelib.ewsdatetime import EWSTimeZone

        return EWSTimeZone("UTC")
    except Exception:
        from datetime import timezone

        return timezone.utc


def localize_dt(dt, tz):
    """Localize a naive datetime. Compatible with zoneinfo and pytz."""
    if getattr(dt, "tzinfo", None) is not None:
        try:
            return dt.astimezone(tz)
        except Exception:
            return dt
    try:
        return dt.replace(tzinfo=tz)
    except Exception:
        return tz.localize(dt)


def resolve_folder(account, folder_path: str):
    """Resolve a folder path string to a folder object.

    Supports aliases: inbox/sent/drafts/trash/junk and Chinese names.
    """
    aliases = {
        "inbox": account.inbox,
        "sent": account.sent,
        "drafts": account.drafts,
        "trash": account.trash,
        "junk": account.junk,
        "收件箱": account.inbox,
        "已发送": account.sent,
        "草稿箱": account.drafts,
        "垃圾箱": account.trash,
        "垃圾邮件": account.junk,
    }
    key = folder_path.strip().lower()
    if key in aliases:
        return aliases[key]

    folder = account.inbox.parent
    for part in folder_path.split("/"):
        part = part.strip()
        if not part:
            continue
        try:
            folder = folder / part
        except Exception:
            from .output import handle_error

            handle_error(f"Folder not found: {folder_path}", "NOT_FOUND", exit_code=4)
    return folder


def find_mail_by_id(account, mail_id: str):
    """Search for a mail by Exchange ItemId or MIME Message-ID.

    Lookup order:
      1. Direct .get() by Exchange ItemId (fastest)
      2. Filter by MIME message_id field (backward compat)
      3. BFS folder scan comparing ItemId strings
    """
    # Method 1: Direct .get() — works with Exchange ItemId
    try:
        item = account.inbox.get(id=mail_id)
        if item:
            return item
    except Exception:
        pass

    # Method 2: Filter by MIME message_id (for legacy MIME IDs)
    try:
        for item in account.inbox.filter(message_id=mail_id):
            return item
    except Exception:
        pass

    # Method 3: BFS across all folders
    root = account.inbox.parent
    queue = deque()
    try:
        for child in root.children:
            queue.append((child, 1))
    except Exception:
        pass

    visited = set()
    while queue:
        folder, depth = queue.popleft()
        if depth > _MAX_FOLDER_DEPTH:
            continue
        folder_id = id(folder)
        if folder_id in visited:
            continue
        visited.add(folder_id)

        try:
            # Try direct get
            item = folder.get(id=mail_id)
            if item:
                return item
        except Exception:
            pass
        try:
            # Try MIME message_id filter
            for item in folder.filter(message_id=mail_id):
                return item
        except Exception:
            pass

        if depth < _MAX_FOLDER_DEPTH:
            try:
                for child in folder.children:
                    queue.append((child, depth + 1))
            except Exception:
                pass

    return None


def safe_filename(name: str) -> str:
    """Sanitize filename to prevent path traversal."""
    name = os.path.basename(name)
    safe = "".join(c if (c.isalnum() or c in "._-()[]") else "_" for c in name)
    return safe.strip() or "attachment"


def strip_re_fwd(subject: str, prefix: str) -> str:
    """Avoid stacking Re:/Fwd: prefixes."""
    if subject.lower().startswith(prefix.lower() + " "):
        return subject
    return f"{prefix} {subject}"


def email_to_dict(item, preview_len: int = 500) -> dict:
    """Convert an exchangelib Message to a flat dict."""
    from .timeutil import iso_utc

    sender = item.sender.email_address if item.sender else "unknown"
    to_list = [m.email_address for m in (item.to_recipients or [])]
    cc_list = [m.email_address for m in (item.cc_recipients or [])]
    body = item.text_body or ""
    body_clean = " ".join(body.split())
    # Use Exchange ItemId (not MIME Message-ID) for consistency with --id flags
    item_id = str(item.id) if hasattr(item, "id") and item.id else ""
    return {
        "id": item_id,
        "subject": item.subject or "(no subject)",
        "sender": sender,
        "to": to_list,
        "cc": cc_list,
        "date": iso_utc(item.datetime_received),
        "is_read": item.is_read,
        "has_attachments": bool(item.attachments),
        "preview": body_clean[:preview_len] + ("..." if len(body_clean) > preview_len else ""),
        "_untrusted": ["subject", "sender", "to", "cc", "preview"],
    }


def reset_connection() -> None:
    """Reset cached connection (for testing or re-login)."""
    global _account
    with _account_lock:
        _account = None


def _probe_cache_path():
    from .config import config_dir

    return config_dir() / _PROBE_CACHE_NAME


def _read_probe_cache(fingerprint: str):
    """Return a fresh cached probe result for this credential fingerprint, else None."""
    path = _probe_cache_path()
    if not path.exists():
        return None
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if cached.get("fingerprint") != fingerprint:
        return None
    if time.time() - cached.get("checked_at", 0) > _PROBE_TTL_SECONDS:
        return None
    return cached.get("result")


def _write_probe_cache(fingerprint: str, result: dict) -> None:
    """Persist a probe result; best-effort, observation must not break the caller."""
    try:
        path = _probe_cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"fingerprint": fingerprint, "checked_at": time.time(), "result": result}),
            encoding="utf-8",
        )
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    except Exception:
        pass


def _run_probe(email: str, password: str, server: str, target_email: str) -> dict:
    """Do a single lightweight authenticated access. Returns a result dict, never raises."""
    try:
        from exchangelib import DELEGATE, Account, Configuration, Credentials
    except ImportError:
        return {"valid": False, "reason": "exchangelib not installed"}

    try:
        credentials = Credentials(email, password)
        if server:
            config = Configuration(server=server, credentials=credentials)
            account = Account(target_email, config=config, access_type=DELEGATE)
        else:
            account = Account(
                target_email,
                credentials=credentials,
                autodiscover=True,
                access_type=DELEGATE,
            )
        # Cheapest authenticated touch that proves the credentials resolve.
        _ = account.inbox.total_count
        return {"valid": True, "reason": ""}
    except Exception as exc:
        return {"valid": False, "reason": type(exc).__name__}


def probe_credentials() -> dict:
    """Cheap, cached probe of whether the configured credentials actually work.

    Returns {"valid": bool, "reason": str, "checked": bool}. Never raises and
    never blocks longer than the probe timeout — on timeout/unconfigured we
    report valid:false with the reason rather than holding up the caller.
    """
    from .config import load

    cfg = load()
    email = cfg.get("email", "").strip()
    password = cfg.get("password", "").strip()
    if not email or not password:
        return {"valid": False, "reason": "not configured", "checked": False}

    server = cfg.get("server", "").strip()
    target_email = cfg.get("shared_mailbox", "").strip() or email
    # Fingerprint excludes the secret itself; password length is enough to bust
    # the cache on a re-login without writing the password to the cache file.
    fingerprint = f"{email}|{target_email}|{server}|{len(password)}"

    cached = _read_probe_cache(fingerprint)
    if cached is not None:
        return {**cached, "checked": True}

    result_holder = {}

    def _worker():
        result_holder["result"] = _run_probe(email, password, server, target_email)

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    thread.join(_PROBE_TIMEOUT_SECONDS)

    if "result" not in result_holder:
        # Probe still running — don't block. Report unknown-as-invalid with a
        # reason; don't cache so the next call can retry.
        return {"valid": False, "reason": "probe timed out", "checked": True}

    result = result_holder["result"]
    _write_probe_cache(fingerprint, result)
    return {**result, "checked": True}
