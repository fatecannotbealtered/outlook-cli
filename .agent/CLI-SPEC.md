# Agent-Facing CLI Design Spec


This document defines the machine contract a CLI must honor when called by an AI agent. The goal: agents can call it reliably, parse it reliably, recover and retry reliably, and never block or mis-write in a non-interactive setting.

## 1. Core rules

1. stdout is the contract: emit a single valid JSON document by default; no logs, progress, prompts, or color codes mixed in.
2. stderr is the side channel: progress, warnings, debug, and error explanations all go to stderr.
3. Machine-first: default `--format json`; `text` is for humans only; `raw` is for raw bytes, logs, diffs passed through verbatim.
4. Non-interactive safe: write operations must not wait on keyboard input; use `--dry-run` + `--confirm <token>`.
5. Deterministic: same input produces the same output structure; field names, field order, and schema version stay stable.
6. Least surprise: queries don't change state; a write with no valid confirm token must fail rather than proceed.
7. Recoverable: error codes, exit codes, and `retryable` must be stable enough for an agent to decide retry, back off, or ask the user.

## 2. Global flags

| Flag | Meaning |
|------|---------|
| `--format json/text/raw` | Output format, default `json` |
| `--json` | Compatibility alias for `--format json`; not recommended for new calls |
| `--fields <a,b,c>` | Return only selected fields, reduces tokens (query commands) |
| `--compact` | Compact JSON output, strips redundant whitespace (query commands) |
| `--dry-run` | Simulate a write, return a change preview and `confirm_token` |
| `--confirm <token>` | Carry the dry-run token to actually execute the write |
| `--quiet` | Suppress progress/prompts on stderr, never suppress errors |

Format responsibilities:

- `json`: structured machine output, the default, and the only format recommended for agents.
- `text`: human-readable, may change, must not be parsed programmatically.
- `raw`: unwrapped bytes / log / diff, passed through verbatim, no JSON envelope.

## 3. Unified output envelope

Success and failure share one shape. The agent only needs to check `ok` first.

Success:

```json
{
  "ok": true,
  "schema_version": "1.0",
  "data": {},
  "meta": {
    "duration_ms": 0
  }
}
```

Failure:

```json
{
  "ok": false,
  "schema_version": "1.0",
  "error": {
    "code": "E_NOT_FOUND",
    "message": "human readable message",
    "details": {},
    "retryable": false
  },
  "meta": {
    "duration_ms": 0
  }
}
```

Conventions:

- Every JSON response must include `ok` and `schema_version`.
- `data` is always the command's business payload; do not hoist business fields to the envelope top level.
- `error.code` is a stable semantic enum, prefixed with `E_`.
- `error.message` is for humans; agents should not parse it.
- `error.details` holds structured context; must be redacted.
- `error.retryable` tells the agent whether it may back off and retry automatically.
- `meta.duration_ms` records command execution time.
- A breaking schema change must bump the `schema_version` major version.

## 4. stdout / stderr rules

- In `json` mode, stdout may contain only one JSON document, or NDJSON for explicitly streaming commands.
- stderr may carry progress, warnings, diagnostics, error envelopes.
- On error, stdout should be empty and the error envelope goes to stderr.
- `--quiet` may only suppress non-error info on stderr.
- No banners, prompts, progress bars, or color codes before/after the JSON on stdout.
- stdout / stderr are always **UTF-8 encoded, no BOM**, newline `\n`, so agents parse reliably across platforms (especially Windows).

## 5. Streaming output (NDJSON)

Large output, log streams, subscription streams, and per-item batch results use NDJSON. Each line must be an independent valid JSON object — easy to consume streaming, low memory, interruptible:

```jsonl
{"ok":true,"schema_version":"1.0","type":"item","data":{}}
{"ok":true,"schema_version":"1.0","type":"item","data":{}}
{"ok":true,"schema_version":"1.0","type":"summary","data":{"count":2}}
```

Conventions:

- Normal queries use a single JSON envelope by default.
- Use NDJSON only when the command is explicitly a log / stream / subscribe / batched-stream.
- NDJSON lines must include `ok`, `schema_version`, `type`.
- The final line should use `type: "summary"`.
- True binary or plain-text passthrough goes through `--format raw`, not wrapped into one giant JSON.

## 6. Exit code table

