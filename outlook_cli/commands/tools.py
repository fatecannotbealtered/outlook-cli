"""Tools commands: contacts, free-busy, rooms, rooms-free-busy, oof, respond."""

from datetime import datetime, timedelta, timezone

import click

from .. import output
from ..exchange import get_account, get_tz, localize_dt


@click.group()
def tools_group():
    """Utility tools (contacts, calendar queries, OOF, meeting response)."""
    pass


# --- Contacts ---


@tools_group.command("contacts")
@click.option("--query", default=None, help="Fuzzy search (name/department)")
@click.option("--email", "email_exact", default=None, help="Exact email lookup")
@click.option("--limit", default=50, type=int, help="Max results (default 50)")
@click.pass_context
def tools_contacts(ctx, query, email_exact, limit):
    """Search company global address list (GAL)."""
    from ..config import check_permission

    check_permission("tools contacts")

    if not query and not email_exact:
        output.handle_error(
            "Provide --query or --email", "VALIDATION_ERROR", exit_code=2
        )

    if query and len(query) < 2:
        output.handle_error(
            "Search query must be at least 2 characters",
            "VALIDATION_ERROR",
            exit_code=2,
        )

    account = get_account()

    search_term = email_exact or query
    try:
        results = account.protocol.resolve_names(
            [search_term],
            return_full_contact_data=True,
        )
    except Exception as e:
        output.handle_error(f"Contact search failed: {e}", "SERVER_ERROR", exit_code=7)

    contacts = []
    for resolution in results:
        mb = getattr(resolution, "mailbox", None)
        contact = getattr(resolution, "contact", None)
        entry = {
            "name": (mb.name if mb else None) or "",
            "email": (mb.email_address if mb else None) or "",
        }
        if contact:
            entry["department"] = getattr(contact, "department", "") or ""
            entry["title"] = getattr(contact, "job_title", "") or ""
            phones = getattr(contact, "phone_numbers", None)
            if phones:
                entry["phone"] = str(phones[0].phone_number) if phones else ""
        contacts.append(entry)

    if limit:
        contacts = contacts[:limit]

    data = {"count": len(contacts), "contacts": contacts}

    if output.is_json():
        output.print_json(data)
    else:
        for c in contacts:
            dept = f" ({c['department']})" if c.get("department") else ""
            title = f" - {c['title']}" if c.get("title") else ""
            output.info(f"  {c['name']}{dept}{title}")
            output.gray(f"    {c['email']}")
        output.info(f"--- {len(contacts)} contacts ---")


# --- Free/Busy ---


@tools_group.command("free-busy")
@click.option(
    "--email", "emails_str", required=True, help="Email addresses (comma-sep)"
)
@click.option("--start", required=True, help="Start date YYYY-MM-DD")
@click.option(
    "--end", default=None, help="End date YYYY-MM-DD (default: same as start)"
)
@click.option(
    "--slot", type=int, default=30, help="Slot granularity in minutes (default 30)"
)
@click.pass_context
def tools_free_busy(ctx, emails_str, start, end, slot):
    """Query free/busy status and suggest available time slots."""
    from ..config import check_permission

    check_permission("tools free-busy")

    account = get_account()
    tz = get_tz()

    emails = [e.strip() for e in emails_str.split(",") if e.strip()]
    if not emails:
        output.handle_error(
            "At least one email address is required", "VALIDATION_ERROR", exit_code=2
        )

    start_dt = datetime.strptime(start, "%Y-%m-%d")
    if end:
        end_dt = datetime.strptime(end, "%Y-%m-%d").replace(hour=23, minute=59)
    else:
        end_dt = start_dt.replace(hour=23, minute=59)

    start_local = localize_dt(start_dt, tz)
    end_local = localize_dt(end_dt, tz)

    try:
        from exchangelib.properties import Email

        email_objs = [Email(email_address=e) for e in emails]
        results = account.protocol.get_free_busy_info(
            accounts=[(em, "Organizer", False) for em in email_objs],
            start=start_local,
            end=end_local,
        )
    except Exception as e:
        output.handle_error(f"Free/busy query failed: {e}", "SERVER_ERROR", exit_code=7)

    output_data = []
    all_busy = []

    for email, view in zip(emails, results):
        busy_slots = []
        if hasattr(view, "calendar_event_array") and view.calendar_event_array:
            for event in view.calendar_event_array:
                s = event.start.strftime("%Y-%m-%d %H:%M") if event.start else ""
                e_ = event.end.strftime("%Y-%m-%d %H:%M") if event.end else ""
                busy_slots.append(
                    {
                        "start": s,
                        "end": e_,
                        "status": getattr(event, "busy_type", "Busy"),
                    }
                )
                if event.start and event.end:
                    all_busy.append((event.start, event.end))
        output_data.append({"email": email, "busy_slots": busy_slots})

    free_slots = _calc_free_slots(start_dt, end_dt, all_busy, slot)

    data = {"results": output_data, "suggested_free_slots": free_slots}

    if output.is_json():
        output.print_json(data)
    else:
        for r in output_data:
            output.info(f"  {r['email']}: {len(r['busy_slots'])} busy slots")
        if free_slots:
            output.info(f"  Suggested free slots ({len(free_slots)}):")
            for s in free_slots[:5]:
                output.gray(f"    {s['start']} ~ {s['end']}")


