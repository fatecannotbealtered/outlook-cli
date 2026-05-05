"""Rules commands: list, create, update, delete, toggle."""

import click

from .. import output
from ..exchange import get_account


@click.group()
def rules_group():
    """Inbox rules management."""
    pass


def _rule_to_dict(rule):
    """Convert Exchange rule to dict."""
    conditions = {}
    actions = {}
    exceptions = {}

    if rule.conditions:
        c = rule.conditions
        if getattr(c, "contains_sender_strings", None):
            conditions["sender_contains"] = list(c.contains_sender_strings)
        if getattr(c, "from_addresses", None):
            conditions["from_addresses"] = [
                m.email_address for m in c.from_addresses if m.email_address
            ]
        if getattr(c, "contains_subject_strings", None):
            conditions["subject_contains"] = list(c.contains_subject_strings)
        if getattr(c, "contains_subject_or_body_strings", None):
            conditions["subject_or_body_contains"] = list(
                c.contains_subject_or_body_strings
            )
        if getattr(c, "contains_body_strings", None):
            conditions["body_contains"] = list(c.contains_body_strings)
        if getattr(c, "contains_recipient_strings", None):
            conditions["recipient_contains"] = list(c.contains_recipient_strings)
        if getattr(c, "sent_to_addresses", None):
            conditions["sent_to"] = [
                m.email_address for m in c.sent_to_addresses if m.email_address
            ]
        if getattr(c, "sent_to_me", None):
            conditions["sent_to_me"] = True
        if getattr(c, "sent_only_to_me", None):
            conditions["sent_only_to_me"] = True
        if getattr(c, "sent_cc_me", None):
            conditions["sent_cc_me"] = True
        if getattr(c, "sent_to_or_cc_me", None):
            conditions["sent_to_or_cc_me"] = True
        if getattr(c, "has_attachments", None):
            conditions["has_attachments"] = True
        if getattr(c, "importance", None):
            conditions["importance"] = str(c.importance)
        if getattr(c, "within_size_range", None):
            conditions["size_range_kb"] = {
                "min": getattr(c.within_size_range, "minimum_size", None),
                "max": getattr(c.within_size_range, "maximum_size", None),
            }
        if getattr(c, "is_meeting_request", None):
            conditions["is_meeting_request"] = True
        if getattr(c, "is_automatic_reply", None):
            conditions["is_automatic_reply"] = True

    if rule.actions:
        a = rule.actions
        if getattr(a, "move_to_folder", None):
            try:
                actions["move_to_folder"] = a.move_to_folder.name
            except Exception:
                actions["move_to_folder"] = str(a.move_to_folder)
        if getattr(a, "copy_to_folder", None):
            try:
                actions["copy_to_folder"] = a.copy_to_folder.name
            except Exception:
                actions["copy_to_folder"] = str(a.copy_to_folder)
        if getattr(a, "delete", None):
            actions["delete"] = True
        if getattr(a, "permanently_delete", None):
            actions["permanently_delete"] = True
        if getattr(a, "mark_as_read", None):
            actions["mark_as_read"] = True
        if getattr(a, "mark_importance", None):
            actions["mark_importance"] = str(a.mark_importance)
        if getattr(a, "forward_to_recipients", None):
            actions["forward_to"] = [
                m.email_address for m in a.forward_to_recipients if m.email_address
            ]
        if getattr(a, "forward_as_attachment_to_recipients", None):
            actions["forward_as_attachment_to"] = [
                m.email_address
                for m in a.forward_as_attachment_to_recipients
                if m.email_address
            ]
        if getattr(a, "redirect_to_recipients", None):
            actions["redirect_to"] = [
                m.email_address for m in a.redirect_to_recipients if m.email_address
            ]
        if getattr(a, "assign_categories", None):
            actions["assign_categories"] = list(a.assign_categories)
        if getattr(a, "stop_processing_rules", None):
            actions["stop_processing"] = True

    if rule.exceptions:
        e = rule.exceptions
        if getattr(e, "contains_sender_strings", None):
            exceptions["except_sender_contains"] = list(e.contains_sender_strings)
        if getattr(e, "contains_subject_strings", None):
            exceptions["except_subject_contains"] = list(e.contains_subject_strings)
        if getattr(e, "contains_body_strings", None):
            exceptions["except_body_contains"] = list(e.contains_body_strings)

    return {
        "id": rule.id,
        "name": rule.display_name or "(unnamed)",
        "priority": rule.priority,
        "is_enabled": rule.is_enabled,
        "conditions": conditions,
        "actions": actions,
        "exceptions": exceptions,
    }


