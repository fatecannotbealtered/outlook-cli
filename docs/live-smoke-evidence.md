# Live Smoke Evidence

Recorded live smoke run against a real Exchange mailbox, as required by
`release_readiness.required_evidence: recorded_live_smoke_for_stable`.

- **Date:** 2026-06-12
- **Environment:** Windows, Python 3.12, exchangelib 5.6.0
- **Mailbox:** real corporate Exchange account (auto-discovered server),
  credentials stored in OS keyring via `setup login`
- **Method:** every command invoked as a subprocess with `--format json`;
  envelope `ok`/`error` asserted; write commands ran the full
  `--dry-run` → `--confirm <token>` cycle with `OUTLOOK_PERMISSIONS=full`.
  All mail was sent to the account owner itself; smoke emails were
  soft-deleted afterwards.

## 2026-06-15 — batch operations (live)

Re-run against the same real mailbox for the new §15 batch commands. The
mailbox defaults to `read-only` (owner safety setting), so every batch command
was first exercised as `--dry-run --format json`; reversible writes were then
run live with `OUTLOOK_PERMISSIONS=full` on 2–3 self-owned objects and cleaned
up afterwards (categories cleared, flags removed, calendar events deleted,
sent test emails soft-deleted, restored items re-deleted). No external
attendees were ever added.

**Method:** subprocess + `--format json`; envelope `ok`/`error` asserted;
write path ran the full `--dry-run` → `--confirm <token>` cycle; aggregated
`items[]` / `summary` shape and per-item `ok`/`error` asserted. No real data
or secrets recorded here.

| Command | Result | Notes |
|---|---|---|
| `mail batch categorize` (`--categories`) | **PASS (live)** | dry-run preview `items[].exists` + token; confirm applied `3/3 succeeded`; categories cleared afterward via `mail categorize --action clear` |
| `mail batch flag` | **PASS (live)** | exercised in the partial-failure test below; reverted via `unflag` |
| `mail batch unflag` | **PASS (live)** | `2/2 succeeded`, used to revert the flag test |
| `mail batch complete` | **PASS (dry-run)** | dry-run preview + token valid; not run live (flag-completion state on shared inbox items left untouched) |
| `mail batch restore` | **PASS (live)** | soft-deleted 2 self test emails, restored from trash `2/2 succeeded` (fresh trash IDs obtained via `mail search --folder trash`, since IDs change after the move) |
| `mail batch delete` | **PASS (live)** | conditionally dangerous: missing `--dangerous` → `E_CONFIRMATION_REQUIRED`, exit 5; with `--dangerous` soft-deleted self test emails `2/2`, used for cleanup |
| `mail draft-send` (plural `--ids`, native `bulk_send`) | **PASS (live)** | created 2 self drafts, batch-sent `2/2 succeeded`; received copies soft-deleted afterward |
| `cal batch create` (`--file`, self only, `--no-send-notifications`) | **PASS (live)** | `2/2 succeeded`, real event IDs returned; no external attendees |
| `cal batch update` (`--file`) | **PASS (dry-run)** | dry-run preview + token valid; not run live (no live update was needed beyond create/delete coverage) |
| `cal batch delete` (plural `--ids`, soft `MOVE_TO_DELETED_ITEMS`) | **PASS (live)** | dangerous-gated (exit 5 without `--dangerous`); deleted the 2 created test events `2/2`, cleanup confirmed |

### Contract points (live)

| Point | Result | Notes |
|---|---|---|
| Partial-failure aggregation | **PASS (live)** | `mail batch flag` over 2 real IDs + 1 bogus → envelope `ok:true`, `message "2/3 succeeded"`, `summary {total:3, succeeded:2, failed:1}`, bogus item `E_NOT_FOUND`; no rollback of applied items |
| Single-use confirm token replay | **PASS (live)** | re-submitting a consumed categorize token → `E_CONFLICT`, exit 6, hint "Re-run --dry-run and use the new confirm_token" |
| `--dangerous` gating on delete | **PASS (live)** | both `mail batch --action delete` and `cal batch --action delete` require `--dangerous`; omitting it → `E_CONFIRMATION_REQUIRED`, exit 5 (verified for both) |

