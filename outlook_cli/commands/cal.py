"""Calendar commands: list, create, update, delete, batch."""

import json
from datetime import datetime, timedelta, timezone

import click

from .. import output
from ..exchange import get_account, get_tz, localize_dt
from ..timeutil import iso_utc, item_version, parse_datetime


@click.group()
def cal_group():
    """Calendar operations."""
    pass


def _parse_dt(s, field_name="time"):
    """Parse datetime string in YYYY-MM-DD HH:MM format."""
    return parse_datetime(s, field_name)


def _event_to_dict(item):
    """Convert CalendarItem to dict."""
    attendees = []
    for att in item.required_attendees or []:
        attendees.append(
            {
                "email": att.mailbox.email_address if att.mailbox else "",
                "response": att.response_type or "unknown",
                "optional": False,
            }
        )
    for att in item.optional_attendees or []:
        attendees.append(
            {
                "email": att.mailbox.email_address if att.mailbox else "",
                "response": att.response_type or "unknown",
                "optional": True,
            }
        )

    item_id = item.id.id if hasattr(item.id, "id") else str(item.id)
    changekey = item.id.changekey if hasattr(item.id, "changekey") else ""
    return {
        "id": item_id,
        "changekey": changekey,
        "subject": item.subject or "(no subject)",
        "start": iso_utc(item.start),
        "end": iso_utc(item.end),
        "location": item.location or "",
        "organizer": item.organizer.email_address if item.organizer else "",
        "attendees": attendees,
        "body": (item.text_body or "")[:500],
        "is_all_day": item.is_all_day or False,
        "_untrusted": [
            "subject",
            "location",
            "organizer",
            "attendees.email",
            "body",
        ],
    }


def _get_event(account, event_id, changekey=""):
    """Get calendar event by ItemId. Falls back to scanning recent events."""
    from exchangelib import ItemId

    try:
        item = account.calendar.get(id=event_id)
        if item:
            return item
    except Exception:
        pass

    if changekey:
        try:
            eid = ItemId(id=event_id, changekey=changekey)
            items = list(account.calendar.get_items([eid]))
            if items:
                return items[0]
        except Exception:
            pass

    try:
        now = datetime.now(timezone.utc)
        start = now - timedelta(days=365)
        end = now + timedelta(days=365)
        for item in account.calendar.view(start=start, end=end):
            item_id = item.id.id if hasattr(item.id, "id") else str(item.id)
            if item_id == event_id:
                return item
    except Exception:
        pass
    return None


@cal_group.command("list")
@click.option("--start", "start_date", default=None, help="Start date YYYY-MM-DD")
@click.option("--end", "end_date", default=None, help="End date YYYY-MM-DD")
@click.option("--days", default=1, help="Number of days (default 1)")
@click.option("--subject", default=None, help="Filter by subject keyword")
@click.option("--limit", default=50, help="Max results per page")
@click.option("--offset", default=0, help="Pagination offset")
@click.pass_context
def cal_list(ctx, start_date, end_date, days, subject, limit, offset):
    """List calendar events."""
    from ..config import check_permission

    check_permission("cal list")

    account = get_account()
    tz = get_tz()

    if start_date and end_date:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(hour=23, minute=59)
    else:
        now = datetime.now()
        start_dt = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end_dt = start_dt + timedelta(days=days)

    start = localize_dt(start_dt, tz)
    end = localize_dt(end_dt, tz)

    try:
        events = [_event_to_dict(item) for item in account.calendar.view(start=start, end=end)]
    except Exception as e:
        output.handle_error(f"Calendar query failed: {e}", "SERVER_ERROR", exit_code=7)

    if subject:
        kw = subject.lower()
        events = [e for e in events if kw in e["subject"].lower()]

    total = len(events)
    page = events[offset : offset + limit + 1]
    has_more = len(page) > limit
    page = page[:limit]

    data = {
        "total": total,
        "count": len(page),
        "offset": offset,
        "has_more": has_more,
        "next_offset": offset + limit if has_more else None,
        "events": page,
    }

    if output.is_json():
        output.print_json(data)
    else:
        for e in page:
            time_str = f"{e['start']} ~ {e['end']}" if e["end"] else e["start"]
            output.info(f"  [{e['id'][:8]}] {time_str}  {e['subject']}")
            if e["location"]:
                output.gray(f"    Location: {e['location']}")
        output.info(f"--- {len(page)} / {total} events ---")


