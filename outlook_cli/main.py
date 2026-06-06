"""outlook-cli entry point.

Outlook Exchange CLI for humans and AI Agents.
Supports mail, calendar, folders, rules, and utility operations.
"""

import functools
import os
import sys
import time

import click

from . import __version__
from . import output
from .audit import log as audit_log


# Track command start time for audit
_start_time: float = 0
_exit_code: int = 0

# Global flags that work at any position (before or after subcommand)
_GLOBAL_BOOL_FLAGS = {"--json", "--quiet", "--dry-run", "--compact"}
_GLOBAL_VALUE_FLAGS = {"--format", "--fields", "--confirm", "--account"}


class FlexibleGroup(click.Group):
    """Click Group that accepts global flags at any position.

    Allows: outlook-cli mail list --json
    As well as: outlook-cli --json mail list
    """

    def parse_args(self, ctx, args):
        # Extract global flags from anywhere in args and prepend them
        remaining = []
        global_args = []
        i = 0
        while i < len(args):
            arg = args[i]
            if arg in _GLOBAL_BOOL_FLAGS:
                global_args.append(arg)
            elif any(arg.startswith(f"{flag}=") for flag in _GLOBAL_VALUE_FLAGS):
                global_args.append(arg)
            elif arg in _GLOBAL_VALUE_FLAGS:
                global_args.append(arg)
                if i + 1 < len(args):
                    global_args.append(args[i + 1])
                    i += 1
            else:
                remaining.append(arg)
            i += 1
        return super().parse_args(ctx, global_args + remaining)


@click.group(cls=FlexibleGroup)
@click.version_option(__version__, prog_name="outlook-cli")
@click.option(
    "--format",
    "format_mode",
    type=click.Choice(["json", "text", "raw"]),
    default="json",
    show_default=True,
    help="Output format",
)
@click.option(
    "--json",
    "json_alias",
    is_flag=True,
    help="Compatibility alias for --format json",
)
@click.option("--fields", default="", help="Comma-separated fields to return")
@click.option("--compact", is_flag=True, help="Compact JSON output")
@click.option("--quiet", is_flag=True, help="Suppress stderr progress/prompts")
@click.option(
    "--dry-run", is_flag=True, help="Preview write operations without executing"
)
@click.option("--confirm", default=None, help="Confirm token from --dry-run")
@click.option("--account", default=None, help="Shared mailbox email (delegate access)")
@click.pass_context
def cli(ctx, format_mode, json_alias, fields, compact, quiet, dry_run, confirm, account):
    """Outlook Exchange CLI for humans and AI Agents.

    Manage email, calendar, folders, rules, and contacts from the terminal.
    """
    global _start_time, _exit_code
    _start_time = time.time()
    _exit_code = 0

    ctx.ensure_object(dict)
    effective_format = "json" if json_alias else format_mode
    ctx.obj["format"] = effective_format
    ctx.obj["json"] = effective_format == "json"
    ctx.obj["quiet"] = quiet
    ctx.obj["dry_run"] = dry_run
    ctx.obj["confirm"] = confirm
    ctx.obj["account"] = account
    ctx.obj["fields"] = fields
    ctx.obj["compact"] = compact

    output.init(
        format_mode=effective_format,
        quiet=quiet,
        compact=compact,
        fields=fields,
    )

    # Register audit hook to fire when the command finishes
    @ctx.call_on_close
    def _on_close():
        _audit_hook(ctx)


# --- Audit hook ---


def _audit_hook(ctx):
    """Write audit entry for write commands on exit."""
    cmd_path = ctx.info_name or "unknown"
    # Build full command path
    if ctx.parent and ctx.parent.info_name:
        cmd_path = f"{ctx.parent.info_name} {cmd_path}"

    from .config import WRITE_COMMANDS, FULL_COMMANDS

    all_write = WRITE_COMMANDS | FULL_COMMANDS
    if cmd_path not in all_write:
        return

    duration_ms = int((time.time() - _start_time) * 1000)
    audit_log(cmd_path, sys.argv[1:], _exit_code, duration_ms)


# --- Register command groups ---


def _register_commands():
    """Register all command groups."""
    from .commands.mail import mail_group
    from .commands.cal import cal_group
    from .commands.folders import folders_group
    from .commands.rules import rules_group
    from .commands.tools import tools_group
    from .commands.setup import setup_group

    cli.add_command(mail_group, "mail")
    cli.add_command(cal_group, "cal")
    cli.add_command(folders_group, "folders")
    cli.add_command(rules_group, "rules")
    cli.add_command(tools_group, "tools")
    cli.add_command(setup_group, "setup")
    cli.add_command(reference_cmd, "reference")
    cli.add_command(context_cmd, "context")
    cli.add_command(doctor_cmd, "doctor")
    cli.add_command(update_cmd, "update")