### Bug found during this run

- **`mail list --folder trash` crashes when the Deleted Items folder contains a
  `CalendarItem`** — soft-deleting calendar events lands them in trash, after
  which `mail list --folder trash` returns
  `E_SERVER: 'CalendarItem' object has no attribute 'sender'`. The list path
  assumes every trash item is a mail message and reads `.sender` unconditionally.
  Worked around in this run by scoping with `mail search --folder trash`. The
  batch commands themselves are unaffected; this is a pre-existing list-path gap
  exposed by mixed-type Deleted Items. Not yet fixed.

## 2026-06-14 — v1.1.3 fixes (live)

Re-run against the same real mailbox (in `read-only` permission mode this time):

| Fix | Result | Notes |
|---|---|---|
| `context.credentials.valid` real probe | PASS | now reflects a live, cached authenticated touch — returned `valid:true, checked:true` (previously just copied `configured`) |
| `mail search --sender` server-side filter | PASS | `--sender noreply` returned an accurate `total: 23` with `has_more` from a real `qs.count()`, not the misleading fetch-window count |
| `mail read` inline images | PASS | response includes the `inline_images` list (cid/filename/content_type/size), separated from `attachments` |
| `mail reply/reply-all/forward --attachments` cc+threading fix | unit-verified; **send not live-exercised** | the mailbox is in `read-only` mode (owner's safety setting), so `mail reply` correctly returns `E_FORBIDDEN`; the create_reply→attach→send ordering and cc/threading preservation are covered by 14 unit tests |

The three read-path fixes are live-verified; the reply-attachments send fix is unit-verified (the live mailbox is intentionally read-only).

## Read path — all PASS

| Command | Result | Notes |
|---|---|---|
| `setup doctor` | PASS | connection ok, inbox 15291 items |
| `mail list` (all / recent / folder trash) | PASS | UTF-8 subjects intact |
| `mail search --keyword/--subject` | PASS | |
| `mail read` | PASS | `_untrusted` markers present |
| `mail thread` | PASS | |
| `mail stats` | PASS | |
| `mail drafts` | PASS | |
| `mail attachment-summary` | PASS | |
| `folders list` | PASS | |
| `cal list` | PASS | |
| `rules list` | PASS | |
| `tools contacts` (GAL) | PASS | |
| `tools oof get` | PASS | |
| `tools free-busy` | PASS | |
| `tools rooms` | E_SERVER | tenant has no Room Lists configured; error envelope + hint correct, accepted as environmental |

## Write path — all PASS

| Step | Result | Notes |
|---|---|---|
| `mail send --bcc` dry-run | PASS | preview shows to/cc/bcc; HMAC confirm token issued |
| `mail send --bcc` confirm | PASS | BCC mail delivered, verified via `search` + `read` |
| `mail send --save-draft` | PASS | |
| `mail draft-edit --html --bcc --attachments` | PASS | `updated: [body, bcc, attachment:...]` |
| `mail draft-read` | PASS | bcc visible, tagged `_untrusted` |
| `mail draft-send` dry-run | PASS | preview includes cc/bcc |
| `mail draft-send` confirm | PASS | delivered |
| `mail delete` (soft) | PASS | item moved to trash |
| `mail restore` with stale ID | E_NOT_FOUND | expected: ID changes after move; hint says re-fetch |
| `mail restore` with fresh trash ID | PASS | item back in inbox |

## Bugs found and fixed during this run

1. **`iso_utc` crashed on EWSDateTime** — exchangelib 5.x `EWSDateTime`
   rejects `astimezone(timezone.utc)` (`InvalidTypeError`), which broke
   `mail list` entirely against a live server (mock objects used plain
   datetimes and never hit it). Fixed by rebuilding the value from the
   epoch timestamp. This is exactly the class of bug live smoke exists
   to catch.
2. **GBK console mangled JSON output** — Windows default code page broke
   non-ASCII subjects on stdout. Fixed by reconfiguring stdout/stderr to
   UTF-8 at entry point (the CLI contract requires UTF-8 JSON).