@cal_group.command("get")
@click.option("--id", "event_id", required=True, help="Event ID from cal list")
@click.option("--changekey", default="", help="Changekey (from cal list, improves lookup)")
@click.pass_context
def cal_get(ctx, event_id, changekey):
    """Get a single calendar event by ID (returns the same shape as cal list items)."""
    from ..config import check_permission

    check_permission("cal get")

    account = get_account()
    item = _get_event(account, event_id, changekey)
    if not item:
        output.handle_error(f"Event not found: {event_id}", "NOT_FOUND", exit_code=3)

    event = _event_to_dict(item)
    if output.is_json():
        output.print_json(event)
    else:
        time_str = f"{event['start']} ~ {event['end']}" if event["end"] else event["start"]
        output.info(f"  [{event['id'][:8]}] {time_str}  {event['subject']}")
        if event["location"]:
            output.gray(f"    Location: {event['location']}")
        if event["organizer"]:
            output.gray(f"    Organizer: {event['organizer']}")


@cal_group.command("create")
@click.option("--subject", required=True, help="Event subject")
@click.option("--start", required=True, help="Start time YYYY-MM-DD HH:MM")
@click.option("--end", required=True, help="End time YYYY-MM-DD HH:MM")
@click.option("--attendees", default=None, help="Comma-separated email addresses")
@click.option("--location", default=None, help="Event location")
@click.option("--body", default=None, help="Event body text")
@click.option(
    "--recurrence",
    type=click.Choice(["daily", "weekly", "monthly"]),
    default=None,
    help="Recurrence pattern",
)
@click.option("--recurrence-interval", default=1, type=int, help="Recurrence interval (default 1)")
@click.option("--recurrence-end", default=None, help="Recurrence end date YYYY-MM-DD")
@click.option("--recurrence-count", default=None, type=int, help="Number of occurrences")
@click.pass_context
def cal_create(
    ctx,
    subject,
    start,
    end,
    attendees,
    location,
    body,
    recurrence,
    recurrence_interval,
    recurrence_end,
    recurrence_count,
):
    """Create a calendar event. Requires dry-run/confirm."""
    from ..config import check_permission

    check_permission("cal create")

    from exchangelib import Attendee, CalendarItem, Mailbox

    account = get_account()
    tz = get_tz()

    start_dt = _parse_dt(start, "start time")
    end_dt = _parse_dt(end, "end time")

    if end_dt <= start_dt:
        output.handle_error("End time must be after start time", "VALIDATION_ERROR", exit_code=2)

    start_local = localize_dt(start_dt, tz)
    end_local = localize_dt(end_dt, tz)

    attendee_list = None
    if attendees:
        attendee_list = [
            Attendee(mailbox=Mailbox(email_address=e.strip()), response_type="Accept")
            for e in attendees.split(",")
            if e.strip()
        ]

    recurrence_obj = None
    if recurrence:
        from exchangelib.recurrence import (
            DailyPattern,
            EndDatePattern,
            MonthlyPattern,
            NoEndDatePattern,
            NumberedPattern,
            Recurrence,
            WeeklyPattern,
        )

        pattern_map = {
            "daily": DailyPattern(interval=recurrence_interval),
            "weekly": WeeklyPattern(interval=recurrence_interval),
            "monthly": MonthlyPattern(interval=recurrence_interval),
        }
        pattern = pattern_map[recurrence]

        if recurrence_end:
            end_date = datetime.strptime(recurrence_end, "%Y-%m-%d").date()
            range_ = EndDatePattern(start=start_dt.date(), end=end_date)
        elif recurrence_count:
            range_ = NumberedPattern(start=start_dt.date(), number=recurrence_count)
        else:
            range_ = NoEndDatePattern(start=start_dt.date())

        recurrence_obj = Recurrence(pattern=pattern, range=range_)

    if ctx.obj.get("dry_run"):
        preview_data = {
            "subject": subject,
            "start": iso_utc(start_local),
            "end": iso_utc(end_local),
            "location": location or "",
            "recurrence": recurrence,
            "attendees": [a.mailbox.email_address for a in (attendee_list or [])],
        }
        output.dry_run_output(
            "Create event",
            preview_data,
            resource_id="new-event",
        )
        return

    from ..confirmation import require_confirmed

    require_confirmed("cal create", resource_id="new-event")

    event = CalendarItem(
        account=account,
        folder=account.calendar,
        subject=subject,
        start=start_local,
        end=end_local,
        body=body or "",
        location=location or "",
        required_attendees=attendee_list,
        recurrence=recurrence_obj,
    )
    event.save(
        send_meeting_invitations="SendToAllAndSaveCopy" if attendee_list else "SendToNone",
    )

    data = {
        "message": "Event created",
        "subject": subject,
        "start": iso_utc(start_local),
        "end": iso_utc(end_local),
        "recurrence": recurrence,
    }

    if output.is_json():
        output.print_json(data)
    else:
        output.success(data["message"])


