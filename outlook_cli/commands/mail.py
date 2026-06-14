"""Mail commands: list, search, read, send, reply, forward, delete, move,
mark, flag, batch, categorize, restore, stats, thread, attachment-summary,
export, download-attachment, drafts, draft-read, draft-edit, draft-send,
draft-delete."""

import os
from datetime import datetime, timedelta, timezone

import click

from .. import output
from ..exchange import (
    email_to_dict,
    find_mail_by_id,
    get_account,
    resolve_folder,
    safe_filename,
)
from ..timeutil import iso_utc, item_version


@click.group()
def mail_group():
    """Email operations."""
    pass


# --- Helper: build full command path from Click context ---


def _cmd_path(ctx):
    """Build full command path string from Click context."""
    parts = []
    p = ctx
    while p:
        if p.info_name:
            parts.append(p.info_name)
        p = p.parent
    return " ".join(reversed(parts))


def _item_id(item):
    """Get Exchange ItemId string from an item."""
    if hasattr(item, "id") and item.id:
        if hasattr(item.id, "id"):
            return item.id.id
        return str(item.id)
    return ""


def _send_reply_with_attachments(account, reply, attachments) -> None:
    """Send a reply/reply-all that carries extra file attachments.

    A ReplyToItem/ReplyAllToItem has no .attach(), so we persist it to drafts to
    materialize a real Message (which keeps the reference_item_id threading and
    the recipients create_reply already resolved), re-fetch it, attach the extra
    files, then send. Only the extra attachments differ from the plain reply.
    """
    from exchangelib import FileAttachment

    save_result = reply.save(account.drafts)
    draft = account.drafts.get(id=save_result.id, changekey=save_result.changekey)
    for att_path in attachments:
        with open(att_path, "rb") as f:
            content = f.read()
        draft.attach(FileAttachment(name=os.path.basename(att_path), content=content))
    draft.send()


def _confirm_item(command: str, item) -> None:
    from ..confirmation import require_confirmed

    require_confirmed(
        command,
        resource_id=_item_id(item),
        resource_version=item_version(item),
    )


# --- Read commands (read-only permission) ---


@mail_group.command("list")
@click.option(
    "--filter",
    "filter_type",
    type=click.Choice(["unread", "recent", "all", "flagged"]),
    default="all",
)
@click.option("--folder", default=None, help="Folder path or alias")
@click.option("--days", default=7, help="Days for 'recent' filter")
@click.option("--start", default=None, help="Start date YYYY-MM-DD")
@click.option("--end", default=None, help="End date YYYY-MM-DD")
@click.option("--limit", default=20, help="Max results")
@click.option("--offset", default=0, help="Pagination offset")
@click.pass_context
def mail_list(ctx, filter_type, folder, days, start, end, limit, offset):
    """List emails in a folder."""
    from ..config import check_permission

    check_permission("mail list")

    account = get_account()
    target = resolve_folder(account, folder) if folder else account.inbox

    if filter_type == "unread":
        qs = target.filter(is_read=False)
    elif filter_type == "recent":
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        qs = target.filter(datetime_received__gt=cutoff)
    elif filter_type == "flagged":
        qs = target.filter(flag__flag_status="Flagged")
    else:
        qs = target.all()

    if start:
        start_dt = datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        qs = qs.filter(datetime_received__gt=start_dt)
    if end:
        end_dt = datetime.strptime(end, "%Y-%m-%d").replace(tzinfo=timezone.utc) + timedelta(days=1)
        qs = qs.filter(datetime_received__lt=end_dt)

    qs = qs.order_by("-datetime_received")

    total = qs.count()
    items = list(qs[offset : offset + limit + 1])
    has_more = len(items) > limit
    items = items[:limit]

    emails = [email_to_dict(m) for m in items]
    data = {
        "count": len(emails),
        "total": total,
        "offset": offset,
        "has_more": has_more,
        "next_offset": offset + limit if has_more else None,
        "folder": str(folder) if folder else "inbox",
        "emails": emails,
    }

    if output.is_json():
        output.print_json(data)
    else:
        for e in emails:
            read_mark = " " if e["is_read"] else "*"
            short_id = e["id"][:12] + "..." if len(e["id"]) > 12 else e["id"]
            output.info(f"[{read_mark}] {short_id}  {e['date']}  {e['sender']}  {e['subject']}")
        output.info(f"--- {len(emails)} / {total} total ---")


@mail_group.command("search")
@click.option("--subject", default=None)
@click.option("--sender", default=None)
@click.option("--to", "to_addr", default=None)
@click.option("--cc", default=None)
@click.option("--keyword", default=None)
@click.option("--attachment-name", default=None)
@click.option("--has-attachments", is_flag=True)
@click.option("--is-flagged", is_flag=True)
@click.option("--days", default=None, type=int)
@click.option("--start", default=None)
@click.option("--end", default=None)
@click.option("--folder", default=None)
@click.option("--all-folders", is_flag=True)
@click.option("--limit", default=20)
@click.option("--offset", default=0)
@click.pass_context
def mail_search(
    ctx,
    subject,
    sender,
    to_addr,
    cc,
    keyword,
    attachment_name,
    has_attachments,
    is_flagged,
    days,
    start,
    end,
    folder,
    all_folders,
    limit,
    offset,
):
    """Search emails by various criteria."""
    from ..config import check_permission

    check_permission("mail search")

    account = get_account()

    if all_folders:
        target = account.inbox.parent
    elif folder:
        target = resolve_folder(account, folder)
    else:
        target = account.inbox

    qs = target.all()

    if subject:
        qs = qs.filter(subject__contains=subject)
    if keyword:
        qs = qs.filter(body__contains=keyword)
    if has_attachments:
        qs = qs.filter(has_attachments=True)
    if is_flagged:
        try:
            from exchangelib import Flag as FlagProp
        except ImportError:
            from exchangelib.extended_properties import Flag as FlagProp
        from exchangelib.items.message import Message as _Msg

        if not any(f.name == "flag" for f in _Msg.FIELDS):
            _Msg.register("flag", FlagProp)
        qs = qs.filter(flag=2)
    if days:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        qs = qs.filter(datetime_received__gt=cutoff)
    if start:
        start_dt = datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        qs = qs.filter(datetime_received__gt=start_dt)
    if end:
        end_dt = datetime.strptime(end, "%Y-%m-%d").replace(tzinfo=timezone.utc) + timedelta(days=1)
        qs = qs.filter(datetime_received__lt=end_dt)
    if to_addr:
        qs = qs.filter(to_recipients__contains=to_addr)
    if cc:
        qs = qs.filter(cc_recipients__contains=cc)
    if sender:
        # Server-side sender match so total/has_more/next_offset stay accurate
        # for large result sets. icontains is a case-insensitive substring over
        # the indexed sender mailbox (name + email_address), matching the intent
        # of the old client-side filter without bounding it to a fetch window.
        qs = qs.filter(sender__icontains=sender)

    qs = qs.order_by("-datetime_received")

    total = qs.count()
    raw = list(qs[offset : offset + limit + 1])
    has_more = len(raw) > limit
    page = raw[:limit]

    emails = [email_to_dict(m) for m in page]
    data = {
        "count": len(emails),
        "total": total,
        "offset": offset,
        "has_more": has_more,
        "next_offset": offset + limit if has_more else None,
        "emails": emails,
    }

    if output.is_json():
        output.print_json(data)
    else:
        for e in emails:
            read_mark = " " if e["is_read"] else "*"
            short_id = e["id"][:12] + "..." if len(e["id"]) > 12 else e["id"]
            output.info(f"[{read_mark}] {short_id}  {e['date']}  {e['sender']}  {e['subject']}")
        output.info(f"--- {len(emails)} / {total} results ---")


