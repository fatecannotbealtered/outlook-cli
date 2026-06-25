#!/usr/bin/env node
// check-spec.js — fail-closed CI guard that the spec-synced assets in this tool
// have not drifted from the ai-native-cli-spec template at the pinned tag
// (.agent/SPEC_VERSION), and that the generated contract module is in sync with
// the vendored contract.json. This is the enforcement half of "managed in ONE
// place": a tool can re-sync but can never silently fork the specs/contract.
//
// Two layers:
//   1) remote drift (network): each spec-synced file == template@<pin>. A network
//      failure DEGRADES to a warning (GitHub hiccups must not flake CI); the local
//      layer below is the strict, offline backstop.
//   2) local drift (offline, STRICT): contract_gen.{go,py} == gen-contract(contract.json).
//      A hand-edited generated file or a contract.json edit without regen turns CI red.
//
// Usage:
//   node scripts/check-spec.js                 # remote (best-effort) + local (strict)
//   node scripts/check-spec.js --from <local>  # compare against a local template checkout (strict remote)
//   node scripts/check-spec.js --local-only    # skip the network layer (still strict on codegen)

"use strict";
const fs = require("fs");
const path = require("path");
const https = require("https");
const { execFileSync } = require("child_process");
const specFiles = require("./spec-files.js");

const REPO = "fatecannotbealtered/ai-native-cli-spec";
const SPEC_VERSION_FILE = path.join(".agent", "SPEC_VERSION");

function arg(name) {
  const i = process.argv.indexOf(name);
  return i >= 0 ? process.argv[i + 1] : undefined;
}
function has(flag) {
  return process.argv.includes(flag);
}
function norm(s) {
  return s.replace(/\r\n/g, "\n");
}

function fetchRaw(tag, relPath) {
  const url = `https://raw.githubusercontent.com/${REPO}/${tag}/template/common/${relPath}`;
  return new Promise((resolve, reject) => {
    https
      .get(url, { headers: { "User-Agent": "check-spec" } }, (res) => {
        if (res.statusCode !== 200) {
          res.resume();
          reject(new Error(`GET ${url} -> ${res.statusCode}`));
          return;
        }
        const chunks = [];
        res.on("data", (c) => chunks.push(c));
        res.on("end", () => resolve(Buffer.concat(chunks).toString("utf8")));
      })
      .on("error", reject);
  });
}

function detectLang() {
  if (fs.existsSync("go.mod")) return "go";
  if (fs.existsSync("setup.py") || fs.existsSync("pyproject.toml")) return "py";
  return "";
}
function pyContractOutDir() {
  const entries = fs.readdirSync(".", { withFileTypes: true });
  const pkgs = entries
    .filter((e) => e.isDirectory() && fs.existsSync(path.join(e.name, "__init__.py")))
    .map((e) => e.name)
    .filter((n) => !n.startsWith(".") && n !== "tests");
  if (pkgs.length === 0) return ".";
  return pkgs.sort((a, b) => a.length - b.length)[0];
}

async function checkRemote(fromLocal, tag) {
  let drift = 0;
  for (const rel of specFiles.all()) {
    if (!fs.existsSync(rel)) {
      console.error(`[spec] MISSING vendored file: ${rel}`);
      drift++;
      continue;
    }
    let src;
    try {
      src = fromLocal
        ? fs.readFileSync(path.join(fromLocal, "template", "common", rel), "utf8")
        : await fetchRaw(tag, rel);
    } catch (e) {
      console.warn(`[spec] WARN: could not fetch template ${rel} (${e.message}); skipping remote diff for it`);
      continue;
    }
    if (norm(src) !== norm(fs.readFileSync(rel, "utf8"))) {
      console.error(`[spec] DRIFT: ${rel} differs from template@${tag}. Run: node scripts/sync-spec.js`);
      drift++;
    }
  }
  return drift;
}

function checkLocalCodegen() {
  const lang = detectLang();
  if (lang === "go") {
    execFileSync("node", ["scripts/gen-contract.js", "--lang", "go", "--out", path.join("internal", "contract"), "--check"], { stdio: "inherit" });
  } else if (lang === "py") {
    execFileSync("node", ["scripts/gen-contract.js", "--lang", "py", "--out", pyContractOutDir(), "--check"], { stdio: "inherit" });
  } else {
    console.warn("[spec] could not detect language; skipped codegen drift check");
  }
}

async function main() {
  const fromLocal = arg("--from");
  const tag = fs.existsSync(SPEC_VERSION_FILE) ? fs.readFileSync(SPEC_VERSION_FILE, "utf8").trim() : "";
  if (!tag && !fromLocal) {
    console.error("[spec] no .agent/SPEC_VERSION pin found");
    process.exit(1);
  }

  // local strict layer first (offline) — surfaces drift even with no network
  try {
    checkLocalCodegen();
  } catch (_) {
    console.error("[spec] contract codegen drift (see above)");
    process.exit(1);
  }

  if (has("--local-only")) {
    console.log("[spec] OK (local-only): contract_gen in sync");
    return;
  }

  const drift = await checkRemote(fromLocal, tag);
  if (drift > 0) {
    console.error(`[spec] FAILED: ${drift} spec-synced file(s) drifted from template@${tag}`);
    process.exit(1);
  }
  console.log(`[spec] OK: spec-synced assets match template@${tag} and contract_gen is in sync`);
}

main();
