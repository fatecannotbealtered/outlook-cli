#!/usr/bin/env node
"use strict";

// Single registry of every place a version string is derived from the source
// of truth (`package.json` "version"). Both the writer (sync-version.js) and
// the verifier (check-version.js) consume THIS file — so adding a derived
// location here makes both the bump and the CI guard cover it automatically,
// and the two can never disagree about "what counts as a version location".
//
// Each descriptor exposes:
//   read()         -> [{ where, value }]  current version occurrences
//   write(version) -> number              occurrences rewritten to `version`
// CHANGELOG is intentionally NOT "equals version"; it has its own descriptor
// whose read() reports the newest released heading.

const fs = require("fs");
const path = require("path");

// ---- JSON helpers that preserve on-disk formatting (EOL + trailing newline) ----
// npm writes package.json/package-lock.json with 2-space indent and a trailing
// newline; the repos may be checked out CRLF. Round-tripping must not reflow the
// file or flip line endings, or every bump produces noisy diffs.
function readRaw(file) {
  return fs.readFileSync(file, "utf8");
}

function writeJSONPreserving(file, obj) {
  const raw = readRaw(file);
  const eol = raw.includes("\r\n") ? "\r\n" : "\n";
  const trailing = raw.endsWith("\n");
  let out = JSON.stringify(obj, null, 2);
  if (eol === "\r\n") out = out.replace(/\n/g, "\r\n");
  if (trailing) out += eol;
  fs.writeFileSync(file, out);
}

function writeTextPreserving(file, oldText, newText) {
  if (oldText === newText) return 0;
  fs.writeFileSync(file, newText);
  return 1;
}

// ---- source of truth ----
// Read from disk (not require()) so repeated calls in one process never serve a
// stale module-cached version after package.json has changed on disk.
function sourceVersion(root) {
  return JSON.parse(readRaw(path.join(root, "package.json"))).version;
}

// ---- descriptor factories ----

function packageJsonOptionalDeps(root) {
  const file = path.join(root, "package.json");
  return {
    label: "package.json optionalDependencies",
    read() {
      const pkg = JSON.parse(readRaw(file));
      const od = pkg.optionalDependencies || {};
      return Object.entries(od).map(([k, v]) => ({ where: k, value: v }));
    },
    write(version) {
      const pkg = JSON.parse(readRaw(file));
      const od = pkg.optionalDependencies || {};
      let n = 0;
      for (const k of Object.keys(od)) {
        if (od[k] !== version) n++;
        od[k] = version;
      }
      if (n) writeJSONPreserving(file, pkg);
      return n;
    },
  };
}

function packageLock(root) {
  const file = path.join(root, "package-lock.json");
  if (!fs.existsSync(file)) return null;
  // Platform entries in the lock are bare {"optional": true} placeholders with
  // no resolved/integrity, so we surgically rewrite only the version-bearing
  // spots. We deliberately do NOT run `npm install --package-lock-only`, which
  // would inject the developer's registry mirror URLs into a public lockfile.
  return {
    label: "package-lock.json",
    read() {
      const l = JSON.parse(readRaw(file));
      const out = [{ where: "version", value: l.version }];
      const rootPkg = l.packages && l.packages[""];
      if (rootPkg) {
        out.push({ where: 'packages[""].version', value: rootPkg.version });
        const od = rootPkg.optionalDependencies || {};
        for (const [k, v] of Object.entries(od)) out.push({ where: `pin ${k}`, value: v });
      }
      return out;
    },
    write(version) {
      const l = JSON.parse(readRaw(file));
      let n = 0;
      if (l.version !== version) { l.version = version; n++; }
      const rootPkg = l.packages && l.packages[""];
      if (rootPkg) {
        if (rootPkg.version !== version) { rootPkg.version = version; n++; }
        const od = rootPkg.optionalDependencies || {};
        for (const k of Object.keys(od)) {
          if (od[k] !== version) n++;
          od[k] = version;
        }
      }
      if (n) writeJSONPreserving(file, l);
      return n;
    },
  };
}