@mail_group.command("read")
@click.option("--id", "mail_id", required=True, help="Mail ID from list/search")
@click.option("--mark-read", is_flag=True, help="Mark as read after reading")
@click.pass_context
def mail_read(ctx, mail_id, mark_read):
    """Read full email content."""
    from ..config import check_permission

    check_permission("mail read")
    if mark_read:
        output.handle_error(
            "mail read is non-mutating; use 'mail mark --status read' with dry-run/confirm",
            "E_VALIDATION",
        )

    account = get_account()
    item = find_mail_by_id(account, mail_id)
    if not item:
        output.handle_error(f"Mail not found: {mail_id}", "NOT_FOUND", exit_code=4)

    attachments = []
    inline_images = []
    for att in item.attachments or []:
        # cid-referenced inline images are surfaced separately so an agent knows
        # the body's `cid:` links resolve to real content; they stay out of the
        # regular attachments list to mirror how mail clients hide them.
        if getattr(att, "is_inline", False) and getattr(att, "content_id", None):
            inline_images.append(
                {
                    "cid": att.content_id,
                    "filename": att.name,
                    "content_type": att.content_type,
                    "size": att.size,
                }
            )
            continue
        attachments.append(
            {
                "name": att.name,
                "size": att.size,
                "content_type": att.content_type,
            }
        )

    data = {
        "id": _item_id(item),
        "subject": item.subject or "",
        "sender": item.sender.email_address if item.sender else "",
        "to": [m.email_address for m in (item.to_recipients or [])],
        "cc": [m.email_address for m in (item.cc_recipients or [])],
        "date": iso_utc(item.datetime_received),
        "is_read": bool(item.is_read),
        "has_attachments": bool(item.has_attachments),
        "body": item.text_body or "",
        "attachments": attachments,
        "inline_images": inline_images,
        "_untrusted": [
            "subject",
            "sender",
            "to",
            "cc",
            "body",
            "attachments.name",
            "inline_images.filename",
            "inline_images.cid",
        ],
    }

    if output.is_json():
        output.print_json(data)
    else:
        output.bold(f"  Subject: {data['subject']}")
        output.info(f"  From: {data['sender']}")
        output.info(f"  To: {', '.join(data['to'])}")
        if data["cc"]:
            output.info(f"  CC: {', '.join(data['cc'])}")
        output.info(f"  Date: {data['date']}")
        output.gray("  " + "─" * 50)
        print(data["body"])


@mail_group.command("stats")
@click.option("--folder", default=None)
@click.option("--days", default=7)
@click.option("--start", default=None)
@click.option("--end", default=None)
@click.option("--top", default=10)
@click.pass_context
def mail_stats(ctx, folder, days, start, end, top):
    """Email statistics (top senders, daily distribution)."""
    from ..config import check_permission

    check_permission("mail stats")

    account = get_account()
    target = resolve_folder(account, folder) if folder else account.inbox

    if start:
        start_dt = datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    else:
        start_dt = datetime.now(timezone.utc) - timedelta(days=days)

    if end:
        end_dt = datetime.strptime(end, "%Y-%m-%d").replace(tzinfo=timezone.utc) + timedelta(days=1)
    else:
        end_dt = datetime.now(timezone.utc)

    qs = target.filter(datetime_received__gt=start_dt, datetime_received__lt=end_dt)

    sender_count = {}
    day_count = {}
    total = 0
    unread = 0
    with_att = 0

    for item in qs:
        total += 1
        if not item.is_read:
            unread += 1
        if item.attachments:
            with_att += 1
        sender = item.sender.email_address if item.sender else "unknown"
        sender_count[sender] = sender_count.get(sender, 0) + 1
        if item.datetime_received:
            day = item.datetime_received.strftime("%Y-%m-%d")
            day_count[day] = day_count.get(day, 0) + 1

    top_senders = sorted(sender_count.items(), key=lambda x: -x[1])[:top]
    by_day = sorted(day_count.items())

    data = {
        "period": {
            "start": iso_utc(start_dt),
            "end": iso_utc(end_dt),
        },
        "folder": str(folder) if folder else "inbox",
        "total": total,
        "unread": unread,
        "read": total - unread,
        "with_attachments": with_att,
        "top_senders": [{"sender": s, "count": c} for s, c in top_senders],
        "by_day": [{"date": d, "count": c} for d, c in by_day],
        "_untrusted": ["top_senders.sender"],
    }

    if output.is_json():
        output.print_json(data)
    else:
        output.bold(
            f"  Stats for {data['folder']} ({data['period']['start']} ~ {data['period']['end']})"
        )
        output.info(f"  Total: {total}, Unread: {unread}, Attachments: {with_att}")
        output.gray("  Top senders:")
        for s in data["top_senders"]:
            output.info(f"    {s['sender']}: {s['count']}")


