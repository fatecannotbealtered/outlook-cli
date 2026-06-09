#!/usr/bin/env node
"use strict";

// postinstall downloader for the prebuilt outlook-cli binary.
// Language-agnostic: the release archive may hold a Go OR Python (e.g. PyInstaller) binary;
// this script only cares that bin/outlook-cli[.exe] ends up in place.

const fs = require("fs");
const path = require("path");
const crypto = require("crypto");
const { execFileSync } = require("child_process");
const os = require("os");

const VERSION = require("../package.json").version;
const REPO = "fatecannotbealtered/outlook-cli";
const NAME = "outlook-cli";

// Env overrides: skip entirely (offline / source build / CI), or force a re-download.
const SKIP = process.env["OUTLOOK_CLI_SKIP_INSTALL"] || process.env.SKIP_INSTALL;
const FORCE = process.env["OUTLOOK_CLI_FORCE_INSTALL"];

const PLATFORM_MAP = { darwin: "darwin", linux: "linux", win32: "windows" };
const ARCH_MAP = { x64: "amd64", arm64: "arm64" };

const platform = PLATFORM_MAP[process.platform];
let arch = ARCH_MAP[process.arch];

// Windows on ARM64 runs amd64 binaries transparently via emulation; no native arm64 build needed.
if (process.platform === "win32" && process.arch === "arm64") {
  console.log("Windows ARM64 detected, falling back to amd64 binary (runs via emulation)");
  arch = "amd64";
}

const isWindows = process.platform === "win32";
const ext = isWindows ? ".zip" : ".tar.gz";
const archiveName = `${NAME}-${VERSION}-${platform}-${arch}${ext}`;
const GITHUB_URL = `https://github.com/${REPO}/releases/download/v${VERSION}/${archiveName}`;
const CHECKSUM_URL = `https://github.com/${REPO}/releases/download/v${VERSION}/checksums.txt`;
const CHECKSUM_BUNDLE_URL = `${CHECKSUM_URL}.sigstore.json`;
const REQUIRE_SIGNATURE = process.env["OUTLOOK_CLI_REQUIRE_SIGNATURE"] === "1";

const binDir = path.join(__dirname, "..", "bin");
const dest = path.join(binDir, NAME + (isWindows ? ".exe" : ""));

function manualHint() {
  return (
    `\nDownload the binary manually and place it at:\n  ${dest}\n` +
    `Release page:\n  https://github.com/${REPO}/releases/tag/v${VERSION}\n` +
    `Direct archive:\n  ${GITHUB_URL}\n` +
    `Then unpack it and (on Unix) run: chmod +x "${dest}"\n`
  );
}

function download(url, destPath) {
  const args = [
    "--fail", "--location", "--silent", "--show-error",
    "--connect-timeout", "15", "--max-time", "120",
    "--output", destPath, url,
  ];
  if (isWindows) {
    args.unshift("--ssl-revoke-best-effort");
  }
  execFileSync("curl", args, { stdio: ["ignore", "ignore", "pipe"] });
}

function commandExists(command) {
  try {
    if (isWindows) {
      execFileSync("where", [command], { stdio: "ignore" });
    } else {
      execFileSync("sh", ["-c", `command -v "${command}" >/dev/null 2>&1`], { stdio: "ignore" });
    }
    return true;
  } catch {
    return false;
  }
}

function verifyChecksum(filePath, expectedHash) {
  const hash = crypto.createHash("sha256").update(fs.readFileSync(filePath)).digest("hex");
  if (hash !== expectedHash) {
    throw new Error(`Checksum mismatch!\n  Expected: ${expectedHash}\n  Actual:   ${hash}`);
  }
}

function escapeRegex(text) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function verifyChecksumSignature(checksumPath, bundlePath) {
  if (!commandExists("cosign")) {
    const msg = "cosign is not installed; checksum signature verification skipped";
    if (REQUIRE_SIGNATURE) throw new Error(msg);
    console.warn(msg);
    return false;
  }
  const identity = `^https://github\\.com/${escapeRegex(REPO)}/\\.github/workflows/release\\.yml@refs/tags/v.*$`;
  execFileSync("cosign", [
    "verify-blob",
    "--bundle", bundlePath,
    "--certificate-identity-regexp", identity,
    "--certificate-oidc-issuer", "https://token.actions.githubusercontent.com",
    checksumPath,
  ], { stdio: ["ignore", "ignore", "pipe"] });
  console.log("Checksum signature verified");
  return true;
}

function install() {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), `${NAME}-`));
  const archivePath = path.join(tmpDir, archiveName);
  const checksumPath = path.join(tmpDir, "checksums.txt");

  try {
    console.log(`Downloading ${NAME} v${VERSION} for ${platform}-${arch}...`);
    download(GITHUB_URL, archivePath);
    download(CHECKSUM_URL, checksumPath);
    const bundlePath = path.join(tmpDir, "checksums.txt.sigstore.json");
    try {
      download(CHECKSUM_BUNDLE_URL, bundlePath);
      verifyChecksumSignature(checksumPath, bundlePath);
    } catch (err) {
      if (REQUIRE_SIGNATURE) throw err;
      console.warn(`Checksum signature verification unavailable: ${err.message}`);
    }

    // Find the SHA256 entry for our archive; missing entry is a hard fail (can't verify integrity).
    let expectedHash = "";
    for (const rawLine of fs.readFileSync(checksumPath, "utf8").split("\n")) {
      const fields = rawLine.trim().split(/\s+/);
      if (fields.length >= 2 && fields[fields.length - 1] === archiveName) {
        expectedHash = fields[0];
        break;
      }
    }
    if (!expectedHash) {
      throw new Error(`No checksum entry for ${archiveName} in checksums.txt`);
    }
    verifyChecksum(archivePath, expectedHash);
    console.log("Checksum verified");

    if (isWindows) {
      execFileSync("powershell", [
        "-Command",
        `Expand-Archive -Path '${archivePath}' -DestinationPath '${tmpDir}' -Force`,
      ], { stdio: "ignore" });
    } else {
      execFileSync("tar", ["-xzf", archivePath, "-C", tmpDir], { stdio: "ignore" });
    }

    fs.mkdirSync(binDir, { recursive: true });
    fs.copyFileSync(path.join(tmpDir, NAME + (isWindows ? ".exe" : "")), dest);
    if (!isWindows) fs.chmodSync(dest, 0o755);
    console.log(`${NAME} v${VERSION} installed successfully`);
  } finally {
    // Always clean the tmpdir, even on failure.
    fs.rmSync(tmpDir, { recursive: true, force: true });
  }
}

// --- entry ---

if (SKIP) {
  console.log(`Skipping ${NAME} binary install (OUTLOOK_CLI_SKIP_INSTALL / SKIP_INSTALL set).`);
  process.exit(0);
}

if (fs.existsSync(dest) && !FORCE) {
  console.log(`${NAME} binary already present; skipping download (set OUTLOOK_CLI_FORCE_INSTALL=1 to redownload).`);
  process.exit(0);
}

if (!platform || !arch) {
  console.error(`Unsupported platform: ${process.platform}-${process.arch}`);
  console.error(manualHint());
  process.exit(1);
}

try {
  install();
} catch (err) {
  console.error(`Failed to install ${NAME}:`, err.message);
  console.error(manualHint());
  process.exit(1);
}
