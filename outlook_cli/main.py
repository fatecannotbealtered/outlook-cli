"""outlook-cli entry point.

Outlook Exchange CLI for humans and AI Agents.
Supports mail, calendar, folders, rules, and utility operations.
"""

import functools
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
_GLOBAL_FLAGS = {"--json", "--quiet", "--dry-run"}


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
            if arg in _GLOBAL_FLAGS:
                global_args.append(arg)
            elif arg.startswith("--json"):
                # Handle --json=value form too
                global_args.append(arg)
            elif i > 0 and args[i - 1] in _GLOBAL_FLAGS:
                # This is a value for a global flag (e.g., --account value)
                global_args.append(arg)
            else:
                remaining.append(arg)
            i += 1
        return super().parse_args(ctx, global_args + remaining)


@click.group(cls=FlexibleGroup)
@click.version_option(__version__, prog_name="outlook-cli")
@click.option(
    "--json", "json_mode", is_flag=True, help="JSON output (machine-readable)"
)
@click.option("--quiet", is_flag=True, help="Suppress non-JSON stdout output")
@click.option(
    "--dry-run", is_flag=True, help="Preview write operations without executing"
)
@click.option("--account", default=None, help="Shared mailbox email (delegate access)")
@click.pass_context
def cli(ctx, json_mode, quiet, dry_run, account):
    """Outlook Exchange CLI for humans and AI Agents.

    Manage email, calendar, folders, rules, and contacts from the terminal.
    """
    global _start_time, _exit_code
    _start_time = time.time()
    _exit_code = 0

    ctx.ensure_object(dict)
    ctx.obj["json"] = json_mode
    ctx.obj["quiet"] = quiet
    ctx.obj["dry_run"] = dry_run
    ctx.obj["account"] = account

    output.init(json_mode, quiet)

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


_register_commands()


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
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 1
        _exit_code = code
        raise SystemExit(code)
    except click.Abort:
        _exit_code = 130
        raise SystemExit(130)
    except Exception as e:
        _exit_code = 7
        output.handle_api_error(e)


if __name__ == "__main__":
    main()
