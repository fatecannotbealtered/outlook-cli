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

`update` is a **single command, not a write with a confirm gate** (see §14): a
bare `update` performs the whole self-update in one call. It may add
tool-specific flags such as `--target-version` or `--channel`, and it keeps
`--check` and `--dry-run` as **optional read-only** flags, but it does NOT take
`--confirm <token>` — self-update is exempt from the §7 write gate.

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
- `meta.duration_ms` records command execution time. `meta` is always emitted on
  every response (success and error); do not mark it `omitempty`, since
  `duration_ms: 0` is a valid value the agent should always be able to read.
- `meta.notices[]` (optional) MAY carry ambient operational notices — currently
  the update-available notice — read **only from the local cache**, never via a
  network call. Each notice has a `severity` (`info` | `warning` | `critical`).
  Omit the field when there is nothing to report. See §14.
- A breaking schema change must bump the `schema_version` major version.

## 4. stdout / stderr rules

- In `json` mode, stdout may contain only one JSON document, or NDJSON for explicitly streaming commands.
- stderr may carry progress, warnings, and diagnostics.
- On error in `json` mode, the failure envelope is that single JSON document on stdout — agents always parse stdout and check `ok`, never scrape stderr. stderr may add human-readable explanation.
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
| 9 | Human action required (see §16.3, optional) | relay to the user, run `resume` once done |

Error codes and exit codes must align:

- `E_USAGE` / `E_VALIDATION` -> 2
- `E_NOT_FOUND` -> 3
- `E_AUTH` / `E_FORBIDDEN` / `E_CONFIG` -> 4
- `E_CONFIRMATION_REQUIRED` -> 5
- `E_CONFLICT` -> 6
- `E_NETWORK` / `E_RATE_LIMITED` / `E_SERVER` -> 7
- `E_TIMEOUT` -> 8
- `E_INTEGRITY` -> 1 (release integrity failure: missing/invalid signature or checksum mismatch; **non-retryable**, see §14)
- `E_IO` -> 1 (local filesystem failure: disk full, file locked, partial write; non-retryable, needs an environment fix; see §14 update replace stage)
- `E_INTERRUPTED` -> 130 (operation cancelled by signal/user, SIGINT = 128+2; retryable — staged work leaves nothing half-applied, see §14)
- `E_HUMAN_REQUIRED` -> 9 (optional, only when §16.3 is enabled)

When the failure comes from an upstream HTTP call, map the status onto the
taxonomy so the agent can tell failure modes apart from `error.code` +
`retryable` — do NOT collapse every 4xx into `E_NETWORK`:

- `401` -> `E_AUTH`
- `403` -> `E_FORBIDDEN`
- `404` -> `E_NOT_FOUND`
- `408` -> `E_TIMEOUT` (retryable)
- `409` -> `E_CONFLICT`
- `429` -> `E_RATE_LIMITED` (retryable)
- `5xx` -> `E_SERVER` (retryable)
- connection refused / DNS / reset -> `E_NETWORK` (retryable)

Map by the upstream's own error TYPE/status where available, not by sniffing
the human-readable message text (substring matching misclassifies messages that
merely contain words like "not found"). Keep this mapping in ONE function so the
status->code->exit contract cannot drift between the output layer and the
command layer. Codes that are declared but never reachable should be annotated
as reserved so an agent does not plan for a branch that cannot occur.

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
- The hash must be keyed (HMAC) with a machine-local secret (e.g. `~/.<tool>/confirm.secret`, created on first use, `0600`), so a token cannot be fabricated by recomputing a public hash — it must come from a real `--dry-run` on the same machine.
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

For offset-based upstreams, echo `offset` and return an explicit `next_offset`
(the value to pass next, present only while `has_more` is true) so the agent
pages deterministically instead of re-deriving `offset + count`:

```json
{
  "items": [],
  "count": 0,
  "offset": 0,
  "next_offset": 20,
  "has_more": true
}
```

When a list is silently capped (e.g. an auto-paginate ceiling), surface
`truncated: true` rather than returning a short list that looks complete.

Conventions:

