"""Tests for DevDoctor CLI."""

import subprocess
import sys


def test_cli_help() -> None:
    """Test that --help works."""
    result = subprocess.run(
        [sys.executable, "-m", "devdoctor.cli.main", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "DevDoctor" in result.stdout
    assert "--version" in result.stdout


def test_cli_version() -> None:
    """Test that --version works."""
    result = subprocess.run(
        [sys.executable, "-m", "devdoctor.cli.main", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "devdoctor 0.1.0" in result.stdout


def test_cli_no_args() -> None:
    """Test CLI with no arguments shows help."""
    result = subprocess.run(
        [sys.executable, "-m", "devdoctor.cli.main"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "DevDoctor" in result.stdout


def test_cli_diagnose_not_implemented() -> None:
    """Test diagnose command shows not implemented message."""
    result = subprocess.run(
        [sys.executable, "-m", "devdoctor.cli.main", "diagnose"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "not yet implemented" in result.stdout


def test_cli_repair_not_implemented() -> None:
    """Test repair command shows not implemented message."""
    result = subprocess.run(
        [sys.executable, "-m", "devdoctor.cli.main", "repair"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "not yet implemented" in result.stdout