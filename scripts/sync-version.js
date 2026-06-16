#!/usr/bin/env node
"use strict";

// Propagate the source-of-truth version (package.json "version") to every
// derived location. Runs automatically as npm's `version` lifecycle hook, so
// `npm version <patch|minor|major|x.y.z>` is the whole release-bump command:
// npm bumps package.json (+ the lockfile's top version) and computes semver,
// then this script syncs optionalDependencies, the lockfile pins, SKILL.md,
// the Python __version__, and rolls the CHANGELOG. No git side effects — the
// repo's .npmrc sets git-tag-version=false so you review, commit, push, and
// tag after CI is green.

const path = require("path");
const { sourceVersion, derivedLocations } = require("./version-files");

const root = path.resolve(__dirname, "..");
const version = sourceVersion(root);

let total = 0;
for (const loc of derivedLocations(root)) {
  const n = loc.write(version);
  if (n > 0) {
    total += n;
    console.log(`  synced ${loc.label} -> ${version}`);
  }
}

console.log(total > 0 ? `sync-version: ${version} (${total} change(s))` : `sync-version: already at ${version}`);