def _find_folder_by_path(account, folder_path):
    """Resolve folder path to folder object."""
    folder = account.inbox.parent
    for part in folder_path.split("/"):
        part = part.strip()
        if not part:
            continue
        try:
            folder = folder / part
        except Exception:
            output.handle_error(
                f"Folder not found: {folder_path}", "NOT_FOUND", exit_code=4
            )
    return folder


def _import_rule_classes():
    """Import rule classes with version compatibility.

    Returns (Rule, Conditions, Actions, Exceptions) — naming varies by version:
      exchangelib 5.x: Rule, Conditions, Actions, Exceptions (all from .properties)
      exchangelib 4.x: Rule (from .items), RuleConditions, RuleActions, RulePredicates
    """
    # exchangelib 5.x: all in properties
    try:
        from exchangelib.properties import Rule, Conditions, Actions, Exceptions

        return Rule, Conditions, Actions, Exceptions
    except ImportError:
        pass
    # exchangelib 4.x: Rule from items, RuleConditions/RuleActions from properties
    try:
        from exchangelib.items import Rule
        from exchangelib.properties import RuleConditions, RuleActions, RulePredicates

        return Rule, RuleConditions, RuleActions, RulePredicates
    except ImportError:
        pass
    # exchangelib 3.x: Rule from top-level
    try:
        from exchangelib import Rule
        from exchangelib.properties import RuleConditions, RuleActions, RulePredicates

        return Rule, RuleConditions, RuleActions, RulePredicates
    except ImportError:
        output.handle_error(
            "Rule management not supported in this exchangelib version, upgrade to 4.x+",
            "CONFIG_ERROR",
            exit_code=3,
        )


def _build_cond_kwargs(**kwargs):
    """Build RuleConditions kwargs from arguments."""
    result = {}
    if kwargs.get("sender"):
        result["contains_sender_strings"] = [
            s.strip() for s in kwargs["sender"].split(",")
        ]
    if kwargs.get("from_address"):
        from exchangelib import Mailbox

        result["from_addresses"] = [
            Mailbox(email_address=e.strip()) for e in kwargs["from_address"].split(",")
        ]
    if kwargs.get("subject"):
        result["contains_subject_strings"] = [
            s.strip() for s in kwargs["subject"].split(",")
        ]
    if kwargs.get("subject_or_body"):
        result["contains_subject_or_body_strings"] = [
            s.strip() for s in kwargs["subject_or_body"].split(",")
        ]
    if kwargs.get("body_keyword"):
        result["contains_body_strings"] = [
            s.strip() for s in kwargs["body_keyword"].split(",")
        ]
    if kwargs.get("recipient"):
        result["contains_recipient_strings"] = [
            s.strip() for s in kwargs["recipient"].split(",")
        ]
    if kwargs.get("sent_to"):
        from exchangelib import Mailbox

        result["sent_to_addresses"] = [
            Mailbox(email_address=e.strip()) for e in kwargs["sent_to"].split(",")
        ]
    if kwargs.get("sent_to_me"):
        result["sent_to_me"] = True
    if kwargs.get("sent_only_to_me"):
        result["sent_only_to_me"] = True
    if kwargs.get("sent_cc_me"):
        result["sent_cc_me"] = True
    if kwargs.get("sent_to_or_cc_me"):
        result["sent_to_or_cc_me"] = True
    if kwargs.get("has_attachments"):
        result["has_attachments"] = True
    if kwargs.get("importance"):
        result["importance"] = kwargs["importance"]
    if kwargs.get("min_size") or kwargs.get("max_size"):
        from exchangelib.properties import RuleSizeRange

        result["within_size_range"] = RuleSizeRange(
            minimum_size=kwargs.get("min_size"),
            maximum_size=kwargs.get("max_size"),
        )
    if kwargs.get("is_meeting_request"):
        result["is_meeting_request"] = True
    if kwargs.get("is_automatic_reply"):
        result["is_automatic_reply"] = True
    return result