def _calc_free_slots(start_dt, end_dt, busy_list, slot_minutes):
    """Calculate free time slots during work hours (08:00-18:00 by default).

    Work hours can be configured via OUTLOOK_WORK_START and OUTLOOK_WORK_END env vars.
    """
    import os

    work_start_h = int(os.environ.get("OUTLOOK_WORK_START", "8"))
    work_end_h = int(os.environ.get("OUTLOOK_WORK_END", "18"))
    free = []
    current = start_dt.replace(hour=work_start_h, minute=0, second=0, microsecond=0)
    day_end = end_dt.replace(hour=work_end_h, minute=0, second=0, microsecond=0)

    busy_naive = []
    for s, e in busy_list:
        try:
            s_naive = s.replace(tzinfo=None) if s.tzinfo else s
            e_naive = e.replace(tzinfo=None) if e.tzinfo else e
            busy_naive.append((s_naive, e_naive))
        except Exception:
            pass
    busy_naive.sort()

    slot_delta = timedelta(minutes=slot_minutes)
    while current + slot_delta <= day_end:
        slot_end = current + slot_delta
        overlap = any(s < slot_end and e > current for s, e in busy_naive)
        if not overlap:
            free.append(
                {
                    "start": current.strftime("%Y-%m-%d %H:%M"),
                    "end": slot_end.strftime("%Y-%m-%d %H:%M"),
                }
            )
        current += slot_delta
        if current.hour >= work_end_h:
            next_day = (current + timedelta(days=1)).replace(
                hour=work_start_h,
                minute=0,
                second=0,
                microsecond=0,
            )
            if next_day > day_end:
                break
            current = next_day

    return free[:10]


# --- Rooms ---


@tools_group.command("rooms")
@click.option("--keyword", default=None, help="Filter room lists by name keyword")
@click.option("--limit", type=int, default=100, help="Max rooms (default 100)")
@click.pass_context
def tools_rooms(ctx, keyword, limit):
    """List meeting rooms grouped by Room List."""
    from ..config import check_permission

    check_permission("tools rooms")

    account = get_account()
    try:
        room_lists = list(account.protocol.get_room_lists())
    except Exception as e:
        output.handle_error(
            f"Failed to get room lists (server may not be configured): {e}",
            "SERVER_ERROR",
            exit_code=7,
        )

    if not room_lists:
        try:
            rooms = list(account.protocol.get_rooms(""))
            if limit:
                rooms = rooms[:limit]
            result = [
                {
                    "list_name": "(ungrouped)",
                    "list_email": "",
                    "rooms": [
                        {"name": r.name, "email": r.email_address} for r in rooms
                    ],
                }
            ]
        except Exception as e:
            output.handle_error(
                f"Failed to get rooms: {e}", "SERVER_ERROR", exit_code=7
            )

        data = {"count": len(rooms), "room_lists": result}
        if output.is_json():
            output.print_json(data)
        return

    result = []
    total = 0
    for rl in room_lists:
        if keyword and keyword.lower() not in (rl.name or "").lower():
            continue
        try:
            rooms = list(account.protocol.get_rooms(rl.email_address))
        except Exception:
            rooms = []
        if limit:
            rooms = rooms[: max(0, limit - total)]
        room_entries = [{"name": r.name, "email": r.email_address} for r in rooms]
        total += len(room_entries)
        result.append(
            {
                "list_name": rl.name or "",
                "list_email": rl.email_address or "",
                "rooms": room_entries,
            }
        )
        if limit and total >= limit:
            break

    data = {"total_rooms": total, "room_lists": result}

    if output.is_json():
        output.print_json(data)
    else:
        for rl in result:
            output.info(f"  {rl['list_name']} ({len(rl['rooms'])} rooms)")
            for r in rl["rooms"]:
                output.gray(f"    {r['name']} - {r['email']}")


