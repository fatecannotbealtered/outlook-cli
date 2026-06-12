# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- darwin-arm64 (Apple Silicon) and linux-arm64 platform packages, built on `macos-14` and `ubuntu-24.04-arm` runners.
- Added runtime `changelog [--since]` derived from `CHANGELOG.md`.
- Added version, schema, Skill compatibility, risk tier, permission, and security metadata to self-description output.
- Added `_untrusted` markers to externally sourced Outlook fields returned to agents.
- Added resource-aware confirm-token payloads that bind operation args, account, permission mode, and resource identity/version when available.

### Changed

- Synced the `.agent/` spec copies from the ai-native-cli-spec template: stdout failure envelope (§4), HMAC confirm-token requirement (§7), signature_status/signature_verified fields (§14), Skill frontmatter `version` rule.
- In JSON mode the failure envelope is now the single JSON document on stdout (stderr keeps a short human-readable line), matching CLI-SPEC §4: agents always parse stdout and check `ok` first.
- Bumped the CLI output schema to `2.0` and normalized command output timestamps to ISO 8601 UTC.
- Changed write dry-runs to enter command-specific preview paths instead of returning only a generic command preview.
- Changed `mail batch` to return per-item results and bind batch confirm tokens to the observed item versions.
- Expanded audit records with UTC timestamps, account context, local-write command coverage, and confirm-token redaction.
- Removed the rules `--permanent-delete` authoring option so CLI-created rules honor the soft-delete-only policy.
- Removed pre-1.1 `--preview` / `--send` compatibility flags; write commands now use only `--dry-run -> --confirm`.
- Made `mail read` non-mutating; use `mail mark --status read` for read-state changes.
- Self-update now syncs the whole Agent Skill directory through `npx skills add fatecannotbealtered/outlook-cli -y -g` and reports `skill_sync_status`.
- Skill, README, `.agent/` specs, and test prompts now follow the unified Agent-first update and Skill sync contract.

### Security

- Documented the tool as a T1 AI-native CLI and aligned mailbox content handling with the untrusted-content convention.
- Release checksums are signed with Sigstore/Cosign, and install/update paths report signature verification status separately from checksum verification.
- Made npm postinstall checksum verification hard-fail when checksums are missing or invalid.


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
- **npm distribution**: `npm install -g @fatecannotbealtered-/outlook-cli` with bundled AI Agent Skill.
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