@mail_group.command("thread")
@click.option("--id", "mail_id", required=True)
@click.option("--days", default=90)
@click.pass_context
def mail_thread(ctx, mail_id, days):
    """Conversation view - group emails by subject."""
    from ..config import check_permission

    check_permission("mail thread")

    account = get_account()
    item = find_mail_by_id(account, mail_id)
    if not item:
        output.handle_error(f"Mail not found: {mail_id}", "NOT_FOUND", exit_code=4)

    subject = item.subject or ""
    clean = subject
    for prefix in ("Re: ", "RE: ", "Fwd: ", "FWD: ", "Fw: ", "FW: "):
        while clean.lower().startswith(prefix.lower()):
            clean = clean[len(prefix) :]

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    qs = account.inbox.filter(
        subject__contains=clean.strip(),
        datetime_received__gt=cutoff,
    ).order_by("datetime_received")

    thread = [email_to_dict(m) for m in qs]

    data = {"subject": clean.strip(), "count": len(thread), "thread": thread}

    if output.is_json():
        output.print_json(data)
    else:
        output.bold(f"  Thread: {clean.strip()} ({len(thread)} messages)")
        for m in thread:
            read_mark = " " if m["is_read"] else "*"
            output.info(f"  [{read_mark}] {m['date']}  {m['sender']}")


@mail_group.command("attachment-summary")
@click.option("--folder", default=None)
@click.option("--days", default=7)
@click.option("--ext", default=None, help="Filter by extensions (comma-sep, e.g. pdf,xlsx)")
@click.option("--limit", default=50)
@click.option("--offset", default=0)
@click.pass_context
def mail_attachment_summary(ctx, folder, days, ext, limit, offset):
    """List attachments across emails."""
    from ..config import check_permission

    check_permission("mail attachment-summary")

    account = get_account()
    target = resolve_folder(account, folder) if folder else account.inbox
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    qs = target.filter(has_attachments=True, datetime_received__gt=cutoff)
    qs = qs.order_by("-datetime_received")

    ext_filter = None
    if ext:
        ext_filter = {e.strip().lower().lstrip(".") for e in ext.split(",")}

    results = []
    for item in qs:
        atts = []
        for att in item.attachments or []:
            name = att.name or ""
            if ext_filter:
                att_ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
                if att_ext not in ext_filter:
                    continue
            atts.append(
                {
                    "name": name,
                    "size_kb": round((att.size or 0) / 1024, 1),
                    "content_type": att.content_type or "",
                }
            )
        if atts:
            results.append(
                {
                    "id": _item_id(item),
                    "subject": item.subject or "",
                    "sender": item.sender.email_address if item.sender else "",
                    "date": iso_utc(item.datetime_received),
                    "attachments": atts,
                    "_untrusted": [
                        "subject",
                        "sender",
                        "attachments.name",
                    ],
                }
            )

    total = len(results)
    page = results[offset : offset + limit]
    has_more = offset + limit < total

    data = {
        "count": len(page),
        "total": total,
        "offset": offset,
        "has_more": has_more,
        "next_offset": offset + limit if has_more else None,
        "emails": page,
    }

    if output.is_json():
        output.print_json(data)
    else:
        for e in page:
            output.info(f"  {e['subject']} ({e['sender']})")
            for a in e["attachments"]:
                output.gray(f"    - {a['name']} ({a['size_kb']} KB)")


@mail_group.command("export")
@click.option("--id", "mail_id", required=True)
@click.option("--output-dir", "output_path", default=".", help="Output directory")
@click.pass_context
def mail_export(ctx, mail_id, output_path):
    """Export email as .eml file."""
    from ..config import check_permission

    check_permission("mail export")

    account = get_account()
    item = find_mail_by_id(account, mail_id)
    if not item:
        output.handle_error(f"Mail not found: {mail_id}", "NOT_FOUND", exit_code=4)

    if not item.mime_content:
        output.handle_error(
            "Email does not have MIME content available",
            "VALIDATION_ERROR",
            exit_code=2,
        )

    subject = safe_filename(item.subject or "email")
    fname = f"{subject}.eml"
    fpath = os.path.join(output_path, fname)

    if ctx.obj.get("dry_run"):
        output.dry_run_output(
            "Export email",
            {"id": mail_id, "subject": item.subject, "path": os.path.abspath(fpath)},
            resource_id=_item_id(item),
            resource_version=item_version(item),
        )
        return

    _confirm_item("mail export", item)

    with open(fpath, "wb") as f:
        f.write(item.mime_content)

    data = {
        "message": "Exported",
        "path": os.path.abspath(fpath),
        "size": os.path.getsize(fpath),
    }

    if output.is_json():
        output.print_json(data)
    else:
        output.success(f"Exported to {fpath}")


@mail_group.command("download-attachment")
@click.option("--id", "mail_id", required=True)
@click.option("--name", default=None, help="Attachment name (empty = all)")
@click.option("--output-dir", "output_path", default=".", help="Output directory")
@click.pass_context
def mail_download_attachment(ctx, mail_id, name, output_path):
    """Download email attachments."""
    from ..config import check_permission

    check_permission("mail download-attachment")

    account = get_account()
    item = find_mail_by_id(account, mail_id)
    if not item:
        output.handle_error(f"Mail not found: {mail_id}", "NOT_FOUND", exit_code=4)

    if not ctx.obj.get("dry_run"):
        _confirm_item("mail download-attachment", item)

    files = []
    planned = []
    for att in item.attachments or []:
        if name and att.name != name:
            continue
        fname = safe_filename(att.name or "attachment")
        # Deduplicate filenames
        fpath = os.path.join(output_path, fname)
        if os.path.exists(fpath):
            base, ext = os.path.splitext(fname)
            fpath = os.path.join(output_path, f"{base}_{len(files)}{ext}")
        if ctx.obj.get("dry_run"):
            planned.append({"name": att.name, "path": os.path.abspath(fpath)})
            continue
        with open(fpath, "wb") as f:
            f.write(att.content)
        files.append(
            {
                "name": att.name,
                "saved_as": os.path.basename(fpath),
                "path": os.path.abspath(fpath),
                "size": att.size or 0,
            }
        )

    if ctx.obj.get("dry_run"):
        output.dry_run_output(
            "Download attachments",
            {"id": mail_id, "files": planned},
            resource_id=_item_id(item),
            resource_version=item_version(item),
        )
        return

    data = {"message": f"Downloaded {len(files)} attachment(s)", "files": files}

    if output.is_json():
        output.print_json(data)
    else:
        for f in files:
            output.success(f"  {f['name']} -> {f['path']}")


# --- Write commands (write permission) ---