# --- Helper decorators ---


def pass_dry_run(f):
    """Decorator to pass dry_run flag and check permission."""

    @functools.wraps(f)
    @click.pass_context
    def wrapper(ctx, *args, **kwargs):
        # Build command path for permission check
        cmd_parts = []
        p = ctx
        while p:
            if p.info_name:
                cmd_parts.append(p.info_name)
            p = p.parent
        cmd_path = " ".join(reversed(cmd_parts))

        from .config import check_permission

        check_permission(cmd_path)
        return ctx.invoke(f, *args, dry_run=ctx.obj["dry_run"], **kwargs)

    return wrapper


def main():
    """Entry point for the CLI."""
    global _exit_code
    try:
        cli(standalone_mode=False)
    except click.exceptions.Exit as e:
        code = e.exit_code if isinstance(e.exit_code, int) else 0
        _exit_code = code
        raise SystemExit(code)
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 1
        _exit_code = code
        raise SystemExit(code)
    except click.Abort:
        _exit_code = 130
        output.handle_error("Aborted", "E_USAGE", exit_code=2)
    except click.ClickException as e:
        _exit_code = 2
        output.handle_error(e.format_message(), "E_USAGE", exit_code=2)
    except Exception as e:
        _exit_code = output.exit_code_for("E_SERVER", fallback=7)
        output.handle_api_error(e)


# --- Self-description commands ---


def _command_type(path: str) -> str:
    from .config import FULL_COMMANDS, LOCAL_WRITE_COMMANDS, WRITE_COMMANDS

    if path in FULL_COMMANDS:
        return "full"
    if path in WRITE_COMMANDS:
        return "write"
    if path in LOCAL_WRITE_COMMANDS:
        return "local-write"
    return "read"


def _param_to_dict(param: click.Parameter) -> dict:
    names = list(getattr(param, "opts", []) or [param.name])
    secondary = list(getattr(param, "secondary_opts", []) or [])
    if secondary:
        names.extend(secondary)
    return {
        "name": param.name,
        "opts": names,
        "required": bool(getattr(param, "required", False)),
        "multiple": bool(getattr(param, "multiple", False)),
        "type": str(getattr(param, "type", "")),
        "default": getattr(param, "default", None),
        "is_flag": bool(getattr(param, "is_flag", False)),
        "help": getattr(param, "help", "") or "",
    }


def _collect_commands(group: click.Group, prefix: tuple[str, ...] = ()) -> list[dict]:
    commands = []
    for name, command in sorted(group.commands.items()):
        path = (*prefix, name)
        path_str = " ".join(path)
        commands.append(
            {
                "name": name,
                "path": path_str,
                "type": _command_type(path_str),
                "help": command.get_short_help_str(limit=120),
                "params": [
                    _param_to_dict(p)
                    for p in command.params
                    if not getattr(p, "hidden", False)
                ],
                "children": _collect_commands(command, path)
                if isinstance(command, click.Group)
                else [],
            }
        )
    return commands


@click.command("reference")
def reference_cmd():
    """Describe CLI commands, parameters, schemas, and exit codes."""
    data = {
        "tool": "outlook-cli",
        "version": __version__,
        "schema_version": output.SCHEMA_VERSION,
        "output": {
            "default_format": "json",
            "envelope": {
                "ok": "boolean",
                "schema_version": "string",
                "data": "object",
                "meta": {"duration_ms": "integer"},
                "error": {
                    "code": "E_*",
                    "message": "string",
                    "details": "object",
                    "retryable": "boolean",
                },
            },
        },
        "global_options": [
            "--format json|text|raw",
            "--json",
            "--fields <a,b,c>",
            "--compact",
            "--dry-run",
            "--confirm <token>",
            "--quiet",
            "--account <email>",
        ],
        "exit_codes": {
            "0": "success",
            "1": "generic error",
            "2": "usage or validation error",
            "3": "resource not found",
            "4": "permission, auth, or configuration failure",
            "5": "confirmation required",
            "6": "precondition conflict or invalid confirm token",
            "7": "retryable transient error",
            "8": "timeout",
        },
        "commands": _collect_commands(cli),
    }
    output.print_json(data)