@cal_group.command("update")
@click.option("--id", "event_id", required=True, help="Event ID from cal list")
@click.option("--changekey", default="", help="Changekey (from cal list, improves lookup)")
@click.option("--subject", default=None)
@click.option("--start", default=None, help="Start time YYYY-MM-DD HH:MM")
@click.option("--end", default=None, help="End time YYYY-MM-DD HH:MM")
@click.option("--attendees", default=None, help="Comma-separated emails (replaces existing)")
@click.option("--location", default=None)
@click.option("--body", default=None)
@click.pass_context
def cal_update(
    ctx,
    event_id,
    changekey,
    subject,
    start,
    end,
    attendees,
    location,
    body,
):
    """Update an existing calendar event. Requires dry-run/confirm."""
    from ..config import check_permission

    check_permission("cal update")

    from exchangelib import Attendee, Mailbox

    account = get_account()
    tz = get_tz()

    item = _get_event(account, event_id, changekey)
    if not item:
        output.handle_error(f"Event not found: {event_id}", "NOT_FOUND", exit_code=4)

    update_fields = []

    if subject is not None:
        item.subject = subject
        update_fields.append("subject")
    if start:
        item.start = localize_dt(_parse_dt(start, "start time"), tz)
        update_fields.append("start")
    if end:
        item.end = localize_dt(_parse_dt(end, "end time"), tz)
        update_fields.append("end")
    if location is not None:
        item.location = location
        update_fields.append("location")
    if body is not None:
        item.body = body
        update_fields.append("body")
    if attendees is not None:
        item.required_attendees = [
            Attendee(mailbox=Mailbox(email_address=e.strip()), response_type="Accept")
            for e in attendees.split(",")
            if e.strip()
        ] or None
        update_fields.append("required_attendees")

    if not update_fields:
        output.handle_error(
            "At least one field to update is required", "VALIDATION_ERROR", exit_code=2
        )

    has_attendees = bool(item.required_attendees or item.optional_attendees)

    if ctx.obj.get("dry_run"):
        output.dry_run_output(
            "Update event",
            {
                "id": event_id,
                "updated_fields": update_fields,
                "has_attendees": has_attendees,
            },
            resource_id=event_id,
            resource_version=item_version(item),
        )
        return

    from ..confirmation import require_confirmed

    require_confirmed(
        "cal update",
        resource_id=event_id,
        resource_version=item_version(item),
    )

    try:
        item.save(
            update_fields=update_fields,
            send_meeting_invitations="SendToAllAndSaveCopy" if has_attendees else "SendToNone",
        )
    except Exception as e:
        output.handle_api_error(e)

    data = {
        "message": "Event updated",
        "updated_fields": update_fields,
        "event": _event_to_dict(item),
    }

    if output.is_json():
        output.print_json(data)
    else:
        output.success(data["message"])
        for f in update_fields:
            output.info(f"  Updated: {f}")


