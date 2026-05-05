---
name: outlook-cli
version: "1.0.2"
description: "Outlook Exchange CLI for email, calendar, folders, rules, and contacts. Atomic commands for AI Agents."
license: MIT
user-invocable: true
metadata: {"openclaw": {"emoji": "📧", "author": "Sean Guo", "requires": {"bins": ["outlook-cli"]}}}
---

# outlook-cli

Outlook Exchange CLI for humans and AI Agents. Provides atomic commands for mail, calendar, folders, rules, and contacts via EWS (Exchange Web Services).

> Install CLI: `npm install -g @fatecannotbealtered-/outlook-cli`
>
> Install Skill: `npx skills add fatecannotbealtered/outlook-cli -y -g`

## Activation

Activate this skill when the user's request involves:

- **Email**: mail, inbox, send, reply, forward, search, delete, archive, draft, attachment, Outlook, Exchange, email
- **Calendar**: calendar, meeting, schedule, event, appointment
- **Contacts**: contacts, address book, find person, lookup
- **Auto-reply**: out of office, OOF, auto-reply, leave
- **Organization**: folders, rules, organize, filter, sort

## Credential Setup

Agent gets credentials from user conversation, then configures once:

```bash
# Step 1: Configure (password encrypted on save)
outlook-cli setup login --email user@co.com --password P@ss --skip-test

# Step 2: Test connection
outlook-cli setup doctor

# Step 3: Use (all subsequent commands read encrypted config)
outlook-cli mail list --json
outlook-cli mail search --sender "boss@company.com" --json
outlook-cli mail read --id "<message-id>" --json
```

If credentials are not yet configured, ask the user for their email and password.

## Permission System

Three permission levels (default: `read-only`):

| Level | Commands |
|-------|----------|
| `read-only` | list, search, read, stats, thread, attachment-summary, export, drafts, draft-read, contacts, free-busy, rooms, oof get |
| `write` | + move, mark, flag, categorize, restore, batch, delete, cal create/update/delete, folders CRUD, rules CRUD, oof set/disable, respond |
| `full` | + send, reply, reply-all, forward, draft-send |

Permission is stored in `~/.outlook-cli/config.json`. The CLI does not provide a command to change it — humans edit the file manually. AI Agents cannot escalate privileges.

## Send Safety

Send commands (send, reply, reply-all, forward, draft-send) require a safety flag:

```bash
# Without flag: REJECTED
outlook-cli mail send --to "a@b.com" --subject "Hi" --body "Hello"
# Error: send commands require --preview or --send

# Preview mode: shows what would be sent
outlook-cli mail send --to "a@b.com" --subject "Hi" --body "Hello" --preview

# Confirm mode: actually sends
outlook-cli mail send --to "a@b.com" --subject "Hi" --body "Hello" --send
```

## Delete Safety

All delete operations are **soft delete** — items go to trash, never permanently deleted. Use `--force` to skip confirmation prompts.

## Command Reference

### setup

```bash
outlook-cli setup login --email user@co.com --password P@ss --skip-test
outlook-cli setup status             # Check configuration
outlook-cli setup doctor             # Test Exchange connection
```

### mail (24 commands)

