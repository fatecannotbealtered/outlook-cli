# Open Source Checklist

Run this checklist before publishing or cutting a release.

- [ ] `README.md` and `README_zh.md` are in sync.
- [ ] `CHANGELOG.md` contains the release section.
- [ ] `NOTICE.md` and `docs/COMPATIBILITY.md` describe Microsoft/Exchange scope.
- [ ] `SECURITY.md` records the risk tier, credential model, and report channel.
- [ ] `outlook-cli reference --compact` includes commands, permissions, risk tier, and security metadata.
- [ ] `outlook-cli context --compact` reports version and credential status without secrets.
- [ ] `outlook-cli doctor --compact` reports version compatibility.
- [ ] `outlook-cli changelog --since <old-version>` works from `CHANGELOG.md`.
- [ ] `python -m pytest -q` passes.
- [ ] `ruff check outlook_cli/ tests/` passes.
- [ ] `ruff format --check outlook_cli/ tests/` passes.
- [ ] Release artifacts are built by CI from a signed/tagged source revision.
- [ ] npm postinstall verifies checksums and hard-fails on mismatch.