@tools_group.command("rooms-free-busy")
@click.option("--start", required=True, help="Start time YYYY-MM-DD HH:MM")
@click.option("--end", required=True, help="End time YYYY-MM-DD HH:MM")
@click.option("--list-name", default=None, help="Filter by Room List name")
@click.option("--emails", default=None, help="Direct room emails (comma-sep)")
@click.option("--limit", type=int, default=50, help="Max rooms to query (default 50)")
@click.pass_context
def tools_rooms_free_busy(ctx, start, end, list_name, emails, limit):
    """Check room availability for a time period."""
    from ..config import check_permission

    check_permission("tools rooms-free-busy")

    account = get_account()
    tz = get_tz()

    start_dt = datetime.strptime(start, "%Y-%m-%d %H:%M")
    end_dt = datetime.strptime(end, "%Y-%m-%d %H:%M")
    start_local = localize_dt(start_dt, tz)
    end_local = localize_dt(end_dt, tz)

    room_emails = []
    room_names = {}

    if emails:
        for e in emails.split(","):
            e = e.strip()
            if e:
                room_emails.append(e)
                room_names[e] = e
    else:
        try:
            room_lists = list(account.protocol.get_room_lists())
            for rl in room_lists:
                if list_name and list_name.lower() not in (rl.name or "").lower():
                    continue
                try:
                    for r in account.protocol.get_rooms(rl.email_address):
                        room_emails.append(r.email_address)
                        room_names[r.email_address] = r.name or r.email_address
                except Exception:
                    pass
        except Exception as e:
            output.handle_error(
                f"Failed to get room lists: {e}", "SERVER_ERROR", exit_code=7
            )

    if not room_emails:
        output.handle_error(
            "No rooms found. Use --emails to specify directly.",
            "NOT_FOUND",
            exit_code=4,
        )

    if limit and len(room_emails) > limit:
        room_emails = room_emails[:limit]
        room_names = {k: v for k, v in room_names.items() if k in room_emails}

    try:
        from exchangelib.properties import Email

        email_objs = [Email(email_address=e) for e in room_emails]
        results = account.protocol.get_free_busy_info(
            accounts=[(em, "Organizer", False) for em in email_objs],
            start=start_local,
            end=end_local,
        )
    except Exception as e:
        output.handle_error(
            f"Room free/busy query failed: {e}", "SERVER_ERROR", exit_code=7
        )

    available = []
    busy = []
    for email, view in zip(room_emails, results):
        has_conflict = False
        if hasattr(view, "calendar_event_array") and view.calendar_event_array:
            for event in view.calendar_event_array:
                if event.start and event.end:
                    if event.start < end_local and event.end > start_local:
                        has_conflict = True
                        break
        entry = {"name": room_names.get(email, email), "email": email}
        if has_conflict:
            busy.append(entry)
        else:
            available.append(entry)

    data = {
        "period": {"start": start, "end": end},
        "queried": len(room_emails),
        "available_count": len(available),
        "busy_count": len(busy),
        "available": available,
        "busy": busy,
    }

    if output.is_json():
        output.print_json(data)
    else:
        output.info(f"  Queried: {len(room_emails)} rooms")
        output.success(f"  Available ({len(available)}):")
        for r in available[:10]:
            output.info(f"    {r['name']} ({r['email']})")
        if busy:
            output.warn(f"  Busy ({len(busy)}):")
            for r in busy[:5]:
                output.gray(f"    {r['name']}")


# --- OOF (Out of Office) ---


@tools_group.group("oof")
def tools_oof():
    """Out of Office (auto-reply) settings."""
    pass


@tools_oof.command("get")
@click.pass_context
def tools_oof_get(ctx):
    """Get current auto-reply settings."""
    from ..config import check_permission

    check_permission("tools oof get")

    account = get_account()
    try:
        oof = account.oof_settings
    except Exception as e:
        output.handle_error(
            f"Failed to get OOF settings: {e}", "SERVER_ERROR", exit_code=7
        )

    def _reply_text(reply):
        if not reply:
            return ""
        if hasattr(reply, "text"):
            return str(reply.text)
        return str(reply)

    data = {
        "state": str(oof.state),
        "internal_reply": _reply_text(oof.internal_reply),
        "external_reply": _reply_text(oof.external_reply),
        "start": oof.start.strftime("%Y-%m-%d %H:%M") if oof.start else "",
        "end": oof.end.strftime("%Y-%m-%d %H:%M") if oof.end else "",
    }

    if output.is_json():
        output.print_json(data)
    else:
        output.bold(f"  OOF State: {data['state']}")
        if data["internal_reply"]:
            output.info(f"  Internal: {data['internal_reply'][:100]}")
        if data["external_reply"]:
            output.info(f"  External: {data['external_reply'][:100]}")
        if data["start"]:
            output.gray(f"  Period: {data['start']} ~ {data['end']}")