@mail_group.command("move")
@click.option("--id", "mail_id", required=True)
@click.option("--folder", required=True, help="Target folder path")
@click.pass_context
def mail_move(ctx, mail_id, folder):
    """Move email to a folder."""
    from ..config import check_permission

    check_permission("mail move")

    account = get_account()
    item = find_mail_by_id(account, mail_id)
    if not item:
        output.handle_error(f"Mail not found: {mail_id}", "NOT_FOUND", exit_code=4)

    if ctx.obj.get("dry_run"):
        output.dry_run_output(
            "Move email",
            {"id": mail_id, "subject": item.subject, "target": folder},
            resource_id=_item_id(item),
            resource_version=item_version(item),
        )
        return

    _confirm_item("mail move", item)
    target = resolve_folder(account, folder)
    subject = item.subject
    item.move(target)

    data = {"message": f"Moved to {folder}", "subject": subject}
    if output.is_json():
        output.print_json(data)
    else:
        output.success(data["message"])


@mail_group.command("mark")
@click.option("--id", "mail_id", required=True)
@click.option("--status", "mark_status", type=click.Choice(["read", "unread"]), required=True)
@click.pass_context
def mail_mark(ctx, mail_id, mark_status):
    """Mark email as read or unread."""
    from ..config import check_permission

    check_permission("mail mark")

    account = get_account()
    item = find_mail_by_id(account, mail_id)
    if not item:
        output.handle_error(f"Mail not found: {mail_id}", "NOT_FOUND", exit_code=4)

    if ctx.obj.get("dry_run"):
        output.dry_run_output(
            "Mark email",
            {"id": mail_id, "status": mark_status},
            resource_id=_item_id(item),
            resource_version=item_version(item),
        )
        return

    _confirm_item("mail mark", item)
    item.is_read = mark_status == "read"
    item.save(update_fields=["is_read"])

    label = "read" if mark_status == "read" else "unread"
    data = {"message": f"Marked as {label}", "subject": item.subject}
    if output.is_json():
        output.print_json(data)
    else:
        output.success(data["message"])


@mail_group.command("flag")
@click.option("--id", "mail_id", required=True)
@click.option(
    "--action",
    "flag_action",
    type=click.Choice(["flag", "unflag", "complete"]),
    required=True,
)
@click.pass_context
def mail_flag(ctx, mail_id, flag_action):
    """Flag, unflag, or complete an email."""
    from ..config import check_permission

    check_permission("mail flag")

    try:
        from exchangelib import Flag as FlagProp
    except ImportError:
        from exchangelib.extended_properties import Flag as FlagProp
    from exchangelib.items.message import Message

    if not any(f.name == "flag" for f in Message.FIELDS):
        Message.register("flag", FlagProp)

    account = get_account()
    item = find_mail_by_id(account, mail_id)
    if not item:
        output.handle_error(f"Mail not found: {mail_id}", "NOT_FOUND", exit_code=4)

    if ctx.obj.get("dry_run"):
        output.dry_run_output(
            "Flag email",
            {"id": mail_id, "action": flag_action},
            resource_id=_item_id(item),
            resource_version=item_version(item),
        )
        return

    _confirm_item("mail flag", item)
    flag_map = {"flag": 2, "complete": 1, "unflag": None}
    item.flag = flag_map.get(flag_action)
    item.save(update_fields=["flag"])

    labels = {"flag": "Flagged", "unflag": "Unflagged", "complete": "Completed"}
    data = {"message": labels[flag_action], "subject": item.subject}
    if output.is_json():
        output.print_json(data)
    else:
        output.success(data["message"])


@mail_group.command("categorize")
@click.option("--id", "mail_id", required=True)
@click.option(
    "--action",
    "cat_action",
    type=click.Choice(["add", "remove", "clear"]),
    required=True,
)
@click.option("--categories", default=None, help="Comma-separated category names")
@click.pass_context
def mail_categorize(ctx, mail_id, cat_action, categories):
    """Add, remove, or clear categories on an email."""
    from ..config import check_permission

    check_permission("mail categorize")

    account = get_account()
    item = find_mail_by_id(account, mail_id)
    if not item:
        output.handle_error(f"Mail not found: {mail_id}", "NOT_FOUND", exit_code=4)

    if ctx.obj.get("dry_run"):
        output.dry_run_output(
            "Categorize email",
            {"id": mail_id, "action": cat_action, "categories": categories},
            resource_id=_item_id(item),
            resource_version=item_version(item),
        )
        return

    _confirm_item("mail categorize", item)
    current = list(item.categories or [])

    if cat_action == "add" and categories:
        for c in categories.split(","):
            c = c.strip()
            if c and c not in current:
                current.append(c)
    elif cat_action == "remove" and categories:
        remove_set = {c.strip() for c in categories.split(",")}
        current = [c for c in current if c not in remove_set]
    elif cat_action == "clear":
        current = []

    item.categories = current
    item.save(update_fields=["categories"])

    data = {
        "message": "Categories updated",
        "subject": item.subject,
        "categories": current,
    }
    if output.is_json():
        output.print_json(data)
    else:
        output.success(f"Categories updated: {', '.join(current) or '(none)'}")


@mail_group.command("restore")
@click.option("--id", "mail_id", required=True)
@click.option("--folder", default=None, help="Restore to folder (default: inbox)")
@click.pass_context
def mail_restore(ctx, mail_id, folder):
    """Restore email from trash."""
    from ..config import check_permission

    check_permission("mail restore")

    account = get_account()
    item = find_mail_by_id(account, mail_id)
    if not item:
        output.handle_error(f"Mail not found: {mail_id}", "NOT_FOUND", exit_code=4)

    if ctx.obj.get("dry_run"):
        output.dry_run_output(
            "Restore email",
            {"id": mail_id, "target": folder or "inbox"},
            resource_id=_item_id(item),
            resource_version=item_version(item),
        )
        return

    _confirm_item("mail restore", item)
    if folder:
        target = resolve_folder(account, folder)
    else:
        target = account.inbox

    subject = item.subject
    item.move(target)

    data = {"message": f"Restored to {folder or 'inbox'}", "subject": subject}
    if output.is_json():
        output.print_json(data)
    else:
        output.success(data["message"])


def _split_ids(raw_values) -> list[str]:
    """Resolve a plural --ids flag into an ordered, de-duplicated id list.

    Accepts both comma-separated (``--ids 1,2,3``) and repeatable
    (``--ids 1 --ids 2``) forms, and mixes of the two. Input order is preserved
    so the agent can zip ``items[]`` back to its inputs (batch contract §15.1).
    """
    seen: set[str] = set()
    ordered: list[str] = []
    for value in raw_values:
        for part in str(value).split(","):
            mid = part.strip()
            if mid and mid not in seen:
                seen.add(mid)
                ordered.append(mid)
    return ordered


