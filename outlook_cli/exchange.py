"""Exchange Web Services connection and shared utilities.

Migrated from the original utils.py with improved structure.
"""

import os

# Lazy import of exchangelib to avoid import errors when not installed
_account = None


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

    email = cfg.get("email", "").strip()
    password = cfg.get("password", "").strip()

    if not email or not password:
        from .output import handle_error as _handle
        _handle(
            "未配置凭据，运行 'outlook-cli setup login' 设置",
            "CONFIG_ERROR",
            exit_code=3,
        )

    try:
        from exchangelib import Credentials, Account, Configuration, DELEGATE
        from exchangelib.errors import AutoDiscoverFailed
    except ImportError:
        from .output import handle_error as _handle
        _handle(
            "exchangelib 未安装，运行: pip install exchangelib",
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
                target_email, credentials=credentials,
                autodiscover=True, access_type=DELEGATE,
            )
    except AutoDiscoverFailed:
        from .output import handle_error as _handle
        _handle(
            "Autodiscover 失败，请设置 OUTLOOK_SERVER 环境变量",
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
    # Fallback: pytz
    try:
        import pytz
        return pytz.timezone(tz_name)
    except Exception:
        pass
    # Fallback: zoneinfo
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
            handle_error(f"文件夹不存在: {folder_path}", "NOT_FOUND", exit_code=4)
    return folder


def find_mail_by_id(account, message_id: str):
    """Search for a mail by message_id across all folders."""
    for item in account.inbox.filter(message_id=message_id):
        return item

    def _search(folder):
        try:
            for item in folder.filter(message_id=message_id):
                return item
        except Exception:
            pass
        try:
            for child in folder.children:
                result = _search(child)
                if result:
                    return result
        except Exception:
            pass
        return None

    return _search(account.inbox.parent)


def safe_filename(name: str) -> str:
    """Sanitize filename to prevent path traversal."""
    name = os.path.basename(name)
    safe = "".join(c if (c.isalnum() or c in " ._-()[]") else "_" for c in name)
    return safe.strip() or "attachment"


def strip_re_fwd(subject: str, prefix: str) -> str:
    """Avoid stacking Re:/Fwd: prefixes."""
    if subject.lower().startswith(prefix.lower() + " "):
        return subject
    return f"{prefix} {subject}"


def email_to_dict(item, preview_len: int = 200) -> dict:
    """Convert an exchangelib Message to a flat dict."""
    sender = item.sender.email_address if item.sender else "unknown"
    to_list = [m.email_address for m in (item.to_recipients or [])]
    cc_list = [m.email_address for m in (item.cc_recipients or [])]
    body = item.text_body or ""
    body_clean = " ".join(body.split())
    return {
        "id": item.message_id or str(item.id),
        "subject": item.subject or "(无主题)",
        "sender": sender,
        "to": to_list,
        "cc": cc_list,
        "date": item.datetime_received.strftime("%Y-%m-%d %H:%M:%S") if item.datetime_received else "",
        "is_read": item.is_read,
        "has_attachments": bool(item.attachments),
        "preview": body_clean[:preview_len] + ("..." if len(body_clean) > preview_len else ""),
    }


def reset_connection() -> None:
    """Reset cached connection (for testing or re-login)."""
    global _account
    _account = None