```bash
# Read (read-only)
outlook-cli mail list [--folder PATH] [--filter unread|recent|all|flagged] [--days N] [--limit N] [--offset N] [--json]
outlook-cli mail search [--subject S] [--sender S] [--to S] [--keyword S] [--days N] [--limit N] [--json]
outlook-cli mail read --id ID [--mark-read] [--json]
outlook-cli mail stats [--folder PATH] [--days N] [--top N] [--json]
outlook-cli mail thread --id ID [--days N] [--json]
outlook-cli mail attachment-summary [--folder PATH] [--days N] [--ext pdf,xlsx] [--json]
outlook-cli mail export --id ID [--output-dir DIR]
outlook-cli mail download-attachment --id ID [--name NAME] [--output-dir DIR]

# Write (write permission)
outlook-cli mail move --id ID --folder PATH
outlook-cli mail mark --id ID --status read|unread
outlook-cli mail flag --id ID --action flag|unflag|complete
outlook-cli mail categorize --id ID --action add|remove|clear [--categories a,b]
outlook-cli mail restore --id ID [--folder PATH]
outlook-cli mail batch --ids "id1,id2" --action delete|mark-read|mark-unread|move [--folder PATH] [--force]
outlook-cli mail delete --id ID [--force]

# Send (full permission, requires --preview or --send)
outlook-cli mail send --to "a@b.com" --subject "Hi" --body "Hello" [--cc "x@y.com"] [--html] [--attachments file.pdf] [--preview|--send]
outlook-cli mail reply --id ID --body "Reply" [--html] [--attachments file.pdf] [--preview|--send]
outlook-cli mail reply-all --id ID --body "Reply" [--html] [--attachments file.pdf] [--preview|--send]
outlook-cli mail forward --id ID --to "a@b.com" [--body "Note"] [--html] [--attachments file.pdf] [--preview|--send]

# Drafts — list/read are read-only; edit/delete are write; send is full
outlook-cli mail drafts [--limit N] [--offset N]
outlook-cli mail draft-read --id ID
outlook-cli mail draft-edit --id ID [--subject S] [--body S] [--to S] [--cc S]
outlook-cli mail draft-send --id ID [--preview|--send]
outlook-cli mail draft-delete --id ID [--force]
```

### cal (4 commands)

```bash
outlook-cli cal list [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--days N] [--subject KEYWORD] [--json]
outlook-cli cal create --subject "Meeting" --start "2026-05-01 10:00" --end "2026-05-01 11:00" [--attendees "a@b.com,c@d.com"] [--location "Room A"] [--recurrence daily|weekly|monthly]
outlook-cli cal update --id ID [--subject S] [--start T] [--end T] [--location S] [--attendees S]
outlook-cli cal delete --id ID [--force]
```

### folders (6 commands)

```bash
outlook-cli folders list [--max-depth N]
outlook-cli folders create --name "Projects/Alpha"
outlook-cli folders rename --name "Old" --new-name "New"
outlook-cli folders move --name "Folder" --target "Archive"
outlook-cli folders empty --name "Folder" [--force]
outlook-cli folders delete --name "Folder" [--force]
```

### rules (5 commands)

```bash
outlook-cli rules list
outlook-cli rules create --name "Rule" [--sender S] [--subject S] [--move-to PATH] [--mark-read] [--forward-to S] ...
outlook-cli rules update --id ID [--name S] [--priority N] ...
outlook-cli rules delete --id ID [--force]
outlook-cli rules toggle --id ID --action enable|disable
```

### tools (8 commands)

```bash
outlook-cli tools contacts --query "John" [--json]
outlook-cli tools contacts --email "john@company.com" [--json]
outlook-cli tools free-busy --email "a@b.com,c@d.com" --start "2026-05-01" [--end "2026-05-02"] [--json]
outlook-cli tools rooms [--keyword KEYWORD] [--limit N] [--json]
outlook-cli tools rooms-free-busy --start "2026-05-01 10:00" --end "2026-05-01 12:00" [--json]
outlook-cli tools oof get
outlook-cli tools oof set --message "On vacation" [--start T] [--end T]
outlook-cli tools oof disable
outlook-cli tools respond --id ID --action accept|decline|tentative [--message S]
outlook-cli tools respond --mail-id MAIL_ID --action accept|decline|tentative [--message S]
```

## Global Flags

| Flag | Description |
|------|-------------|
| `--json` | JSON output (machine-readable) |
| `--quiet` | Suppress non-error output |
| `--dry-run` | Preview write operations without executing |
| `--account EMAIL` | Shared mailbox email (delegate access) |
| `--version` | Show version |

## Error Codes

| Code | Exit | Meaning |
|------|------|---------|
| `CONFIG_ERROR` | 3 | Not configured — run `setup login` |
| `AUTH_REQUIRED` | 3 | Bad credentials |
| `FORBIDDEN` | 5 | Insufficient permission level |
| `NOT_FOUND` | 4 | Resource not found |
| `VALIDATION_ERROR` | 2 | Invalid arguments |
| `SERVER_ERROR` | 7 | Exchange server error |
| `NETWORK_ERROR` | 7 | Connection failed |

