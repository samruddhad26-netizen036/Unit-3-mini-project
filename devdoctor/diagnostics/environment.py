"""Local development environment inspection (read-only, stdlib only).

Every external tool lookup is defensive: missing tools are reported as
unavailable instead of raising.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from importlib import metadata

from devdoctor.diagnostics.models import EnvironmentInfo


def _tool_version(command: list[str]) -> str | None:
    """Run `<tool> --version` and return stripped stdout, or None if unavailable."""
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    output = (result.stdout or result.stderr or "").strip()
    return output.splitlines()[0].strip() if output else None


def _pip_version() -> str | None:
    """Return the installed pip version, or None if pip is not available."""
    try:
        return metadata.version("pip")
    except metadata.PackageNotFoundError:
        pass
    version = _tool_version([sys.executable, "-m", "pip", "--version"])
    if version:
        # Output looks like: "pip 24.0 from ... (python 3.12)"
        parts = version.split()
        if len(parts) >= 2 and parts[0] == "pip":
            return parts[1]
        return version
    return None


def _venv_info() -> tuple[bool, str | None]:
    """Detect whether we run inside a virtual environment."""
    is_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
    venv_path = os.environ.get("VIRTUAL_ENV")
    if is_venv and not venv_path:
        venv_path = sys.prefix
    if not is_venv:
        venv_path = None
    return is_venv, venv_path


def inspect_environment() -> EnvironmentInfo:
    """Collect local environment facts without modifying anything."""
    git_version: str | None = None
    git_available = shutil.which("git") is not None
    if git_available:
        git_version = _tool_version(["git", "--version"])
        git_available = git_version is not None

    docker_version: str | None = None
    docker_available = shutil.which("docker") is not None
    if docker_available:
        docker_version = _tool_version(["docker", "--version"])
        docker_available = docker_version is not None

    is_venv, venv_path = _venv_info()

    return EnvironmentInfo(
        os_name=platform.system() or "unknown",
        os_version=platform.release() or platform.version() or "unknown",
        architecture=platform.machine() or "unknown",
        python_executable=sys.executable,
        python_version=platform.python_version(),
        pip_version=_pip_version(),
        is_venv=is_venv,
        venv_path=venv_path,
        git_available=git_available,
        git_version=git_version,
        docker_available=docker_available,
        docker_version=docker_version,
    )