def _apply_batch_action(account, item, batch_action, folder, categories):
    """Apply one batch action to one resolved item (single-item logic reuse)."""
    if batch_action == "delete":
        item.move_to_trash()
    elif batch_action == "mark-read":
        item.is_read = True
        item.save(update_fields=["is_read"])
    elif batch_action == "mark-unread":
        item.is_read = False
        item.save(update_fields=["is_read"])
    elif batch_action == "move":
        item.move(resolve_folder(account, folder))
    elif batch_action == "restore":
        item.move(resolve_folder(account, folder) if folder else account.inbox)
    elif batch_action in ("flag", "unflag", "complete"):
        _ensure_flag_field()
        item.flag = {"flag": 2, "complete": 1, "unflag": None}[batch_action]
        item.save(update_fields=["flag"])
    elif batch_action == "categorize":
        _apply_categorize(item, categories)


def _ensure_flag_field() -> None:
    """Register the extended Flag property on Message once (mirrors mail flag)."""
    try:
        from exchangelib import Flag as FlagProp
    except ImportError:
        from exchangelib.extended_properties import Flag as FlagProp
    from exchangelib.items.message import Message

    if not any(f.name == "flag" for f in Message.FIELDS):
        Message.register("flag", FlagProp)


def _apply_categorize(item, categories: str | None) -> None:
    """Add categories on an item (batch categorize is add-only, like a label)."""
    current = list(item.categories or [])
    for c in (categories or "").split(","):
        c = c.strip()
        if c and c not in current:
            current.append(c)
    item.categories = current
    item.save(update_fields=["categories"])


@mail_group.command("batch")
@click.option("--ids", multiple=True, required=True, help="Mail IDs (comma-separated or repeated)")
@click.option(
    "--action",
    "batch_action",
    type=click.Choice(
        [
            "delete",
            "mark-read",
            "mark-unread",
            "move",
            "categorize",
            "flag",
            "unflag",
            "complete",
            "restore",
        ]
    ),
    required=True,
)
@click.option("--folder", default=None, help="Target folder (required for move; optional restore)")
@click.option("--categories", default=None, help="Categories to add (required for categorize)")
@click.option(
    "--continue-on-error/--no-continue-on-error",
    "continue_on_error",
    default=True,
    help="Keep going after an item fails (default: true)",
)
@click.option("--force", is_flag=True, help="Skip confirmation")
@click.pass_context
def mail_batch(ctx, ids, batch_action, folder, categories, continue_on_error, force):
    """Batch operations on multiple emails.

    One command, one confirm token, one aggregated items[]/summary result.
    Per-item failures do not roll back already-applied items.
    """
    from ..config import check_permission, require_dangerous

    # Batch delete is the only irreversible/high-blast batch action — gate it
    # (in both dry-run and confirm steps) behind the --dangerous opt-in. This
    # runs before check_permission so the token isn't validated/consumed first.
    if batch_action == "delete":
        require_dangerous("mail batch")

    check_permission("mail batch")

    id_list = _split_ids(ids)
    if not id_list:
        output.handle_error("No mail IDs provided", "VALIDATION_ERROR", exit_code=2)
    if batch_action == "move" and not folder:
        output.handle_error(
            "--folder is required when --action move",
            "VALIDATION_ERROR",
            exit_code=2,
        )
    if batch_action == "categorize" and not (categories and categories.strip()):
        output.handle_error(
            "--categories is required when --action categorize",
            "VALIDATION_ERROR",
            exit_code=2,
        )

    if batch_action == "delete" and not force:
        if not output.is_json() and not ctx.obj.get("confirm"):
            click.confirm(f"Delete {len(id_list)} email(s)?", abort=True)

    if ctx.obj.get("dry_run"):
        account = get_account()
        targets = []
        for mid in id_list:
            item = find_mail_by_id(account, mid)
            targets.append(
                {
                    "target": mid,
                    "exists": bool(item),
                    "resource_version": item_version(item) if item else "",
                }
            )
        output.dry_run_output(
            "Batch operation",
            {
                "action": batch_action,
                "total": len(id_list),
                "targets": [t["target"] for t in targets],
                "items": targets,
            },
            resource_id=",".join(id_list),
            resource_version=";".join(t["resource_version"] for t in targets),
        )
        return

    from ..confirmation import require_confirmed

    account = get_account()
    preflight = []
    for mid in id_list:
        item = find_mail_by_id(account, mid)
        preflight.append((mid, item, item_version(item) if item else ""))

    require_confirmed(
        "mail batch",
        resource_id=",".join(id_list),
        resource_version=";".join(version for _, _, version in preflight),
    )

    items = []
    stopped = False
    for mid, item, _version in preflight:
        if stopped:
            items.append({"target": mid, "ok": None, "status": "skipped"})
            continue
        if not item:
            items.append(
                {
                    "target": mid,
                    "ok": False,
                    "error": {"code": "E_NOT_FOUND", "retryable": False},
                }
            )
            if not continue_on_error:
                stopped = True
            continue
        try:
            _apply_batch_action(account, item, batch_action, folder, categories)
            items.append({"target": mid, "ok": True})
        except Exception as exc:
            code = output._api_error_code_from_type(exc) or "E_SERVER"
            items.append(
                {
                    "target": mid,
                    "ok": False,
                    "error": {"code": code, "retryable": code in output.RETRYABLE_ERRORS},
                }
            )
            if not continue_on_error:
                stopped = True

    succeeded = sum(1 for i in items if i["ok"] is True)
    failed = sum(1 for i in items if i["ok"] is False)
    skipped = sum(1 for i in items if i["ok"] is None)
    summary = {"total": len(id_list), "succeeded": succeeded, "failed": failed}
    if skipped:
        summary["skipped"] = skipped

    data = {
        "message": f"Batch {batch_action}: {succeeded}/{len(id_list)} succeeded",
        "items": items,
        "summary": summary,
    }

    if output.is_json():
        output.print_json(data)
    else:
        output.success(data["message"])
        failed_ids = [i["target"] for i in items if i["ok"] is False]
        if failed_ids:
            output.warn(f"  Failed IDs: {', '.join(failed_ids)}")


@mail_group.command("delete")
@click.option("--id", "mail_id", required=True)
@click.option("--force", is_flag=True, help="Skip confirmation")
@click.pass_context
def mail_delete(ctx, mail_id, force):
    """Move email to trash (soft delete only)."""
    from ..config import check_permission

    check_permission("mail delete")

    account = get_account()
    item = find_mail_by_id(account, mail_id)
    if not item:
        output.handle_error(f"Mail not found: {mail_id}", "NOT_FOUND", exit_code=4)

    if not force and not output.is_json() and not ctx.obj.get("confirm"):
        click.confirm(f"Delete email '{item.subject}'?", abort=True)

    if ctx.obj.get("dry_run"):
        output.dry_run_output(
            "Delete email",
            {"id": mail_id, "subject": item.subject},
            resource_id=_item_id(item),
            resource_version=item_version(item),
        )
        return

    _confirm_item("mail delete", item)
    subject = item.subject
    item.move_to_trash()

    data = {"message": "Moved to trash", "subject": subject}
    if output.is_json():
        output.print_json(data)
    else:
        output.success(data["message"])


