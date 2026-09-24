"""Tests for combined inspection and report rendering."""

import json
from pathlib import Path

from devdoctor.cli.main import run_diagnose
from devdoctor.diagnostics import inspect
from devdoctor.reporting import format_human, format_json


def test_inspect_combines_env_and_project(tmp_path: Path) -> None:
    """Combined inspection carries both environment and project payloads."""
    (tmp_path / "a.py").write_text("import os\n", encoding="utf-8")
    result = inspect(tmp_path)
    assert result.environment.python_executable
    assert result.project.exists is True
    assert result.errors == []


def test_inspect_invalid_path_records_error(tmp_path: Path) -> None:
    """Invalid paths surface in both project.error and result.errors."""
    result = inspect(tmp_path / "missing")
    assert result.project.error is not None
    assert result.errors == [result.project.error]


def test_format_human_valid_project(tmp_path: Path) -> None:
    """Human report contains the key sections for a valid project."""
    (tmp_path / "a.py").write_text("import os\n", encoding="utf-8")
    text = format_human(inspect(tmp_path))
    assert "Environment:" in text
    assert "Project files:" in text
    assert "Python sources:" in text
    assert "Project tree:" in text


def test_format_human_unavailable_tool() -> None:
    """Missing optional tools render as 'unavailable', not a crash."""
    from devdoctor.diagnostics.models import EnvironmentInfo, ProjectInfo

    env = EnvironmentInfo(
        os_name="TestOS",
        os_version="1.0",
        architecture="x86_64",
        python_executable="/usr/bin/python",
        python_version="3.12.0",
        pip_version=None,
        is_venv=False,
        venv_path=None,
        git_available=False,
        git_version=None,
        docker_available=False,
        docker_version=None,
    )
    proj = ProjectInfo(path="/tmp/x", exists=False, is_directory=False, error="nope")
    from devdoctor.diagnostics.models import InspectionResult

    text = format_human(InspectionResult(environment=env, project=proj))
    assert "Docker: unavailable" in text
    assert "Git: unavailable" in text


def test_format_json_roundtrip(tmp_path: Path) -> None:
    """JSON output parses and contains environment + project keys."""
    (tmp_path / "a.py").write_text("import os\n", encoding="utf-8")
    payload = json.loads(format_json(inspect(tmp_path)))
    assert "environment" in payload
    assert "project" in payload
    assert payload["project"]["source"]["imports"] == ["os"]


def test_run_diagnose_exit_codes(tmp_path: Path, capsys) -> None:
    """run_diagnose returns 0 for valid projects, 2 for invalid paths."""
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    assert run_diagnose(str(tmp_path), as_json=False) == 0
    capsys.readouterr()
    assert run_diagnose(str(tmp_path), as_json=True) == 0
    capsys.readouterr()
    assert run_diagnose(str(tmp_path / "missing"), as_json=False) == 2