function skillMd(root) {
  const skillsDir = path.join(root, "skills");
  if (!fs.existsSync(skillsDir)) return [];
  const descriptors = [];
  for (const name of fs.readdirSync(skillsDir)) {
    const file = path.join(skillsDir, name, "SKILL.md");
    if (!fs.existsSync(file)) continue;
    descriptors.push({
      label: `skills/${name}/SKILL.md`,
      read() {
        const text = readRaw(file);
        const out = [];
        const ver = text.match(/^version:\s*"([^"]+)"/m);
        if (ver) out.push({ where: "version", value: ver[1] });
        const min = text.match(/"min_version"\s*:\s*"([^"]+)"/);
        if (min) out.push({ where: "min_version", value: min[1] });
        return out;
      },
      write(version) {
        const text = readRaw(file);
        // Only the frontmatter `version:` line; tolerant of whitespace.
        let next = text.replace(/^(version:\s*")[^"]+(")/m, `$1${version}$2`);
        next = next.replace(/("min_version"\s*:\s*")[^"]+(")/, `$1${version}$2`);
        return writeTextPreserving(file, text, next);
      },
    });
  }
  return descriptors;
}

function pythonVersion(root) {
  // Python single source is `<pkg>/__init__.py` __version__. setup.py reads it
  // dynamically (see template setup.py), so it is NOT a separate hand-copied
  // location and is not registered here.
  const skip = new Set(["node_modules", "tests", "test", "dist", "build", "scripts", ".git", ".github"]);
  for (const name of fs.readdirSync(root, { withFileTypes: true })) {
    if (!name.isDirectory() || skip.has(name.name)) continue;
    const file = path.join(root, name.name, "__init__.py");
    if (!fs.existsSync(file)) continue;
    const text = readRaw(file);
    if (!/__version__\s*=/.test(text)) continue;
    return {
      label: `${name.name}/__init__.py`,
      read() {
        const m = readRaw(file).match(/__version__\s*=\s*"([^"]+)"/);
        return m ? [{ where: "__version__", value: m[1] }] : [];
      },
      write(version) {
        const t = readRaw(file);
        const next = t.replace(/(__version__\s*=\s*")[^"]+(")/, `$1${version}$2`);
        return writeTextPreserving(file, t, next);
      },
    };
  }
  return null;
}

// CHANGELOG: not "equals version" — read() reports the newest *released*
// heading (skipping [Unreleased]); write() rolls [Unreleased] into a dated
// [version] section (idempotent: no-op if [version] already present).
function changelog(root) {
  const file = path.join(root, "CHANGELOG.md");
  if (!fs.existsSync(file)) return null;
  function newestReleased(text) {
    const re = /^## \[([^\]]+)\]/gm;
    let m;
    while ((m = re.exec(text))) {
      if (m[1].toLowerCase() !== "unreleased") return m[1];
    }
    return null;
  }
  return {
    label: "CHANGELOG.md",
    isChangelog: true,
    read() {
      return [{ where: "newest released heading", value: newestReleased(readRaw(file)) }];
    },
    write(version) {
      const text = readRaw(file);
      const escaped = version.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      if (new RegExp(`^## \\[${escaped}\\]`, "m").test(text)) {
        return 0; // already has a section for this version
      }
      const eol = text.includes("\r\n") ? "\r\n" : "\n";
      const date = new Date().toISOString().slice(0, 10);
      if (/^## \[Unreleased\]/m.test(text)) {
        // Roll [Unreleased] into a dated [version] section, leaving a fresh
        // empty [Unreleased] above; entries previously under [Unreleased] thus
        // become the [version] body.
        const next = text.replace(
          /^## \[Unreleased\][^\n\r]*/m,
          `## [Unreleased]${eol}${eol}## [${version}] - ${date}`
        );
        return writeTextPreserving(file, text, next);
      }
      // No [Unreleased] section: insert one plus the dated [version] heading
      // before the first existing release heading (or after the preamble).
      const block = `## [Unreleased]${eol}${eol}## [${version}] - ${date}${eol}${eol}`;
      const firstHeading = text.match(/^## \[/m);
      const next = firstHeading
        ? text.slice(0, firstHeading.index) + block + text.slice(firstHeading.index)
        : text.replace(/\s*$/, eol) + eol + block.replace(/\s*$/, eol);
      return writeTextPreserving(file, text, next);
    },
  };
}

// Assemble all descriptors for `root`.
function derivedLocations(root) {
  const list = [packageJsonOptionalDeps(root)];
  const lock = packageLock(root);
  if (lock) list.push(lock);
  list.push(...skillMd(root));
  const py = pythonVersion(root);
  if (py) list.push(py);
  const cl = changelog(root);
  if (cl) list.push(cl);
  return list;
}

module.exports = { sourceVersion, derivedLocations };