| Code | Meaning | Agent behavior |
|------|---------|----------------|
| 0 | Success | continue |
| 1 | Generic error | read the error envelope to decide |
| 2 | Argument/usage error | don't retry, fix args |
| 3 | Resource not found | don't retry |
| 4 | Permission/auth/config failure | don't retry, surface credentials or permission |
| 5 | Confirmation required but token missing | run dry-run for a token, then retry |
| 6 | Precondition conflict or invalid token | re-read state, then retry |
| 7 | Retryable transient error (network/rate-limit/server) | back off and retry |
| 8 | Timeout | back off and retry |
| 9 | Human action required (see §14.3, optional) | relay to the user, run `resume` once done |

Error codes and exit codes must align:

- `E_USAGE` / `E_VALIDATION` -> 2
- `E_NOT_FOUND` -> 3
- `E_AUTH` / `E_FORBIDDEN` / `E_CONFIG` -> 4
- `E_CONFIRMATION_REQUIRED` -> 5
- `E_CONFLICT` -> 6
- `E_NETWORK` / `E_RATE_LIMITED` / `E_SERVER` -> 7
- `E_TIMEOUT` -> 8
- `E_HUMAN_REQUIRED` -> 9 (optional, only when §14.3 is enabled)

## 7. Write flow (dry-run -> confirm)

A write command must first support `--dry-run`, returning a preview and a token:

```json
{
  "ok": true,
  "schema_version": "1.0",
  "data": {
    "preview": {
      "changes": [
        {
          "action": "delete",
          "resource": "mail",
          "id": "123",
          "before": {},
          "after": null
        }
      ]
    },
    "confirm_token": "ct_9f2a...",
    "expires_at": "2026-06-05T12:00:00Z"
  },
  "meta": {
    "duration_ms": 0
  }
}
```

The second step carries the token to execute:

```bash
tool resource delete --id 123 --confirm ct_9f2a...
```

Confirm-token conventions:

- The token must bind a hash of the operation content: command path, args, target resource ID, calling account, permission context.
- When a resource version is available, also bind it (version, etag, changekey, or updated_at) to prevent state drift.
- The token must expire; `expires_at` is ISO 8601 UTC.
- On expiry, changed args, or changed target state, execution returns `E_CONFLICT`, exit code 6.
- With no token, return `E_CONFIRMATION_REQUIRED`, exit code 5.
- dry-run must not cause external side effects, but may read state to build the preview.

## 8. Query, pagination, and field selection

Query commands support, by default:

- `--fields <a,b,c>`: return only selected fields; when dotted paths are supported, declare it in reference.
- `--compact`: strip JSON whitespace.
- `--limit`: cap the number of returned items.
- `--cursor` or `--offset`: pagination cursor or offset.

Suggested pagination shape:

```json
{
  "items": [],
  "count": 0,
  "next_cursor": null,
  "has_more": false
}
```

Conventions:

- All IDs are strings, even if numeric underneath.
- All times are ISO 8601 UTC.
- List order must be stable; declare the default sort in reference.
- Query commands must not fall into an interactive prompt just because an optional filter is missing.

## 9. Idempotency and concurrency safety

Write commands should support idempotent semantics where possible:

- Create-type commands should support `--request-id` or `--idempotency-key`.
- Retrying the same idempotency key must not create duplicate resources.
- Update/delete commands should record the target resource version during dry-run.
- If a version change is detected at confirm time, return `E_CONFLICT`.
- Batch writes should return per-item results; don't hide other items' status because one failed.

Suggested batch-write result:

```json
{
  "results": [
    {
      "id": "1",
      "ok": true,
      "action": "deleted"
    },
    {
      "id": "2",
      "ok": false,
      "error": {
        "code": "E_NOT_FOUND"
      }
    }
  ],
  "summary": {
    "ok_count": 1,
    "error_count": 1
  }
}
```

## 10. Sensitive data and auditing

- password, token, secret, authorization header, cookie must not appear in stdout, stderr, error.details, or the audit log.
- dry-run previews must redact sensitive fields.
- reference/context/doctor must not leak plaintext credentials.
- context may report whether credentials exist, but only as a boolean or redacted summary.
- The audit log should record command path, redacted args, calling account, time, exit code, duration.
- `--quiet` must not disable auditing.

## 11. Self-description commands (reference / context / doctor / changelog)

### reference

Declares the tool's capabilities, commands, params, output schema, error codes, and permission levels, so an agent understands the tool first.

```json
{
  "ok": true,
  "schema_version": "1.0",
  "data": {
    "tool": "tool-name",
    "version": "1.0.0",
    "commands": [
      {
        "path": "resource delete",
        "type": "write",
        "description": "Delete a resource",
        "params": [
          {
            "name": "id",
            "type": "string",
            "required": true,
            "multiple": false
          }
        ],
        "output_schema": {}
      }
    ],
    "exit_codes": {}
  },
  "meta": {
    "duration_ms": 0
  }
}
```

