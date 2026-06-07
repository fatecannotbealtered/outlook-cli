# AI-Native Open-Source Repo Spec


This document defines a unified repo standard for all your open-source projects: required docs, template files, directory layout, release conventions. The goal: ten projects look the same, and anyone (including an AI agent) entering any repo finds the same things in the same places.

Companion specs (all under `.agent/`, entry is `AGENT.md`):

- `AGENT.md` — entry / playbook: how to build & extend a tool here, navigates to the four below.
- `CLI-SPEC.md` — the CLI machine contract (how the tool speaks).
- `SKILL-SPEC.md` — Skill authoring spec (how the agent uses it).
- `SEC-SPEC.md` — security baseline (how not to get burned, or burn others).
- This doc — repo skeleton (what the project looks like).

## 1. File manifest (required matrix)

Levels: **MUST** required; **SHOULD** strongly recommended; **optional** as needed.

| File | Level | Role |
|------|-------|------|
| `README.md` | MUST | project front door: what it is, how to install, how to use |
| `README_zh.md` | SHOULD | Chinese version (i18n convention in §3) |
| `LICENSE` | MUST | open-source license (default MIT) |
| `CHANGELOG.md` | MUST | version change log (Keep a Changelog + SemVer) |
| `CONTRIBUTING.md` | MUST | how to contribute: env, branch, commit, test, PR flow |
| `SECURITY.md` | MUST | vulnerability disclosure channel and supported versions |
| `CODE_OF_CONDUCT.md` | SHOULD | code of conduct (Contributor Covenant) |
| `NOTICE.md` | MUST† | third-party trademark / attribution notice (†required when wrapping a third-party product) |
| `docs/COMPATIBILITY.md` | MUST† | verified backend version matrix (†required when integrating an external system) |
| `docs/OPEN_SOURCE_CHECKLIST.md` | SHOULD | security gate checklist before the first public push |
| `docs/E2E.md` | SHOULD† | E2E / integration test environment notes (†recommended when calling external APIs) |
| `.gitignore` | MUST | ignore build artifacts, venvs, IDE, caches by language |
| `.github/workflows/ci.yml` | MUST | on push / PR: lint + test |
| `.github/workflows/release.yml` | SHOULD | on tag: build + publish |
| `.github/ISSUE_TEMPLATE/` | SHOULD | bug / feature templates |
| `.github/PULL_REQUEST_TEMPLATE.md` | SHOULD | PR self-check checklist |
| `.github/dependabot.yml` | optional | dependency updates |
| `AGENTS.md` | MUST* | cross-tool entry hook, points to `.agent/AGENT.md` |
| `.agent/AGENT.md` | MUST* | AI-native tool entry / playbook, navigates to the four specs below |
| `.agent/CLI-SPEC.md` | MUST* | the CLI machine contract (*CLI projects only) |
| `.agent/SKILL-SPEC.md` | MUST* | Skill authoring spec (*projects with a Skill) |
| `.agent/SEC-SPEC.md` | MUST* | security baseline (risk tiers + injection/privilege/credential/supply-chain) |
| `skills/<name>/SKILL.md` | MUST* | Agent Skill (*required for AI-native tools) |

`*` items are specific to "AI-native tools" — a plain library may omit them, but any agent-facing CLI / tool must have them. `†` items are scenario-triggered: wrapping a third-party product (Outlook/Exchange, GitLab, Jira, Kibana, etc.) requires the trademark notice and compatibility matrix.

## 2. Required README skeleton

Every README follows a fixed order, for easy cross-comparison:

1. **Title + one-line positioning** + badges (version / CI / license / language switch link)
2. **What** — one paragraph: what problem it solves, for whom (human / agent / both)
3. **Install** — copy-paste-runnable install blocks (CLI install and Skill install listed separately)
4. **Quick Start** — minimal working example (configure → verify → first command)
5. **Usage / Commands** — core capabilities, detail points to `reference` or a separate doc
6. **Configuration** — config items, environment variables, credential location
7. **For AI Agents** — agent onboarding, points to `SKILL.md` and `.agent/CLI-SPEC.md`
8. **Development** — local dev, build, test
9. **License / Contributing / Security** — point to the respective files

Conventions:

- Install blocks must be copy-paste-runnable, with prerequisites noted.
- Example commands use real runnable forms, time as ISO 8601, ID as placeholder `<message-id>`.

## 3. Internationalization (i18n) convention

- Primary doc in English `README.md`, Chinese `README_zh.md`, filename gets a `_zh` suffix.
- The two link to each other at the top.
- Other governance docs (CONTRIBUTING / SECURITY / code of conduct) are English-only by default, unless the project is primarily for a Chinese community.
- Bilingual docs are **kept in sync**: change one, change the other; CI may add a link / section consistency check.

## 4. Versioning and release convention

