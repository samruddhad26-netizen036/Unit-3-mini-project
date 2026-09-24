"""Controlled repair tools for DevDoctor Phase 6.

These tools perform safe, bounded package operations on the target project.
No arbitrary shell commands - only controlled subprocess calls.
"""

from __future__ import annotations

import contextlib
import re
import subprocess
import sys
import venv
from pathlib import Path

from devdoctor.agent.repair_models import (
    RepairAction,
    RepairResult,
    Snapshot,
    is_valid_repair_action,
    validate_package_name,
)

# Version pattern: allow basic semver-like strings
VERSION_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._+-]*$")


def validate_version(version: str) -> bool:
    """Validate version string format."""
    return bool(VERSION_PATTERN.match(version)) if version else True


def is_within_project(project_path: Path, target: Path) -> bool:
    """Check a path stays inside the target project (no escape via .. etc.)."""
    try:
        return target.resolve().is_relative_to(project_path.resolve())
    except (OSError, ValueError):
        return False


def get_project_python(project_path: Path) -> str:
    """Get the Python executable for the project (prefers .venv)."""
    # Check for project-specific virtual environment
    candidates = [
        project_path / ".venv" / "Scripts" / "python.exe",
        project_path / ".venv" / "bin" / "python",
        project_path / "venv" / "Scripts" / "python.exe",
        project_path / "venv" / "bin" / "python",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return sys.executable


def run_pip_command(python: str, args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    """Run pip via the project's Python, with safe defaults."""
    return subprocess.run(
        [python, "-m", "pip", *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(cwd),
        timeout=120,
    )


def create_virtualenv(project_path: Path, action: RepairAction, snapshot: Snapshot | None = None) -> RepairResult:
    """Create a virtual environment in the project directory."""
    if not action.package:
        return RepairResult(
            action=action,
            success=False,
            error="create_virtualenv requires 'package' field to specify venv name (e.g., '.venv')",
        )

    venv_name = action.package
    if not validate_package_name(venv_name):
        return RepairResult(
            action=action,
            success=False,
            error=f"Invalid virtual environment name: {venv_name}",
        )

    venv_path = project_path / venv_name
    if not is_within_project(project_path, venv_path):
        return RepairResult(
            action=action,
            success=False,
            error=f"Virtual environment path escapes the target project: {venv_name}",
        )
    if venv_path.exists():
        return RepairResult(
            action=action,
            success=False,
            error=f"Virtual environment '{venv_name}' already exists",
        )

    try:
        # Create virtual environment
        builder = venv.EnvBuilder(with_pip=True)
        builder.create(str(venv_path))

        # Record modified files for potential rollback
        modified = []
        if snapshot:
            # Snapshot key files that indicate venv creation
            for marker in ["pyvenv.cfg", "Scripts/activate", "bin/activate"]:
                marker_path = venv_path / marker
                if marker_path.exists():
                    snapshot.save_file(str(marker_path))
                    modified.append(str(marker_path))

        return RepairResult(
            action=action,
            success=True,
            message=f"Created virtual environment: {venv_name}",
            modified_files=modified,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        return RepairResult(
            action=action,
            success=False,
            error=f"Failed to create virtual environment: {exc}",
        )


def install_package(project_path: Path, action: RepairAction, snapshot: Snapshot | None = None) -> RepairResult:
    """Install a package with optional version constraint."""
    if not validate_package_name(action.package):
        return RepairResult(
            action=action,
            success=False,
            error=f"Invalid package name: {action.package}",
        )

    if action.version and not validate_version(action.version):
        return RepairResult(
            action=action,
            success=False,
            error=f"Invalid version format: {action.version}",
        )

    python = get_project_python(project_path)
    pkg_spec = f"{action.package}=={action.version}" if action.version else action.package

    # Snapshot requirements.txt if it exists and we're updating it
    requirements_path = project_path / "requirements.txt"
    modified_files = []
    if snapshot and requirements_path.exists():
        snapshot.save_file(str(requirements_path))
        modified_files.append(str(requirements_path))

    # Run pip install
    proc = run_pip_command(python, ["install", pkg_spec], project_path)

    if proc.returncode != 0:
        return RepairResult(
            action=action,
            success=False,
            error=f"pip install failed: {proc.stderr.strip() or proc.stdout.strip()}",
        )

    # Update requirements.txt if it exists (non-fatal if it fails)
    if requirements_path.exists():
        with contextlib.suppress(OSError, UnicodeDecodeError, KeyError):
            # Get installed version
            freeze_proc = run_pip_command(python, ["freeze"], project_path)
            if freeze_proc.returncode == 0:
                lines = freeze_proc.stdout.strip().splitlines()
                installed = {}
                for line in lines:
                    if "==" in line:
                        name, ver = line.split("==", 1)
                        installed[name.lower()] = ver

                pkg_lower = action.package.lower()
                if pkg_lower in installed:
                    # Read current requirements
                    content = requirements_path.read_text(encoding="utf-8")
                    lines = content.splitlines()
                    updated = False
                    for i, line in enumerate(lines):
                        if line.strip().lower().startswith(action.package.lower()):
                            lines[i] = f"{action.package}=={installed[pkg_lower]}"
                            updated = True
                            break
                    if not updated:
                        lines.append(f"{action.package}=={installed[pkg_lower]}")

                    requirements_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
                    modified_files.append(str(requirements_path))

    return RepairResult(
        action=action,
        success=True,
        message=f"Installed {pkg_spec}",
        modified_files=modified_files,
    )


def upgrade_package(project_path: Path, action: RepairAction, snapshot: Snapshot | None = None) -> RepairResult:
    """Upgrade a package to a specific version or latest."""
    if not validate_package_name(action.package):
        return RepairResult(
            action=action,
            success=False,
            error=f"Invalid package name: {action.package}",
        )

    python = get_project_python(project_path)
    pkg_spec = f"{action.package}=={action.version}" if action.version else f"{action.package} --upgrade"

    requirements_path = project_path / "requirements.txt"
    modified_files = []
    if snapshot and requirements_path.exists():
        snapshot.save_file(str(requirements_path))
        modified_files.append(str(requirements_path))

    proc = run_pip_command(python, ["install", pkg_spec], project_path)

    if proc.returncode != 0:
        return RepairResult(
            action=action,
            success=False,
            error=f"pip upgrade failed: {proc.stderr.strip() or proc.stdout.strip()}",
        )

    # Update requirements.txt (non-fatal if it fails)
    if requirements_path.exists():
        with contextlib.suppress(OSError, UnicodeDecodeError, KeyError):
            freeze_proc = run_pip_command(python, ["freeze"], project_path)
            if freeze_proc.returncode == 0:
                lines = freeze_proc.stdout.strip().splitlines()
                installed = {}
                for line in lines:
                    if "==" in line:
                        name, ver = line.split("==", 1)
                        installed[name.lower()] = ver

                pkg_lower = action.package.lower()
                if pkg_lower in installed:
                    content = requirements_path.read_text(encoding="utf-8")
                    req_lines = content.splitlines()
                    updated = False
                    for i, line in enumerate(req_lines):
                        if line.strip().lower().startswith(action.package.lower()):
                            req_lines[i] = f"{action.package}=={installed[pkg_lower]}"
                            updated = True
                            break
                    if not updated:
                        req_lines.append(f"{action.package}=={installed[pkg_lower]}")

                    requirements_path.write_text("\n".join(req_lines) + "\n", encoding="utf-8")
                    modified_files.append(str(requirements_path))

    return RepairResult(
        action=action,
        success=True,
        message=f"Upgraded {action.package} to {action.version or 'latest'}",
        modified_files=modified_files,
    )


def downgrade_package(project_path: Path, action: RepairAction, snapshot: Snapshot | None = None) -> RepairResult:
    """Downgrade a package to a specific version."""
    if not validate_package_name(action.package):
        return RepairResult(
            action=action,
            success=False,
            error=f"Invalid package name: {action.package}",
        )

    if not action.version:
        return RepairResult(
            action=action,
            success=False,
            error="downgrade_package requires a version",
        )

    if not validate_version(action.version):
        return RepairResult(
            action=action,
            success=False,
            error=f"Invalid version format: {action.version}",
        )

    # Same as upgrade but with explicit version
    action_ext = RepairAction(action="install_package", package=action.package, version=action.version)
    return install_package(project_path, action_ext, snapshot)


def remove_package(project_path: Path, action: RepairAction, snapshot: Snapshot | None = None) -> RepairResult:
    """Remove a package (only if possibly unused)."""
    if not validate_package_name(action.package):
        return RepairResult(
            action=action,
            success=False,
            error=f"Invalid package name: {action.package}",
        )

    python = get_project_python(project_path)
    requirements_path = project_path / "requirements.txt"
    modified_files = []
    if snapshot and requirements_path.exists():
        snapshot.save_file(str(requirements_path))
        modified_files.append(str(requirements_path))

    proc = run_pip_command(python, ["uninstall", "-y", action.package], project_path)

    if proc.returncode != 0:
        return RepairResult(
            action=action,
            success=False,
            error=f"pip uninstall failed: {proc.stderr.strip() or proc.stdout.strip()}",
        )

    # Remove from requirements.txt (non-fatal if it fails)
    if requirements_path.exists():
        with contextlib.suppress(OSError, UnicodeDecodeError):
            content = requirements_path.read_text(encoding="utf-8")
            lines = content.splitlines()
            filtered = [line for line in lines if not line.strip().lower().startswith(action.package.lower())]
            requirements_path.write_text("\n".join(filtered) + "\n", encoding="utf-8")
            modified_files.append(str(requirements_path))

    return RepairResult(
        action=action,
        success=True,
        message=f"Removed {action.package}",
        modified_files=modified_files,
    )


def update_requirements(project_path: Path, action: RepairAction, snapshot: Snapshot | None = None) -> RepairResult:
    """Update requirements.txt based on current installed packages."""
    requirements_path = project_path / "requirements.txt"
    if not requirements_path.exists():
        return RepairResult(
            action=action,
            success=False,
            error="requirements.txt does not exist",
        )

    if snapshot:
        snapshot.save_file(str(requirements_path))

    python = get_project_python(project_path)
    freeze_proc = run_pip_command(python, ["freeze"], project_path)

    if freeze_proc.returncode != 0:
        return RepairResult(
            action=action,
            success=False,
            error="pip freeze failed",
        )

    # Filter to only packages declared in requirements.txt or pyproject.toml
    # For simplicity, write all installed packages
    installed_lines = [line for line in freeze_proc.stdout.strip().splitlines() if "==" in line]
    requirements_path.write_text("\n".join(installed_lines) + "\n", encoding="utf-8")

    return RepairResult(
        action=action,
        success=True,
        message=f"Updated requirements.txt with {len(installed_lines)} packages",
        modified_files=[str(requirements_path)],
    )


REPAIR_TOOLS = {
    "create_virtualenv": create_virtualenv,
    "install_package": install_package,
    "upgrade_package": upgrade_package,
    "downgrade_package": downgrade_package,
    "remove_package": remove_package,
    "update_requirements": update_requirements,
}

REPAIR_TOOL_SCHEMAS = {
    "create_virtualenv": {
        "type": "object",
        "properties": {
            "package": {"type": "string", "description": "Virtual environment name (e.g., '.venv')"},
        },
        "required": ["package"],
    },
    "install_package": {
        "type": "object",
        "properties": {
            "package": {"type": "string", "description": "Package name to install"},
            "version": {"type": "string", "description": "Version constraint (optional)"},
        },
        "required": ["package"],
    },
    "upgrade_package": {
        "type": "object",
        "properties": {
            "package": {"type": "string", "description": "Package name to upgrade"},
            "version": {"type": "string", "description": "Target version (optional, defaults to latest)"},
        },
        "required": ["package"],
    },
    "downgrade_package": {
        "type": "object",
        "properties": {
            "package": {"type": "string", "description": "Package name to downgrade"},
            "version": {"type": "string", "description": "Target version (required)"},
        },
        "required": ["package", "version"],
    },
    "remove_package": {
        "type": "object",
        "properties": {
            "package": {"type": "string", "description": "Package name to remove"},
        },
        "required": ["package"],
    },
    "update_requirements": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}


def get_repair_tool(name: str):
    """Get a repair tool function by name. Unknown names return None (never executed)."""
    if not is_valid_repair_action(name):
        return None
    return REPAIR_TOOLS.get(name)