@cal_group.command("delete")
@click.option("--id", "event_id", required=True, help="Event ID")
@click.option("--changekey", default="", help="Changekey (improves lookup)")
@click.option("--force", is_flag=True, help="Skip confirmation")
@click.pass_context
def cal_delete(ctx, event_id, changekey, force):
    """Delete a calendar event (sends cancellation to attendees)."""
    from ..config import check_permission

    check_permission("cal delete")

    account = get_account()
    item = _get_event(account, event_id, changekey)
    if not item:
        output.handle_error(f"Event not found: {event_id}", "NOT_FOUND", exit_code=4)

    has_attendees = bool(item.required_attendees or item.optional_attendees)

    if not force and not output.is_json() and not ctx.obj.get("confirm"):
        click.confirm(f"Delete event '{item.subject}'?", abort=True)

    if ctx.obj.get("dry_run"):
        output.dry_run_output(
            "Delete event",
            {
                "id": event_id,
                "subject": item.subject,
                "has_attendees": has_attendees,
            },
            resource_id=event_id,
            resource_version=item_version(item),
        )
        return

    from ..confirmation import require_confirmed

    require_confirmed(
        "cal delete",
        resource_id=event_id,
        resource_version=item_version(item),
    )

    subject = item.subject
    item.delete(
        send_meeting_cancellations="SendToAllAndSaveCopy" if has_attendees else "SendToNone"
    )

    data = {"message": "Event deleted", "subject": subject}
    if output.is_json():
        output.print_json(data)
    else:
        output.success(data["message"])


# --- Batch operations (class A: native exchangelib bulk_*) -----------------


def _split_ids(raw_values) -> list[str]:
    """Resolve a plural --ids flag into an ordered, de-duplicated id list.

    Accepts comma-separated (``--ids 1,2,3``) and repeatable (``--ids 1 --ids
    2``) forms, and mixes; input order is preserved so the agent can zip
    ``items[]`` back to its inputs (batch contract §15.1).
    """
    seen: set[str] = set()
    ordered: list[str] = []
    for value in raw_values:
        for part in str(value).split(","):
            eid = part.strip()
            if eid and eid not in seen:
                seen.add(eid)
                ordered.append(eid)
    return ordered


def _load_event_specs(file_path: str) -> list[dict]:
    """Read a batch create/update payload: a JSON array of event objects.

    A single object is accepted as a batch of one. Each object's natural key is
    its ``subject`` (create) or ``id`` (update); both are reported as the
    ``target`` in results so the agent can zip results back to inputs.
    """
    try:
        with open(file_path, encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, ValueError) as exc:
        output.handle_error(f"Cannot read --file: {exc}", "VALIDATION_ERROR", exit_code=2)
    if isinstance(payload, dict):
        payload = [payload]
    if not isinstance(payload, list) or not payload:
        output.handle_error(
            "--file must contain a non-empty JSON array of event objects",
            "VALIDATION_ERROR",
            exit_code=2,
        )
    for spec in payload:
        if not isinstance(spec, dict):
            output.handle_error(
                "each --file entry must be a JSON object", "VALIDATION_ERROR", exit_code=2
            )
    return payload


def _err_item(target: str, exc: Exception) -> dict:
    """Map a per-item exception onto the contract error shape (§15.5)."""
    code = output._api_error_code_from_type(exc) or "E_SERVER"
    return {
        "target": target,
        "ok": False,
        "error": {"code": code, "retryable": code in output.RETRYABLE_ERRORS},
    }


def _not_found_item(target: str) -> dict:
    """Per-item entry for a target that could not be resolved."""
    return {"target": target, "ok": False, "error": {"code": "E_NOT_FOUND", "retryable": False}}


def _build_event(account, tz, spec: dict):
    """Build an unsaved CalendarItem from a create spec dict."""
    from exchangelib import Attendee, CalendarItem, Mailbox

    start_dt = parse_datetime(spec["start"], "start time")
    end_dt = parse_datetime(spec["end"], "end time")
    if end_dt <= start_dt:
        raise ValueError("end time must be after start time")

    attendees = None
    raw_attendees = spec.get("attendees")
    if raw_attendees:
        emails = raw_attendees.split(",") if isinstance(raw_attendees, str) else raw_attendees
        attendees = [
            Attendee(mailbox=Mailbox(email_address=e.strip()), response_type="Accept")
            for e in emails
            if str(e).strip()
        ]
    return CalendarItem(
        account=account,
        folder=account.calendar,
        subject=spec["subject"],
        start=localize_dt(start_dt, tz),
        end=localize_dt(end_dt, tz),
        body=spec.get("body") or "",
        location=spec.get("location") or "",
        required_attendees=attendees,
    )


def _summarize(items: list[dict], total: int) -> dict:
    succeeded = sum(1 for i in items if i["ok"] is True)
    failed = sum(1 for i in items if i["ok"] is False)
    skipped = sum(1 for i in items if i["ok"] is None)
    summary = {"total": total, "succeeded": succeeded, "failed": failed}
    if skipped:
        summary["skipped"] = skipped
    return summary