@tools_oof.command("set")
@click.option("--message", required=True, help="Internal auto-reply message")
@click.option(
    "--external-message",
    default=None,
    help="External message (default: same as internal)",
)
@click.option("--start", default=None, help="Start time YYYY-MM-DD HH:MM")
@click.option("--end", default=None, help="End time YYYY-MM-DD HH:MM")
@click.option("--preview", is_flag=True, help="Preview without enabling")
@click.option("--send", "do_send", is_flag=True, help="Confirm enabling auto-reply")
@click.pass_context
def tools_oof_set(ctx, message, external_message, start, end, preview, do_send):
    """Enable auto-reply (Out of Office). Requires --preview or --send."""
    from ..config import check_permission

    check_permission("tools oof set")

    if not preview and not do_send:
        output.handle_error(
            "Enabling auto-reply requires --preview or --send",
            "VALIDATION_ERROR",
            exit_code=2,
        )

    from exchangelib import OofSettings, Body

    account = get_account()
    tz = get_tz()

    oof_kwargs = {
        "state": "Scheduled" if (start and end) else "Enabled",
        "internal_reply": Body(message),
        "external_reply": Body(external_message or message),
    }
    if start and end:
        oof_kwargs["start"] = localize_dt(
            datetime.strptime(start, "%Y-%m-%d %H:%M"), tz
        )
        oof_kwargs["end"] = localize_dt(datetime.strptime(end, "%Y-%m-%d %H:%M"), tz)

    if preview:
        preview_data = {
            "state": oof_kwargs["state"],
            "internal_reply": message[:200],
            "external_reply": (external_message or message)[:200],
            "start": start or "",
            "end": end or "",
        }
        if output.is_json():
            output.print_json({"preview": preview_data, "enabled": False})
        else:
            output.bold("  OOF Preview:")
            output.info(f"  State: {preview_data['state']}")
            output.info(f"  Internal: {preview_data['internal_reply']}")
            if external_message:
                output.info(f"  External: {preview_data['external_reply']}")
            if start:
                output.info(f"  Period: {start} ~ {end}")
        return

    account.oof_settings = OofSettings(**oof_kwargs)

    data = {"message": "Auto-reply enabled"}
    if output.is_json():
        output.print_json(data)
    else:
        output.success(data["message"])


@tools_oof.command("disable")
@click.option("--preview", is_flag=True, help="Preview without disabling")
@click.option("--send", "do_send", is_flag=True, help="Confirm disabling auto-reply")
@click.pass_context
def tools_oof_disable(ctx, preview, do_send):
    """Disable auto-reply (Out of Office). Requires --preview or --send."""
    from ..config import check_permission

    check_permission("tools oof disable")

    if not preview and not do_send:
        output.handle_error(
            "Disabling auto-reply requires --preview or --send",
            "VALIDATION_ERROR",
            exit_code=2,
        )

    if preview:
        if output.is_json():
            output.print_json({"preview": {"action": "disable_oof"}, "disabled": False})
        else:
            output.info("[DRY RUN] Would disable auto-reply")
        return

    from exchangelib import OofSettings

    account = get_account()
    account.oof_settings = OofSettings(state="Disabled")

    data = {"message": "Auto-reply disabled"}
    if output.is_json():
        output.print_json(data)
    else:
        output.success(data["message"])


# --- Meeting Response ---


