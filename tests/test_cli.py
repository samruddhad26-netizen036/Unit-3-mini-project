"""Tests for DevDoctor CLI (Phase 1 commands + diagnose wiring)."""

import json
import subprocess
import sys


def _run(*cli_args: str, cwd: str | None = None) -> subprocess.CompletedProcess[str]:
    """Run the CLI in a subprocess."""
    return subprocess.run(
        [sys.executable, "-m", "devdoctor.cli.main", *cli_args],
        capture_output=True,
        text=True,
        check=False,
        cwd=cwd,
    )


def test_cli_help() -> None:
    """Test that --help works."""
    result = _run("--help")
    assert result.returncode == 0
    assert "DevDoctor" in result.stdout
    assert "--version" in result.stdout


def test_cli_version() -> None:
    """Test that --version works."""
    result = _run("--version")
    assert result.returncode == 0
    assert "devdoctor 0.1.0" in result.stdout


def test_cli_no_args() -> None:
    """Test CLI with no arguments shows help."""
    result = _run()
    assert result.returncode == 0
    assert "DevDoctor" in result.stdout


def test_cli_diagnose_current_dir(tmp_path) -> None:
    """Test diagnose runs against a valid directory."""
    (tmp_path / "app.py").write_text("import os\n", encoding="utf-8")
    result = _run("diagnose", str(tmp_path))
    assert result.returncode == 0
    assert "Environment:" in result.stdout
    assert "Project:" in result.stdout


def test_cli_diagnose_invalid_path(tmp_path) -> None:
    """Test diagnose reports an invalid path with a non-zero exit code."""
    missing = tmp_path / "does-not-exist"
    result = _run("diagnose", str(missing))
    assert result.returncode == 2
    assert "does not exist" in result.stdout


def test_cli_diagnose_json(tmp_path) -> None:
    """Test diagnose --json emits parseable JSON."""
    (tmp_path / "app.py").write_text("import os\n", encoding="utf-8")
    result = _run("diagnose", str(tmp_path), "--json")
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert "environment" in payload
    assert "project" in payload
    assert "errors" in payload


def test_cli_repair_not_implemented() -> None:
    """Test repair command shows not implemented message."""
    result = _run("repair")
    assert result.returncode == 1
    assert "not yet implemented" in result.stdout
