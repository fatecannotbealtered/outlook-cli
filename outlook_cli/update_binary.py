"""Binary self-update for the frozen outlook-cli executable.

Downloads the platform archive + checksums.txt + Sigstore bundle from the GitHub
release, verifies the Sigstore signature on checksums.txt in-process against this
repo's tagged release-workflow identity, verifies the archive SHA256, extracts the
binary, and replaces the running executable. It does not depend on pip/npm being
present, and there is no skip path: an unsigned or unverifiable release is refused.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import platform
import stat
import sys
import tarfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

REPO = "fatecannotbealtered/outlook-cli"
GITHUB_API = "https://api.github.com"
OIDC_ISSUER = "https://token.actions.githubusercontent.com"
BINARY_NAME = "outlook-cli"
MAX_DOWNLOAD_BYTES = 200 * 1024 * 1024


class IntegrityError(Exception):
    """Non-retryable release-integrity failure: missing/invalid signature or
    checksum mismatch. Mapped by the caller to E_INTEGRITY, never to a retryable
    network code — a forged or corrupt release is not fixed by retrying."""


class ReplaceError(Exception):
    """Local failure committing the binary swap (temp dir, extract, file write,
    rename, permission, disk full). The atomic swap never committed, so the old
    binary is still installed (binary_replaced=False). Mapped by the caller to
    E_FORBIDDEN for permission failures and E_IO for io/disk failures — never to
    a retryable network code, since these need an environment fix.

    `error_code` is "E_FORBIDDEN" (permission) or "E_IO" (everything else)."""

    def __init__(self, message: str, error_code: str = "E_IO"):
        super().__init__(message)
        self.error_code = error_code


def normalize_version(v: str) -> str:
    v = (v or "").strip()
    for prefix in ("refs/tags/", "v", "V"):
        if v.startswith(prefix):
            v = v[len(prefix) :]
    return v


def canonical_tag(v: str) -> str:
    v = normalize_version(v)
    return "" if not v or v == "latest" else f"v{v}"


def signer_identity(version: str) -> str:
    """Exact certificate SAN expected for the release that ships `version`.

    Because we resolve the concrete release tag before verifying, we can pin the
    exact identity (tag included) rather than a regexp — stricter than a pattern."""
    return f"https://github.com/{REPO}/.github/workflows/release.yml@refs/tags/{canonical_tag(version)}"


def _platform() -> tuple[str, str]:
    system = platform.system()
    osname = {"Linux": "linux", "Darwin": "darwin", "Windows": "windows"}.get(system, "")
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        arch = "amd64"
    elif machine in ("arm64", "aarch64"):
        arch = "arm64"
    else:
        arch = ""
    if osname == "windows" and arch == "arm64":
        arch = "amd64"
    return osname, arch


def platform_asset_name(version: str) -> tuple[str, bool]:
    osname, arch = _platform()
    if not osname or not arch:
        plat = f"{platform.system()}-{platform.machine()}"
        raise IntegrityError(f"unsupported update platform: {plat}")
    is_zip = osname == "windows"
    ext = ".zip" if is_zip else ".tar.gz"
    return f"{BINARY_NAME}-{normalize_version(version)}-{osname}-{arch}{ext}", is_zip


def _http_get(url: str, accept: str, max_bytes: int = MAX_DOWNLOAD_BYTES) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": BINARY_NAME, "Accept": accept})
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = resp.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise IntegrityError(f"download from {url} exceeds {max_bytes} bytes")
    return data


def fetch_release(target_version: str) -> dict:
    base = GITHUB_API.rstrip("/")
    tag = canonical_tag(target_version)
    if tag:
        url = f"{base}/repos/{REPO}/releases/tags/{tag}"
    else:
        url = f"{base}/repos/{REPO}/releases/latest"
    data = _http_get(url, "application/json", max_bytes=5 * 1024 * 1024)
    rel = json.loads(data.decode("utf-8"))
    if not rel.get("tag_name"):
        raise IntegrityError("release is missing tag_name")
    return rel


def asset_url(release: dict, name: str) -> str:
    for asset in release.get("assets", []):
        if asset.get("name") == name:
            return asset.get("browser_download_url", "")
    return ""


# Seam: production verifies via sigstore; tests monkeypatch this to exercise the
# surrounding fail-closed control flow without a live OIDC-signed bundle.
def verify_signature(checksums_bytes: bytes, bundle_bytes: bytes, identity_san: str) -> None:
    try:
        from sigstore.models import Bundle
        from sigstore.verify import Verifier
        from sigstore.verify.policy import Identity
    except ImportError as exc:  # pragma: no cover - sigstore is a hard dependency
        raise IntegrityError(f"sigstore verification library unavailable: {exc}") from exc
    try:
        bundle = Bundle.from_json(bundle_bytes)
        verifier = Verifier.production()
        policy = Identity(identity=identity_san, issuer=OIDC_ISSUER)
        verifier.verify_artifact(input_=checksums_bytes, bundle=bundle, policy=policy)
    except Exception as exc:
        raise IntegrityError(f"signature verification failed: {exc}") from exc


def verify_checksum(archive_bytes: bytes, checksums_text: str, asset_name: str) -> None:
    expected = ""
    for line in checksums_text.splitlines():
        fields = line.split()
        if len(fields) >= 2 and Path(fields[-1]).name == asset_name:
            expected = fields[0].lower()
            break
    if not expected:
        raise IntegrityError(f"checksum for {asset_name} not found")
    actual = hashlib.sha256(archive_bytes).hexdigest()
    if actual != expected:
        raise IntegrityError(f"checksum mismatch for {asset_name}")


def extract_binary(archive_bytes: bytes, is_zip: bool) -> bytes:
    want = BINARY_NAME + (".exe" if is_zip else "")
    if is_zip:
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as zf:
            for info in zf.infolist():
                if Path(info.filename).name == want:
                    return zf.read(info)
    else:
        with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as tf:
            for member in tf.getmembers():
                if member.isfile() and Path(member.name).name == want:
                    fh = tf.extractfile(member)
                    if fh is not None:
                        with fh:
                            return fh.read()
    raise IntegrityError(f"{want} not found in release archive")


def replace_executable(target: Path, new_bytes: bytes) -> str:
    """Replace the running executable with new_bytes in place, atomically.

    Uses the same cross-platform rename trick on every OS: write `.<name>.new`,
    rename the in-use binary out of the way to `.<name>.old`, rename `.new` into
    place, roll back from `.old` on failure, then remove `.old`. On Windows the
    running .exe cannot be deleted or overwritten, but it CAN be renamed, so
    moving it to `.old` frees the path and lets `.new` land — no helper script,
    no restart. Returns 'installed' on success."""
    target = Path(target)
    # Resolve symlinks so we replace the real file, not the link itself — a
    # self-update reached through a /usr/local/bin symlink (e.g. into a cellar)
    # must clobber the target binary, not the link. Matches the jira reference's
    # filepath.EvalSymlinks; os.path.realpath is best-effort and never raises.
    target = Path(os.path.realpath(target))
    new_path = target.with_name("." + target.name + ".new")
    backup_path = target.with_name("." + target.name + ".old")

    mode = target.stat().st_mode if target.exists() else 0o755

    if new_path.exists():
        os.remove(new_path)

    # Stage the verified bytes into `.new`. Any failure or interrupt (incl.
    # SIGINT->KeyboardInterrupt, a BaseException) before the binary is renamed
    # out of the way must leave no half-written `.new` behind — the swap has not
    # committed, so the temp artifact is never trusted by a later run.
    try:
        new_path.write_bytes(new_bytes)
        os.chmod(new_path, (mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH) & 0o7777)

        if backup_path.exists():
            try:
                os.remove(backup_path)
            except OSError:
                pass
        os.rename(target, backup_path)
    except BaseException:
        try:
            os.remove(new_path)
        except OSError:
            pass
        raise
    try:
        os.rename(new_path, target)
    except BaseException:
        # Restore the original and discard the staged replacement so no
        # half-applied `.new` survives a failed/interrupted final swap.
        os.rename(backup_path, target)
        try:
            os.remove(new_path)
        except OSError:
            pass
        raise
    # Best effort: on Windows the old binary may still be mapped by the running
    # process and undeletable — that is fine, it no longer occupies the path.
    try:
        os.remove(backup_path)
    except OSError:
        pass
    return "installed"


def perform_binary_update(target_version: str, on_stage=None) -> dict:
    """Download, verify (signature + checksum), and install the target release.

    Returns a result dict with status / signature_status. Raises IntegrityError on
    any supply-chain failure (non-retryable) or other Exception on transport
    failures (retryable).

    `on_stage`, when given, is called with the current stage name
    (`discover|download|verify_signature|verify_checksum|replace`) as each phase
    begins, so the caller can attribute an interrupt to the stage it actually
    fell in (truthful post-failure state, CLI-SPEC §14)."""

    def _stage(name: str) -> None:
        if on_stage is not None:
            on_stage(name)

    target_path = Path(sys.executable)

    _stage("discover")
    release = fetch_release(target_version)
    resolved = normalize_version(release["tag_name"])
    asset_name, is_zip = platform_asset_name(resolved)

    archive_link = asset_url(release, asset_name)
    if not archive_link:
        raise IntegrityError(f"release {release['tag_name']} does not include asset {asset_name}")
    checksums_link = asset_url(release, "checksums.txt")
    if not checksums_link:
        raise IntegrityError(f"release {release['tag_name']} does not include checksums.txt")
    bundle_link = asset_url(release, "checksums.txt.sigstore.json")
    if not bundle_link:
        raise IntegrityError(
            "release does not include checksums.txt.sigstore.json; "
            "refusing to install an unsigned release"
        )

    _stage("download")
    archive_bytes = _http_get(archive_link, "application/octet-stream")
    checksums_bytes = _http_get(checksums_link, "text/plain", max_bytes=1024 * 1024)
    bundle_bytes = _http_get(bundle_link, "application/json", max_bytes=1024 * 1024)

    # Verify the signature on checksums.txt first, then bind the archive to it.
    _stage("verify_signature")
    verify_signature(checksums_bytes, bundle_bytes, signer_identity(resolved))
    _stage("verify_checksum")
    verify_checksum(archive_bytes, checksums_bytes.decode("utf-8", "replace"), asset_name)

    new_binary = extract_binary(archive_bytes, is_zip)
    _stage("replace")
    try:
        status = replace_executable(target_path, new_binary)
    except PermissionError as exc:
        raise ReplaceError(
            f"permission denied replacing {target_path}: {exc}", "E_FORBIDDEN"
        ) from exc
    except OSError as exc:
        raise ReplaceError(f"failed to write or replace {target_path}: {exc}", "E_IO") from exc
    return {
        "status": status,
        "signature_status": "verified",
        "signature_verified": True,
        "current_version": resolved,
        "asset": asset_name,
        "path": str(target_path),
    }
