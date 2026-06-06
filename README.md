# outlook-cli

[![CI](https://github.com/fatecannotbealtered/outlook-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/fatecannotbealtered/outlook-cli/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![npm version](https://img.shields.io/npm/v/@fatecannotbealtered-/outlook-cli.svg)](https://www.npmjs.com/package/@fatecannotbealtered-/outlook-cli)

English | [中文](README_zh.md)

Outlook Exchange CLI for humans and AI Agents.

Manage email, calendar, folders, rules, and contacts from the terminal. Built for automation with flat JSON output, permission control, and send safety mechanisms.

[Features](#features) · [Installation](#installation) · [Commands](#commands) · [Security](#security) · [Project Structure](#project-structure) · [Contributing](#contributing)

## Disclaimer

This project is shared for **personal learning, research, and everyday productivity** — not as a product with SLAs. The maintainers do not offer commercial support or make any **fitness-for-production** promise. If you use it at work, that is your call: follow your org's rules. Software is provided "as is," without warranty of any kind.

## Features

- **50 atomic commands** across mail, calendar, folders, rules, tools, and setup
- **Dual output**: `--json` for machine-readable, human-friendly by default
- **Permission system**: read-only (default) → write → full
- **Send safety**: send/reply/forward require `--preview` or `--send` flag
- **Soft delete only**: all deletes go to trash, no permanent deletion
- **Audit logging**: JSONL format, monthly rotation
- **Single binary**: PyInstaller-packaged, no Python runtime needed
- **npm distribution**: `npm install -g @fatecannotbealtered-/outlook-cli`
- **Built-in updater**: check and update the CLI with dry-run/confirm safety

## Installation

Copy the block below to your agent (or run it yourself):

```bash
# Please install outlook-cli and use it for all Outlook/Exchange operations going forward (always pass --json).
# Install CLI
npm install -g @fatecannotbealtered-/outlook-cli

# Install CLI Skill (required) — copies into your agent-supported skills directory
npx skills add fatecannotbealtered/outlook-cli -y -g

# Configure and verify
outlook-cli setup login
outlook-cli setup doctor --json

# Check for CLI updates
outlook-cli update --check
```

### Manual (development)

```bash
git clone https://github.com/fatecannotbealtered/outlook-cli.git
cd outlook-cli
pip install -e .
```

## Quick Start

```bash
outlook-cli mail list --json
outlook-cli cal list --days 7 --json
outlook-cli tools contacts --query "John" --json
```

## Commands

### `setup` — Configuration

| Command | Description |
|---------|-------------|
| `setup login` | Interactive credential setup |
| `setup status` | Check configuration status |
| `setup doctor` | Test Exchange connection |

### `update` — Self-update

| Command | Description |
|---------|-------------|
| `update --check` | Check the latest available CLI version |
| `update --dry-run` | Preview the package-manager update command |
| `update --confirm <token>` | Run the confirmed update command |

### `mail` — Email Operations (24 commands)

| Command | Permission | Description |
|---------|------------|-------------|
| `mail list` | read-only | List emails in folder |
| `mail search` | read-only | Search by sender/subject/keyword/etc. |
| `mail read` | read-only | Read full email content |
| `mail stats` | read-only | Email statistics (top senders, daily) |
| `mail thread` | read-only | Conversation view |
| `mail attachment-summary` | read-only | List attachments across emails |
| `mail export` | read-only | Export as .eml |
| `mail download-attachment` | read-only | Download attachments |
| `mail move` | write | Move to folder |
| `mail mark` | write | Mark as read/unread |
| `mail flag` | write | Flag/unflag/complete |
| `mail categorize` | write | Add/remove/clear categories |
| `mail restore` | write | Restore from trash |
| `mail batch` | write | Batch operations |
| `mail delete` | write | Soft delete (trash) |
| `mail send` | full | Send email (`--preview`/`--send`) |
| `mail reply` | full | Reply to sender |
| `mail reply-all` | full | Reply to all |
| `mail forward` | full | Forward email |
| `mail drafts` | read-only | List drafts |
| `mail draft-read` | read-only | Read draft content |
| `mail draft-edit` | write | Edit draft |
| `mail draft-send` | full | Send draft |
| `mail draft-delete` | write | Delete draft |

### `cal` — Calendar (4 commands)

| Command | Permission | Description |
|---------|------------|-------------|
| `cal list` | read-only | List events |
| `cal create` | write | Create event |
| `cal update` | write | Update event |
| `cal delete` | write | Delete event |

### `folders` — Folder Management (6 commands)

| Command | Permission | Description |
|---------|------------|-------------|
| `folders list` | read-only | List all folders |
| `folders create` | write | Create folder |
| `folders rename` | write | Rename folder |
| `folders move` | write | Move folder |
| `folders empty` | write | Empty folder |
| `folders delete` | write | Delete folder |

### `rules` — Inbox Rules (5 commands)

| Command | Permission | Description |
|---------|------------|-------------|
| `rules list` | read-only | List all rules |
| `rules create` | write | Create rule |
| `rules update` | write | Update rule |
| `rules delete` | write | Delete rule |
| `rules toggle` | write | Enable/disable rule |

### `tools` — Utilities (8 commands)

| Command | Permission | Description |
|---------|------------|-------------|
| `tools contacts` | read-only | Search global address list |
| `tools free-busy` | read-only | Query free/busy status |
| `tools rooms` | read-only | List meeting rooms |
| `tools rooms-free-busy` | read-only | Check room availability |
| `tools oof get` | read-only | Get auto-reply settings |
| `tools oof set` | write | Enable auto-reply |
| `tools oof disable` | write | Disable auto-reply |
| `tools respond` | write | Accept/decline/tentative meeting |

## Global Flags

| Flag | Description |
|------|-------------|
| `--json` | JSON output (machine-readable) |
| `--quiet` | Suppress non-error output |
| `--dry-run` | Preview write operations |
| `--account EMAIL` | Shared mailbox email (delegate access) |
| `--version` | Show version |

## Permission System

Default permission is `read-only`. To enable write/full operations, edit `~/.outlook-cli/config.json`:

```json
{
  "email": "user@company.com",
  "password": "...",
  "permissions": {
    "mode": "full"
  }
}
```

**AI Agents cannot change this file programmatically** — the CLI provides no command to modify permissions. Only humans can edit the config file.

## Send Safety

Commands that send email (`send`, `reply`, `reply-all`, `forward`, `draft-send`) require an explicit safety flag:

```bash
# Preview without sending
outlook-cli mail send --to "a@b.com" --subject "Hi" --body "Hello" --preview

# Actually send
outlook-cli mail send --to "a@b.com" --subject "Hi" --body "Hello" --send

# Without flag: ERROR
outlook-cli mail send --to "a@b.com" --subject "Hi" --body "Hello"
# Error: send commands require --preview or --send
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `OUTLOOK_EMAIL` | Override email |
| `OUTLOOK_PASSWORD` | Override password |
| `OUTLOOK_SERVER` | Override Exchange server |
| `OUTLOOK_TIMEZONE` | Override timezone |
| `OUTLOOK_PERMISSIONS` | Override permission mode |
| `OUTLOOK_SHARED_MAILBOX` | Shared mailbox email (delegate access) |
| `OUTLOOK_NO_AUDIT` | Set to `1` to disable audit logging |
| `OUTLOOK_AUDIT_RETENTION_MONTHS` | Audit log retention (default: 3) |
| `NO_COLOR` | Disable ANSI colors |

## Error Codes

| Code | Exit | Meaning |
|------|------|---------|
| `CONFIG_ERROR` | 3 | Not configured |
| `AUTH_REQUIRED` | 3 | Bad credentials |
| `FORBIDDEN` | 5 | Insufficient permissions |
| `NOT_FOUND` | 4 | Resource not found |
| `VALIDATION_ERROR` | 2 | Invalid arguments |
| `SERVER_ERROR` | 7 | Exchange error |
| `NETWORK_ERROR` | 7 | Connection failed |

## JSON Output

All commands support `--json` for machine-readable output. The default format is **flat and token-efficient** (ideal for AI Agents):

```bash
# Flat JSON — minimal fields, low token cost
outlook-cli mail list --limit 5 --json
outlook-cli mail search --sender "boss@company.com" --json

# Pipe-friendly (suppress non-JSON noise)
outlook-cli mail list --json --quiet

# Preview write operations without executing
outlook-cli mail delete --id "abc123" --dry-run --json
```

Error responses include machine-readable error codes and actionable hints:

```json
{
  "error": "Mail not found: abc123",
  "errorCode": "NOT_FOUND",
  "hint": "Confirm the resource ID is correct (from list/search results)"
}
```

Set `NO_COLOR=1` to disable colored output (useful in CI/CD).

## Config File

Credentials stored at `~/.outlook-cli/config.json` (permissions: 0600):

```json
{
  "email": "user@company.com",
  "password": "your-password-or-app-password",
  "server": "",
  "timezone": "Asia/Shanghai",
  "shared_mailbox": "",
  "permissions": {
    "mode": "read-only"
  }
}
```

| Field | Description |
|-------|-------------|
| `email` | Exchange email address |
| `password` | Password or App Password (for 2FA) |
| `server` | Exchange server URL (empty = auto-discover) |
| `timezone` | Timezone for calendar operations (default: `Asia/Shanghai`) |
| `shared_mailbox` | Shared mailbox email for delegate access (optional) |
| `permissions.mode` | Permission level: `read-only` / `write` / `full` |

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Config not found | Run `outlook-cli setup login` or set `OUTLOOK_EMAIL` and `OUTLOOK_PASSWORD` env vars |
| Authentication failed | Check credentials; for 2FA, use App Password |
| Permission denied | Check `permissions.mode` in `~/.outlook-cli/config.json` |
| Resource not found | Verify the ID from `list`/`search` results |
| Autodiscover failed | Set `OUTLOOK_SERVER` env var or `server` in config |
| Connection timeout | Check network and Exchange server availability |
| Send rejected | Add `--preview` or `--send` flag to send commands |

## Security

> **⚠️ Warning: AI Agent Email Risk**
>
> Granting `write` or `full` permissions to AI Agents carries **real-world consequences** that differ fundamentally from other CLI tools:
>
> - **Email is irreversible** — once sent, it cannot be recalled. A misconfigured or hallucinating Agent can send emails to wrong recipients, disclose confidential information, or cause reputational damage.
> - **Delete affects live data** — while deletes go to trash, bulk operations on a production mailbox can disrupt workflows before recovery.
> - **Rules and OOF affect all incoming mail** — a bad rule or auto-reply can silently misroute or respond to emails for days before anyone notices.
>
> **Recommendations:**
> - Keep the default `read-only` permission unless you explicitly need write/send capabilities
> - For AI Agents: use `read-only` by default, and only escalate to `write` for specific trusted workflows
> - **Never grant `full` permission to unattended AI Agents** — always require human review before sending
> - Use `--preview` to review what an Agent intends to do before `--send`
> - Use `--dry-run` to test write operations without executing them
> - Monitor `~/.outlook-cli/audit/` logs regularly for unexpected operations
>
> The permission system exists to protect you. Changing it is a deliberate, human-only action — treat it with the same caution as sharing your mailbox password.

**Permission system (3 levels):**

| Level | Scope | Example commands |
|-------|-------|-----------------|
| `read-only` (default) | Read-only operations | list, search, read, contacts, free-busy, oof get |
| `write` | + data modification | move, delete, mark, cal create, folders CRUD, rules CRUD |
| `full` | + send/reply/forward | send, reply, reply-all, forward, draft-send |

**How it works:**
- Permission stored in `~/.outlook-cli/config.json` (`permissions.mode`)
- **The CLI provides no command to change permissions** — only humans can edit the config file
- AI Agents cannot escalate privileges programmatically
- Environment variable `OUTLOOK_PERMISSIONS` can override (useful for CI)

**Send safety (irreversible operations):**
- Send commands (`send`, `reply`, `reply-all`, `forward`, `draft-send`) require explicit `--preview` or `--send` flag
- Without flag: command is **rejected** with error
- `--preview`: outputs what would be sent, does NOT send
- `--send`: actually sends the email

**Soft delete only:**
- All `delete` commands move items to trash (never permanent)
- Deleted items can be restored with `mail restore`

**Credential security:**
- Credentials stored at `~/.outlook-cli/config.json` with `0600` permissions (user-only readable)
- Config directory created with `0700` permissions
- Password input is hidden during `setup login`
- Sensitive flags (`--password`, `--token`) are stripped from audit logs
- No credentials are logged or transmitted to third parties

**Audit logging:**
- Every write command is logged to `~/.outlook-cli/audit/` in JSONL format
- Monthly file rotation with configurable retention (default: 3 months)
- Disable with `OUTLOOK_NO_AUDIT=1`

> For vulnerability reports, see [SECURITY.md](SECURITY.md).

## Audit Logging

Every write command (send, delete, move, create, update, etc.) is automatically logged to `~/.outlook-cli/audit/` in JSONL format — one JSON object per line, one file per month.

```bash
# Example: view this month's audit log
cat ~/.outlook-cli/audit/audit-2026-05.jsonl

# Each entry:
# {"ts":"2026-05-03T14:22:01+08:00","cmd":"mail delete","args":["mail","delete","--id","abc123"],"exit":0,"ms":450}
```

| Env var | Default | Description |
|---------|---------|-------------|
| `OUTLOOK_NO_AUDIT` | (unset) | Set to `1` to disable audit logging |
| `OUTLOOK_AUDIT_RETENTION_MONTHS` | `3` | Auto-delete files older than N months (`0` = keep forever) |

Cleanup runs lazily on each write command — no background process or cron needed.

## Requirements

- Exchange Server 2016/2019 or Microsoft 365 with EWS enabled
- npm install: Node.js 16+, no Python needed
- Development: Python 3.10+, exchangelib, click, cryptography

## Project Structure

```
outlook-cli/
├── outlook_cli/                  # Python package
│   ├── __init__.py               # Version
│   ├── main.py                   # Click entry point, global flags, permission check
│   ├── config.py                 # Config management (~/.outlook-cli/config.json)
│   ├── crypto.py                 # AES-256-GCM credential encryption (machine-bound)
│   ├── exchange.py               # Exchange EWS connection and utilities
│   ├── output.py                 # Dual-mode output (JSON / human-readable)
│   ├── audit.py                  # Write-operation audit logging (JSONL)
│   └── commands/
│       ├── setup.py              # login, status, doctor
│       ├── mail.py               # 24 mail commands
│       ├── cal.py                # 4 calendar commands
│       ├── folders.py            # 6 folder commands
│       ├── rules.py              # 5 inbox rules commands
│       └── tools.py              # 8 utility commands
├── tests/                        # Unit tests (config, output, audit, crypto, permissions, e2e, integration)
├── scripts/
│   ├── install.js                # npm postinstall (downloads binary)
│   └── run.js                    # npm bin wrapper
├── skills/outlook-cli/
│   └── SKILL.md                  # AI Agent skill definition
├── .github/workflows/
│   ├── ci.yml                    # Test matrix (Python 3.10/3.11/3.12)
│   └── release.yml               # Tag-triggered build + npm publish
├── build.py                      # PyInstaller build script
├── setup.py                      # pip install (development)
├── requirements.txt              # Python dependencies
├── package.json                  # npm distribution
└── .gitignore
```

## Contributing

Contributions welcome! See [CONTRIBUTING.md](CONTRIBUTING.md). Release notes: [CHANGELOG.md](CHANGELOG.md).

## License

MIT © Sean Guo
