# Security Policy

## Supported Versions

Security fixes are applied to the latest minor release on the default branch (`main`). Release binaries are published via GitHub Releases and the npm package `outlook-cli`.

## Security Design

outlook-cli implements several security measures to protect users:

### Credential Storage

- Credentials are stored in `~/.outlook-cli/config.json` with file permissions `0600`
- The config directory has permissions `0700`
- **Password is encrypted** with AES-256-GCM, derived from a machine fingerprint (hostname + CPU + platform identifiers)
- Encrypted password only decryptable on the same machine — moving the config file to another machine will fail
- Backward compatible: legacy plaintext passwords are read transparently, encrypted on next `setup login`
- Environment variable `OUTLOOK_PASSWORD` takes precedence over config file (plain text, never written to disk)
- Sensitive flags (`--password`, `--token`) are stripped from audit logs

### Permission System

Three permission levels prevent unauthorized operations:

- **read-only** (default): Only read operations are allowed
- **write**: Includes move, delete, create, update operations
- **full**: Includes send, reply, forward operations

The permission level is stored in the config file. **The CLI provides no command to change permissions** — this must be done by manually editing the config file.

### Send Safety

Commands that send email (`send`, `reply`, `reply-all`, `forward`, `draft-send`) require an explicit `--preview` or `--send` flag. Without these flags, the command is rejected. This prevents accidental email sending.

### Soft Delete

All delete operations move items to trash. There is no permanent delete command. Deleted items can be recovered using the `restore` command.

### Audit Logging

All write operations are logged to `~/.outlook-cli/audit/` in JSONL format:
- Monthly file rotation
- Configurable retention period (default: 3 months)
- Sensitive arguments are sanitized
- Can be disabled with `OUTLOOK_NO_AUDIT=1`

## Reporting a Vulnerability

Please **do not** file a public GitHub issue for undisclosed security vulnerabilities.

Instead, report privately via [GitHub Security Advisories](https://github.com/fatecannotbealtered/outlook-cli/security/advisories/new) for this repository, or contact the maintainers through the contact options on the repository homepage.

Include:

- Description of the issue and impact
- Steps to reproduce (if safe to share)
- Affected versions or install methods (npm / binary)

You should receive an acknowledgment as capacity allows. Thank you for helping keep users safe.

## Credential handling (design)

- Credentials are stored only in `~/.outlook-cli/config.json` with file mode `0600` and directory `0700`.
- Password is encrypted at rest with AES-256-GCM using a machine-bound key derived via PBKDF2 (100k iterations, SHA-256).
- Machine fingerprint combines hostname, CPU info, and platform-specific identifiers (Windows MachineGuid, Linux machine-id, macOS IOPlatformUUID).
- Encrypted passwords are prefixed with `enc:v1:` for detection; legacy plaintext configs work transparently.
- Password input is hidden with hidden input in interactive terminals.
- Sensitive flags (`--password`, `--token`) are stripped from audit logs.
- Environment variables `OUTLOOK_EMAIL` and `OUTLOOK_PASSWORD` take precedence over config file; prefer them in CI/Agent workflows to avoid persisting credentials on disk.

Review these assumptions when integrating outlook-cli into automation or AI agent workflows.