- **SemVer**: `MAJOR.MINOR.PATCH`. Breaking changes bump MAJOR, backward-compatible additions bump MINOR, fixes bump PATCH.
- The tool version (package version) is decoupled from the CLI's output `schema_version` — the latter bumps only when the JSON contract breaks (see `CLI-SPEC.md`).
- **CHANGELOG uses Keep a Changelog format**: `Unreleased` on top, split into `Added/Changed/Fixed/Deprecated/Removed/Security`.
- A release means tagging git `vX.Y.Z`, triggering build & publish via `release.yml`.
- Single source of truth for the version number (e.g. `package.json` / `setup.py`); everything else references it, no hand-copying.

### CHANGELOG single source of truth

`CHANGELOG.md` is the only human-maintained change source; everything else is **derived**, must not be separately maintained, and derived artifacts must not be committed:

```
CHANGELOG.md (human-maintained, single source of truth)
   ├─ release.yml slices the "## [version]" section → GitHub Release body (generated at build)
   └─ embedded into the binary at build → runtime changelog command (see CLI-SPEC.md §11)
```

- release-notes are generated by `release.yml` at release time (`sed -n "/^## \[VERSION\]/,/^## \[/p"`), **don't keep a hand-maintained `release-notes.md` in the repo**.
- The runtime `changelog` command reuses the same CHANGELOG, embedded at build — zero new source, just one more outlet.

## 4b. Distribution convention (npm wrapper)

Cross-language tools distribute via a uniform npm wrapper, so Go binaries and Python packages both `npm install -g` and are called consistently by agents:

- `package.json` declares the scoped package name and the `bin` entry.
- `scripts/install.js`: at install, fetch / link the platform binary into `bin/`.
- `scripts/run.js`: a thin forwarding layer, `execFileSync` invoking the real binary, passing through `argv` and stdio, with an actionable reinstall hint if the binary is missing.
- The binary itself (`bin/`, `*.exe`, `dist/`) goes into `.gitignore`, produced by CI, not committed.

## 5. Directory layout convention

```text
project/
├── README.md / README_zh.md
├── LICENSE / CHANGELOG.md / CONTRIBUTING.md / SECURITY.md
├── .gitignore
├── AGENTS.md                   # cross-tool entry hook, points to .agent/AGENT.md
├── .github/
│   ├── workflows/{ci,release}.yml
│   ├── ISSUE_TEMPLATE/
│   └── PULL_REQUEST_TEMPLATE.md
├── .agent/                     # AI-native specs
│   ├── AGENT.md                # entry / playbook
│   ├── CLI-SPEC.md             # CLI machine contract
│   ├── SKILL-SPEC.md           # Skill authoring spec
│   ├── SEC-SPEC.md             # security baseline
│   └── REPO-SPEC.md            # repo skeleton spec
├── skills/<name>/SKILL.md      # Agent Skill
├── <package>/                  # source (package name)
├── tests/                      # tests, structure mirrors source
├── scripts/                    # dev / build helper scripts
└── <build manifest>            # language-specific: package.json / setup.py / pyproject.toml ...
```

Conventions:

- Source, tests, scripts, docs each in their place, not dumped in the root.
- Test directory mirrors the source structure, for easy locating.
- Build artifacts, caches, venvs, IDE config all go into `.gitignore`, not committed.

## 6. Quality gate convention

- CI must run lint + tests; red means no merge.
- A unified formatter (by language: Python ruff, JS prettier, etc.), config committed, no manual alignment.
- The PR template has built-in self-check items: tests pass, docs synced, CHANGELOG updated, bilingual synced.

## 7. New-project checklist

- [ ] `README.md` (+ `README_zh.md` as needed) follows the §2 skeleton
- [ ] `LICENSE` chosen
- [ ] `CHANGELOG.md` initialized, with `Unreleased`
- [ ] `CONTRIBUTING.md` / `SECURITY.md` in place
- [ ] `.gitignore` set up by language
- [ ] `.github/workflows/ci.yml` (lint + test) in place
- [ ] Single source of truth for version; CHANGELOG is the only change source, derived artifacts not committed
- [ ] Source / tests / scripts separated, tests mirror source
- [ ] Formatter config committed, enforced in CI
- [ ] (npm wrapper) `package.json` + `scripts/{install,run}.js`, binary not committed
- [ ] (wrapping a third-party product) `NOTICE.md` + `docs/COMPATIBILITY.md` in place
- [ ] (calling external APIs) `docs/E2E.md` + integration tests in place
- [ ] `docs/OPEN_SOURCE_CHECKLIST.md` in place, run through before the first push
- [ ] (AI-native tool) root `AGENTS.md` + `.agent/{AGENT,CLI-SPEC,SKILL-SPEC,SEC-SPEC,REPO-SPEC}.md` + `skills/<name>/SKILL.md` complete
- [ ] PR / Issue templates in place