# --- Send commands (full permission, guarded by dry-run/confirm) ---


@mail_group.command("send")
@click.option("--to", "to_addr", required=True, help="Recipient emails (comma-sep)")
@click.option("--cc", default=None)
@click.option("--bcc", default=None, help="BCC recipients (comma-sep)")
@click.option("--subject", required=True)
@click.option("--body", required=True)
@click.option("--html", is_flag=True, help="Body is HTML (default: plain text)")
@click.option("--attachments", multiple=True, help="File paths to attach")
@click.option("--save-draft", is_flag=True, help="Save as draft instead of sending")
@click.pass_context
def mail_send(ctx, to_addr, cc, bcc, subject, body, html, attachments, save_draft):
    """Send an email. Requires dry-run/confirm."""
    from ..config import check_permission

    check_permission("mail send")

    to_list = [a.strip() for a in to_addr.split(",")]
    cc_list = [a.strip() for a in cc.split(",")] if cc else []
    bcc_list = [a.strip() for a in bcc.split(",")] if bcc else []

    preview_data = {
        "to": to_list,
        "cc": cc_list,
        "bcc": bcc_list,
        "subject": subject,
        "body_preview": body[:200] + ("..." if len(body) > 200 else ""),
        "html": html,
        "attachments": list(attachments) if attachments else [],
    }

    if ctx.obj.get("dry_run"):
        output.dry_run_output(
            "Save draft" if save_draft else "Send email",
            preview_data,
            resource_id="new-draft" if save_draft else "new-message",
        )
        return

    from ..confirmation import require_confirmed

    require_confirmed(
        "mail send",
        resource_id="new-draft" if save_draft else "new-message",
    )

    from exchangelib import FileAttachment, HTMLBody, Mailbox, Message

    account = get_account()
    msg_body = HTMLBody(body) if html else body
    msg = Message(
        account=account,
        subject=subject,
        body=msg_body,
        to_recipients=[Mailbox(email_address=a) for a in to_list],
        cc_recipients=[Mailbox(email_address=a) for a in cc_list] if cc_list else None,
        bcc_recipients=[Mailbox(email_address=a) for a in bcc_list] if bcc_list else None,
    )

    for att_path in attachments:
        with open(att_path, "rb") as f:
            content = f.read()
        msg.attach(
            FileAttachment(
                name=os.path.basename(att_path),
                content=content,
            )
        )

    if save_draft:
        msg.folder = account.drafts
        msg.save()
        data = {"message": "Saved to drafts", "to": to_addr, "subject": subject}
    else:
        msg.send()
        data = {
            "message": "Email sent",
            "to": to_addr,
            "subject": subject,
            "sent": True,
        }

    if output.is_json():
        output.print_json(data)
    else:
        output.success(data["message"])


@mail_group.command("reply")
@click.option("--id", "mail_id", required=True)
@click.option("--body", required=True)
@click.option("--html", is_flag=True, help="Body is HTML (default: plain text)")
@click.option("--attachments", multiple=True, help="File paths to attach")
@click.pass_context
def mail_reply(ctx, mail_id, body, html, attachments):
    """Reply to sender. Requires dry-run/confirm."""
    from ..config import check_permission

    check_permission("mail reply")

    account = get_account()
    item = find_mail_by_id(account, mail_id)
    if not item:
        output.handle_error(f"Mail not found: {mail_id}", "NOT_FOUND", exit_code=4)

    if ctx.obj.get("dry_run"):
        output.dry_run_output(
            "Reply to email",
            {
                "id": mail_id,
                "to": item.sender.email_address if item.sender else "",
                "subject": item.subject,
                "body_preview": body[:200],
                "html": html,
                "attachments": list(attachments) if attachments else [],
            },
            resource_id=_item_id(item),
            resource_version=item_version(item),
        )
        return

    _confirm_item("mail reply", item)

    reply_subject = f"Re: {item.subject}" if not item.subject.startswith("Re:") else item.subject

    if attachments:
        from exchangelib import HTMLBody

        # Build the reply through create_reply so threading (reference_item_id)
        # and the original recipients match the no-attachment path. Save to
        # drafts, re-fetch as a Message, attach the extra files, then send —
        # ReplyToItem itself has no .attach(), only a saved draft does.
        msg_body = HTMLBody(body) if html else body
        reply = item.create_reply(reply_subject, msg_body)
        _send_reply_with_attachments(account, reply, attachments)
    else:
        if html:
            from exchangelib import HTMLBody

            item.reply(reply_subject, HTMLBody(body))
        else:
            item.reply(reply_subject, body)

    data = {"message": "Replied", "original_subject": item.subject, "sent": True}
    if output.is_json():
        output.print_json(data)
    else:
        output.success(data["message"])


@mail_group.command("reply-all")
@click.option("--id", "mail_id", required=True)
@click.option("--body", required=True)
@click.option("--html", is_flag=True, help="Body is HTML (default: plain text)")
@click.option("--attachments", multiple=True, help="File paths to attach")
@click.pass_context
def mail_reply_all(ctx, mail_id, body, html, attachments):
    """Reply to all recipients. Requires dry-run/confirm."""
    from ..config import check_permission

    check_permission("mail reply-all")

    account = get_account()
    item = find_mail_by_id(account, mail_id)
    if not item:
        output.handle_error(f"Mail not found: {mail_id}", "NOT_FOUND", exit_code=4)

    if ctx.obj.get("dry_run"):
        all_to = [item.sender.email_address] if item.sender else []
        all_to += [m.email_address for m in (item.to_recipients or [])]
        all_to += [m.email_address for m in (item.cc_recipients or [])]
        output.dry_run_output(
            "Reply all to email",
            {
                "id": mail_id,
                "to": sorted(set(all_to)),
                "subject": item.subject,
                "body_preview": body[:200],
                "html": html,
                "attachments": list(attachments) if attachments else [],
            },
            resource_id=_item_id(item),
            resource_version=item_version(item),
        )
        return

    _confirm_item("mail reply-all", item)

    reply_subject = f"Re: {item.subject}" if not item.subject.startswith("Re:") else item.subject

    if attachments:
        from exchangelib import HTMLBody

        # create_reply_all keeps threading and the sender+to+cc fan-out (minus
        # the current user) identical to the no-attachment path; the saved
        # draft is what carries the extra attachments before send.
        msg_body = HTMLBody(body) if html else body
        reply = item.create_reply_all(reply_subject, msg_body)
        _send_reply_with_attachments(account, reply, attachments)
    else:
        if html:
            from exchangelib import HTMLBody

            item.reply_all(reply_subject, HTMLBody(body))
        else:
            item.reply_all(reply_subject, body)

    data = {"message": "Replied to all", "original_subject": item.subject, "sent": True}
    if output.is_json():
        output.print_json(data)
    else:
        output.success(data["message"])


