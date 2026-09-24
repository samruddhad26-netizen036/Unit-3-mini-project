"""Tests for Phase 7 audit logging, reporting integration, and skip flags."""

import json
import subprocess
import sys
from pathlib import Path

from devdoctor.cli.main import run_diagnose
from devdoctor.diagnostics import inspect
from devdoctor.reporting import format_human, format_json
from devdoctor.reporting.audit import (
    audit_enabled,
    audit_event,
    audit_log_path,
    read_audit_events,
)


def _audit_env(monkeypatch, tmp_path: Path) -> Path:
    log = tmp_path / "audit.jsonl"
    monkeypatch.setenv("DEVDOCTOR_AUDIT_LOG", str(log))
    monkeypatch.delenv("DEVDOCTOR_AUDIT_DISABLED", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    return log


# --- audit core ---


def test_audit_event_persisted(tmp_path: Path, monkeypatch) -> None:
    """Events append as JSONL with timestamp/event/project/status."""
    log = _audit_env(monkeypatch, tmp_path)
    record = audit_event("diagnosis_completed", project="/tmp/demo", status="ok",
                         metadata={"exit_code": 0})
    assert record is not None
    assert set(record) == {"timestamp", "event", "project", "status", "metadata"}
    lines = log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["event"] == "diagnosis_completed"


def test_audit_secret_redaction(tmp_path: Path, monkeypatch) -> None:
    """Secret-bearing metadata is redacted; safe metadata survives."""
    log = _audit_env(monkeypatch, tmp_path)
    audit_event("repair_action", project="/tmp/demo", status="ok",
                metadata={"password": "hunter2", "api_key": "abc123",
                          "package": "pandas", "count": 3})
    blob = log.read_text(encoding="utf-8")
    assert "hunter2" not in blob
    assert "abc123" not in blob
    payload = json.loads(blob.splitlines()[0])
    assert payload["metadata"]["password"] == "[REDACTED]"
    assert payload["metadata"]["package"] == "pandas"
    assert payload["metadata"]["count"] == 3


def test_audit_disabled(tmp_path: Path, monkeypatch) -> None:
    """Disabled auditing writes nothing and returns None."""
    log = tmp_path / "audit.jsonl"
    monkeypatch.setenv("DEVDOCTOR_AUDIT_LOG", str(log))
    monkeypatch.setenv("DEVDOCTOR_AUDIT_DISABLED", "1")
    assert audit_enabled() is False
    assert audit_event("x", project="y") is None
    assert not log.exists()


def test_audit_never_raises(tmp_path: Path, monkeypatch) -> None:
    """Unwritable log paths degrade silently."""
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    # Point at an invalid location via a file blocking the directory
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setenv("DEVDOCTOR_AUDIT_LOG", str(blocker / "audit.jsonl"))
    assert audit_event("x", project="y") is None


def test_read_audit_events(tmp_path: Path, monkeypatch) -> None:
    """Recent events filter by project with a bounded limit."""
    _audit_env(monkeypatch, tmp_path)
    audit_event("a", project="/tmp/one")
    audit_event("b", project="/tmp/two")
    audit_event("c", project="/tmp/one")
    events = read_audit_events("/tmp/one", limit=5)
    assert [e["event"] for e in events] == ["c", "a"]
    assert len(read_audit_events("/tmp/one", limit=1)) == 1
    assert read_audit_events("/tmp/nothing") == []


def test_audit_log_path_default(monkeypatch) -> None:
    """Without overrides the log lives outside any target project."""
    monkeypatch.delenv("DEVDOCTOR_AUDIT_LOG", raising=False)
    path = audit_log_path()
    assert path.name == "audit.jsonl"
    assert ".devdoctor" in path.parts


# --- reporting integration ---


def _tiny_project(root: Path) -> Path:
    root.mkdir(exist_ok=True)
    (root / "app.py").write_text("import os\n", encoding="utf-8")
    return root


def test_inspect_includes_phase7_sections(tmp_path: Path) -> None:
    """inspect() populates security/vulnerabilities/docker payloads."""
    _tiny_project(tmp_path / "p")
    payload = inspect(tmp_path / "p", run_tests=False).to_dict()
    assert set(payload) >= {"security", "vulnerabilities", "docker", "tests"}
    assert payload["security"]["files_scanned"] == 1
    assert payload["security"]["findings"] == []
    assert "docker_available" in payload["docker"]


def test_human_report_sections(tmp_path: Path) -> None:
    """Human output contains SECURITY/DOCKER/AUDIT sections."""
    _tiny_project(tmp_path / "p")
    text = format_human(inspect(tmp_path / "p", run_tests=False))
    for section in ("SECURITY", "DOCKER", "AUDIT", "DEPENDENCIES", "TESTS"):
        assert section in text


def test_json_report_audit_key(tmp_path: Path) -> None:
    """JSON output carries a valid audit trail object."""
    _tiny_project(tmp_path / "p")
    payload = json.loads(format_json(inspect(tmp_path / "p", run_tests=False)))
    assert set(payload["audit"]) == {"log", "recent_events"}
    assert isinstance(payload["audit"]["recent_events"], list)


def test_skip_flags(tmp_path: Path, capsys) -> None:
    """--skip-security/--skip-docker produce skipped markers, not scans."""
    _tiny_project(tmp_path / "p")
    code = run_diagnose(str(tmp_path / "p"), False, True, False, True, True)
    assert code == 0
    out = capsys.readouterr().out
    assert "security scan disabled" in out
    assert "docker analysis disabled" in out


def test_repair_cli_preserved() -> None:
    """Phase 6 repair flags still advertised and repair needs approval."""
    proc = subprocess.run(
        [sys.executable, "-m", "devdoctor.cli.main", "repair", "--help"],
        capture_output=True, text=True, check=False)
    assert proc.returncode == 0
    assert "--dry-run" in proc.stdout
    assert "--yes" in proc.stdout


def test_diagnose_help_lists_skip_flags() -> None:
    """New skip flags are discoverable via --help."""
    proc = subprocess.run(
        [sys.executable, "-m", "devdoctor.cli.main", "diagnose", "--help"],
        capture_output=True, text=True, check=False)
    assert proc.returncode == 0
    assert "--skip-security" in proc.stdout
    assert "--skip-docker" in proc.stdout