def _batch_create(account, tz, specs, send_invitations) -> list[dict]:
    """Native bulk_create over every event; map results back per target."""
    targets = [s.get("subject") or "(no subject)" for s in specs]
    built = []
    build_errors = {}
    for idx, spec in enumerate(specs):
        try:
            built.append((idx, _build_event(account, tz, spec)))
        except (KeyError, ValueError) as exc:
            build_errors[idx] = exc

    results_by_idx = {}
    if built:
        created = account.bulk_create(
            folder=account.calendar,
            items=[ev for _, ev in built],
            send_meeting_invitations=("SendToAllAndSaveCopy" if send_invitations else "SendToNone"),
        )
        for (idx, _), res in zip(built, created, strict=True):
            results_by_idx[idx] = res

    items = []
    for idx, target in enumerate(targets):
        if idx in build_errors:
            items.append(_err_item(target, build_errors[idx]))
            continue
        res = results_by_idx.get(idx)
        if isinstance(res, Exception):
            items.append(_err_item(target, res))
        else:
            entry = {"target": target, "ok": True}
            new_id = getattr(getattr(res, "id", None), "id", None) or getattr(res, "id", None)
            if new_id:
                entry["id"] = str(new_id)
            items.append(entry)
    return items


def _batch_update(account, tz, specs, send_notifications) -> list[dict]:
    """Native bulk_update over resolved events; map results back per target."""
    prepared = []
    items = [None] * len(specs)
    for idx, spec in enumerate(specs):
        eid = str(spec.get("id") or "").strip()
        if not eid:
            items[idx] = _err_item("(missing id)", ValueError("id is required for update"))
            continue
        event = _get_event(account, eid, str(spec.get("changekey") or ""))
        if not event:
            items[idx] = _not_found_item(eid)
            continue
        fields = _apply_update_fields(event, tz, spec)
        if not fields:
            items[idx] = _err_item(eid, ValueError("no updatable fields supplied"))
            continue
        prepared.append((idx, eid, event, fields))

    if prepared:
        updated = account.bulk_update(
            items=[(ev, fields) for _, _, ev, fields in prepared],
            send_meeting_invitations_or_cancellations=(
                "SendToAllAndSaveCopy" if send_notifications else "SendToNone"
            ),
        )
        for (idx, eid, _, _), res in zip(prepared, updated, strict=True):
            if isinstance(res, Exception):
                items[idx] = _err_item(eid, res)
            else:
                items[idx] = {"target": eid, "ok": True}
    return items


def _apply_update_fields(event, tz, spec: dict) -> list[str]:
    """Mutate an event in place from a spec; return the changed field names."""
    from exchangelib import Attendee, Mailbox

    fields = []
    if "subject" in spec:
        event.subject = spec["subject"]
        fields.append("subject")
    if spec.get("start"):
        event.start = localize_dt(parse_datetime(spec["start"], "start time"), tz)
        fields.append("start")
    if spec.get("end"):
        event.end = localize_dt(parse_datetime(spec["end"], "end time"), tz)
        fields.append("end")
    if "location" in spec:
        event.location = spec["location"]
        fields.append("location")
    if "body" in spec:
        event.body = spec["body"]
        fields.append("body")
    if "attendees" in spec:
        raw = spec["attendees"]
        emails = raw.split(",") if isinstance(raw, str) else (raw or [])
        event.required_attendees = [
            Attendee(mailbox=Mailbox(email_address=str(e).strip()), response_type="Accept")
            for e in emails
            if str(e).strip()
        ] or None
        fields.append("required_attendees")
    return fields


