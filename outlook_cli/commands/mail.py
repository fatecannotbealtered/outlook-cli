"""Mail commands: list, search, read, send, reply, forward, delete, move,
mark, flag, batch, categorize, restore, stats, thread, attachment-summary,
export, download-attachment, drafts, draft-read, draft-edit, draft-send,
draft-delete."""

import os
from datetime import datetime, timedelta, timezone

import click

from .. import output
from ..exchange import (
    email_to_dict, find_mail_by_id, get_account,
    resolve_folder, safe_filename,
)


@click.group()
def mail_group():
    """Email operations."""
    pass


# --- Read commands (read-only permission) ---

@mail_group.command("list")
@click.option("--filter", "filter_type", type=click.Choice(["unread", "recent", "all", "flagged"]), default="all")
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

    qs = target.all()
    if filter_type == "unread":
        qs = target.filter(is_read=False)
    elif filter_type == "recent":
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        qs = target.filter(datetime_received__gt=cutoff)
    elif filter_type == "flagged":
        qs = target.filter(flag__flag_status="Flagged")

    if start:
        start_dt = datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        qs = qs.filter(datetime_received__gt=start_dt)
    if end:
        end_dt = datetime.strptime(end, "%Y-%m-%d").replace(tzinfo=timezone.utc) + timedelta(days=1)
        qs = qs.filter(datetime_received__lt=end_dt)

    qs = qs.order_by("-datetime_received")

    total = qs.count()
    items = list(qs[offset:offset + limit + 1])
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
            output.info(f"[{read_mark}] {e['date']}  {e['sender']}  {e['subject']}")
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
def mail_search(ctx, subject, sender, to_addr, cc, keyword, attachment_name,
                has_attachments, is_flagged, days, start, end, folder,
                all_folders, limit, offset):
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
        # Register Flag extended property if needed, then filter by value=2 (Flagged)
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

    qs = qs.order_by("-datetime_received")
    total = qs.count()
    items = list(qs[offset:offset + limit + 1])

    # Client-side sender filter (exchangelib Mailbox field paths are unreliable)
    if sender:
        _s = sender.lower()
        items = [m for m in items
                 if _s in (getattr(getattr(m, 'sender', None), 'email_address', '') or '').lower()
                 or _s in (getattr(getattr(m, 'author', None), 'email_address', '') or '').lower()]

    has_more = len(items) > limit
    items = items[:limit]

    emails = [email_to_dict(m) for m in items]
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
            output.info(f"[{read_mark}] {e['date']}  {e['sender']}  {e['subject']}")
        output.info(f"--- {len(emails)} / {total} results ---")


@mail_group.command("read")
@click.option("--id", "mail_id", required=True, help="Mail ID from list/search")
@click.option("--mark-read", is_flag=True, help="Mark as read after reading")
@click.pass_context
def mail_read(ctx, mail_id, mark_read):
    """Read full email content."""
    from ..config import check_permission
    check_permission("mail read")

    account = get_account()
    item = find_mail_by_id(account, mail_id)
    if not item:
        output.handle_error(f"邮件未找到: {mail_id}", "NOT_FOUND", exit_code=4)

    if mark_read and not item.is_read:
        item.is_read = True
        item.save(update_fields=["is_read"])

    attachments = []
    for att in (item.attachments or []):
        attachments.append({
            "name": att.name,
            "size": att.size,
            "content_type": att.content_type,
        })

    data = {
        "id": item.message_id or str(item.id),
        "subject": item.subject or "",
        "sender": item.sender.email_address if item.sender else "",
        "to": [m.email_address for m in (item.to_recipients or [])],
        "cc": [m.email_address for m in (item.cc_recipients or [])],
        "date": item.datetime_received.strftime("%Y-%m-%d %H:%M:%S") if item.datetime_received else "",
        "is_read": bool(item.is_read),
        "has_attachments": bool(item.has_attachments),
        "body": item.text_body or "",
        "attachments": attachments,
    }

    if output.is_json():
        output.print_json(data)
    else:
        output.bold(f"  Subject: {data['subject']}")
        output.info(f"  From: {data['sender']}")
        output.info(f"  To: {', '.join(data['to'])}")
        if data['cc']:
            output.info(f"  CC: {', '.join(data['cc'])}")
        output.info(f"  Date: {data['date']}")
        output.gray("  " + "─" * 50)
        print(data['body'])


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
        "period": {"start": start_dt.strftime("%Y-%m-%d"), "end": end_dt.strftime("%Y-%m-%d")},
        "folder": str(folder) if folder else "inbox",
        "total": total, "unread": unread,
        "read": total - unread, "with_attachments": with_att,
        "top_senders": [{"sender": s, "count": c} for s, c in top_senders],
        "by_day": [{"date": d, "count": c} for d, c in by_day],
    }

    if output.is_json():
        output.print_json(data)
    else:
        output.bold(f"  Stats for {data['folder']} ({data['period']['start']} ~ {data['period']['end']})")
        output.info(f"  Total: {total}, Unread: {unread}, Attachments: {with_att}")
        output.gray("  Top senders:")
        for s in data["top_senders"]:
            output.info(f"    {s['sender']}: {s['count']}")


