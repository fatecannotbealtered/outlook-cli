"""Tests for binary self-update planning and the fail-closed signature gate."""

from unittest import mock

import pytest

from outlook_cli import update_binary, updater
from outlook_cli.update_binary import IntegrityError


def test_plan_update_is_binary_and_supported():
    plan = updater.plan_update("auto", "latest")
    assert plan["supported"] is True
    assert plan["install_method"] == "github-binary"
    assert plan["changes"][0]["action"] == "download_verify_replace_binary"
    assert plan["signature_status"] == "not_checked"


def test_check_update_resolves_from_github_releases():
    with mock.patch.object(updater, "latest_version", return_value=("9.9.9", None)):
        data = updater.check_update()
    assert data["install_method"] == "github-binary"
    assert data["latest_version"] == "9.9.9"
    assert data["update_available"] is True
    assert data["signature_status"] == "not_checked"


def test_execute_update_runs_binary_pipeline_and_syncs_skill():
    completed = mock.Mock(returncode=0, stdout="", stderr="")
    with (
        mock.patch.object(
            update_binary,
            "perform_binary_update",
            return_value={
                "status": "installed",
                "signature_status": "verified",
                "current_version": "2.0.1",
            },
        ),
        mock.patch.object(updater.subprocess, "run", return_value=completed),
    ):
        result = updater.execute_update("auto", "latest", quiet=True)

    assert result["previous_version"] == updater.__version__
    assert result["current_version"] == "2.0.1"
    assert result["install_method"] == "github-binary"
    assert result["signature_status"] == "verified"
    assert result["skill_sync_status"] == "synced"


def test_execute_update_propagates_integrity_error():
    # A supply-chain failure must surface as a non-retryable IntegrityError, not
    # be swallowed or remapped to a network error.
    with mock.patch.object(
        update_binary, "perform_binary_update", side_effect=IntegrityError("bad signature")
    ):
        with pytest.raises(IntegrityError):
            updater.execute_update("auto", "latest", quiet=True)


def test_perform_binary_update_refuses_unsigned_release():
    # No checksums.txt.sigstore.json asset -> refused (no skip path).
    release = {
        "tag_name": "v9.9.9",
        "assets": [
            {"name": "outlook-cli-9.9.9-linux-amd64.tar.gz", "browser_download_url": "https://x/a"},
            {"name": "checksums.txt", "browser_download_url": "https://x/c"},
        ],
    }
    with (
        mock.patch.object(update_binary, "fetch_release", return_value=release),
        mock.patch.object(update_binary, "_platform", return_value=("linux", "amd64")),
        mock.patch("sys.executable", "/tmp/outlook-cli"),
    ):
        with pytest.raises(IntegrityError, match="unsigned release"):
            update_binary.perform_binary_update("latest")


def test_signer_identity_pins_exact_tag():
    ident = update_binary.signer_identity("1.2.3")
    assert ident == (
        "https://github.com/fatecannotbealtered/outlook-cli/"
        ".github/workflows/release.yml@refs/tags/v1.2.3"
    )


def test_verify_checksum_detects_mismatch():
    archive = b"hello"
    checksums = "0000  outlook-cli-1-linux-amd64.tar.gz\n"
    with pytest.raises(IntegrityError, match="checksum mismatch"):
        update_binary.verify_checksum(archive, checksums, "outlook-cli-1-linux-amd64.tar.gz")