### context

Reports the current runtime, config, target, and credential status.

```json
{
  "ok": true,
  "schema_version": "1.0",
  "data": {
    "env": "prod",
    "account": "user@example.com",
    "config": {},
    "credentials": {
      "configured": true
    }
  },
  "meta": {
    "duration_ms": 0
  }
}
```

### doctor

Environment and risk check-up; each item gives an actionable fix.

```json
{
  "ok": true,
  "schema_version": "1.0",
  "data": {
    "checks": [
      {
        "check": "auth",
        "status": "pass",
        "fix": null
      },
      {
        "check": "network",
        "status": "fail",
        "fix": "set HTTP_PROXY or check VPN"
      }
    ]
  },
  "meta": {
    "duration_ms": 0
  }
}
```

### changelog

Reports **what changed between versions** so an agent that just self-updated can refresh its knowledge instead of reusing stale patterns. This is the time-axis complement to `reference` (which describes current capabilities).

```bash
tool changelog                    # all version changes
tool changelog --since 1.0.3      # only versions newer than 1.0.3
```

```json
{
  "ok": true,
  "schema_version": "1.0",
  "data": {
    "current_version": "1.1.0",
    "since": "1.0.3",
    "entries": [
      {
        "version": "1.1.0",
        "date": "2026-06-07",
        "changes": {
          "added": [
            "..."
          ],
          "changed": [
            "..."
          ],
          "fixed": []
        }
      }
    ]
  },
  "meta": {
    "duration_ms": 0
  }
}
```

Conventions:

- **Single source of truth**: `changelog` output is derived from `CHANGELOG.md` (embedded into the binary at build time by `## [version]` section); no separate data maintained. Same source as release notes.
- `--since <version>` returns only entries strictly newer than that version, for an agent that "last saw version X" to pull the delta.
- Change categories follow Keep a Changelog: `added` / `changed` / `fixed` / `deprecated` / `removed` / `security`.
- After a successful self-update, the tool should hint the agent to run `changelog --since <old version>` (see §13).

## 12. Command design conventions

1. Use the shortest command that completes a clear task; reduce combinatorial complexity.
2. Query commands support `--fields` and `--compact` by default to cut tokens.
3. Write commands must support `--dry-run` and `--confirm`.
4. Naming uses `<noun> <verb>` or `<verb> <noun>` style, consistent across the tool.
5. Don't require agents to parse help text; `--help` is for humans, machine capability is exposed via `reference`.
6. All times ISO 8601 UTC; all IDs strings.
7. On failure, return a structured error rather than a half-finished success payload.
8. Avoid ambiguous params; booleans are flags, enums are bounded choices.

## 13. Versioning and compatibility

- `schema_version` is the output schema version, not the tool version.
- A breaking schema change bumps the major version, e.g. `1.x` -> `2.0`.
- Non-breaking added fields may keep the major version.
- Deprecated fields should keep a compatibility window and be marked deprecated in reference.
- Compatibility aliases may exist but should not be the recommended usage in new docs.
- Agents should rely on `reference`, not `--help` or README.

### Version negotiation (tool version ↔ Skill expectation)

A Skill is a snapshot of the capabilities the day it was written; once the binary version drifts, things misalign: a Skill written for v1.1 against a v1.0 binary will silently call commands that don't exist.

- The tool must report its own version: `tool --version` and `context.data.version`.
- The Skill declares a minimum compatible version in frontmatter (see SKILL-SPEC `requires.min_version`).
- `doctor` should include a check "does the current version meet the declared minimum"; if not, give a `fix` (upgrade command), status `fail`.

### Self-update loop

For tools with `self-update`, after a successful update they **must close the knowledge-refresh loop**, or the agent won't know what new capabilities it just gained:

- After `update --confirm <token>` succeeds, return `previous_version` and `current_version` in `data`.
- Also hint in the result: `run "changelog --since <previous_version>" to see what changed`.
- Agent convention: after self-update, before continuing, read `changelog --since <old version>` (see the SKILL-SPEC recipe).

## 14. Optional patterns (enable as needed)

These three patterns are **not for everyone**: implement them if your tool needs them, ignore them otherwise — zero overhead. They let the spec scale with tool complexity — a simple tool stays light, a complex tool need not reinvent the wheel. Each is marked "when applicable."

### 14.1 Credential lifecycle (when tokens expire)

**When applicable**: credentials are not static but expire / need refresh — OAuth access_token (WeChat Official Account ~2h), cookie / session (Xiaohongshu), temporary STS credentials, etc. Tools with static username/password skip this section.

