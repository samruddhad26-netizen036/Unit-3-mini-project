"""Target project inspection (strictly read-only).

Detects project layout markers, Python/test files, a bounded project tree,
and git repository status. Never modifies the target directory.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from devdoctor.diagnostics.models import ProjectInfo
from devdoctor.diagnostics.source import inspect_python_sources

# Files probed at the project root.
KNOWN_FILES = [
    "requirements.txt",
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "Pipfile",
    "poetry.lock",
    "Dockerfile",
    "docker-compose.yml",
    "compose.yml",
    "README.md",
    ".gitignore",
]

# Directories never descended into when scanning/listing.
EXCLUDE_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    "dist",
    "build",
}


def _is_excluded(dirname: str) -> bool:
    """Check whether a directory should be skipped during scanning."""
    return dirname in EXCLUDE_DIRS or dirname.endswith(".egg-info")

# Safety bound so a huge directory cannot hang inspection.
MAX_TREE_ENTRIES = 500


def _is_env_file(name: str) -> bool:
    """Check for `.env` files (`.env`, `.env.local`, ...)."""
    return name == ".env" or name.startswith(".env.")


def _is_test_file(name: str) -> bool:
    """Check common pytest/unittest file naming conventions."""
    return (name.startswith("test_") or name.endswith("_test.py")) and name.endswith(".py")


def _git_info(root: Path) -> tuple[bool, str | None, bool | None]:
    """Return (is_repo, branch, clean). Missing git is not an error."""
    if not (root / ".git").exists():
        return False, None, None
    try:
        branch_proc = subprocess.run(
            ["git", "-C", str(root), "branch", "--show-current"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        branch = branch_proc.stdout.strip() or None
        status_proc = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        if status_proc.returncode != 0:
            return True, branch, None
        return True, branch, not status_proc.stdout.strip()
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return True, None, None


def inspect_project(path: str | Path) -> ProjectInfo:
    """Inspect a target project directory without modifying it."""
    target = Path(path)
    abs_path = str(target.resolve()) if target.exists() else str(target.absolute())

    if not target.exists():
        return ProjectInfo(
            path=abs_path,
            exists=False,
            is_directory=False,
            error=f"Path does not exist: {path}",
        )
    if not target.is_dir():
        return ProjectInfo(
            path=abs_path,
            exists=True,
            is_directory=False,
            name=target.name,
            error=f"Path is not a directory: {path}",
        )

    root = target.resolve()
    info = ProjectInfo(path=str(root), exists=True, is_directory=True, name=root.name)

    try:
        for name in KNOWN_FILES:
            info.files_present[name] = (root / name).is_file()
    except OSError as exc:
        info.error = f"Cannot read project directory: {exc.strerror or exc}"
        return info

    tree: list[str] = []
    truncated = False
    try:
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            # Prune excluded directories in place so we never descend into them.
            dirnames[:] = sorted(d for d in dirnames if not _is_excluded(d))
            dirnames.sort()
            rel_dir = Path(dirpath).relative_to(root)
            prefix = "" if str(rel_dir) == "." else rel_dir.as_posix() + "/"
            if prefix:
                tree.append(prefix)
            for filename in sorted(filenames):
                rel = prefix + filename
                tree.append(rel)
                rel_path = Path(rel)
                if filename.endswith(".py"):
                    info.python_files.append(rel)
                    if _is_test_file(filename):
                        info.test_files.append(rel)
                if _is_env_file(filename):
                    info.env_files.append(rel)
                # Test files inside a test/tests directory (any naming).
                if (
                    filename.endswith(".py")
                    and rel not in info.test_files
                    and any(part in ("test", "tests") for part in rel_path.parts[:-1])
                ):
                    info.test_files.append(rel)
            # Record test directories.
            for dirname in dirnames:
                rel_d = (prefix + dirname + "/") if prefix else (dirname + "/")
                if dirname in ("test", "tests") and rel_d not in info.test_dirs:
                    info.test_dirs.append(rel_d)
            if len(tree) >= MAX_TREE_ENTRIES:
                truncated = True
                break
    except PermissionError as exc:
        info.error = f"Permission denied while scanning: {exc.filename or exc}"
    except OSError as exc:
        info.error = f"Error while scanning project: {exc.strerror or exc}"

    if truncated:
        tree.append(f"... (listing truncated at {MAX_TREE_ENTRIES} entries)")
    info.project_tree = tree
    info.python_files.sort()
    info.test_files.sort()
    info.test_dirs.sort()
    info.env_files.sort()

    is_repo, branch, clean = _git_info(root)
    info.is_git_repo = is_repo
    info.git_branch = branch
    info.git_clean = clean

    info.source = inspect_python_sources(root, info.python_files)
    return info
