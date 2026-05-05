#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");
const crypto = require("crypto");
const { execFileSync } = require("child_process");
const os = require("os");

const VERSION = require("../package.json").version;
const REPO = "fatecannotbealtered/outlook-cli";
const NAME = "outlook-cli";

const PLATFORM_MAP = {
  darwin: "darwin",
  linux: "linux",
  win32: "windows",
};

const ARCH_MAP = {
  x64: "amd64",
  arm64: "arm64",
};

const platform = PLATFORM_MAP[process.platform];
let arch = ARCH_MAP[process.arch];

// Windows ARM64: fall back to amd64 (runs via emulation)
if (process.platform === "win32" && process.arch === "arm64") {
  console.log("Windows ARM64 detected, falling back to x64 binary (runs via emulation)");
  arch = "amd64";
}

if (!platform || !arch) {
  console.error(`Unsupported platform: ${process.platform}-${process.arch}`);
  console.error(`\nManually download from:\n  https://github.com/${REPO}/releases`);
  process.exit(1);
}

const isWindows = process.platform === "win32";
const ext = isWindows ? ".zip" : ".tar.gz";
const archiveName = `${NAME}-${VERSION}-${platform}-${arch}${ext}`;
const GITHUB_URL = `https://github.com/${REPO}/releases/download/v${VERSION}/${archiveName}`;

const binDir = path.join(__dirname, "..", "bin");
const dest = path.join(binDir, NAME + (isWindows ? ".exe" : ""));

fs.mkdirSync(binDir, { recursive: true });

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

function verifyChecksum(filePath, expectedHash) {
  const fileBuffer = fs.readFileSync(filePath);
  const hash = crypto.createHash("sha256").update(fileBuffer).digest("hex");
  if (hash !== expectedHash) {
    throw new Error(
      `Checksum mismatch!\n  Expected: ${expectedHash}\n  Actual:   ${hash}`
    );
  }
}

function install() {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "outlook-cli-"));
  const archivePath = path.join(tmpDir, archiveName);
  const checksumURL = `https://github.com/${REPO}/releases/download/v${VERSION}/checksums.txt`;
  const checksumPath = path.join(tmpDir, "checksums.txt");

  try {
    console.log(`Downloading ${NAME} v${VERSION} for ${platform}-${arch}...`);
    download(GITHUB_URL, archivePath);

    // Verify checksum
    try {
      download(checksumURL, checksumPath);
      const checksumContent = fs.readFileSync(checksumPath, "utf8");
      const line = checksumContent
        .split("\n")
        .find((l) => l.includes(archiveName));
      if (line) {
        const expectedHash = line.trim().split(/\s+/)[0];
        verifyChecksum(archivePath, expectedHash);
        console.log("✔ Checksum verified");
      } else {
        throw new Error(
          `Archive ${archiveName} not found in checksums.txt. ` +
          `Possible tampering — aborting installation.`
        );
      }
    } catch (checksumErr) {
      if (checksumErr.message.includes("Checksum mismatch") ||
          checksumErr.message.includes("not found in checksums.txt")) {
        throw checksumErr;
      }
      console.warn("Warning: could not verify checksum —", checksumErr.message);
    }

    // Extract binary
    if (isWindows) {
      execFileSync("powershell", [
        "-Command",
        `Expand-Archive -Path '${archivePath}' -DestinationPath '${tmpDir}' -Force`,
      ], { stdio: "ignore" });
    } else {
      execFileSync("tar", ["-xzf", archivePath, "-C", tmpDir], {
        stdio: "ignore",
      });
    }

    const binaryName = NAME + (isWindows ? ".exe" : "");
    const extractedBinary = path.join(tmpDir, binaryName);

    fs.copyFileSync(extractedBinary, dest);
    if (!isWindows) {
      fs.chmodSync(dest, 0o755);
    }
    console.log(`✔ ${NAME} v${VERSION} installed successfully`);
  } finally {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  }
}

try {
  install();
} catch (err) {
  console.error(`Failed to install ${NAME}:`, err.message);
  console.error(
    `\nManually download from:\n  https://github.com/${REPO}/releases\n`
  );
  process.exit(1);
}