def _build_act_kwargs(account, **kwargs):
    """Build RuleActions kwargs from arguments."""
    result = {}
    if kwargs.get("move_to"):
        result["move_to_folder"] = _find_folder_by_path(account, kwargs["move_to"])
    if kwargs.get("copy_to"):
        result["copy_to_folder"] = _find_folder_by_path(account, kwargs["copy_to"])
    if kwargs.get("mark_read"):
        result["mark_as_read"] = True
    if kwargs.get("mark_importance"):
        result["mark_importance"] = kwargs["mark_importance"]
    if kwargs.get("forward_to"):
        from exchangelib import Mailbox

        result["forward_to_recipients"] = [
            Mailbox(email_address=e.strip()) for e in kwargs["forward_to"].split(",")
        ]
    if kwargs.get("forward_as_attachment_to"):
        from exchangelib import Mailbox

        result["forward_as_attachment_to_recipients"] = [
            Mailbox(email_address=e.strip())
            for e in kwargs["forward_as_attachment_to"].split(",")
        ]
    if kwargs.get("redirect_to"):
        from exchangelib import Mailbox

        result["redirect_to_recipients"] = [
            Mailbox(email_address=e.strip()) for e in kwargs["redirect_to"].split(",")
        ]
    if kwargs.get("delete_msg"):
        result["delete"] = True
    if kwargs.get("permanent_delete"):
        result["permanently_delete"] = True
    if kwargs.get("assign_categories"):
        result["assign_categories"] = [
            c.strip() for c in kwargs["assign_categories"].split(",")
        ]
    if kwargs.get("stop"):
        result["stop_processing_rules"] = True
    return result


def _add_condition_options(f):
    """Add condition-related Click options."""
    # Using a custom approach since Click doesn't support option groups natively
    decorators = [
        click.option("--sender", default=None, help="Sender contains (comma-sep)"),
        click.option(
            "--from-address", default=None, help="Exact sender email (comma-sep)"
        ),
        click.option("--subject", default=None, help="Subject contains (comma-sep)"),
        click.option(
            "--subject-or-body", default=None, help="Subject or body contains"
        ),
        click.option("--body-keyword", default=None, help="Body contains"),
        click.option("--recipient", default=None, help="Recipient contains"),
        click.option(
            "--sent-to", default=None, help="Sent to email (exact, comma-sep)"
        ),
        click.option("--sent-to-me", is_flag=True),
        click.option("--sent-only-to-me", is_flag=True),
        click.option("--sent-cc-me", is_flag=True),
        click.option("--sent-to-or-cc-me", is_flag=True),
        click.option("--has-attachments", is_flag=True),
        click.option(
            "--importance", type=click.Choice(["High", "Normal", "Low"]), default=None
        ),
        click.option("--min-size", type=int, default=None, help="Min size (KB)"),
        click.option("--max-size", type=int, default=None, help="Max size (KB)"),
        click.option("--is-meeting-request", is_flag=True),
        click.option("--is-automatic-reply", is_flag=True),
    ]
    for d in reversed(decorators):
        f = d(f)
    return f


def _add_action_options(f):
    """Add action-related Click options."""
    decorators = [
        click.option("--move-to", default=None, help="Move to folder path"),
        click.option("--copy-to", default=None, help="Copy to folder path"),
        click.option("--mark-read", is_flag=True),
        click.option(
            "--mark-importance",
            type=click.Choice(["High", "Normal", "Low"]),
            default=None,
        ),
        click.option(
            "--forward-to", default=None, help="Forward to (comma-sep emails)"
        ),
        click.option("--forward-as-attachment-to", default=None),
        click.option("--redirect-to", default=None),
        click.option("--delete-msg", is_flag=True, help="Delete (move to trash)"),
        click.option("--permanent-delete", is_flag=True),
        click.option(
            "--assign-categories", default=None, help="Categories (comma-sep)"
        ),
        click.option("--stop", is_flag=True, help="Stop processing rules"),
    ]
    for d in reversed(decorators):
        f = d(f)
    return f


def _add_exception_options(f):
    """Add exception-related Click options."""
    decorators = [
        click.option("--except-sender", default=None),
        click.option("--except-subject", default=None),
        click.option("--except-keyword", default=None),
    ]
    for d in reversed(decorators):
        f = d(f)
    return f