## JSON Output Schema

All commands return flat JSON with `--json`. Key schemas:

### mail list / search

```json
{
  "count": 10,
  "total": 42,
  "offset": 0,
  "has_more": true,
  "next_offset": 10,
  "emails": [
    {
      "id": "<message-id>",
      "subject": "Subject",
      "sender": "sender@company.com",
      "to": ["recipient@company.com"],
      "cc": [],
      "date": "2026-05-03 10:00:00",
      "is_read": false,
      "has_attachments": true,
      "preview": "First 200 chars..."
    }
  ]
}
```

### mail read

```json
{
  "id": "<message-id>",
  "subject": "Subject",
  "sender": "sender@company.com",
  "to": ["a@b.com"],
  "cc": ["c@d.com"],
  "date": "2026-05-03 10:00:00",
  "is_read": true,
  "has_attachments": true,
  "body": "Full body text...",
  "attachments": [{"name": "file.pdf", "size": 12345}]
}
```

### mail send / reply / forward (preview)

```json
{
  "preview": {
    "action": "send|reply|forward",
    "to": ["a@b.com"],
    "subject": "Subject",
    "body_preview": "First 200 chars...",
    "html": false,
    "attachments": ["file.pdf"]
  },
  "sent": false
}
```

### mail send / reply / forward (sent)

```json
{
  "message": "邮件已发送",
  "to": "a@b.com",
  "subject": "Subject",
  "sent": true
}
```

### cal list

```json
{
  "count": 5,
  "total": 5,
  "events": [
    {
      "id": "event-id",
      "subject": "Meeting",
      "start": "2026-05-03 10:00",
      "end": "2026-05-03 11:00",
      "location": "Room A",
      "organizer": "boss@company.com",
      "is_all_day": false
    }
  ]
}
```

### Error response (stderr)

```json
{
  "error": "Human-readable error message",
  "errorCode": "NOT_FOUND",
  "hint": "Suggested fix"
}
```

## Agent Usage Patterns

### Read inbox
```bash
outlook-cli mail list --filter unread --limit 10 --json
```

### Search for specific sender
```bash
outlook-cli mail search --sender "boss@company.com" --days 7 --json
```

### Read and respond
```bash
outlook-cli mail read --id "<id>" --json
outlook-cli mail reply --id "<id>" --body "Got it, thanks!" --preview
outlook-cli mail reply --id "<id>" --body "Got it, thanks!" --send
```

### Calendar management
```bash
outlook-cli cal list --days 7 --json
outlook-cli cal create --subject "Standup" --start "2026-05-04 09:00" --end "2026-05-04 09:30" --recurrence daily
```

### Check someone's availability
```bash
outlook-cli tools free-busy --email "colleague@company.com" --start "2026-05-05" --json
```

### Find a meeting room
```bash
outlook-cli tools rooms-free-busy --start "2026-05-05 14:00" --end "2026-05-05 15:00" --json
```

## Notes

- All IDs come from `list`/`search` commands — use `--json` to get machine-readable IDs
- Folder paths use `/` separator: `Projects/Alpha`
- Folder aliases: `inbox`, `sent`, `drafts`, `trash`, `junk` (and Chinese: 收件箱, 已发送, 草稿箱, 垃圾箱, 垃圾邮件)
- Timezone defaults to `Asia/Shanghai` (configurable via `setup login --timezone`)
- Supports Exchange 2016/2019 and Microsoft 365 with EWS enabled
- Binary includes all dependencies; development setup requires `pip install -e .`
- Shared mailbox: use `--account user@company.com` or set `OUTLOOK_SHARED_MAILBOX` env var
- HTML email: use `--html` flag on send/reply/forward commands to send HTML-formatted body
- Meeting response: use `--mail-id` with a meeting invitation mail to respond directly from inbox
