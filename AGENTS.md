# Agent Entry

This repository is an AI-native CLI project. Agents must start with
`.agent/AGENT.md`, then read only the spec needed for the current task:

- `.agent/CLI-SPEC.md` for command/output/error contract changes.
- `.agent/SEC-SPEC.md` for security, untrusted content, credentials, and supply chain.
- `.agent/SKILL-SPEC.md` for `skills/outlook-cli/SKILL.md` changes.
- Shared [`REPO-SPEC.md`](https://github.com/fatecannotbealtered/ai-native-cli-spec/blob/main/REPO-SPEC.md) for repository layout, release, and documentation changes.

Before completing work, run the relevant checklist from the spec you touched.

Before release, Functional Contract Coverage must remain 100%: every public README / Skill / reference / help / context / doctor / changelog / update behavior needs command-level tests.