@mail_group.command("forward")
@click.option("--id", "mail_id", required=True)
@click.option("--to", "to_addr", required=True)
@click.option("--body", default="")
@click.option("--html", is_flag=True, help="Body is HTML (default: plain text)")
@click.option("--attachments", multiple=True, help="Additional file paths to attach")
@click.pass_context
def mail_forward(ctx, mail_id, to_addr, body, html, attachments):
    """Forward email. Requires dry-run/confirm."""
    from ..config import check_permission

    check_permission("mail forward")

    account = get_account()
    item = find_mail_by_id(account, mail_id)
    if not item:
        output.handle_error(f"Mail not found: {mail_id}", "NOT_FOUND", exit_code=4)

    to_list = [a.strip() for a in to_addr.split(",")]

    if ctx.obj.get("dry_run"):
        output.dry_run_output(
            "Forward email",
            {
                "id": mail_id,
                "to": to_list,
                "subject": item.subject,
                "body_preview": body[:200] if body else "",
                "html": html,
                "attachments": list(attachments) if attachments else [],
            },
            resource_id=_item_id(item),
            resource_version=item_version(item),
        )
        return

    _confirm_item("mail forward", item)

    from exchangelib import HTMLBody, Mailbox

    fwd_body = HTMLBody(body) if html else body
    fwd_subject = f"Fwd: {item.subject}"
    fwd_recipients = [Mailbox(email_address=a) for a in to_list]

    if attachments:
        # create_forward carries the original body and attachments server-side
        # (the no-attachment path's item.forward() does the same), so we only
        # add the extra files to the saved draft before sending.
        forward = item.create_forward(
            subject=fwd_subject, body=fwd_body, to_recipients=fwd_recipients
        )
        _send_reply_with_attachments(account, forward, attachments)
    else:
        item.forward(subject=fwd_subject, body=fwd_body, to_recipients=fwd_recipients)

    data = {
        "message": "Forwarded",
        "to": to_addr,
        "original_subject": item.subject,
        "sent": True,
    }
    if output.is_json():
        output.print_json(data)
    else:
        output.success(data["message"])


# --- Draft commands ---


@mail_group.command("drafts")
@click.option("--limit", default=20)
@click.option("--offset", default=0)
@click.pass_context
def mail_drafts(ctx, limit, offset):
    """List draft emails."""
    from ..config import check_permission

    check_permission("mail drafts")

    account = get_account()
    qs = account.drafts.all().order_by("-datetime_received")
    total = qs.count()
    items = list(qs[offset : offset + limit + 1])
    has_more = len(items) > limit
    items = items[:limit]

    drafts = [email_to_dict(m) for m in items]
    data = {
        "count": len(drafts),
        "total": total,
        "offset": offset,
        "has_more": has_more,
        "next_offset": offset + limit if has_more else None,
        "drafts": drafts,
    }

    if output.is_json():
        output.print_json(data)
    else:
        for d in drafts:
            short_id = d["id"][:12] + "..." if len(d["id"]) > 12 else d["id"]
            output.info(
                f"  [{short_id}] {d['subject']} -> {', '.join(d['to']) or '(no recipients)'}"
            )
        output.info(f"  --- {len(drafts)} drafts ---")


@mail_group.command("draft-read")
@click.option("--id", "mail_id", required=True)
@click.pass_context
def mail_draft_read(ctx, mail_id):
    """Read a draft's content."""
    from ..config import check_permission

    check_permission("mail draft-read")

    account = get_account()
    item = find_mail_by_id(account, mail_id)
    if not item:
        output.handle_error(f"Draft not found: {mail_id}", "NOT_FOUND", exit_code=4)

    data = {
        "id": _item_id(item),
        "subject": item.subject or "",
        "to": [m.email_address for m in (item.to_recipients or [])],
        "cc": [m.email_address for m in (item.cc_recipients or [])],
        "bcc": [m.email_address for m in (item.bcc_recipients or [])],
        "body": item.text_body or "",
        "_untrusted": ["subject", "to", "cc", "bcc", "body"],
    }

    if output.is_json():
        output.print_json(data)
    else:
        output.bold(f"  Subject: {data['subject']}")
        output.info(f"  To: {', '.join(data['to'])}")
        output.gray("  " + "─" * 50)
        print(data["body"])


@mail_group.command("draft-edit")
@click.option("--id", "mail_id", required=True)
@click.option("--subject", default=None)
@click.option("--body", default=None)
@click.option("--html", is_flag=True, help="Body is HTML (default: plain text)")
@click.option("--to", "to_addr", default=None)
@click.option("--cc", default=None)
@click.option("--bcc", default=None, help="BCC recipients (comma-sep)")
@click.option("--attachments", multiple=True, help="File paths to attach (appended)")
@click.pass_context
def mail_draft_edit(ctx, mail_id, subject, body, html, to_addr, cc, bcc, attachments):
    """Edit a draft (subject, body, recipients, attachments)."""
    from ..config import check_permission

    check_permission("mail draft-edit")

    account = get_account()
    item = find_mail_by_id(account, mail_id)
    if not item:
        output.handle_error(f"Draft not found: {mail_id}", "NOT_FOUND", exit_code=4)

    if ctx.obj.get("dry_run"):
        output.dry_run_output(
            "Edit draft",
            {
                "id": mail_id,
                "subject": subject,
                "body": body[:100] if body else None,
                "html": html,
                "attachments": list(attachments) if attachments else [],
            },
            resource_id=_item_id(item),
            resource_version=item_version(item),
        )
        return

    _confirm_item("mail draft-edit", item)
    from exchangelib import FileAttachment, HTMLBody, Mailbox

    updated = []
    if subject is not None:
        item.subject = subject
        updated.append("subject")
    if body is not None:
        item.body = HTMLBody(body) if html else body
        updated.append("body")
    if to_addr is not None:
        item.to_recipients = [Mailbox(email_address=a.strip()) for a in to_addr.split(",")]
        updated.append("to")
    if cc is not None:
        item.cc_recipients = [Mailbox(email_address=a.strip()) for a in cc.split(",")]
        updated.append("cc")
    if bcc is not None:
        item.bcc_recipients = [Mailbox(email_address=a.strip()) for a in bcc.split(",")]
        updated.append("bcc")
    for att_path in attachments:
        with open(att_path, "rb") as f:
            content = f.read()
        item.attach(FileAttachment(name=os.path.basename(att_path), content=content))
        updated.append(f"attachment:{os.path.basename(att_path)}")

    if not updated:
        output.handle_error(
            "At least one field to update is required", "VALIDATION_ERROR", exit_code=2
        )

    item.save()
    data = {
        "message": "Draft updated",
        "id": mail_id,
        "subject": item.subject,
        "updated": updated,
    }

    if output.is_json():
        output.print_json(data)
    else:
        output.success(data["message"])


