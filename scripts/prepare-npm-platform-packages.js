#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");
const { execFileSync } = require("child_process");

const root = path.resolve(__dirname, "..");
const rootPackage = require(path.join(root, "package.json"));
const toolName = Object.keys(rootPackage.bin || {})[0] || rootPackage.name.split("/").pop();
const version = rootPackage.version;
const inputDir = path.resolve(process.argv[2] || path.join(root, "dist"));
const outputDir = path.resolve(process.argv[3] || path.join(root, "npm-platform"));

const osMap = { darwin: "darwin", linux: "linux", win32: "windows" };
const archMap = { x64: "amd64", arm64: "arm64" };

function walk(dir) {
  const out = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...walk(p));
    else out.push(p);
  }
  return out;
}

function findArchive(npmOS, npmCPU) {
  const releaseOS = osMap[npmOS];
  let releaseArch = archMap[npmCPU];
  let archive = findArchiveExact(releaseOS, releaseArch);
  if (!archive && npmOS === "win32" && npmCPU === "arm64") {
    releaseArch = "amd64";
    archive = findArchiveExact(releaseOS, releaseArch);
  }
  if (!archive) {
    throw new Error(`No release archive found for npm platform ${npmOS}-${npmCPU}`);
  }
  return archive;
}

function findArchiveExact(releaseOS, releaseArch) {
  const base = `${toolName}-${version}-${releaseOS}-${releaseArch}`;
  return archives.find((f) => path.basename(f) === `${base}.tar.gz`) ||
    archives.find((f) => path.basename(f) === `${base}.zip`);
}

function extractZip(archive, binaryName, destBin) {
  const bytes = process.platform === "win32"
    ? execFileSync("tar", ["-xf", archive, "-O", binaryName])
    : execFileSync("unzip", ["-p", archive, binaryName]);
  fs.writeFileSync(destBin, bytes);
}

function extractBinary(archive, destBin, npmOS) {
  fs.mkdirSync(path.dirname(destBin), { recursive: true });
  const binaryName = toolName + (npmOS === "win32" ? ".exe" : "");
  if (archive.endsWith(".zip")) {
    extractZip(archive, binaryName, destBin);
  } else {
    execFileSync("tar", ["-xzf", archive, "-C", path.dirname(destBin), binaryName], { stdio: "ignore" });
  }
  if (npmOS !== "win32") fs.chmodSync(destBin, 0o755);
}

function platformParts(packageName) {
  const prefix = `${rootPackage.name}-`;
  if (!packageName.startsWith(prefix)) {
    throw new Error(`Optional dependency ${packageName} does not start with ${prefix}`);
  }
  const suffix = packageName.slice(prefix.length);
  const idx = suffix.indexOf("-");
  if (idx < 0) throw new Error(`Cannot parse npm platform package ${packageName}`);
  return { os: suffix.slice(0, idx), cpu: suffix.slice(idx + 1) };
}

fs.rmSync(outputDir, { recursive: true, force: true });
fs.mkdirSync(outputDir, { recursive: true });

if (!fs.existsSync(inputDir)) {
  throw new Error(`Input directory does not exist: ${inputDir}`);
}

const archives = walk(inputDir);

for (const packageName of Object.keys(rootPackage.optionalDependencies || {})) {
  const { os, cpu } = platformParts(packageName);
  const archive = findArchive(os, cpu);
  const packageDir = path.join(outputDir, packageName.replace(/^@/, "").replace("/", "__"));
  const binPath = path.join(packageDir, "bin", toolName + (os === "win32" ? ".exe" : ""));
  extractBinary(archive, binPath, os);
  const platformPackage = {
    name: packageName,
    version,
    description: `${toolName} prebuilt binary for ${os}-${cpu}`,
    license: rootPackage.license,
    author: rootPackage.author,
    homepage: rootPackage.homepage,
    repository: rootPackage.repository,
    publishConfig: { access: "public" },
    os: [os],
    cpu: [cpu],
    files: ["bin/"],
    engines: rootPackage.engines || { node: ">=16" }
  };
  fs.writeFileSync(path.join(packageDir, "package.json"), JSON.stringify(platformPackage, null, 2) + "\n");
  console.log(`Prepared ${packageName} from ${path.basename(archive)}`);
}
