#!/usr/bin/env node
// sync-spec.js — pull the spec-synced assets (.agent specs, contract.json, the
// sync/check tooling) from the ai-native-cli-spec template at the pinned tag in
// .agent/SPEC_VERSION, then regenerate the per-language contract module
// (contract_gen.{go,py}) from the freshly synced contract.json.
//
// This is how a tool re-aligns to the single source after the spec bumps. The
// human edits the spec ONLY in the template; here we vendor a byte-identical
// copy and regenerate derived code.
//
// Usage:
//   node scripts/sync-spec.js                         # fetch template@<SPEC_VERSION> from GitHub
//   node scripts/sync-spec.js --version v1.4          # override the pinned tag (also rewrites SPEC_VERSION)
//   node scripts/sync-spec.js --from <localTemplate>  # sync from a local ai-native-cli-spec checkout (dev)
//
// --from points at the ai-native-cli-spec repo root; sources are read from
// <root>/template/common/<path>.

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

function readPin() {
  try {
    return fs.readFileSync(SPEC_VERSION_FILE, "utf8").trim();
  } catch (_) {
    return "";
  }
}

function fetchRaw(tag, relPath) {
  const url = `https://raw.githubusercontent.com/${REPO}/${tag}/template/common/${relPath}`;
  return new Promise((resolve, reject) => {
    https
      .get(url, { headers: { "User-Agent": "sync-spec" } }, (res) => {
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

async function readSource(fromLocal, tag, relPath) {
  if (fromLocal) {
    return fs.readFileSync(path.join(fromLocal, "template", "common", relPath), "utf8");
  }
  return fetchRaw(tag, relPath);
}

function detectLang() {
  if (fs.existsSync("go.mod")) return "go";
  if (fs.existsSync("setup.py") || fs.existsSync("pyproject.toml")) return "py";
  return "";
}

// goContractOutDir / pyContractOutDir resolve where the generated contract module
// lives. Go: internal/contract. Python: the package dir holding contract.json's
// consumer (default: the single top-level package with an __init__.py).
function goContractOutDir() {
  return path.join("internal", "contract");
}
function pyContractOutDir() {
  // pick the package directory (one containing __init__.py), preferring one that
  // matches the repo name with underscores; fall back to the first found.
  const entries = fs.readdirSync(".", { withFileTypes: true });
  const pkgs = entries
    .filter((e) => e.isDirectory() && fs.existsSync(path.join(e.name, "__init__.py")))
    .map((e) => e.name)
    .filter((n) => !n.startsWith(".") && n !== "tests");
  if (pkgs.length === 0) return ".";
  return pkgs.sort((a, b) => a.length - b.length)[0];
}

async function main() {
  const fromLocal = arg("--from");
  let tag = arg("--version") || readPin();
  if (!tag && !fromLocal) {
    console.error("no spec version: create .agent/SPEC_VERSION or pass --version <tag> / --from <localTemplate>");
    process.exit(2);
  }

  // 1) vendor every spec-synced file byte-for-byte
  for (const rel of specFiles.all()) {
    let content;
    try {
      content = await readSource(fromLocal, tag, rel);
    } catch (e) {
      console.error(`sync-spec: failed to read ${rel}: ${e.message}`);
      process.exit(1);
    }
    fs.mkdirSync(path.dirname(rel), { recursive: true });
    fs.writeFileSync(rel, content);
    console.log(`synced ${rel}`);
  }

  // 2) record / refresh the pin
  if (arg("--version")) {
    fs.mkdirSync(".agent", { recursive: true });
    fs.writeFileSync(SPEC_VERSION_FILE, (arg("--version") || "").trim() + "\n");
    console.log(`pinned ${SPEC_VERSION_FILE} -> ${arg("--version")}`);
  }

  // 3) regenerate the per-language contract module from the synced contract.json
  const lang = detectLang();
  if (lang === "go") {
    execFileSync("node", ["scripts/gen-contract.js", "--lang", "go", "--out", goContractOutDir()], { stdio: "inherit" });
  } else if (lang === "py") {
    execFileSync("node", ["scripts/gen-contract.js", "--lang", "py", "--out", pyContractOutDir()], { stdio: "inherit" });
  } else {
    console.warn("sync-spec: could not detect language (no go.mod/setup.py); skipped contract codegen");
  }
  console.log("sync-spec: done");
}

main();