- Beyond "is it configured," `context.data.credentials` should report **validity and expiry** (redacted):

  ```json
  {
    "credentials": {
      "configured": true,
      "valid": true,
      "expires_at": "2026-06-07T12:00:00Z",
      "refreshable": true
    }
  }
  ```

- When a token is expired and cannot auto-refresh, the operation returns `E_AUTH` (exit 4), with `details` indicating re-auth is needed.
- Tools that can auto-refresh should do so **transparently**, not bothering the agent; degrade to `E_AUTH` only if refresh fails.
- `doctor` adds a `check: "credentials"` item; for near-expiry give `warn` + a renew `fix`.
- Refresh tokens and secrets are always redacted — never in stdout / stderr / details.

### 14.2 Async job lifecycle (long jobs: submit → poll → fetch result)

**When applicable**: the operation can't return a result synchronously — async SQL execution / approval (Archery), bulk send, scrape/crawl jobs, large exports. Commands that return results synchronously skip this section.

- The submit command returns a `job_id` and status immediately, without blocking:

  ```json
  {
    "ok": true,
    "schema_version": "1.0",
    "data": {
      "job_id": "job_abc123",
      "status": "pending",
      "poll": "tool job status --id job_abc123",
      "result": "tool job result --id job_abc123"
    },
    "meta": { "duration_ms": 12 }
  }
  ```

- Status queries return a stable enum: `pending` / `running` / `succeeded` / `failed` / `cancelled`, with progress (e.g. `progress`, `eta_seconds`).
- Result and status are fetched separately: after `succeeded`, use the `result` command to pull data (large results via NDJSON / `--format raw`).
- A `failed` result uses the standard error envelope; `retryable` indicates whether the whole job can be retried.
- Submission of a write-type long job still goes through `dry-run → confirm`; the `job_id` is created only after confirm.

### 14.3 Human-in-the-loop checkpoints (when a human must scan / solve captcha / approve)

**When applicable**: a step mid-flow must be completed by a human — QR login / captcha (Xiaohongshu), approver sign-off (Archery), secondary confirmation. Fully automated tools skip this section.

- When stuck at a human step, **don't block, don't guess** — return a dedicated signal so the agent hands off to the user:

  ```json
  {
    "ok": false,
    "schema_version": "1.0",
    "error": {
      "code": "E_HUMAN_REQUIRED",
      "message": "Scan the QR code to continue",
      "details": { "action": "scan_qr", "resume": "tool login resume --id sess_1", "qr_path": "/tmp/qr.png" },
      "retryable": false
    },
    "meta": { "duration_ms": 30 }
  }
  ```

- `E_HUMAN_REQUIRED` uses exit code `9` (added beyond the existing 0–8; not reusing `4`, to distinguish "bad credentials" from "waiting on a human action").
- `details.action` is a stable enum describing what the human must do; `details.resume` gives the command to continue after the human is done.
- Agent convention: on `E_HUMAN_REQUIRED` → relay `message` and the required action to the user → wait for them → run `resume`; do not auto-retry.

## 15. Design checklist

> Items marked `(optional)` only apply when the corresponding optional pattern is enabled.

- [ ] Default `--format json`
- [ ] stdout contains only valid JSON / NDJSON, no pollution
- [ ] Logs and progress all go to stderr
- [ ] Success/failure share one envelope, with `ok` and `schema_version`
- [ ] `error` has semantic `code`, `details`, `retryable`
- [ ] Exit codes tiered and consistent with `retryable`
- [ ] Write commands have the dry-run / confirm-token loop
- [ ] Confirm token binds operation args, account, permission context, resource version
- [ ] Provides `reference` / `context` / `doctor`
- [ ] Provides `changelog [--since]`, same source as CHANGELOG/release-notes
- [ ] Tool reports its own version (`--version` and `context.version`)
- [ ] (with self-update) post-update returns previous/current version and hints to read changelog
- [ ] Query commands support `fields` / `compact`
- [ ] List commands support pagination or explicitly state none is needed
- [ ] All times ISO 8601 UTC
- [ ] All IDs strings
- [ ] Secrets redacted end to end
- [ ] Schema changes have a versioning/compat policy
- [ ] stdout/stderr are UTF-8 without BOM
- [ ] (optional · expiring tokens) `context`/`doctor` report credential validity and expiry; refresh failure degrades to `E_AUTH`
- [ ] (optional · long jobs) submit returns `job_id` + status enum, status/result separated
- [ ] (optional · human needed) stuck human steps return `E_HUMAN_REQUIRED` (exit 9) + `resume`, no auto-retry