def _batch_delete(account, id_list, continue_on_error) -> list[dict]:
    """Soft-delete events via native bulk_delete, sending cancellations.

    Items move to Deleted Items (recoverable), honoring the tool's
    soft-delete-only policy. A not-found target is reported per item; with
    --no-continue-on-error the first failure stops the run and the remainder is
    reported as skipped.
    """
    from exchangelib.items import MOVE_TO_DELETED_ITEMS

    resolved = []  # (target, item_or_None)
    for eid in id_list:
        resolved.append((eid, _get_event(account, eid)))

    items = []
    to_delete = []  # (target, item)
    stopped = False
    for eid, event in resolved:
        if stopped:
            items.append({"target": eid, "ok": None, "status": "skipped"})
            continue
        if not event:
            items.append(_not_found_item(eid))
            if not continue_on_error:
                stopped = True
            continue
        to_delete.append((eid, event))

    if to_delete:
        has_attendees = any((ev.required_attendees or ev.optional_attendees) for _, ev in to_delete)
        results = account.bulk_delete(
            ids=[ev for _, ev in to_delete],
            delete_type=MOVE_TO_DELETED_ITEMS,
            send_meeting_cancellations=("SendToAllAndSaveCopy" if has_attendees else "SendToNone"),
        )
        for (eid, _), res in zip(to_delete, results, strict=True):
            if isinstance(res, Exception):
                items.append(_err_item(eid, res))
            else:
                items.append({"target": eid, "ok": True})
    return items


@cal_group.command("batch")
@click.option(
    "--action",
    "batch_action",
    type=click.Choice(["create", "update", "delete"]),
    required=True,
)
@click.option("--ids", multiple=True, help="Event IDs for delete (comma-separated or repeated)")
@click.option("--file", "file_path", default=None, help="JSON array of event specs (create/update)")
@click.option(
    "--send-notifications/--no-send-notifications",
    "send_notifications",
    default=True,
    help="Send invitations/cancellations to attendees (default: true)",
)
@click.option(
    "--continue-on-error/--no-continue-on-error",
    "continue_on_error",
    default=True,
    help="Keep going after an item fails (default: true)",
)
@click.option("--force", is_flag=True, help="Skip confirmation prompt (delete)")
@click.pass_context
def cal_batch(ctx, batch_action, ids, file_path, send_notifications, continue_on_error, force):
    """Batch create/update/delete calendar events (native exchangelib bulk).

    One command, one confirm token, one aggregated items[]/summary result.
    Per-item failures do not roll back already-applied items. create/update take
    a JSON --file; delete takes plural --ids. Bulk delete is dangerous.
    """
    from ..config import check_permission, require_dangerous

    # Bulk delete is irreversible/high-blast — gate it (in both dry-run and
    # confirm) behind --dangerous before the token is validated/consumed.
    if batch_action == "delete":
        require_dangerous("cal batch")

    check_permission("cal batch")

    # Resolve and validate inputs per action BEFORE any account/network call, so
    # a usage error (empty targets, missing --file) returns exit 2 deterministically.
    if batch_action == "delete":
        id_list = _split_ids(ids)
        if not id_list:
            output.handle_error(
                "--ids is required for --action delete", "VALIDATION_ERROR", exit_code=2
            )
        targets = id_list
    else:
        if not file_path:
            output.handle_error(
                f"--file is required for --action {batch_action}",
                "VALIDATION_ERROR",
                exit_code=2,
            )
        specs = _load_event_specs(file_path)
        if batch_action == "create":
            targets = [s.get("subject") or "(no subject)" for s in specs]
        else:
            targets = [str(s.get("id") or "(missing id)") for s in specs]

    if batch_action == "delete" and not force:
        if not output.is_json() and not ctx.obj.get("confirm"):
            click.confirm(f"Delete {len(targets)} event(s)?", abort=True)

    if ctx.obj.get("dry_run"):
        output.dry_run_output(
            "Batch calendar operation",
            {
                "action": batch_action,
                "total": len(targets),
                "targets": targets,
                "send_notifications": send_notifications,
            },
            resource_id=",".join(targets),
        )
        return

    from ..confirmation import require_confirmed

    require_confirmed("cal batch", resource_id=",".join(targets))

    account = get_account()
    tz = get_tz()

    if batch_action == "create":
        items = _batch_create(account, tz, specs, send_notifications)
    elif batch_action == "update":
        items = _batch_update(account, tz, specs, send_notifications)
    else:
        items = _batch_delete(account, id_list, continue_on_error)

    data = {
        "message": f"Batch {batch_action}: "
        f"{sum(1 for i in items if i['ok'] is True)}/{len(targets)} succeeded",
        "items": items,
        "summary": _summarize(items, len(targets)),
    }

    if output.is_json():
        output.print_json(data)
    else:
        output.success(data["message"])
        failed = [i["target"] for i in items if i["ok"] is False]
        if failed:
            output.warn(f"  Failed: {', '.join(failed)}")
