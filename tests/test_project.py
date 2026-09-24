"""Tests for target project inspection (uses tmp fixtures only)."""

from pathlib import Path

from devdoctor.diagnostics import inspect_project


def _make_project(root: Path) -> Path:
    """Create a small fake project with common marker files."""
    (root / "app.py").write_text("import os\n\nprint('hi')\n", encoding="utf-8")
    (root / "requirements.txt").write_text("requests\n", encoding="utf-8")
    (root / "pyproject.toml").write_text('[project]\nname = "demo"\n', encoding="utf-8")
    (root / "README.md").write_text("# demo\n", encoding="utf-8")
    (root / ".gitignore").write_text("*.pyc\n", encoding="utf-8")
    (root / ".env").write_text("KEY=value\n", encoding="utf-8")
    tests_dir = root / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_app.py").write_text("import app\n\ndef test_x():\n    pass\n", encoding="utf-8")
    return root


def test_inspect_valid_project(tmp_path: Path) -> None:
    """Valid projects report layout, files, tests, and source info."""
    project = tmp_path / "demo"
    project.mkdir()
    _make_project(project)
    info = inspect_project(project)
    assert info.exists is True
    assert info.is_directory is True
    assert info.error is None
    assert info.name == "demo"
    assert "app.py" in info.python_files
    assert "tests/test_app.py" in info.python_files
    assert info.files_present["requirements.txt"] is True
    assert info.files_present["pyproject.toml"] is True
    assert info.files_present["setup.py"] is False
    assert info.files_present["Dockerfile"] is False
    assert ".env" in info.env_files
    assert "tests/" in info.test_dirs
    assert "tests/test_app.py" in info.test_files
    assert info.source is not None
    assert info.source.file_count == 2
    assert "os" in info.source.imports
    assert info.is_git_repo is False


def test_inspect_invalid_path(tmp_path: Path) -> None:
    """Non-existent paths produce a clear error, not an exception."""
    info = inspect_project(tmp_path / "nope")
    assert info.exists is False
    assert info.is_directory is False
    assert info.error is not None
    assert "does not exist" in info.error


def test_inspect_file_not_directory(tmp_path: Path) -> None:
    """A file path (not a directory) is reported as an error."""
    target = tmp_path / "file.txt"
    target.write_text("hello", encoding="utf-8")
    info = inspect_project(target)
    assert info.exists is True
    assert info.is_directory is False
    assert info.error is not None
    assert "not a directory" in info.error


def test_inspect_skips_excluded_dirs(tmp_path: Path) -> None:
    """Excluded dirs (.git, venv, __pycache__, node_modules) are not scanned."""
    project = tmp_path / "demo"
    project.mkdir()
    (project / "main.py").write_text("x = 1\n", encoding="utf-8")
    for dirname in (".git", "venv", "__pycache__", "node_modules"):
        hidden = project / dirname
        hidden.mkdir()
        (hidden / "hidden.py").write_text("y = 2\n", encoding="utf-8")
    info = inspect_project(project)
    assert info.python_files == ["main.py"]
    assert not any("hidden.py" in entry for entry in info.project_tree)


def test_inspect_detects_compose_and_docker(tmp_path: Path) -> None:
    """Docker-related marker files are detected."""
    project = tmp_path / "dock"
    project.mkdir()
    (project / "Dockerfile").write_text("FROM python:3.12\n", encoding="utf-8")
    (project / "compose.yml").write_text("services: {}\n", encoding="utf-8")
    info = inspect_project(project)
    assert info.files_present["Dockerfile"] is True
    assert info.files_present["compose.yml"] is True
    assert info.files_present["docker-compose.yml"] is False


def test_inspect_git_repo(tmp_path: Path) -> None:
    """A directory containing .git is flagged as a git repo without crashing."""
    project = tmp_path / "repo"
    project.mkdir()
    (project / ".git").mkdir()
    (project / "a.py").write_text("x = 1\n", encoding="utf-8")
    info = inspect_project(project)
    assert info.is_git_repo is True
    # git_branch/clean may be None if git is missing - must not crash either way.
    assert info.git_branch is None or isinstance(info.git_branch, str)


def test_inspect_to_dict(tmp_path: Path) -> None:
    """Project info serializes with nested source payload."""
    project = tmp_path / "demo"
    project.mkdir()
    (project / "a.py").write_text("import sys\n", encoding="utf-8")
    payload = inspect_project(project).to_dict()
    assert payload["exists"] is True
    assert payload["source"]["file_count"] == 1
    assert payload["source"]["imports"] == ["sys"]
