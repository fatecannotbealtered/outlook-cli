# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- Sync the vendored spec to `ai-native-cli-spec@v1.6.0` (from v1.4). SEC-SPEC §5
  now requires a dependency audit for every ecosystem a tool ships in and names
  the per-language tool; the Lint job's `pip-audit` and `npm audit` already
  satisfy it here. CLI-SPEC §14 states the `update` final-state contract
  explicitly, which this tool has implemented since 1.1.13.
- `contract_gen.py` is now emitted through `ruff format`, so the generated module
  is byte-identical to what `ruff format --check` expects. Its `extend-exclude`
  entry in `ruff.toml` is removed as a result — the formatter and the generator
  no longer fight, and a file that ships to users is back under lint. Formatting
  only; no behaviour change.

### Fixed

- The `Verify version sync` job now installs Python and ruff before running
  `check-spec.js`. That job set up Node only, and `gen-contract.js` silently
  falls back to unformatted output when ruff is missing — so it regenerated a
  differently-formatted `contract_gen.py` and reported drift against the
  correctly-formatted committed file. A fail-closed drift guard whose verdict
  depended on what happened to be installed is now given the codegen's own
  toolchain.

## [1.1.13] - 2026-07-08

### Fixed

- Successful binary and package-manager `update` results now report final post-install state (`current_version == target_version`, `update_available: false`) and clear the cached update notice after the binary or package manager commits.
- Post-swap Skill-sync partial-success payloads now also report `target_version == current_version` and `update_available: false`, so agents can tell the binary is already at the target version even though the Skill still needs syncing.
- The no-op `update` result now carries `target_version` and `update_available: false`, so an already-current install cannot look like an available update.
- `reference` now lists `update_available` in the `update_result` schema, matching the runtime update payload.

## [1.1.12] - 2026-07-02

### Security

