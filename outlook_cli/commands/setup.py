"""Setup commands: login, status, doctor."""

import click

from .. import output
from ..config import config_path, is_configured, load, save


@click.group()
def setup_group():
    """Configure Outlook Exchange credentials."""
    pass


@setup_group.command("login")
@click.option("--email", default=None, help="Exchange email (required)")
@click.option("--password", default=None, help="Password (required; avoid shell history)")
@click.option(
    "--server",
    default="",
    help="Exchange server URL (optional, auto-discover if empty)",
)
@click.option("--timezone", default="Asia/Shanghai", help="Timezone (default: Asia/Shanghai)")
@click.option("--skip-test", is_flag=True, help="Skip connection test")
@click.pass_context
def setup_login(ctx, email, password, server, timezone, skip_test):
    """Configure Exchange credentials.

    Non-interactive (Agent):
        outlook-cli setup login --email user@co.com --password P@ss --dry-run
        outlook-cli setup login --email user@co.com --password P@ss --confirm <token>
    """
    import os

    from ..confirmation import command_preview_payload, validate_token

    if email is None:
        output.handle_error("--email is required", "E_VALIDATION")
    if password is None:
        output.handle_error("--password is required", "E_VALIDATION")

    if ctx.obj.get("dry_run"):
        output.print_json(command_preview_payload("setup login"))
        return

    confirm = ctx.obj.get("confirm")
    if not confirm:
        output.handle_error(
            "Command 'setup login' requires --dry-run followed by --confirm <token>",
            "E_CONFIRMATION_REQUIRED",
            details={"command": "setup login"},
        )
    valid, reason = validate_token(confirm)
    if not valid:
        output.handle_error(
            "Confirm token is invalid for this operation",
            "E_CONFLICT",
            details={"command": "setup login", "reason": reason},
        )

    cfg = {
        "email": email.strip(),
        "password": password.strip(),
        "server": server.strip(),
        "timezone": timezone.strip() or "Asia/Shanghai",
        "permissions": {"mode": "read-only"},
    }

    # Test connection (skippable for Agent)
    from ..exchange import reset_connection

    reset_connection()

    if not skip_test:
        if not output.is_quiet():
            output.info("Testing connection...")
        try:
            from ..exchange import get_account

            os.environ["OUTLOOK_EMAIL"] = cfg["email"]
            os.environ["OUTLOOK_PASSWORD"] = cfg["password"]
            if cfg["server"]:
                os.environ["OUTLOOK_SERVER"] = cfg["server"]
            reset_connection()
            account = get_account()
            inbox_count = account.inbox.total_count
            if not output.is_quiet():
                output.success(f"Connected as {account.primary_smtp_address}")
                output.info(f"Inbox: {inbox_count} messages")
        except SystemExit:
            raise
        except Exception as e:
            output.handle_api_error(e)
        finally:
            for k in ("OUTLOOK_EMAIL", "OUTLOOK_PASSWORD", "OUTLOOK_SERVER"):
                os.environ.pop(k, None)
            reset_connection()
    else:
        if not output.is_quiet():
            output.warn("Connection test skipped")

    save(cfg)
    if not output.is_quiet():
        output.success(f"Credentials saved to {config_path()}")
        output.info("Permission mode: read-only (edit config to change)")

    if output.is_json():
        output.print_json(
            {
                "email": cfg["email"],
                "server": cfg["server"] or "(auto-discover)",
                "timezone": cfg["timezone"],
                "permissions": "read-only",
            }
        )


@setup_group.command("status")
def setup_status():
    """Check configuration status."""
    cfg = load()
    configured = bool(cfg.get("email") and cfg.get("password"))

    data = {
        "configured": configured,
        "email": cfg.get("email", ""),
        "server": cfg.get("server", "") or "(auto-discover)",
        "timezone": cfg.get("timezone", "Asia/Shanghai"),
        "config_file": str(config_path()),
        "permissions": cfg.get("permissions", {}).get("mode", "read-only")
        if isinstance(cfg.get("permissions"), dict)
        else "read-only",
    }

    if output.is_json():
        output.print_json(data)
    else:
        if configured:
            output.success(f"Configured: {data['email']}")
            output.info(f"Server: {data['server']}")
            output.info(f"Timezone: {data['timezone']}")
            output.info(f"Permissions: {data['permissions']}")
        else:
            output.warn("Not configured. Run 'outlook-cli setup login'")


@setup_group.command("doctor")
def setup_doctor():
    """Test Exchange connection and report health."""
    if not is_configured():
        output.handle_error(
            "Credentials not configured. Run 'outlook-cli setup login'",
            "CONFIG_ERROR",
            exit_code=3,
        )

    from ..exchange import get_account, reset_connection

    reset_connection()

    output.info("Testing Exchange connection...")
    try:
        account = get_account()
        inbox = account.inbox
        data = {
            "connection": "ok",
            "email": account.primary_smtp_address,
            "inbox_total": inbox.total_count,
            "inbox_unread": inbox.unread_count,
        }
        if output.is_json():
            output.print_json(data)
        else:
            output.success(f"Connected: {data['email']}")
            output.info(f"Inbox: {data['inbox_total']} total, {data['inbox_unread']} unread")
    except Exception as e:
        output.handle_api_error(e)