@click.command("context")
def context_cmd():
    """Describe the current runtime, config, and credential status."""
    from .config import config_path, get_permission_mode, load

    cfg = load()
    data = {
        "env": os.environ.get("OUTLOOK_ENV", "default"),
        "account": cfg.get("shared_mailbox") or cfg.get("email", ""),
        "configured": bool(cfg.get("email") and cfg.get("password")),
        "config": {
            "config_file": str(config_path()),
            "server": cfg.get("server", "") or "(auto-discover)",
            "timezone": cfg.get("timezone", "Asia/Shanghai"),
            "permissions": get_permission_mode(cfg),
            "has_password": bool(cfg.get("password")),
        },
        "credentials": {
            "OUTLOOK_EMAIL": bool(os.environ.get("OUTLOOK_EMAIL")),
            "OUTLOOK_PASSWORD": bool(os.environ.get("OUTLOOK_PASSWORD")),
            "OUTLOOK_SERVER": bool(os.environ.get("OUTLOOK_SERVER")),
            "OUTLOOK_SHARED_MAILBOX": bool(os.environ.get("OUTLOOK_SHARED_MAILBOX")),
        },
    }
    output.print_json(data)


@click.command("doctor")
def doctor_cmd():
    """Run non-invasive environment checks."""
    from .config import PERMISSION_LEVELS, config_path, get_permission_mode, load

    checks = []
    cfg = load()
    path = config_path()
    checks.append(
        {
            "check": "config_file",
            "status": "pass" if path.exists() else "warn",
            "fix": None if path.exists() else "run setup login --dry-run, then setup login --confirm <token>",
            "details": {"path": str(path)},
        }
    )
    checks.append(
        {
            "check": "credentials",
            "status": "pass" if cfg.get("email") and cfg.get("password") else "fail",
            "fix": None if cfg.get("email") and cfg.get("password") else "set OUTLOOK_EMAIL/OUTLOOK_PASSWORD or run setup login",
        }
    )
    mode = get_permission_mode(cfg)
    checks.append(
        {
            "check": "permissions",
            "status": "pass" if mode in PERMISSION_LEVELS else "fail",
            "fix": None if mode in PERMISSION_LEVELS else "set permissions.mode to read-only, write, or full",
            "details": {"mode": mode},
        }
    )
    try:
        import exchangelib  # noqa: F401

        exchangelib_status = "pass"
        exchangelib_fix = None
    except ImportError:
        exchangelib_status = "fail"
        exchangelib_fix = "install package dependencies with pip install -r requirements.txt"
    checks.append(
        {
            "check": "dependency_exchangelib",
            "status": exchangelib_status,
            "fix": exchangelib_fix,
        }
    )
    output.print_json({"checks": checks})


@click.command("update")
@click.option("--check", "check_only", is_flag=True, help="Only check for an update")
@click.option(
    "--manager",
    type=click.Choice(["auto", "npm", "pip", "manual"]),
    default="auto",
    show_default=True,
    help="Update manager",
)
@click.option(
    "--target-version",
    default="latest",
    show_default=True,
    help="Version to install",
)
@click.pass_context
def update_cmd(ctx, check_only, manager, target_version):
    """Check for or install a newer outlook-cli release."""
    from .confirmation import issue_token, validate_token
    from .updater import (
        UpdateFailed,
        UpdateUnsupported,
        check_update,
        detect_install_method,
        execute_update,
        plan_update,
    )

    resolved_manager = detect_install_method(manager)

    if check_only:
        data = check_update(resolved_manager)
        output.print_json(data)
        return

    if ctx.obj.get("dry_run"):
        plan = plan_update(resolved_manager, target_version)
        token, expires_at = issue_token()
        output.print_json(
            {
                "preview": {"changes": plan["changes"]},
                "confirm_token": token,
                "expires_at": expires_at,
                "current_version": plan["current_version"],
                "target_version": plan["target_version"],
                "install_method": plan["install_method"],
                "supported": plan["supported"],
                "command": plan["command"],
                "manual_url": plan["manual_url"],
            }
        )
        return

    confirm = ctx.obj.get("confirm")
    if not confirm:
        output.handle_error(
            "Command 'update' requires --dry-run followed by --confirm <token>",
            "E_CONFIRMATION_REQUIRED",
            details={"command": "update"},
        )

    valid, reason = validate_token(confirm)
    if not valid:
        output.handle_error(
            "Confirm token is invalid for this operation",
            "E_CONFLICT",
            details={"command": "update", "reason": reason},
        )

    try:
        data = execute_update(
            resolved_manager,
            target_version,
            quiet=ctx.obj.get("quiet", False),
        )
    except UpdateUnsupported as exc:
        output.handle_error(
            str(exc),
            "E_VALIDATION",
            details={"install_method": resolved_manager},
        )
    except UpdateFailed as exc:
        output.handle_error(
            str(exc),
            "E_NETWORK",
            details=exc.details,
            retryable=True,
        )

    output.print_json(data)


_register_commands()


if __name__ == "__main__":
    main()
