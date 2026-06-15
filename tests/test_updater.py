"""Tests for self-update planning."""

from unittest import mock

import pytest

from outlook_cli import updater


def test_detect_install_method_env_override():
    with mock.patch.dict("os.environ", {"OUTLOOK_CLI_UPDATE_MANAGER": "npm"}):
        assert updater.detect_install_method("auto") == "npm"


def test_detect_install_method_explicit():
    assert updater.detect_install_method("pip") == "pip"


def test_npm_update_command_latest():
    assert updater.update_command("npm", "latest") == [
        "npm",
        "install",
        "-g",
        "@ananke/outlook-cli@latest",
    ]


def test_pip_update_command_version():
    command = updater.update_command("pip", "1.2.3")
    assert command[-1] == "outlook-cli==1.2.3"
    assert "pip" in command


def test_plan_update_manual_is_unsupported():
    plan = updater.plan_update("manual", "latest")
    assert plan["supported"] is False
    assert plan["command"] == []
    assert plan["changes"][0]["action"] == "update"


def test_execute_update_manual_raises():
    with pytest.raises(updater.UpdateUnsupported):
        updater.execute_update("manual", "latest", quiet=True)


def test_execute_update_latest_reports_resolved_version():
    completed = mock.Mock(returncode=0, stdout="", stderr="")
    with (
        mock.patch.object(updater.shutil, "which", return_value="npm"),
        mock.patch.object(updater, "latest_version", return_value=("2.0.1", None)),
        mock.patch.object(updater.subprocess, "run", return_value=completed),
    ):
        result = updater.execute_update("npm", "latest", quiet=True)

    assert result["previous_version"] == updater.__version__
    assert result["current_version"] == "2.0.1"
    assert result["target_version"] == "latest"
