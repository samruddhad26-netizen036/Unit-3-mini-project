"""Tests for environment inspection."""

import sys

from devdoctor.diagnostics import inspect_environment
from devdoctor.diagnostics.environment import _tool_version


def test_inspect_environment_fields() -> None:
    """Environment inspection returns all required fields with sane values."""
    env = inspect_environment()
    assert env.os_name
    assert env.os_version
    assert env.architecture
    assert env.python_executable
    assert env.python_version
    assert isinstance(env.is_venv, bool)
    assert isinstance(env.git_available, bool)
    assert isinstance(env.docker_available, bool)
    # Version fields are either a string or None (never crash on missing tools).
    assert env.pip_version is None or isinstance(env.pip_version, str)
    assert env.git_version is None or isinstance(env.git_version, str)
    assert env.docker_version is None or isinstance(env.docker_version, str)
    assert env.venv_path is None or isinstance(env.venv_path, str)


def test_inspect_environment_python_matches_runtime() -> None:
    """Reported interpreter details match the running process."""
    env = inspect_environment()
    assert env.python_executable == sys.executable
    assert env.python_version.count(".") >= 1


def test_tool_version_missing_tool() -> None:
    """Unknown tools report None instead of raising."""
    assert _tool_version(["devdoctor-definitely-not-a-real-tool-xyz"]) is None


def test_tool_version_unavailable(monkeypatch) -> None:
    """Simulate git/docker missing from PATH."""
    import shutil

    real_which = shutil.which
    monkeypatch.setattr(
        shutil, "which", lambda name: None if name in ("git", "docker") else real_which(name)
    )
    env = inspect_environment()
    assert env.git_available is False
    assert env.git_version is None
    assert env.docker_available is False
    assert env.docker_version is None


def test_environment_to_dict() -> None:
    """Environment info serializes to JSON-compatible dict."""
    payload = inspect_environment().to_dict()
    assert set(payload) == {
        "os_name",
        "os_version",
        "architecture",
        "python_executable",
        "python_version",
        "pip_version",
        "is_venv",
        "venv_path",
        "git_available",
        "git_version",
        "docker_available",
        "docker_version",
    }