@tools_group.command("respond")
@click.option("--id", "event_id", default=None, help="Event ID from cal list")
@click.option("--changekey", default="", help="Changekey (improves lookup)")
@click.option(
    "--mail-id", default=None, help="Respond from a meeting invitation mail ID"
)
@click.option(
    "--action",
    "response_action",
    type=click.Choice(["accept", "decline", "tentative"]),
    required=True,
)
@click.option("--message", default=None, help="Optional message")
@click.option("--preview", is_flag=True, help="Preview without responding")
@click.option(
    "--send", "do_send", is_flag=True, help="Confirm response (sends to organizer)"
)
@click.pass_context
def tools_respond(
    ctx, event_id, changekey, mail_id, response_action, message, preview, do_send
):
    """Respond to a meeting invitation (accept/decline/tentative). Requires --preview or --send.

    Use --id with a calendar event ID, or --mail-id with a meeting
    invitation mail ID (e.g. from 'outlook-cli mail list').
    """
    from ..config import check_permission

    check_permission("tools respond")

    if not preview and not do_send:
        output.handle_error(
            "Meeting response requires --preview or --send (response will be sent to organizer)",
            "VALIDATION_ERROR",
            exit_code=2,
        )

    if not event_id and not mail_id:
        output.handle_error(
            "Provide --id (event ID) or --mail-id (invitation mail ID)",
            "VALIDATION_ERROR",
            exit_code=2,
        )

    account = get_account()

    target = None

    # --- Path 1: respond from mail ID (meeting invitation) ---
    if mail_id:
        from ..exchange import find_mail_by_id

        mail_item = find_mail_by_id(account, mail_id)
        if not mail_item:
            output.handle_error(f"Mail not found: {mail_id}", "NOT_FOUND", exit_code=4)

        from exchangelib import MeetingRequest

        if not isinstance(mail_item, MeetingRequest):
            output.handle_error(
                "This email is not a meeting invitation. Use --id to specify a calendar event ID",
                "VALIDATION_ERROR",
                exit_code=2,
            )

        try:
            cal_item = mail_item._get_meeting_item()
            if cal_item:
                target = cal_item
        except Exception:
            pass

        if not target:
            try:
                subject = mail_item.subject or ""
                for prefix in ["Accepted:", "Declined:", "Tentative:", "FW:", "Fwd:"]:
                    if subject.lower().startswith(prefix.lower()):
                        subject = subject[len(prefix) :].strip()
                        break

                now = datetime.now(timezone.utc)
                for item in account.calendar.view(
                    start=now - timedelta(days=30),
                    end=now + timedelta(days=365),
                ):
                    if item.subject and subject.lower() in item.subject.lower():
                        target = item
                        break
            except Exception:
                pass

        if not target:
            output.handle_error(
                "Could not find calendar event from meeting invitation. Use --id to specify",
                "NOT_FOUND",
                exit_code=4,
            )

    # --- Path 2: respond from calendar event ID ---
    else:
        try:
            from exchangelib import ItemId

            try:
                eid = ItemId(id=event_id, changekey=changekey)
                items = list(account.calendar.get_items([eid]))
                if items:
                    target = items[0]
            except Exception:
                pass

            if not target:
                now = datetime.now(timezone.utc)
                start = now - timedelta(days=180)
                end = now + timedelta(days=365)
                for item in account.calendar.view(start=start, end=end):
                    item_id = item.id.id if hasattr(item.id, "id") else str(item.id)
                    if item_id == event_id:
                        target = item
                        break
        except Exception as e:
            output.handle_error(
                f"Failed to find event: {e}", "SERVER_ERROR", exit_code=7
            )

        if not target:
            output.handle_error(
                f"Event not found: {event_id}", "NOT_FOUND", exit_code=4
            )

    if preview:
        action_labels = {
            "accept": "Accept",
            "decline": "Decline",
            "tentative": "Tentative",
        }
        preview_data = {
            "action": action_labels[response_action],
            "subject": target.subject,
            "message": message or "",
            "source": "mail" if mail_id else "calendar",
        }
        if output.is_json():
            output.print_json({"preview": preview_data, "responded": False})
        else:
            output.bold("  Response preview:")
            output.info(f"  Action: {preview_data['action']}")
            output.info(f"  Meeting: {preview_data['subject']}")
            if message:
                output.info(f"  Message: {message}")
        return

    action_map = {
        "accept": target.accept,
        "decline": target.decline,
        "tentative": target.tentatively_accept,
    }
    fn = action_map[response_action]
    if message:
        fn(message=message, send_response=True)
    else:
        fn(send_response=True)

    action_labels = {
        "accept": "Accepted",
        "decline": "Declined",
        "tentative": "Tentatively accepted",
    }
    data = {
        "message": f"{action_labels[response_action]} meeting",
        "subject": target.subject,
        "source": "mail" if mail_id else "calendar",
    }

    if output.is_json():
        output.print_json(data)
    else:
        output.success(data["message"])