@mail_group.command("thread")
@click.option("--id", "mail_id", required=True)
@click.option("--days", default=90)
@click.pass_context
def mail_thread(ctx, mail_id, days):
    """Conversation view — group emails by subject."""
    from ..config import check_permission
    check_permission("mail thread")

    account = get_account()
    item = find_mail_by_id(account, mail_id)
    if not item:
        output.handle_error(f"邮件未找到: {mail_id}", "NOT_FOUND", exit_code=4)

    subject = item.subject or ""
    clean = subject
    for prefix in ("Re: ", "RE: ", "Fwd: ", "FWD: ", "Fw: ", "FW: "):
        while clean.lower().startswith(prefix.lower()):
            clean = clean[len(prefix):]

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
        for att in (item.attachments or []):
            name = att.name or ""
            if ext_filter:
                att_ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
                if att_ext not in ext_filter:
                    continue
            atts.append({
                "name": name,
                "size_kb": round((att.size or 0) / 1024, 1),
                "content_type": att.content_type or "",
            })
        if atts:
            results.append({
                "id": item.message_id or str(item.id),
                "subject": item.subject or "",
                "sender": item.sender.email_address if item.sender else "",
                "date": item.datetime_received.strftime("%Y-%m-%d %H:%M:%S") if item.datetime_received else "",
                "attachments": atts,
            })

    total = len(results)
    page = results[offset:offset + limit]
    has_more = offset + limit < total

    data = {
        "count": len(page), "total": total,
        "offset": offset, "has_more": has_more,
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
        output.handle_error(f"邮件未找到: {mail_id}", "NOT_FOUND", exit_code=4)

    subject = safe_filename(item.subject or "email")
    fname = f"{subject}.eml"
    fpath = os.path.join(output_path, fname)

    with open(fpath, "wb") as f:
        f.write(item.mime_content)

    data = {"message": "已导出", "path": os.path.abspath(fpath), "size": os.path.getsize(fpath)}

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
        output.handle_error(f"邮件未找到: {mail_id}", "NOT_FOUND", exit_code=4)

    files = []
    for att in (item.attachments or []):
        if name and att.name != name:
            continue
        fname = safe_filename(att.name or "attachment")
        fpath = os.path.join(output_path, fname)
        with open(fpath, "wb") as f:
            f.write(att.content)
        files.append({
            "name": att.name,
            "saved_as": fname,
            "path": os.path.abspath(fpath),
            "size": att.size or 0,
        })

    data = {"message": f"已下载 {len(files)} 个附件", "files": files}

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
        output.handle_error(f"邮件未找到: {mail_id}", "NOT_FOUND", exit_code=4)

    target = resolve_folder(account, folder)
    subject = item.subject
    item.move(target)

    data = {"message": f"已移动到 {folder}", "subject": subject}
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
        output.handle_error(f"邮件未找到: {mail_id}", "NOT_FOUND", exit_code=4)

    item.is_read = (mark_status == "read")
    item.save(update_fields=["is_read"])

    label = "已读" if mark_status == "read" else "未读"
    data = {"message": f"已标记为{label}", "subject": item.subject}
    if output.is_json():
        output.print_json(data)
    else:
        output.success(data["message"])


@mail_group.command("flag")
@click.option("--id", "mail_id", required=True)
@click.option("--action", "flag_action", type=click.Choice(["flag", "unflag", "complete"]), required=True)
@click.pass_context
def mail_flag(ctx, mail_id, flag_action):
    """Flag, unflag, or complete an email."""
    from ..config import check_permission
    check_permission("mail flag")

    # Register Flag extended property (exchangelib 5.x: property_tag 0x1090)
    # Values: None=NotFlagged, 1=Complete, 2=Flagged
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
        output.handle_error(f"邮件未找到: {mail_id}", "NOT_FOUND", exit_code=4)

    flag_map = {"flag": 2, "complete": 1, "unflag": None}
    item.flag = flag_map.get(flag_action)
    item.save(update_fields=["flag"])

    labels = {"flag": "已标记", "unflag": "已取消标记", "complete": "已完成"}
    data = {"message": labels[flag_action], "subject": item.subject}
    if output.is_json():
        output.print_json(data)
    else:
        output.success(data["message"])


@mail_group.command("categorize")
@click.option("--id", "mail_id", required=True)
@click.option("--action", "cat_action", type=click.Choice(["add", "remove", "clear"]), required=True)
@click.option("--categories", default=None, help="Comma-separated category names")
@click.pass_context
def mail_categorize(ctx, mail_id, cat_action, categories):
    """Add, remove, or clear categories on an email."""
    from ..config import check_permission
    check_permission("mail categorize")

    account = get_account()
    item = find_mail_by_id(account, mail_id)
    if not item:
        output.handle_error(f"邮件未找到: {mail_id}", "NOT_FOUND", exit_code=4)

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

    data = {"message": "标签已更新", "subject": item.subject, "categories": current}
    if output.is_json():
        output.print_json(data)
    else:
        output.success(f"标签已更新: {', '.join(current) or '(无)'}")


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
        output.handle_error(f"邮件未找到: {mail_id}", "NOT_FOUND", exit_code=4)

    if folder:
        target = resolve_folder(account, folder)
    else:
        target = account.inbox

    subject = item.subject
    item.move(target)

    data = {"message": f"已恢复到 {folder or '收件箱'}", "subject": subject}
    if output.is_json():
        output.print_json(data)
    else:
        output.success(data["message"])


@mail_group.command("batch")
@click.option("--ids", required=True, help="Comma-separated mail IDs")
@click.option("--action", "batch_action", type=click.Choice(["delete", "mark-read", "mark-unread", "move"]), required=True)
@click.option("--folder", default=None, help="Target folder (required for move)")
@click.option("--force", is_flag=True, help="Skip confirmation")
@click.pass_context
def mail_batch(ctx, ids, batch_action, folder, force):
    """Batch operations on multiple emails."""
    from ..config import check_permission
    check_permission("mail batch")

    id_list = [i.strip() for i in ids.split(",") if i.strip()]
    if not id_list:
        output.handle_error("未提供邮件 ID", "VALIDATION_ERROR", exit_code=2)

    if batch_action == "delete" and not force:
        if not output.is_json():
            click.confirm(f"确认删除 {len(id_list)} 封邮件？", abort=True)

    account = get_account()
    success_count = 0
    for mid in id_list:
        item = find_mail_by_id(account, mid)
        if not item:
            continue
        try:
            if batch_action == "delete":
                item.move_to_trash()
            elif batch_action == "mark-read":
                item.is_read = True
                item.save(update_fields=["is_read"])
            elif batch_action == "mark-unread":
                item.is_read = False
                item.save(update_fields=["is_read"])
            elif batch_action == "move" and folder:
                target = resolve_folder(account, folder)
                item.move(target)
            success_count += 1
        except Exception:
            pass

    labels = {"delete": "删除", "mark-read": "标记已读", "mark-unread": "标记未读", "move": "移动"}
    data = {"message": f"已批量{labels[batch_action]} {success_count} 封邮件", "success": success_count, "total": len(id_list)}

    if output.is_json():
        output.print_json(data)
    else:
        output.success(data["message"])


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
        output.handle_error(f"邮件未找到: {mail_id}", "NOT_FOUND", exit_code=4)

    if not force and not output.is_json():
        click.confirm(f"确认删除邮件 '{item.subject}'？", abort=True)

    subject = item.subject
    item.move_to_trash()

    data = {"message": "已移至回收站", "subject": subject}
    if output.is_json():
        output.print_json(data)
    else:
        output.success(data["message"])


# --- Send commands (full permission, requires --preview or --send) ---

def _require_send_flag(preview, do_send):
    """Enforce --preview or --send for send-like commands."""
    if not preview and not do_send:
        output.handle_error(
            "发送类命令需要 --preview（预览）或 --send（确认发送）",
            "VALIDATION_ERROR",
            exit_code=2,
        )


@mail_group.command("send")
@click.option("--to", "to_addr", required=True, help="Recipient emails (comma-sep)")
@click.option("--cc", default=None)
@click.option("--subject", required=True)
@click.option("--body", required=True)
@click.option("--html", is_flag=True, help="Body is HTML (default: plain text)")
@click.option("--attachments", multiple=True, help="File paths to attach")
@click.option("--save-draft", is_flag=True)
@click.option("--preview", is_flag=True, help="Preview without sending")
@click.option("--send", "do_send", is_flag=True, help="Confirm and send")
@click.pass_context
def mail_send(ctx, to_addr, cc, subject, body, html, attachments, save_draft, preview, do_send):
    """Send an email. Requires --preview or --send (unless --save-draft)."""
    from ..config import check_permission
    check_permission("mail send")
    if not save_draft:
        _require_send_flag(preview, do_send)

    to_list = [a.strip() for a in to_addr.split(",")]
    cc_list = [a.strip() for a in cc.split(",")] if cc else []

    preview_data = {
        "to": to_list,
        "cc": cc_list,
        "subject": subject,
        "body_preview": body[:200] + ("..." if len(body) > 200 else ""),
        "html": html,
        "attachments": list(attachments) if attachments else [],
    }

    if preview:
        if output.is_json():
            output.print_json({"preview": preview_data, "sent": False})
        else:
            output.bold("  Preview:")
            output.info(f"  To: {', '.join(to_list)}")
            if cc_list:
                output.info(f"  CC: {', '.join(cc_list)}")
            output.info(f"  Subject: {subject}")
            output.info(f"  Body: {preview_data['body_preview']}")
            if html:
                output.gray("  (HTML format)")
        return

    from exchangelib import Message, Mailbox, FileAttachment, HTMLBody
    account = get_account()
    msg_body = HTMLBody(body) if html else body
    msg = Message(
        account=account,
        subject=subject,
        body=msg_body,
        to_recipients=[Mailbox(email_address=a) for a in to_list],
        cc_recipients=[Mailbox(email_address=a) for a in cc_list] if cc_list else None,
    )

    for att_path in attachments:
        with open(att_path, "rb") as f:
            content = f.read()
        msg.attach(FileAttachment(
            name=os.path.basename(att_path),
            content=content,
        ))

    if save_draft:
        msg.folder = account.drafts
        msg.save()
        data = {"message": "已保存到草稿箱", "to": to_addr, "subject": subject}
    else:
        msg.send()
        data = {"message": "邮件已发送", "to": to_addr, "subject": subject, "sent": True}

    if output.is_json():
        output.print_json(data)
    else:
        output.success(data["message"])


@mail_group.command("reply")
@click.option("--id", "mail_id", required=True)
@click.option("--body", required=True)
@click.option("--html", is_flag=True, help="Body is HTML (default: plain text)")
@click.option("--attachments", multiple=True, help="File paths to attach")
@click.option("--preview", is_flag=True)
@click.option("--send", "do_send", is_flag=True)
@click.pass_context
def mail_reply(ctx, mail_id, body, html, attachments, preview, do_send):
    """Reply to sender. Requires --preview or --send."""
    from ..config import check_permission
    check_permission("mail reply")
    _require_send_flag(preview, do_send)

    account = get_account()
    item = find_mail_by_id(account, mail_id)
    if not item:
        output.handle_error(f"邮件未找到: {mail_id}", "NOT_FOUND", exit_code=4)

    if preview:
        data = {
            "preview": {
                "action": "reply",
                "to": item.sender.email_address if item.sender else "",
                "original_subject": item.subject,
                "body_preview": body[:200],
                "html": html,
                "attachments": list(attachments) if attachments else [],
            },
            "sent": False,
        }
        if output.is_json():
            output.print_json(data)
        else:
            output.bold("  Reply preview:")
            output.info(f"  To: {data['preview']['to']}")
            output.info(f"  Subject: Re: {item.subject}")
        return

    if attachments:
        # exchangelib's item.reply() doesn't support attachments;
        # build a manual reply with threading headers
        from exchangelib import Message, Mailbox, FileAttachment, HTMLBody
        msg_body = HTMLBody(body) if html else body
        msg = Message(
            account=account,
            subject=f"Re: {item.subject}",
            body=msg_body,
            to_recipients=[Mailbox(email_address=item.sender.email_address)],
            in_reply_to=item.message_id,
        )
        for att_path in attachments:
            with open(att_path, "rb") as f:
                content = f.read()
            msg.attachments.append(
                FileAttachment(
                    name=os.path.basename(att_path),
                    content=content,
                )
            )
        msg.send()
    else:
        reply_subject = f"Re: {item.subject}" if not item.subject.startswith("Re:") else item.subject
        if html:
            from exchangelib import HTMLBody
            item.reply(reply_subject, HTMLBody(body))
        else:
            item.reply(reply_subject, body)

    data = {"message": "已回复", "original_subject": item.subject, "sent": True}
    if output.is_json():
        output.print_json(data)
    else:
        output.success(data["message"])


@mail_group.command("reply-all")
@click.option("--id", "mail_id", required=True)
@click.option("--body", required=True)
@click.option("--html", is_flag=True, help="Body is HTML (default: plain text)")
@click.option("--attachments", multiple=True, help="File paths to attach")
@click.option("--preview", is_flag=True)
@click.option("--send", "do_send", is_flag=True)
@click.pass_context
def mail_reply_all(ctx, mail_id, body, html, attachments, preview, do_send):
    """Reply to all recipients. Requires --preview or --send."""
    from ..config import check_permission
    check_permission("mail reply-all")
    _require_send_flag(preview, do_send)

    account = get_account()
    item = find_mail_by_id(account, mail_id)
    if not item:
        output.handle_error(f"邮件未找到: {mail_id}", "NOT_FOUND", exit_code=4)

    if preview:
        all_to = [item.sender.email_address] if item.sender else []
        all_to += [m.email_address for m in (item.to_recipients or [])]
        all_to += [m.email_address for m in (item.cc_recipients or [])]
        data = {
            "preview": {
                "action": "reply-all",
                "to": list(set(all_to)),
                "original_subject": item.subject,
                "body_preview": body[:200],
                "html": html,
                "attachments": list(attachments) if attachments else [],
            },
            "sent": False,
        }
        if output.is_json():
            output.print_json(data)
        else:
            output.bold("  Reply-all preview:")
            output.info(f"  To: {', '.join(set(all_to))}")
            output.info(f"  Subject: Re: {item.subject}")
        return

    if attachments:
        # exchangelib's item.reply_all() doesn't support attachments;
        # build a manual reply with threading headers
        from exchangelib import Message, Mailbox, FileAttachment, HTMLBody
        msg_body = HTMLBody(body) if html else body
        all_recipients = []
        if item.sender:
            all_recipients.append(Mailbox(email_address=item.sender.email_address))
        for m in (item.to_recipients or []):
            all_recipients.append(Mailbox(email_address=m.email_address))
        for m in (item.cc_recipients or []):
            all_recipients.append(Mailbox(email_address=m.email_address))
        msg = Message(
            account=account,
            subject=f"Re: {item.subject}",
            body=msg_body,
            to_recipients=list(set(all_recipients)),
            in_reply_to=item.message_id,
        )
        for att_path in attachments:
            with open(att_path, "rb") as f:
                content = f.read()
            msg.attachments.append(
                FileAttachment(
                    name=os.path.basename(att_path),
                    content=content,
                )
            )
        msg.send()
    else:
        reply_subject = f"Re: {item.subject}" if not item.subject.startswith("Re:") else item.subject
        if html:
            from exchangelib import HTMLBody
            item.reply_all(reply_subject, HTMLBody(body))
        else:
            item.reply_all(reply_subject, body)

    data = {"message": "已回复全部", "original_subject": item.subject, "sent": True}
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
@click.option("--preview", is_flag=True)
@click.option("--send", "do_send", is_flag=True)
@click.pass_context
def mail_forward(ctx, mail_id, to_addr, body, html, attachments, preview, do_send):
    """Forward email. Requires --preview or --send."""
    from ..config import check_permission
    check_permission("mail forward")
    _require_send_flag(preview, do_send)

    account = get_account()
    item = find_mail_by_id(account, mail_id)
    if not item:
        output.handle_error(f"邮件未找到: {mail_id}", "NOT_FOUND", exit_code=4)

    to_list = [a.strip() for a in to_addr.split(",")]

    if preview:
        data = {
            "preview": {
                "action": "forward",
                "to": to_list,
                "original_subject": item.subject,
                "body_preview": body[:200] if body else "",
                "html": html,
                "attachments": list(attachments) if attachments else [],
            },
            "sent": False,
        }
        if output.is_json():
            output.print_json(data)
        else:
            output.bold("  Forward preview:")
            output.info(f"  To: {', '.join(to_list)}")
            output.info(f"  Subject: Fwd: {item.subject}")
        return

    from exchangelib import Mailbox, FileAttachment, HTMLBody

    fwd_body = HTMLBody(body) if html else body
    fwd_subject = f"Fwd: {item.subject}"
    fwd_recipients = [Mailbox(email_address=a) for a in to_list]

    if attachments:
        # Build manual forward with attachments (exchangelib 5.x forward() has no attachments param)
        from exchangelib import Message
        original_body = item.text_body or ""
        combined = f"{body}\n\n---------- Forwarded message ----------\nFrom: {item.sender.email_address if item.sender else ''}\nSubject: {item.subject}\n\n{original_body}"
        msg_body = HTMLBody(combined) if html else combined
        msg = Message(
            account=account,
            subject=fwd_subject,
            body=msg_body,
            to_recipients=fwd_recipients,
        )
        for att_path in attachments:
            with open(att_path, "rb") as f:
                content = f.read()
            msg.attachments.append(
                FileAttachment(name=os.path.basename(att_path), content=content)
            )
        # Attach original attachments too
        for orig_att in (item.attachments or []):
            msg.attachments.append(orig_att)
        msg.send()
    else:
        item.forward(subject=fwd_subject, body=fwd_body, to_recipients=fwd_recipients)

    data = {"message": "已转发", "to": to_addr, "original_subject": item.subject, "sent": True}
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
    items = list(qs[offset:offset + limit + 1])
    has_more = len(items) > limit
    items = items[:limit]

    drafts = [email_to_dict(m) for m in items]
    data = {
        "count": len(drafts), "total": total,
        "offset": offset, "has_more": has_more,
        "next_offset": offset + limit if has_more else None,
        "drafts": drafts,
    }

    if output.is_json():
        output.print_json(data)
    else:
        for d in drafts:
            output.info(f"  {d['subject']} -> {', '.join(d['to']) or '(no recipients)'}")
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
        output.handle_error(f"草稿未找到: {mail_id}", "NOT_FOUND", exit_code=4)

    data = {
        "id": item.message_id or str(item.id),
        "subject": item.subject or "",
        "to": [m.email_address for m in (item.to_recipients or [])],
        "cc": [m.email_address for m in (item.cc_recipients or [])],
        "body": item.text_body or "",
    }

    if output.is_json():
        output.print_json(data)
    else:
        output.bold(f"  Subject: {data['subject']}")
        output.info(f"  To: {', '.join(data['to'])}")
        output.gray("  " + "─" * 50)
        print(data['body'])


@mail_group.command("draft-edit")
@click.option("--id", "mail_id", required=True)
@click.option("--subject", default=None)
@click.option("--body", default=None)
@click.option("--to", "to_addr", default=None)
@click.option("--cc", default=None)
@click.pass_context
def mail_draft_edit(ctx, mail_id, subject, body, to_addr, cc):
    """Edit a draft (subject, body, recipients)."""
    from ..config import check_permission
    check_permission("mail draft-edit")

    account = get_account()
    item = find_mail_by_id(account, mail_id)
    if not item:
        output.handle_error(f"草稿未找到: {mail_id}", "NOT_FOUND", exit_code=4)

    from exchangelib import Mailbox
    updated = []
    if subject is not None:
        item.subject = subject
        updated.append("subject")
    if body is not None:
        item.body = body
        updated.append("body")
    if to_addr is not None:
        item.to_recipients = [Mailbox(email_address=a.strip()) for a in to_addr.split(",")]
        updated.append("to")
    if cc is not None:
        item.cc_recipients = [Mailbox(email_address=a.strip()) for a in cc.split(",")]
        updated.append("cc")

    if not updated:
        output.handle_error("至少需要指定一个修改字段", "VALIDATION_ERROR", exit_code=2)

    item.save()
    data = {"message": "草稿已更新", "id": mail_id, "subject": item.subject, "updated": updated}

    if output.is_json():
        output.print_json(data)
    else:
        output.success(data["message"])


@mail_group.command("draft-send")
@click.option("--id", "mail_id", required=True)
@click.option("--preview", is_flag=True)
@click.option("--send", "do_send", is_flag=True)
@click.pass_context
def mail_draft_send(ctx, mail_id, preview, do_send):
    """Send a draft. Requires --preview or --send."""
    from ..config import check_permission
    check_permission("mail draft-send")
    _require_send_flag(preview, do_send)

    account = get_account()
    item = find_mail_by_id(account, mail_id)
    if not item:
        output.handle_error(f"草稿未找到: {mail_id}", "NOT_FOUND", exit_code=4)

    if preview:
        data = {
            "preview": {
                "subject": item.subject,
                "to": [m.email_address for m in (item.to_recipients or [])],
            },
            "sent": False,
        }
        if output.is_json():
            output.print_json(data)
        else:
            output.bold("  Draft preview:")
            output.info(f"  Subject: {item.subject}")
            output.info(f"  To: {', '.join(data['preview']['to'])}")
        return

    subject = item.subject
    item.send()
    data = {"message": "草稿已发送", "subject": subject, "sent": True}
    if output.is_json():
        output.print_json(data)
    else:
        output.success(data["message"])


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
        output.handle_error(f"草稿未找到: {mail_id}", "NOT_FOUND", exit_code=4)

    if not force and not output.is_json():
        click.confirm(f"确认删除草稿 '{item.subject}'？", abort=True)

    subject = item.subject
    item.move_to_trash()

    data = {"message": "草稿已删除", "subject": subject}
    if output.is_json():
        output.print_json(data)
    else:
        output.success(data["message"])
