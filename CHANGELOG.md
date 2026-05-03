# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/fatecannotbealtered/outlook-cli/compare/v1.0.1...HEAD
[1.0.1]: https://github.com/fatecannotbealtered/outlook-cli/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/fatecannotbealtered/outlook-cli/releases/tag/v1.0.0
