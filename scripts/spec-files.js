// spec-files.js — the single registry of files that are SOURCED FROM the
// ai-native-cli-spec template and must stay byte-identical to a pinned spec tag.
// Both sync-spec.js (writer) and check-spec.js (verifier) consume this list, so
// adding a spec-synced file is covered by both automatically. Paths are relative
// to the template's `template/common/` (source) and to a tool's repo root (dest);
// the mapping is 1:1.
//
// These are the "managed in ONE place" assets: the .agent behavioral specs, the
// canonical JSON contract, and the sync/check tooling itself. A tool never
// hand-edits them — it bumps .agent/SPEC_VERSION and re-runs sync-spec.

"use strict";

module.exports = {
  // the .agent behavioral specs (bilingual)
  agentSpecs: [
    ".agent/AGENT.md",
    ".agent/AGENT_zh.md",
    ".agent/CLI-SPEC.md",
    ".agent/CLI-SPEC_zh.md",
    ".agent/SEC-SPEC.md",
    ".agent/SEC-SPEC_zh.md",
    ".agent/SKILL-SPEC.md",
    ".agent/SKILL-SPEC_zh.md",
  ],
  // the canonical machine-readable JSON contract
  contract: ["contract/contract.json"],
  // the sync/check/codegen tooling (kept in lockstep across the fleet)
  tooling: [
    "scripts/spec-files.js",
    "scripts/gen-contract.js",
    "scripts/sync-spec.js",
    "scripts/check-spec.js",
  ],
  // everything that must match the pinned spec tag
  all() {
    return [...this.agentSpecs, ...this.contract, ...this.tooling];
  },
};