def _send_error_item(target: str, exc: Exception) -> dict:
    """Map a send exception to a contract per-item failure entry."""
    code = output._api_error_code_from_type(exc) or "E_SERVER"
    return {
        "target": target,
        "ok": False,
        "error": {"code": code, "retryable": code in output.RETRYABLE_ERRORS},
    }


def _bulk_send_drafts(account, preflight, continue_on_error) -> list[dict]:
    """Send resolved drafts and aggregate per-item results (contract §15.5).

    ``continue_on_error`` true uses a single native ``bulk_send`` over every
    resolved draft (true server-side batch). False short-circuits on the first
    failure, leaving already-sent drafts sent and the remainder reported as
    skipped, so the agent can resume.
    """
    if continue_on_error:
        existing = [item for _, item, _ in preflight if item]
        results = iter(account.bulk_send(existing) if existing else [])
        items = []
        for did, item, _ in preflight:
            if not item:
                items.append(
                    {
                        "target": did,
                        "ok": False,
                        "error": {"code": "E_NOT_FOUND", "retryable": False},
                    }
                )
                continue
            result = next(results)
            items.append(
                _send_error_item(did, result)
                if isinstance(result, Exception)
                else {"target": did, "ok": True}
            )
        return items

    # Stop-on-first-failure: attempt one at a time so the remainder stays unsent.
    items = []
    stopped = False
    for did, item, _ in preflight:
        if stopped:
            items.append({"target": did, "ok": None, "status": "skipped"})
            continue
        if not item:
            items.append(
                {"target": did, "ok": False, "error": {"code": "E_NOT_FOUND", "retryable": False}}
            )
            stopped = True
            continue
        result = account.bulk_send([item])[0]
        if isinstance(result, Exception):
            items.append(_send_error_item(did, result))
            stopped = True
        else:
            items.append({"target": did, "ok": True})
    return items


@mail_group.command("draft-send")
@click.option("--id", "mail_id", default=None, help="Single draft ID (batch of one)")
@click.option("--ids", multiple=True, help="Draft IDs (comma-separated or repeated)")
@click.option(
    "--continue-on-error/--no-continue-on-error",
    "continue_on_error",
    default=True,
    help="Keep going after an item fails (default: true)",
)
@click.pass_context
def mail_draft_send(ctx, mail_id, ids, continue_on_error):
    """Send one or more drafts. Requires dry-run/confirm.

    Native batch via account.bulk_send; a single --id is a batch of one with the
    same envelope. One confirm token covers the whole batch (contract §15).
    """
    from ..config import check_permission

    check_permission("mail draft-send")

    id_list = _split_ids((*ids, mail_id) if mail_id else ids)
    if not id_list:
        output.handle_error(
            "No draft IDs provided (use --id or --ids)", "VALIDATION_ERROR", exit_code=2
        )

    account = get_account()
    preflight = []
    for did in id_list:
        item = find_mail_by_id(account, did)
        preflight.append((did, item, item_version(item) if item else ""))

    if ctx.obj.get("dry_run"):
        output.dry_run_output(
            "Send drafts",
            {
                "action": "draft-send",
                "total": len(id_list),
                "targets": id_list,
                "items": [
                    {
                        "target": did,
                        "exists": bool(item),
                        "subject": item.subject if item else "",
                    }
                    for did, item, _ in preflight
                ],
            },
            resource_id=",".join(id_list),
            resource_version=";".join(v for _, _, v in preflight),
        )
        return

    from ..confirmation import require_confirmed

    require_confirmed(
        "mail draft-send",
        resource_id=",".join(id_list),
        resource_version=";".join(v for _, _, v in preflight),
    )

    items = _bulk_send_drafts(account, preflight, continue_on_error)

    succeeded = sum(1 for i in items if i["ok"] is True)
    failed = sum(1 for i in items if i["ok"] is False)
    skipped = sum(1 for i in items if i["ok"] is None)
    summary = {"total": len(id_list), "succeeded": succeeded, "failed": failed}
    if skipped:
        summary["skipped"] = skipped

    data = {
        "message": f"Drafts sent: {succeeded}/{len(id_list)} succeeded",
        "items": items,
        "summary": summary,
    }
    if output.is_json():
        output.print_json(data)
    else:
        output.success(data["message"])
        failed_ids = [i["target"] for i in items if i["ok"] is False]
        if failed_ids:
            output.warn(f"  Failed IDs: {', '.join(failed_ids)}")


@mail_group.command("draft-delete")
@click.option("--id", "mail_id", required=True)
@click.option("--force", is_flag=True)
@click.pass_context
def mail_draft_delete(ctx, mail_id, force):
    """Delete a draft."""
    from ..config import check_permission

    check_permission("mail draft-delete")

    account = get_account()
    item = find_mail_by_id(account, mail_id)
    if not item:
        output.handle_error(f"Draft not found: {mail_id}", "NOT_FOUND", exit_code=4)

    if not force and not output.is_json() and not ctx.obj.get("confirm"):
        click.confirm(f"Delete draft '{item.subject}'?", abort=True)

    if ctx.obj.get("dry_run"):
        output.dry_run_output(
            "Delete draft",
            {"id": mail_id, "subject": item.subject},
            resource_id=_item_id(item),
            resource_version=item_version(item),
        )
        return

    _confirm_item("mail draft-delete", item)
    subject = item.subject
    item.move_to_trash()

    data = {"message": "Draft deleted", "subject": subject}
    if output.is_json():
        output.print_json(data)
    else:
        output.success(data["message"])