- All IDs are strings, even if numeric underneath.
- All times are ISO 8601 UTC.
- List order must be stable; declare the default sort in reference.
- Query commands must not fall into an interactive prompt just because an optional filter is missing.

### 8.1 Server-side filters over client-side faking

Prefer pushing a filter to the upstream over post-filtering a page client-side. A
filter applied after pagination silently undercounts: it looks complete but only
reflects the fetched page. If the upstream gained a filter in a known version, map
the flag to it and record the minimum version (reference + compatibility doc)
rather than emulating it; if you must filter locally, page the full set first and
say so.

### 8.2 Heavy sub-resources are separate, structured, and projectable

A sub-resource whose size is unbounded (a diff, a log, an artifact, a full file
body) is its own command, never inlined into a list. The cheap, bounded summary
(counts, paths, stats) belongs on the list; the heavy payload is fetched on demand
for the specific item the agent chose. Return it **structured** (e.g. a diff as
per-file entries, not one opaque blob) so `--fields` can project it down to an
inventory (paths + line counts) without shipping the payload. This makes the
agent's token cost a choice, not a surprise — no bespoke truncation protocol
required.

### 8.3 Multi-scope queries fan out under the batch contract

When a read spans many containers (projects in a group, every project in the
instance), resolve the scope to a concrete set and fan out as a client-side loop
(§15, class B): one external command, exactly one scope selector, results
aggregated with each item annotated by its source container. A container that
fails to scan is reported in the result (e.g. `projectErrors[]` / `scope` /
`projectsScanned`), never silently dropped, and a single failure must not abort
the rest. Aggregating bounded metadata across containers is safe; never aggregate
an unbounded sub-resource (§8.2) across the whole set. An instance-wide scope that
only makes sense for one actor (all of a user's commits) must be bound to that
actor and fail closed otherwise, so a bare unbounded scan is impossible.

## 9. Idempotency and concurrency safety

Write commands should support idempotent semantics where possible:

- Create-type commands should support `--request-id` or `--idempotency-key`. Where the upstream
  honors an idempotency header (e.g. GitLab's `Idempotency-Key`), forward it; bind the key into the
  confirm scope so the token matches only that key.
- Retrying the same idempotency key must not create duplicate resources.
- Update/delete commands should record the target resource version during dry-run.
- If a version change is detected at confirm time, return `E_CONFLICT`.
- **Confirm tokens are single-use.** Once a token has been accepted to execute a write, record its
  fingerprint (e.g. under `~/.<tool>/confirm-consumed.json`, pruned by expiry) and reject any replay
  with `E_CONFLICT` ("token already used; re-run `--dry-run`"). This gives agents safe-retry: a
  confirmed write that times out cannot be blindly re-sent — the retry is rejected and re-running
  `--dry-run` reveals the now-current state. This is the universal safe-retry mechanism for upstreams
  that expose no resource version to bind. Mark consumed BEFORE the write executes (a crash mid-write
  conservatively blocks the replay rather than risking a duplicate). A storage failure must degrade
  gracefully and never block the write.
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

Each command's `output_schema` MUST be machine-usable, not a stub. Use a string label that
resolves to an entry in a top-level `schemas` catalog: `{ "shape": "object"|"array", "fields":
[...], "untrusted_fields": [...] }`, with the field list enumerated from the command's actual
returned data (the flatten structs / `*ToMap` builders) and `untrusted_fields` listing the
attacker-controllable keys. Each command SHOULD also carry `examples`: one runnable invocation
(write commands show the `--dry-run` then `--confirm` pair, dangerous commands include
`--dangerous`). A guard test SHOULD assert every leaf command resolves to a non-empty schema and has
at least one example, so `reference` cannot silently regress to a stub.

```json
{
  "ok": true,
  "schema_version": "1.0",
  "data": {
    "tool": "tool-name",
    "version": "1.0.0",
    "release_readiness": {
      "level": "beta",
      "fcc_required": true,
      "fcc_status": "verified",
      "mock_upstream_required": true,
      "mock_upstream_status": "verified",
      "live_smoke_required_for_stable": true,
      "live_smoke_status": "missing",
      "reason": "Stable requires recorded live smoke/E2E evidence.",
      "required_evidence": [
        "functional_contract_coverage_100",
        "mock_upstream_contract_tests",
        "recorded_live_smoke_for_stable"
      ]
    },
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
        "output_schema": "deleted_resource",
        "examples": [
          "<tool> resource delete <id> --dry-run --compact",
          "<tool> resource delete <id> --confirm <confirm_token> --compact"
        ]
      }
    ],
    "schemas": {
      "deleted_resource": {
        "shape": "object",
        "fields": ["id", "status"],
        "untrusted_fields": []
      }
    },
    "exit_codes": {}
  },
  "meta": {
    "duration_ms": 0
  }
}
```

`release_readiness` is the machine-readable release gate. It must appear in
`reference` for every AI-native CLI:

- `level`: `stable`, `beta`, or `unpublishable`.
- `stable`: FCC is 100%, mock upstream/contract tests cover external behavior,
  and at least one recorded live smoke/E2E run exists for the release candidate.
- `beta`: FCC is 100% and mock upstream/contract tests exist, but live
  smoke/E2E evidence is missing or explicitly not available yet.
- `unpublishable`: any public behavior lacks command-level coverage, or mock
  upstream/contract tests cover only happy paths while failure/auth/pagination/
  empty/rate-limit behavior remains untested.
- `fcc_status`, `mock_upstream_status`, and `live_smoke_status` use
  `verified`, `missing`, `not_applicable`, or `unknown`; `stable` may not use
  `missing` or `unknown` for any required item.
- `required_evidence[]` names the evidence an agent or release script should
  inspect before trusting the level.

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
      },
      {
        "check": "release_readiness",
        "status": "warn",
        "fix": "record live smoke/E2E evidence before declaring stable"
      }
    ]
  },
  "meta": {
    "duration_ms": 0
  }
}
```

`doctor` must include `check: "release_readiness"` with the same release level
reported by `reference`. Use `pass` for `stable`, `warn` for intentional `beta`,
and `fail` for `unpublishable` or for a declared `stable` state with missing
evidence. The check should include an actionable `fix` when the status is not
`pass`.

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
- After a successful self-update, the tool should hint the agent to run `changelog --since <old version>` (see §14).

## 12. Command design conventions

1. Use the shortest command that completes a clear task; reduce combinatorial complexity.
2. Query commands support `--fields` and `--compact` by default to cut tokens.
3. Write commands must support `--dry-run` and `--confirm`.
4. Naming uses `<noun> <verb>` or `<verb> <noun>` style, consistent across the tool.
5. Don't require agents to parse help text; `--help` is for humans, machine capability is exposed via `reference`.
6. All times ISO 8601 UTC; all IDs strings.
7. On failure, return a structured error rather than a half-finished success payload.
8. Avoid ambiguous params; booleans are flags, enums are bounded choices.

## 13. Functional contract coverage and release gate

Functional Contract Coverage (FCC) is the release blocker: every public behavior
an agent can rely on must have automated command-level test coverage. Numeric
line or branch coverage is useful engineering telemetry, but it is secondary and
must not be used as a substitute for missing functional contract tests.

A public functional contract is anything declared in:

- `README.md` / `README_zh.md`, `SKILL.md`, or Skill reference pages;
- `tool reference`, `--help`, `context`, `doctor`, `changelog`, or `update`
  output;
- JSON envelope fields, command output schemas, global flags, error codes, exit
  codes, retryability, and stdout/stderr behavior;
- documented config/env variables, credential handling, write safety, update
  verification, Skill sync, and `_untrusted` security guarantees.

Required coverage for each public command or contract:

- success path;
- missing/invalid arguments;
- missing config, missing auth, or permission failure when applicable;
- upstream API failure, network failure, rate limit, or timeout when applicable;
- JSON envelope shape, output schema, exit code, and stderr/stdout boundary;
- non-interactive behavior: no prompts, no blocking, and write commands use
  `--dry-run` -> `--confirm <token>`;
- regression test for every bug fix that changes observable behavior.

What `FCC = 100%` means:

- every command/flag/output/error behavior listed in the public contract is
  mapped to at least one automated test, or explicitly marked non-applicable;
- command-level tests validate the CLI boundary, not just internal helpers;
- broad generated code, version constants, build metadata, or unreachable
  platform guards may be excluded from numeric coverage, but not from FCC if
  they are documented public behavior;
- a release cannot be tagged while known FCC gaps remain;
- `fcc_status: "verified"` must be machine-backed by an enumeration guard
  test: enumerate every leaf command from live `reference` output and assert
  each one is invoked by at least one command-level test. The guard skips
  while the status is honestly declared `missing`, and fails if the claim is
  flipped to `verified` without the coverage (the template ships this guard).

CI should run the unit and command-level suites for every PR. Numeric coverage
thresholds may ratchet upward over time per repository, but the release standard
is absolute: public functional contracts must be covered.

### Release readiness levels

Release readiness is deliberately stricter than "tests pass":

- **Stable**: FCC is 100%; mock upstream/contract tests cover success,
  validation, config/auth/permission failures, upstream/network/rate-limit/
  timeout failures, empty results, pagination, output schema, exit codes, and
  stdout/stderr boundaries; at least one live smoke/E2E run has been recorded
  for the release candidate.
- **Beta**: FCC is 100% and mock upstream/contract tests meet the same
  behavioral breadth, but recorded live smoke/E2E evidence is missing or the
  project explicitly declares that live E2E is not available yet.
- **Unpublishable**: any public command/flag/output/error behavior lacks
  command-level coverage, or mock upstream tests only cover happy paths.

`reference.release_readiness` and `doctor.checks[]` are the machine-readable
surface for this gate. A repository may choose not to publish `beta` artifacts,
but it must not describe itself as `stable` without the live evidence above.

## 14. Versioning and compatibility

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

### Self-update and Skill-sync loop

For tools with `self-update`, after a successful update they **must close both
refresh loops**:

1. the binary/package is current;
2. the bundled Agent Skill directory is current, with the same end state as
   running `npx skills add <repo> -y -g`.

The user-facing Skill install command stays `npx skills add ...`; the binary
must not expose a separate `install-skill` command. During update, however, the
tool owns the full lifecycle and must either sync the entire `skills/<tool>/`
directory or return an explicit `skill_sync_status` and `skill_sync_command`
that the agent can execute before using new behavior.

Single-command update contract (no leaf commands, no confirm token):

- A bare `update` performs the whole update in ONE call: resolve the latest (or
  `--target-version`) release, verify its integrity, replace the binary/package,
  then sync the Skill directory. Self-update is a single-target, non-destructive,
  self-verifying operation, so it is **exempt from the §7 `--dry-run → --confirm
  <token>` write gate** — the safety guarantee is the in-process signature
  verification below, not an agent's review of a preview. There are no `update`
  leaf subcommands.
- `update --check` is an OPTIONAL read-only probe: report current/target
  versions, install method, whether an update is available, whether Skill sync is
  supported, and signature/checksum availability. It changes nothing.
- `update --dry-run` is an OPTIONAL read-only preview of the same changes
  (binary/package update, Skill sync, verification plan). It issues NO token and
  is never a required step before `update`.
- `update` is idempotent: when already on the latest (or requested) version it
  returns `ok` with a no-op result, so an agent may call it freely.
- On success, `data` carries `previous_version`, `current_version`,
  `signature_verified`, `signature_status`, `skill_sync_status`, and enough
  verification metadata for the agent to audit what happened.
- If the binary/package updates but Skill sync fails, return partial success
  (`ok: false`, `binary_replaced: true`) with `skill_sync_command`; the agent
  must not use newly documented behavior until the Skill sync has completed.

Version notification contract:

- `update --check` actively checks the latest release and refreshes the local
  update notice cache.
- `doctor` may actively check with a short timeout; network failure must not
  make `doctor` fail by itself.
- `context` and `--help` only read the local cache and must not contact remote
  registries or GitHub.
- The cached notice MAY also be attached to **every command's `meta.notices`**,
  read **only from the local cache** (no network; cost is one local file read).
  Business commands surface the cached notice — they never actively check / phone
  home. Omit `meta.notices` when the cache has nothing to report.
- When an update is available, the notice carries `type: "update_available"`,
  `severity`, current/latest versions, install method, `recommended_command`,
  release URL when known, checked-at timestamp, and machine-readable next steps.
  It appears in active-check command `data` (`context` / `doctor` / `update
  --check`) and, read-only from cache, in any command's `meta.notices`. Text/help
  output may append one concise hint.
- **Severity grading** — computed at check time from the embedded CHANGELOG delta
  between the running version and the latest, and stored in the cache so the
  cached `meta.notices` carries the right level:
  - `info` (default): routine patch/minor with no security entry.
  - `warning`: the changelog delta since the running version contains a
    `security` entry, OR the latest crosses a **major** version (first semver
    component increased) — i.e. likely security-relevant or breaking.
  - `critical`: reserved for a running version that is known-yanked or
    known-vulnerable (not derived from the changelog delta).

Release verification baseline:

- **Mandatory signature verification, no skip path**: the binary self-update path
  MUST verify the Sigstore signature on `checksums.txt` in-process, then verify
  the archive SHA256 against it. A missing signature bundle, a signature that does
  not verify, or a checksum mismatch all fail closed — there is no "can't verify,
  proceed anyway" degradation. The whole chain surfaces `E_INTEGRITY` (exit 1,
  non-retryable): a forged or corrupt release is not a transient blip to retry.
- **Verifier embedded, no user-environment dependency**: verification happens
  inside the tool binary (Go via `sigstore-go`, Python inside the frozen binary
  via `sigstore`) with **no external cosign** and nothing pre-installed on the
  machine. The TUF trust root is bootstrapped from the library's embedded
  `root.json`, not fetched on first-use trust (TOFU).
- **New bundle format**: the signing side produces a Sigstore protobuf bundle
  (`checksums.txt.sigstore.json`) via `cosign sign-blob --new-bundle-format`, which
  the in-process verifier consumes; the legacy cosign bundle format is not accepted.
- **Identity binding**: verifiers bind the certificate SAN to this repo's tagged
  release workflow (`…/release.yml@refs/tags/v*`, anchored `^…$`) and validate the
  GitHub OIDC issuer. When the target tag is known, pin the exact identity (stronger
  than a regexp).
- **Cross-language parity**: Go binaries and Python frozen binaries follow the same
  self-update contract — download archive → in-process signature verify → checksum
  → replace binary. Package managers do not own integrity.
- Update results carry `signature_status` (`verified` on success; any failure exits
  via the error envelope) and `signature_verified` (true only when in-process
  Sigstore verification actually ran and succeeded). Never imply checksum
  verification is a signature.

- After `update` succeeds, return `previous_version` and `current_version` in `data`.
- Also hint in the result: `run "changelog --since <previous_version>" to see what changed`.
- Agent convention: after self-update, before continuing, read `changelog --since <old version>` (see the SKILL-SPEC recipe).

Failure and interruption contract:

Single-command `update` runs as staged work — discover → download → verify
signature → verify checksum → replace binary → sync Skill — with exactly one
atomic commit point. The invariant that makes every failure message honest:

- Everything BEFORE the binary swap touches only a temp dir; any failure or
  interruption there leaves the installed binary untouched and fully usable
  (`current_version` unchanged, `binary_replaced: false`).
- The swap itself is atomic (verify in temp → same-filesystem rename; on Windows
  stage `<bin>.new` + replace-on-restart, and a later `update` cleans any stale
  staged file and re-verifies from scratch — a leftover temp artifact is never
  trusted). A crash mid-swap leaves either the old or the new binary, never a
  hybrid.
- Skill sync runs AFTER the swap and is independently replayable.

So the tool can always determine — and MUST always report — its post-failure
state. Every update failure envelope carries, in `error.details` (or `data` on
partial success): `stage`
(`discover|download|verify_signature|verify_checksum|replace|skill_sync`),
`current_version`, `binary_replaced`, and `skill_sync_status`.

Classify the failure by the agent's next action, not by the raw cause:

| Stage | Failure | code / exit | retryable | Post-state | Message must say |
|-------|---------|-------------|-----------|------------|------------------|
| discover / download | network / timeout / rate-limit | `E_NETWORK` / `E_TIMEOUT` / `E_RATE_LIMITED` → 7,8 | true | old version, no change | "transient — re-run `update`, it is idempotent" |
| verify_signature / verify_checksum | missing/invalid signature, identity mismatch, checksum mismatch | `E_INTEGRITY` → 1 | **false** | old version, install refused | "integrity failure — do NOT retry, stop and report" |
| replace | permission / disk full / file locked | `E_FORBIDDEN` / `E_CONFIG` / `E_IO` → 4,1 | false (needs fix) | old version (atomic not committed) | the concrete fix, then re-run |
| skill_sync (post-swap) | npx missing / network | partial success (`ok:false`, `binary_replaced:true`) | true | binary NEW, Skill OLD | "binary at vX; run `<skill_sync_command>`, then `changelog --since <prev>`" |
| any | user/signal interrupt (SIGINT) | `E_INTERRUPTED` → 130 | true | per the stage invariant above | what actually happened + the safe next step |

Interruption (Ctrl-C / SIGTERM):

- Trap the signal, unwind the current stage to a clean state, and STILL emit the
  terminal JSON envelope on stdout before exiting non-zero — an interrupted agent
  must receive a parseable terminal state, never a bare killed process.
- Always clean the temp dir on interrupt; a partial download must never be
  trusted by a later run (re-download + re-verify always).
- The message depends on the interrupted stage: before the swap → "cancelled, no
  change, still on `<current>`"; during the atomic swap → report old-or-new
  truthfully; after the swap during Skill sync → partial success with
  `skill_sync_command`.

Three rules the messages must never break:

1. Never misstate the version: every terminal envelope states the version the
   tool is actually running now.
2. Never let an agent retry an integrity failure: `E_INTEGRITY` is
   `retryable: false` and verbally distinct from any network failure — a forged
   release is not a transient blip to loop on.
3. Never call a partial a success: binary replaced but Skill not synced is
   partial success with `skill_sync_command`, not `ok: true`.

## 15. Batch operations

Many write workflows need to act on a batch of objects in one call (close many issues, send to many openids, run one SQL across many instances). A batch command is still **one** agent-facing command with **one** envelope, **one** confirm token, and **one** aggregated result — never a loop the agent has to drive. The contract below is identical whether the batch is served by a native upstream bulk endpoint (class A) or by a client-side loop (class B); the agent must not be able to tell which.

### 15.1 Plural inputs

- Batch targets use a plural flag: `--ids`, `--symbols`, `--instances`, `--openids`, etc.
- Each plural flag accepts both **comma-separated** (`--ids 1,2,3`) and **repeatable** (`--ids 1 --ids 2 --ids 3`) forms; the two are equivalent and may be mixed.
- A single value degrades gracefully: `--ids 1` is a valid batch of one, same envelope as a batch of many. Where a singular flag (`--symbol`) already exists, keep it as a compatibility alias of the plural and declare it deprecated in reference; do not run two divergent code paths.
- De-duplicate targets before executing and preserve input order in the result `items[]` so the agent can zip results back to inputs deterministically.
- An empty target list is a usage error (`E_VALIDATION`, exit 2), not a silent no-op.

### 15.2 Dry-run summary for a batch

`--dry-run` on a batch returns **what will happen to N objects** before any write, plus a single `confirm_token` that covers the whole batch:

```json
{
  "ok": true,
  "schema_version": "1.0",
  "data": {
    "preview": {
      "action": "close",
      "total": 3,
      "targets": ["1042", "1043", "1044"],
      "changes": [
        { "action": "close", "resource": "issue", "id": "1042" },
        { "action": "close", "resource": "issue", "id": "1043" },
        { "action": "close", "resource": "issue", "id": "1044" }
      ]
    },
    "confirm_token": "ct_9f2a...",
    "expires_at": "2026-06-15T12:00:00Z"
  },
  "meta": { "duration_ms": 0 }
}
```

- The preview must state the operation and the full target set, so a human or agent can audit the blast radius before confirming.
- The token binds the **whole resolved target set** (plus command path, args, account, permission context per §7), so adding or removing a target invalidates it with `E_CONFLICT`.

### 15.3 One confirm token covers the whole batch, consumed once

- A single `--confirm <token>` from the batch dry-run authorizes the entire batch; the agent does not confirm per item.
- The token is **single-use** exactly as in §9: it is fingerprinted and marked consumed before the write runs, and any replay is rejected with `E_CONFLICT` ("token already used; re-run `--dry-run`"). This reuses each repo's existing single-consumption confirm infrastructure — batch adds no new token mechanism.
- On a partial batch failure the token stays consumed; the agent re-runs `--dry-run` (which now resolves to the still-pending targets) rather than replaying the old token.

### 15.4 Dangerous batches: `--dangerous` two-step gate

Irreversible or high-blast-radius batches — bulk `delete`, MR `merge`, mass send / broadcast — require an extra gate **on top of** dry-run → confirm:

- The command must be invoked with `--dangerous`; without it the command fails with `E_CONFIRMATION_REQUIRED` (exit 5) even when a valid confirm token is present.
- This is a two-step human-intent gate: `--dangerous` declares intent, the confirm token authorizes the specific resolved batch. Both are required; neither alone executes.
- Reference marks these commands `dangerous: true`, and their `examples[]` show the `--dangerous` form.
- Tools may layer stricter local policy on a dangerous batch (e.g. per-item confirm, default `--continue-on-error false`, or night-time dry-run-only); such overrides must be declared in reference, not hidden.

### 15.5 Per-item aggregated result, no whole-batch rollback

Batch results aggregate per item. A partial failure does **not** roll back succeeded items:

```json
{
  "ok": true,
  "schema_version": "1.0",
  "data": {
    "items": [
      { "target": "1042", "ok": true },
      { "target": "1043", "ok": true },
      {
        "target": "1044",
        "ok": false,
        "error": { "code": "E_NOT_FOUND", "retryable": false }
      }
    ],
    "summary": { "total": 3, "succeeded": 2, "failed": 1 }
  },
  "meta": { "duration_ms": 0 }
}
```

- Each `items[]` entry carries `target` (the input identifier — `id`, `symbol`, `instance`, …; use the natural key, not an array index), `ok`, and on failure `error` with the same `{ code, retryable }` taxonomy as the top-level envelope (§6).
- `summary` always reports `{ total, succeeded, failed }`. The counts must equal the item tally.
- Top-level `ok` is `true` when the batch executed and produced a result, even with per-item failures; per-item status lives in `items[]`. Reserve top-level `ok: false` for a batch that could not run at all (bad args, auth, no targets). Do not hide other items' status because one failed (consistent with §9).
- `--continue-on-error` controls whether the batch keeps going after the first item failure; **default `true`** (best-effort, finish the batch). Set `--continue-on-error false` to stop at the first failure — already-applied items stay applied (no rollback), and `summary` reflects only attempted items, with the unattempted remainder reported (e.g. `skipped`) so the agent can resume. Dangerous batches may flip the default to `false`; declare it in reference.

### 15.6 Upstream caps: client-side auto-chunking

When the native bulk endpoint has a per-call limit, the command splits the batch into chunks and submits them sequentially, presenting a single command to the agent:

- Known caps: Jira `/issue/bulk`, agile `backlog/issue` and `sprint/{id}/issue` ≤ 50; WeChat openid batches ≤ 100, mass-send openid lists per upstream limit. The command must chunk to the cap; it must not pass a too-large batch straight through and let the upstream 400.
- Chunking is invisible in the contract: still one envelope, one `confirm_token`, one aggregated `items[]`/`summary` across all chunks.
- A chunk-level failure is mapped back onto the affected `items[]`; one failed chunk does not fail the whole command (subject to `--continue-on-error`).
- Keep the chunk size in one shared helper per tool so the cap cannot drift between commands sharing an endpoint.

### 15.7 A/B classes, one external contract

- **Class A** uses a native upstream bulk endpoint (true server-side batch, possibly atomic per the upstream).
- **Class B** loops client-side over single-target calls because no native bulk exists.
- The external contract is identical for both: plural inputs, dry-run summary, single confirm token, dangerous gate, aggregated `items[]`/`summary`, and `--continue-on-error`. The agent cannot and need not tell A from B.
- Atomicity is **not** part of the external contract. A class-B (or capped, chunked class-A) batch must not claim upstream atomicity; where the upstream genuinely is non-atomic or order-unstable, say so in the output schema / reference rather than implying a transaction.

### 15.8 Self-description for batch commands

Every batch command carries a real `output_schema` and runnable `examples[]` (per §11):

- The schema declares the `items[]` shape (`target`, `ok`, `error{code,retryable}`) and the `summary{total,succeeded,failed}` shape, with attacker-controllable keys listed in `untrusted_fields` (`_untrusted`).
- `examples[]` show the plural-input dry-run then confirm pair; dangerous batches include `--dangerous`.
- These must pass the reference guard (non-empty schema + at least one example per leaf command) and count toward FCC (§13) like any other public behavior.

## 16. Optional patterns (enable as needed)

These three patterns are **not for everyone**: implement them if your tool needs them, ignore them otherwise — zero overhead. They let the spec scale with tool complexity — a simple tool stays light, a complex tool need not reinvent the wheel. Each is marked "when applicable."

### 16.1 Credential lifecycle (when tokens expire)

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

### 16.2 Async job lifecycle (long jobs: submit -> poll -> fetch result)

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

### 16.3 Human-in-the-loop checkpoints (when a human must scan / solve captcha / approve)

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

## 17. Design checklist

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
- [ ] `reference` reports `release_readiness`, and `doctor` checks it
- [ ] (with self-update) `update` is a single command (no leaf subcommands, no confirm token); `--check` / `--dry-run` are optional read-only
- [ ] (with self-update) release integrity is verified, and signature status is explicit
- [ ] (with self-update) whole Skill directory sync is part of the update result
- [ ] (with self-update) post-update returns previous/current version and hints to read changelog
- [ ] (with self-update) every update failure/interruption envelope carries `stage` + `current_version` + `binary_replaced` + `skill_sync_status`; `E_INTEGRITY` is non-retryable; binary-replaced-but-Skill-unsynced is partial success, not `ok`
- [ ] (with self-update) SIGINT/SIGTERM is trapped, leaves nothing half-applied, and still emits the terminal JSON envelope
- [ ] Query commands support `fields` / `compact`
- [ ] List commands support pagination or explicitly state none is needed
- [ ] Batch commands take plural inputs (`--ids`/`--symbols`/…), comma-separated or repeatable, single value degrades
- [ ] Batch dry-run summarizes the full target set; one confirm token covers and is consumed once for the whole batch
- [ ] Dangerous batches (delete / merge / mass-send) require the `--dangerous` two-step gate
- [ ] Batch results aggregate `items[].{target,ok,error{code,retryable}}` + `summary{total,succeeded,failed}`, no whole-batch rollback, `--continue-on-error` default true
- [ ] Capped upstream bulk auto-chunks client-side under one command; A/B classes share one external contract; batch commands ship real `output_schema` + `examples`
- [ ] Functional Contract Coverage is 100% for public README / Skill / reference / help / context / doctor / changelog / update behavior
- [ ] Stable releases have recorded live smoke/E2E evidence; otherwise the tool declares `beta`
- [ ] All times ISO 8601 UTC
- [ ] All IDs strings
- [ ] Secrets redacted end to end
- [ ] Schema changes have a versioning/compat policy
- [ ] stdout/stderr are UTF-8 without BOM
- [ ] (optional · expiring tokens) `context`/`doctor` report credential validity and expiry; refresh failure degrades to `E_AUTH`
- [ ] (optional · long jobs) submit returns `job_id` + status enum, status/result separated
- [ ] (optional · human needed) stuck human steps return `E_HUMAN_REQUIRED` (exit 9) + `resume`, no auto-retry
