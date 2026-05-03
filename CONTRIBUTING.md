# Contributing

Thank you for improving outlook-cli. This document describes how to build, test, and submit changes.

**Note:** This is a side project shared for learning and personal use; maintainers do not offer commercial support or production guarantees — see the readme disclaimer.

## Development setup

- Python **3.10+**
- Optional: **Node.js 16+** if you work on npm install scripts

Clone and verify:

```bash
git clone https://github.com/fatecannotbealtered/outlook-cli.git
cd outlook-cli
pip install -e ".[dev]"
pytest tests/ -v
python -m outlook_cli.main --help
```

## Commands

| Goal | Command |
|------|---------|
| Run tests | `pytest tests/ -v` |
| Run tests with coverage | `pytest tests/ -v --cov=outlook_cli` |
| Lint | `ruff check outlook_cli/ tests/` |
| Format | `ruff format outlook_cli/ tests/` |
| Build binary | `python build.py` |
| Install dev | `pip install -e ".[dev]"` |

CI mirrors `.github/workflows/ci.yml`: lint with ruff, pytest on Python 3.10/3.11/3.12, `--help` smoke test.

## Integration tests

Integration tests hit a **real Exchange server**. They are skipped by default — set these env vars to enable:

```bash
# Required
set OUTLOOK_IT_EMAIL=user@company.com
set OUTLOOK_IT_PASSWORD=your-password

# Optional (set if autodiscover is not available)
set OUTLOOK_IT_SERVER=mail.company.com

# Run
python -m pytest tests/test_integration.py -v
```

What they cover (66 tests, ~15 min):

| Group | Tests | What it does |
|-------|-------|--------------|
| `TestStep1Connection` | 2 | `setup status`, `setup doctor` |
| `TestStep2MailRoundTrip` | 19 | send → search → read → list → filter → thread → mark → flag → categorize → move → restore → stats → attachment-summary → export → download → reply/forward preview → batch preview → keyword search → delete cleanup |
| `TestStep2bSendVariants` | 10 | HTML send, attachment send, real reply, real reply-all, real forward, verification, cleanup |
| `TestStep3DraftRoundTrip` | 6 | create → list → read → edit → send preview → delete |
| `TestStep4CalendarRoundTrip` | 4 | create → list → update → delete |
| `TestStep4bCalendarVariants` | 4 | multi-attendees, subject filter |
| `TestStep5FolderRoundTrip` | 6 | list → create → rename → move → empty → delete |
| `TestStep6RulesRoundTrip` | 5 | list → create → update → toggle → delete |
| `TestStep7Tools` | 8 | contacts, contacts query, free-busy, rooms, rooms-free-busy, OOF get/set/disable/time-range, respond |

All tests are self-contained: each round-trip creates its own data, verifies, then cleans up. No impact on other people's mailboxes.

**CI note:** Integration tests are **not** run in CI (no real credentials in GitHub Actions). Run them locally before tagging a release.

## Pull requests

1. **One logical change per PR** when possible.
2. **Tests**: add or update tests for behavior changes in `outlook_cli/` or stable CLI contracts.
3. **Docs**: update `README.md` / `README_zh.md` if user-facing flags or flows change; add a line to `CHANGELOG.md` under *Unreleased*.
4. **Commits**: clear messages; no secrets or real credentials in code or docs.

## Commit messages

- `feat: add new command for X`
- `fix: resolve issue with Y`
- `docs: update README`
- `test: add tests for Z`
- `refactor: improve code structure`

## AI Agent skill bundle

Bundled skills live under `skills/outlook-cli/`. After editing SKILL.md, test that the skill activates correctly with a compatible AI coding assistant.

## Security

Do not open public issues for undisclosed security vulnerabilities. See [SECURITY.md](SECURITY.md).

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