def _build_exc_kwargs(**kwargs):
    """Build exception kwargs from arguments."""
    result = {}
    if kwargs.get("except_sender"):
        result["contains_sender_strings"] = [
            s.strip() for s in kwargs["except_sender"].split(",")
        ]
    if kwargs.get("except_subject"):
        result["contains_subject_strings"] = [
            s.strip() for s in kwargs["except_subject"].split(",")
        ]
    if kwargs.get("except_keyword"):
        result["contains_body_strings"] = [
            s.strip() for s in kwargs["except_keyword"].split(",")
        ]
    return result


@rules_group.command("list")
@click.pass_context
def rules_list(ctx):
    """List all inbox rules."""
    from ..config import check_permission

    check_permission("rules list")

    account = get_account()
    try:
        rules = list(account.rules)
        result = [_rule_to_dict(r) for r in rules]
    except Exception as e:
        output.handle_error(f"Failed to get rules: {e}", "SERVER_ERROR", exit_code=7)

    data = {"count": len(result), "rules": result}

    if output.is_json():
        output.print_json(data)
    else:
        for r in result:
            status = "ON" if r["is_enabled"] else "OFF"
            output.info(f"  [{status}] #{r['priority']} {r['name']}")
            if r["conditions"]:
                output.gray(f"    Conditions: {', '.join(r['conditions'].keys())}")
            if r["actions"]:
                output.gray(f"    Actions: {', '.join(r['actions'].keys())}")


@rules_group.command("create")
@click.option("--name", required=True, help="Rule name")
@click.option("--priority", type=int, default=1, help="Rule priority (default 1)")
@_add_condition_options
@_add_action_options
@_add_exception_options
@click.pass_context
def rules_create(ctx, name, priority, **kwargs):
    """Create a new inbox rule."""
    from ..config import check_permission

    check_permission("rules create")

    account = get_account()
    Rule, RuleConditions, RuleActions, RulePredicates = _import_rule_classes()

    cond_kwargs = _build_cond_kwargs(**kwargs)
    if not cond_kwargs:
        output.handle_error(
            "At least one condition is required", "VALIDATION_ERROR", exit_code=2
        )

    act_kwargs = _build_act_kwargs(account, **kwargs)
    if not act_kwargs:
        output.handle_error(
            "At least one action is required", "VALIDATION_ERROR", exit_code=2
        )

    exc_kwargs = _build_exc_kwargs(**kwargs)

    if ctx.obj.get("dry_run"):
        output.dry_run_output(
            "Create rule",
            {
                "name": name,
                "priority": priority,
                "conditions": list(cond_kwargs.keys()),
                "actions": list(act_kwargs.keys()),
            },
        )
        return

    rule = Rule(
        account=account,
        display_name=name,
        priority=priority,
        is_enabled=True,
        conditions=RuleConditions(**cond_kwargs),
        actions=RuleActions(**act_kwargs),
        exceptions=RulePredicates(**exc_kwargs) if exc_kwargs else None,
    )
    rule.save()

    data = {"message": f"Rule created: {name}", "rule": _rule_to_dict(rule)}

    if output.is_json():
        output.print_json(data)
    else:
        output.success(data["message"])


