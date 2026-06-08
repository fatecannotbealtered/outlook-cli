"""Calendar commands: list, create, update, delete."""

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
        events = [
            _event_to_dict(item) for item in account.calendar.view(start=start, end=end)
        ]
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
@click.option(
    "--recurrence-interval", default=1, type=int, help="Recurrence interval (default 1)"
)
@click.option("--recurrence-end", default=None, help="Recurrence end date YYYY-MM-DD")
@click.option(
    "--recurrence-count", default=None, type=int, help="Number of occurrences"
)
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

    from exchangelib import CalendarItem, Mailbox, Attendee

    account = get_account()
    tz = get_tz()

    start_dt = _parse_dt(start, "start time")
    end_dt = _parse_dt(end, "end time")

    if end_dt <= start_dt:
        output.handle_error(
            "End time must be after start time", "VALIDATION_ERROR", exit_code=2
        )

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
            Recurrence,
            DailyPattern,
            WeeklyPattern,
            MonthlyPattern,
            NoEndDatePattern,
            EndDatePattern,
            NumberedPattern,
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
        send_meeting_invitations="SendToAllAndSaveCopy"
        if attendee_list
        else "SendToNone",
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
@click.option(
    "--changekey", default="", help="Changekey (from cal list, improves lookup)"
)
@click.option("--subject", default=None)
@click.option("--start", default=None, help="Start time YYYY-MM-DD HH:MM")
@click.option("--end", default=None, help="End time YYYY-MM-DD HH:MM")
@click.option(
    "--attendees", default=None, help="Comma-separated emails (replaces existing)"
)
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

    from exchangelib import Mailbox, Attendee

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
            send_meeting_invitations="SendToAllAndSaveCopy"
            if has_attendees
            else "SendToNone",
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
        send_meeting_cancellations="SendToAllAndSaveCopy"
        if has_attendees
        else "SendToNone"
    )

    data = {"message": "Event deleted", "subject": subject}
    if output.is_json():
        output.print_json(data)
    else:
        output.success(data["message"])
