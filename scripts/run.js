#!/usr/bin/env node
"use strict";

// Thin forwarder: exec the binary shipped by the npm platform package.
const { execFileSync } = require("child_process");
const path = require("path");

const rootPackage = require("../package.json");
const toolName = Object.keys(rootPackage.bin || {})[0] || "outlook-cli";
const ext = process.platform === "win32" ? ".exe" : "";
const platformKey = `${process.platform}-${process.arch}`;
const platformPackage = `${rootPackage.name}-${platformKey}`;
const optionalDependencies = rootPackage.optionalDependencies || {};

if (!Object.prototype.hasOwnProperty.call(optionalDependencies, platformPackage)) {
  console.error(
    `${toolName} does not ship an npm platform package for ${platformKey}.\n` +
    "Install a supported platform package or use the GitHub standalone binary."
  );
  process.exit(1);
}

let bin;
try {
  const platformPackageJson = require.resolve(`${platformPackage}/package.json`);
  bin = path.join(path.dirname(platformPackageJson), "bin", toolName + ext);
} catch {
  console.error(
    `${toolName} platform package ${platformPackage} is not installed.\n` +
    "This usually means npm optional dependencies were omitted.\n" +
    `Reinstall with:  npm install -g ${rootPackage.name} --include=optional`
  );
  process.exit(1);
}

try {
  execFileSync(bin, process.argv.slice(2), { stdio: "inherit" });
} catch (e) {
  if (e.code === "ENOENT") {
    console.error(
      `${toolName} binary not found inside ${platformPackage}.\n` +
      `Reinstall with:  npm install -g ${rootPackage.name} --include=optional`
    );
  }
  process.exit(e.status || 1);
}