@rules_group.command("update")
@click.option("--id", "rule_id", required=True, help="Rule ID from rules list")
@click.option("--name", default=None, help="New rule name")
@click.option("--priority", type=int, default=None, help="New priority")
@_add_condition_options
@_add_action_options
@_add_exception_options
@click.pass_context
def rules_update(ctx, rule_id, name, priority, **kwargs):
    """Update an existing inbox rule. Conditions/actions merge with existing ones."""
    from ..config import check_permission

    check_permission("rules update")

    account = get_account()
    Rule, RuleConditions, RuleActions, RulePredicates = _import_rule_classes()

    try:
        rules = list(account.rules)
        target = next((r for r in rules if r.id == rule_id), None)
        if not target:
            output.handle_error(f"Rule not found: {rule_id}", "NOT_FOUND", exit_code=4)
    except Exception as e:
        output.handle_error(f"Failed to get rules: {e}", "SERVER_ERROR", exit_code=7)

    if name is not None:
        target.display_name = name
    if priority is not None:
        target.priority = priority

    # Merge new conditions into existing ones (additive, not replacement)
    cond_kwargs = _build_cond_kwargs(**kwargs)
    if cond_kwargs:
        existing_cond = {}
        if target.conditions:
            for attr in dir(target.conditions):
                if not attr.startswith("_"):
                    val = getattr(target.conditions, attr, None)
                    if val is not None:
                        existing_cond[attr] = val
        existing_cond.update(cond_kwargs)
        target.conditions = RuleConditions(**existing_cond)

    # Merge new actions into existing ones
    act_kwargs = _build_act_kwargs(account, **kwargs)
    if act_kwargs:
        existing_act = {}
        if target.actions:
            for attr in dir(target.actions):
                if not attr.startswith("_"):
                    val = getattr(target.actions, attr, None)
                    if val is not None:
                        existing_act[attr] = val
        existing_act.update(act_kwargs)
        target.actions = RuleActions(**existing_act)

    # Handle exceptions
    exc_kwargs = _build_exc_kwargs(**kwargs)
    if exc_kwargs:
        existing_exc = {}
        if target.exceptions:
            for attr in dir(target.exceptions):
                if not attr.startswith("_"):
                    val = getattr(target.exceptions, attr, None)
                    if val is not None:
                        existing_exc[attr] = val
        existing_exc.update(exc_kwargs)
        target.exceptions = RulePredicates(**existing_exc)

    if ctx.obj.get("dry_run"):
        output.dry_run_output(
            "Update rule",
            {
                "id": rule_id,
                "name": name,
                "priority": priority,
                "conditions_updated": list(cond_kwargs.keys()),
                "actions_updated": list(act_kwargs.keys()),
            },
        )
        return

    target.save()

    data = {
        "message": f"Rule updated: {target.display_name}",
        "rule": _rule_to_dict(target),
    }

    if output.is_json():
        output.print_json(data)
    else:
        output.success(data["message"])


@rules_group.command("delete")
@click.option("--id", "rule_id", required=True, help="Rule ID")
@click.option("--force", is_flag=True, help="Skip confirmation")
@click.pass_context
def rules_delete(ctx, rule_id, force):
    """Delete an inbox rule."""
    from ..config import check_permission

    check_permission("rules delete")

    account = get_account()
    try:
        rules = list(account.rules)
        target = next((r for r in rules if r.id == rule_id), None)
        if not target:
            output.handle_error(f"Rule not found: {rule_id}", "NOT_FOUND", exit_code=4)
    except Exception as e:
        output.handle_error(f"Failed to get rules: {e}", "SERVER_ERROR", exit_code=7)

    if not force and not output.is_json():
        click.confirm(f"Delete rule '{target.display_name}'?", abort=True)

    if ctx.obj.get("dry_run"):
        output.dry_run_output(
            "Delete rule", {"id": rule_id, "name": target.display_name}
        )
        return

    name = target.display_name
    target.delete()

    data = {"message": f"Rule deleted: {name}"}
    if output.is_json():
        output.print_json(data)
    else:
        output.success(data["message"])


@rules_group.command("toggle")
@click.option("--id", "rule_id", required=True, help="Rule ID")
@click.option(
    "--action", "toggle_action", type=click.Choice(["enable", "disable"]), required=True
)
@click.pass_context
def rules_toggle(ctx, rule_id, toggle_action):
    """Enable or disable an inbox rule."""
    from ..config import check_permission

    check_permission("rules toggle")

    account = get_account()
    try:
        rules = list(account.rules)
        target = next((r for r in rules if r.id == rule_id), None)
        if not target:
            output.handle_error(f"Rule not found: {rule_id}", "NOT_FOUND", exit_code=4)
    except Exception as e:
        output.handle_error(f"Failed to get rules: {e}", "SERVER_ERROR", exit_code=7)

    if ctx.obj.get("dry_run"):
        output.dry_run_output("Toggle rule", {"id": rule_id, "action": toggle_action})
        return

    target.is_enabled = toggle_action == "enable"
    target.save()

    status = "enabled" if toggle_action == "enable" else "disabled"
    data = {
        "message": f"Rule {status}: {target.display_name}",
        "is_enabled": target.is_enabled,
    }

    if output.is_json():
        output.print_json(data)
    else:
        output.success(data["message"])