- **Bumped `sigstore` to `>=4.3.0,<5`** (#7), pulling in the sigstore fixes for CVE-2024-55655 and CVE-2026-24408. sigstore backs `update`'s signature verification.

### Changed

- **Bumped `click` to `>=8.4.2,<9.0`** (#8) — CLI-framework runtime dependency.

## [1.1.11] - 2026-06-29

### Fixed

- `update` notice cache reads are now version-aware: a cached `update_available` notice is suppressed once the running binary is already at or past the cached latest version. Business commands no longer keep advertising an update to a version that is already installed for up to the 24h cache TTL (for example, right after a successful update).

## [1.1.10] - 2026-06-25

### Added

- Contract single-source: `outlook_cli/contract_gen.py` is now generated from `contract/contract.json` (vendored from `ai-native-cli-spec@v1.4`) via `node scripts/gen-contract.js --lang py`. `output.SCHEMA_VERSION`, `exit_code_for()`, and the `retryable` check in `error_envelope()` delegate to `contract_gen` so they cannot drift from the fleet contract.
- Conformance test `tests/test_contract_conformance.py`: asserts every `E_*` in `EXIT_CODE_BY_ERROR` is in `contract_gen.CODES` with exact exit + retryability, that `RETRYABLE_ERRORS` matches, that `SCHEMA_VERSION` matches, and that success/error/meta envelope keys are within the canonical set.
- CI guard `node scripts/check-spec.js --local-only` in the `version-check` job: fails if `contract_gen.py` drifts from `contract/contract.json`.
- `update --manager pip|npm` now **drives** the package manager (`pip install -U outlook-cli==<ver>` or `npm install -g @fateforge/outlook-cli@<ver>`) instead of only printing the command. The manager-path result carries `signature_status: "not_checked"` (package manager provenance owns integrity), `binary_replaced: true`, and `skill_sync_status: "synced"`. `--check`/`--dry-run` remain read-only. A testable seam (`_run_package_manager_install`) allows unit tests to stub the subprocess without shelling out.

### Changed

- `.agent/` spec files synced from `ai-native-cli-spec@v1.4` (single-source; do not hand-edit).

## [1.1.9] - 2026-06-25

### Changed

- Windows binary self-update now performs the same in-place atomic **rename trick** used on POSIX instead of writing a `.cmd` helper that swapped the binary on the next restart. `update` writes `.<name>.new`, renames the running binary out of the way to `.<name>.old`, renames `.new` into place, rolls back from `.old` on failure, and removes `.old` (ignored if still mapped by the running process). The swap now completes in-process and returns `status: "installed"` on every OS — Windows no longer returns a `scheduled`/restart-pending state.

### Fixed

- A failed/interrupted Skill sync during `update` is no longer misreported as a server error. `npx` missing (`FileNotFoundError`) or the Skill sync timing out (`subprocess.TimeoutExpired`) after the binary swap now surface as a PARTIAL SUCCESS (`ok:false`, `binary_replaced:true`, retryable) with `skill_sync_command` and `skill_sync_status: "failed"`, instead of escaping to a catch-all `E_SERVER`.
- A SIGINT/SIGTERM that lands **after** the binary swap no longer misstates the version. The interrupt handler now reports the true post-failure state — the actual stage, the new `current_version`, `binary_replaced: true`, and the `skill_sync_command` to finish — instead of hardcoding `stage: download` and the old version (CLI-SPEC §14 rule #1: never misstate the version).
- An interrupt during the verify stage is now classified as `E_INTERRUPTED` (retryable, exit 130) at the correct stage, never as a non-retryable `E_INTEGRITY`; transient network failures fetching verification material stay `E_NETWORK`.
- `replace_executable` now cleans up the half-written `.<name>.new` staging file on any failure or interrupt before the swap commits, so a later run never trusts a leftover artifact. `extract_binary` now closes the `tarfile` member handle returned by `extractfile()`, fixing a file-handle leak.

## [1.1.8] - 2026-06-22

### Added

- The cached update-available notice is now attached to **every command's `meta.notices`** (read-only from the local TTL-bounded cache, no network I/O), omitted when the cache has nothing to report. The fresh/active view still appears in `data.notices` on `context`, `doctor`, and `update --check`.
- Update notices are now **severity-graded** from the embedded CHANGELOG delta between the running version and the latest: `warning` when the delta contains a `security` entry or the latest crosses a major version, otherwise `info` (graded at check time and stored in the cache). `critical` remains reserved.

## [1.1.7] - 2026-06-21

### Changed

- `update` is now a SINGLE command with NO confirm token: a bare `outlook-cli update` resolves the latest (or `--target-version`) release, verifies its signature and checksum, replaces the binary, and syncs the Skill in one call. The previous `--dry-run` → `--confirm <token>` write gate has been removed from `update` (self-update is exempt from the §7 write gate; the safety guarantee is the in-process Sigstore verification, not a confirm token). `--check` and `--dry-run` remain OPTIONAL read-only previews and no longer issue a `confirm_token` or `expires_at`. `update` is idempotent: already-latest returns a no-op success. Other data-write commands keep the dry-run/confirm flow unchanged.

### Added

- Staged update failure & interruption contract: every update failure envelope now carries `stage` (`discover|download|verify_signature|verify_checksum|replace|skill_sync`), `current_version`, `binary_replaced`, and `skill_sync_status`. Replace-stage local failures are classified as `E_IO` (disk/io, exit 1) or `E_FORBIDDEN` (permission, exit 4) instead of being misreported as `E_NETWORK`. A Skill-sync failure after a successful binary swap is now a PARTIAL SUCCESS (`ok:false`, `binary_replaced:true`, retryable) carrying `skill_sync_command`, instead of a hard network error that hid the completed binary update.
- SIGINT/SIGTERM are trapped during `update`: the run unwinds to a clean state, the temp dir is always cleaned, and a terminal JSON envelope (`E_INTERRUPTED`, exit 130) is still emitted before exiting.
- New error codes `E_IO` (→ exit 1, non-retryable) and `E_INTERRUPTED` (→ exit 130, retryable) added to the output package and the code→exit mapping.

### Security

- Verification is unchanged and still fail-closed: signature-then-checksum order preserved, integrity failures remain non-retryable `E_INTEGRITY` (exit 1), and the embedded TUF root / in-process Sigstore path is untouched. Removing the confirm-token gate does not weaken integrity verification (the token was never an integrity mechanism).

## [1.1.6] - 2026-06-16

### Fixed

- npm `optionalDependencies` platform-package pins now match the package version. The previous release bumped the top-level version but left the pins at the prior version, so `npm install` resolved a stale platform binary (the new wrapper with the old binary). The publish workflow now rewrites `optionalDependencies` from the package version before `npm publish`, so the pins can no longer drift from the single source of truth.

## [1.1.5] - 2026-06-16

### Changed

- `update` is rewritten from package-manager delegation (pip/npm) to a verified binary self-update of the frozen executable: download the release archive + `checksums.txt` + Sigstore bundle, verify the signature **in-process** with the `sigstore` library (bundled into the frozen binary; TUF root embedded) against this repo's tagged release-workflow identity, verify the archive SHA256, and replace the running binary — no dependency on pip/npm. Releases are signed with `cosign sign-blob --new-bundle-format`.

### Security

- Verification is mandatory and fail-closed (no skip path); release-integrity failures return the non-retryable `E_INTEGRITY` code (exit 1) instead of a retryable network code.

## [1.1.4] - 2026-06-15

### Added

- Batch operations (CLI-SPEC §15): one command, one confirm token (single-use), one aggregated `items[].{target,ok,error{code,retryable}}` + `summary{total,succeeded,failed}` result. Plural inputs accept comma-separated or repeated forms and de-duplicate while preserving order; partial failures do not roll back, and `--continue-on-error` (default true) controls stop-on-first-failure.
  - `mail batch` gains `categorize` (`--categories`), `flag`, `unflag`, `complete`, and `restore` actions on top of the existing `delete`/`mark-read`/`mark-unread`/`move` (class B, client-side loop).
  - `mail draft-send` accepts plural `--ids` and sends a whole batch via native `account.bulk_send` (class A); a single `--id` is a batch of one with the same envelope.
  - `cal batch --action create|update|delete` via native `account.bulk_create`/`bulk_update`/`bulk_delete` (class A). `create`/`update` take a JSON `--file`; `delete` takes plural `--ids`. `--send-notifications` (default true) controls meeting invitations/cancellations. Bulk delete is soft (moves to Deleted Items, recoverable) per the soft-delete-only policy.
- `cal batch --action delete` joins `mail batch --action delete` as a `--dangerous` two-step-gated command (required in both dry-run and confirm steps).

### Changed

- npm scope 迁移 `@fatecannotbealtered-` → `@fateforge`（无横线 org 在 npm 被占，迁移到 `@fateforge`）。根包及 6 个平台 optionalDependencies 包名同步改为 `@fateforge/outlook-cli[-<os>-<arch>]`；GitHub org / go module path / `npx skills add` 源 / release URL 中的裸 `fatecannotbealtered` 不变。
- `mail batch` and `mail draft-send` result shape moved to the §15.5 batch contract (`items[]` + `summary{total,succeeded,failed}`), replacing the previous `success`/`failed_ids`/`results` shape.

### Fixed

- `mail list` no longer raises `E_SERVER: 'CalendarItem' object has no attribute 'sender'` when a folder (e.g. Deleted Items / trash) holds non-Message items such as a cancelled-meeting `CalendarItem`. The item→dict conversion now reads `sender`, `to_recipients`, `cc_recipients`, `datetime_received`, `subject`, `is_read`, and `attachments` defensively via `getattr`, returning safe defaults (`sender="unknown"`, empty lists, empty date) for non-mail items.

## [1.1.3] - 2026-06-14

### Added

- `mail read` now surfaces inline (cid) images in an `inline_images` list, separated from attachments.
- T2 `--dangerous` second gate (both dry-run and confirm) for `folders empty`, `folders delete`, `mail batch --action delete`, `tools oof set`, `tools oof disable`.
- `reference` now exposes a real per-command `output_schema` + `examples[]`, guarded against regression.

### Changed

- Confirm tokens are now single-use (E_CONFLICT on replay) and bind the item `changekey` as resource version where available.
- `mail reply`/`reply-all`/`forward --attachments` now preserve recipients (cc), `In-Reply-To` threading, and original attachments.
- `mail search --sender` filters server-side, so `total`/`has_more` are accurate for large result sets.
- `context.credentials.valid` now reflects a cached real credential probe instead of copying `configured`.

## [1.1.2] - 2026-06-14

### Added

- `cal get --id <event_id>` — a first-class single-event read returning the same flattened, `_untrusted`-tagged shape as `cal list` items, so an agent can read one event without re-scanning a list.

### Changed

- `handle_api_error` now classifies failures by exception **type** (and its base classes) first — `ErrorServerBusy`/`RateLimitError` → `E_RATE_LIMITED`, `ErrorItemNotFound`/`ErrorFolderNotFound` → `E_NOT_FOUND`, timeouts → `E_TIMEOUT`, etc. — and only falls back to message-substring sniffing for unmapped errors. This makes `E_RATE_LIMITED`/`E_TIMEOUT` reachable and stops misclassifying messages that merely contain words like "not found".

### Fixed

- The error envelope and `print_flat_json` now honor the global `--compact` flag instead of hard-coding compact JSON, so the same command produces consistent whitespace on success and error.

## [1.1.1] - 2026-06-12

### Added

- `--bcc` support on `mail send` and `mail draft-edit`; BCC recipients now appear in `draft-read` output (tagged `_untrusted`) and `draft-send` dry-run previews so agents can verify the full recipient list before sending.
- `mail draft-edit` now supports `--html` and `--attachments` (appended to the draft), closing the gap with `mail send` so the draft-review workflow covers formatted mail with attachments.
- Recorded live smoke evidence against a real Exchange mailbox (`docs/live-smoke-evidence.md`); `release_readiness` is now `stable` with `live_smoke_status: verified`.
- FCC enumeration guard (`tests/test_fcc_guard.py`): enumerates every leaf command from live `reference` output and asserts each has a command-level test; skips while `fcc_status` is honestly declared non-verified, so the claim cannot be flipped without coverage.
- Command-level tests for `setup login` (validation, dry-run token, confirm-required, password redaction) and `tools free-busy` / `tools rooms-free-busy` (usage and config-missing paths) — the three leaves the guard found uncovered.
- darwin-arm64 (Apple Silicon) and linux-arm64 platform packages, built on `macos-14` and `ubuntu-24.04-arm` runners.
- Added runtime `changelog [--since]` derived from `CHANGELOG.md`.
- Added version, schema, Skill compatibility, risk tier, permission, and security metadata to self-description output.
- Added `_untrusted` markers to externally sourced Outlook fields returned to agents.
- Added resource-aware confirm-token payloads that bind operation args, account, permission mode, and resource identity/version when available.

### Changed

- Synced the `.agent/` spec copies from the ai-native-cli-spec template: stdout failure envelope (§4), HMAC confirm-token requirement (§7), signature_status/signature_verified fields (§14), Skill frontmatter `version` rule.
- In JSON mode the failure envelope is now the single JSON document on stdout (stderr keeps a short human-readable line), matching CLI-SPEC §4: agents always parse stdout and check `ok` first.
- Normalized command output timestamps to ISO 8601 UTC. The output schema version stays `1.0`: nothing has been released yet, so there are no external consumers of any earlier envelope shape and the first published contract starts at `1.0`.
- Changed write dry-runs to enter command-specific preview paths instead of returning only a generic command preview.
- Changed `mail batch` to return per-item results and bind batch confirm tokens to the observed item versions.
- Expanded audit records with UTC timestamps, account context, local-write command coverage, and confirm-token redaction.
- Removed the rules `--permanent-delete` authoring option so CLI-created rules honor the soft-delete-only policy.
- Removed pre-1.1 `--preview` / `--send` compatibility flags; write commands now use only `--dry-run -> --confirm`.
- Made `mail read` non-mutating; use `mail mark --status read` for read-state changes.
- Self-update now syncs the whole Agent Skill directory through `npx skills add fatecannotbealtered/outlook-cli -y -g` and reports `skill_sync_status`.
- Skill, README, `.agent/` specs, and test prompts now follow the unified Agent-first update and Skill sync contract.

### Security

- Exchange password now lives in the OS keyring; `config.json` keeps zero secrets, only a `password_storage` marker. Machine-bound AES encryption remains as the fallback when no keyring backend exists, and `context.data.credentials.storage` reports the active backend. Adds the `keyring` dependency.
- Synced `.agent/` SEC-SPEC from the template: credential-at-rest is now the keyring three-part pattern (password discarded after login / secrets in the OS keyring / zero-secret config), file encryption demoted to a visible fallback, env vars as the recommended secret channel, and an honest note on Windows `0600` semantics.
- Documented the tool as a T1 AI-native CLI and aligned mailbox content handling with the untrusted-content convention.
- Release checksums are signed with Sigstore/Cosign, and install/update paths report signature verification status separately from checksum verification.
- Made npm postinstall checksum verification hard-fail when checksums are missing or invalid.

### Fixed

- `mail thread` help text rendered as mojibake on non-UTF-8 consoles (em dash in docstring replaced with ASCII).
- `iso_utc` crashed with `InvalidTypeError` on exchangelib 5.x `EWSDateTime` values (rejects `astimezone(timezone.utc)`), breaking `mail list` against a live server; timestamps are now rebuilt from the epoch. Found by live smoke.
- JSON output was mangled on Windows GBK consoles; stdout/stderr are now reconfigured to UTF-8 at the entry point per the CLI contract.

## [1.1.0] - 2026-06-07

### Added

- **Agent-safe CLI contract**: JSON is now the default machine output with a stable `ok` / `schema_version` / `data` / `meta` envelope and matching error envelope.
- **Global output controls**: added `--format json|text|raw`, `--fields`, `--compact`, and `--confirm`; `--json` remains as a compatibility alias.
- **Dry-run/confirm flow**: mutating operations now require `--dry-run` followed by `--confirm <token>`, with operation-bound confirm tokens.
- **Self-description commands**: added top-level `reference`, `context`, and `doctor` commands for Agent discovery and environment checks.
- **Self-update command**: added `update --check`, `update --dry-run`, and `update --confirm <token>` with npm/pip/manual update manager support.

### Changed

- **Exit code contract**: error exits now follow the Agent CLI semantic table, including confirmation-required and conflict codes.
- **Setup flow**: `setup login` is non-interactive in machine mode and participates in the dry-run/confirm flow.
- **Legacy safety flags**: pre-1.1 `--preview` / `--send` command flags are compatibility-only and hidden from help/reference output.
- **Documentation**: README and README_zh now document the self-update workflow.

## [1.0.3] - 2026-05-06

### Fixed

- **search/list ID usable with read**: `find_mail_by_id` now looks up by Exchange ItemId (`.get()`) first, then falls back to MIME `message_id` filter. search → read workflow works end-to-end.
- **Preview length**: `email_to_dict` preview increased from 200 to 500 characters.
- **NOT_FOUND hint**: added troubleshooting direction for ID-related failures.

## [1.0.2] - 2026-05-06

### Security

- **Audit hook wired**: `_audit_hook` now fires via `ctx.call_on_close`, write commands produce audit records.
- **Irreversible op guards**: `cal create/update/delete` (with attendees), `tools oof set/disable`, `tools respond` now require `--preview` or `--send`.
- **PBKDF2 salt uniqueness**: salt derived from machine_id (SHA256), iterations bumped from 100k to 600k (OWASP 2023).
- **Atomic config write**: `tempfile` + `os.replace` prevents corruption on crash.
- **Decryption error handling**: `decrypt()` raises `DecryptionError` instead of returning empty string.
- **Audit log sanitization**: `--password=value` form now properly stripped.
- **Plaintext fallback warning**: `encrypt()` prints stderr warning when cryptography is unavailable.

### Fixed

- **`--json`/`--quiet`/`--dry-run` at any position**: custom `FlexibleGroup` extracts global flags from any CLI position. `mail list --json` now works.
- **`mail list`/`search`/`drafts` human output includes short ID**: enables `list → read` workflow.
- **`mail_search` pagination**: client-side sender filter now correctly computes `total`/`has_more`/`next_offset`.
- **`mail read` ID field**: returns Exchange ItemId (not MIME Message-ID) for consistency with `--id` flags.
- **`email_to_dict` ID field**: unified to Exchange ItemId across all commands.
- **`rules_update` merge**: conditions/actions merge with existing (additive), exceptions properly handled.
- **`find_mail_by_id`**: recursive → iterative BFS with depth limit 20, prevents `RecursionError`.
- **Thread safety**: `threading.Lock` on `exchange._account` and `crypto._fernet` globals.
- **Config load error**: corrupted JSON now warns instead of silently returning empty dict.
- **Permission mode validation**: invalid `OUTLOOK_PERMISSIONS` value warns and falls back to `read-only`.
- **`cal_create` time validation**: end time must be after start time.
- **`mail_export` MIME check**: errors gracefully when `mime_content` is unavailable.
- **Attachment download dedup**: same-name attachments get `_N` suffix.
- **macOS UUID parsing**: regex replaces fragile `split('"')[-2]`.
- **`setup_login` env var cleanup**: properly restores original env vars on failure.
- **Audit cleanup month arithmetic**: year-month subtraction replaces `months * 30` days.
- **Audit cleanup frequency**: runs once per month instead of every `log()` call.
- **`handle_api_error` matching**: "connect" no longer matches "disconnect"/"reconnect".

### Changed

- **`--dry-run` on all write commands**: expanded from 2/30 to 30/30 write commands.
- **All error messages in English**: 40+ Chinese messages converted to English for consistency.
- **`print_flat_json`**: `indent=None` (was `indent=2`), truly token-efficient for AI agents.
- **`dry_run_output`**: returns `None`, outputs JSON in `--json` mode.
- **`_NO_COLOR`**: evaluated at runtime (was frozen at import time).
- **`pass_dry_run`**: added `@functools.wraps` for correct Click help text.
- **`build.py`**: `--collect-all exchangelib` replaces 4 `--hidden-import` entries.
- **`install.js`**: checksum verification now hard-fails on mismatch.
- **Work hours**: configurable via `OUTLOOK_WORK_START`/`OUTLOOK_WORK_END` env vars (default 08-18).
- **Folder output**: `_folder_to_dict` includes `id` field.

### CI/CD

- **`ruff format --check`** added to CI pipeline (equivalent to `gofmt`).
- **Release notes**: CHANGELOG.md extracted per-version for GitHub Release page.

## [1.0.1] - 2026-05-03

### Fixed

- **PyInstaller binary crash**: fixed `ImportError: attempted relative import with no known parent package` by adding a top-level `cli.py` entry point with absolute imports for the binary build. Added explicit `--hidden-import` flags for all submodules (including lazy imports inside functions).
- Build script (`build.py`) now uses `cli.py` as entry point instead of `outlook_cli/main.py`.

## [1.0.0] - 2026-05-03

Initial release of outlook-cli for Microsoft Exchange.

### Features

- **50 atomic CLI commands** across 6 command groups:
  - `mail` (24 commands): list, search, read, stats, thread, attachment-summary, export, download-attachment, move, mark, flag, categorize, restore, batch, delete, send, reply, reply-all, forward, drafts, draft-read, draft-edit, draft-send, draft-delete
  - `cal` (4 commands): list, create, update, delete
  - `folders` (6 commands): list, create, rename, move, empty, delete
  - `rules` (5 commands): list, create, update, delete, toggle
  - `tools` (8 commands): contacts, free-busy, rooms, rooms-free-busy, oof get/set/disable, respond
  - `setup` (3 commands): login, status, doctor
- **Permission system** with three levels: read-only (default), write, full — CLI provides no command to change permissions, human-only edit.
- **Send safety**: send/reply/forward require explicit `--preview` or `--send` flag; bare command is rejected.
- **Soft delete only**: all delete operations go to trash, no permanent deletion.
- **Dual output mode**: `--json` for machine-readable flat format (token-efficient for AI Agents), human-friendly colored output by default.
- **Audit logging**: automatic JSONL audit trail for all write commands (`~/.outlook-cli/audit/`), monthly file rotation, configurable retention (default 3 months). Disable with `OUTLOOK_NO_AUDIT=1`.
- **Global flags**: `--json`, `--quiet`, `--dry-run`, `--account`.
- **Error code taxonomy**: CONFIG_ERROR, AUTH_REQUIRED, FORBIDDEN, NOT_FOUND, VALIDATION_ERROR, SERVER_ERROR, NETWORK_ERROR with actionable hints.
- **Credential encryption**: AES-256-GCM with machine-bound key derived via PBKDF2.
- **PyInstaller binary packaging** for Windows, macOS (Intel/ARM), Linux.
- **npm distribution**: `npm install -g @fateforge/outlook-cli` with bundled AI Agent Skill.
- **Environment variables**: `OUTLOOK_EMAIL`, `OUTLOOK_PASSWORD`, `OUTLOOK_SERVER`, `OUTLOOK_TIMEZONE`, `OUTLOOK_PERMISSIONS` override config file for CI/Agent use.

### Documentation

- Bilingual README (English + Chinese) with CI/License/npm badges.
- Security section with AI Agent risk warning.
- Project structure tree, Troubleshooting table, JSON output examples.
- SKILL.md with complete command reference and usage patterns.
- SECURITY.md with vulnerability reporting and credential handling design.

[Unreleased]: https://github.com/fatecannotbealtered/outlook-cli/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/fatecannotbealtered/outlook-cli/compare/v1.0.3...v1.1.0
[1.0.3]: https://github.com/fatecannotbealtered/outlook-cli/compare/v1.0.2...v1.0.3
[1.0.2]: https://github.com/fatecannotbealtered/outlook-cli/compare/v1.0.1...v1.0.2
[1.0.1]: https://github.com/fatecannotbealtered/outlook-cli/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/fatecannotbealtered/outlook-cli/releases/tag/v1.0.0
