"""Tests for Phase 7 pip-audit vulnerability analysis (fully mocked)."""

import json
import subprocess
from pathlib import Path

import devdoctor.diagnostics.vulnerabilities as vulns
from devdoctor.diagnostics.vulnerabilities import (
    analyze_vulnerabilities,
    parse_pip_audit_json,
)

AUDIT_JSON = json.dumps({
    "dependencies": [
        {"name": "requests", "version": "2.28.0", "vulns": [
            {"id": "PYSEC-2023-1", "fix_versions": ["2.31.0"],
             "aliases": ["CVE-2023-1234"], "spec": ">=2.28.0,<2.31.0",
             "description": "Proxy-Authorization header leak"},
        ]},
        {"name": "flask", "version": "2.0.0", "vulns": []},
    ]
})


def _completed(stdout="", returncode=0, stderr=""):
    return subprocess.CompletedProcess(args=["pip-audit"], returncode=returncode,
                                       stdout=stdout, stderr=stderr)


def test_pip_audit_unavailable(tmp_path: Path, monkeypatch) -> None:
    """Missing pip-audit reports unavailable without raising."""
    monkeypatch.setattr(vulns, "_pip_audit_base", lambda: None)
    analysis = analyze_vulnerabilities(tmp_path)
    assert analysis.skipped == "pip-audit unavailable"
    assert analysis.vulnerabilities == []


def test_mocked_successful_scan(tmp_path: Path, monkeypatch) -> None:
    """Mocked pip-audit output parses into structured vulnerabilities."""
    monkeypatch.setattr(vulns, "pip_audit_version", lambda: "24.0.0")
    monkeypatch.setattr(vulns, "run_pip_audit",
                        lambda root, timeout_s=120: _completed(AUDIT_JSON, 1))
    analysis = analyze_vulnerabilities(tmp_path)
    assert analysis.skipped is None
    assert analysis.pip_audit_version == "24.0.0"
    assert len(analysis.vulnerabilities) == 1
    vuln = analysis.vulnerabilities[0]
    assert vuln.package == "requests"
    assert vuln.installed_version == "2.28.0"
    assert vuln.vuln_id == "PYSEC-2023-1"
    assert vuln.aliases == ["CVE-2023-1234"]
    assert vuln.fix_versions == ["2.31.0"]
    assert "Proxy-Authorization" in vuln.description


def test_pip_audit_timeout(tmp_path: Path, monkeypatch) -> None:
    """Timeouts are recorded as notes, not crashes."""
    monkeypatch.setattr(vulns, "pip_audit_version", lambda: "24.0.0")

    def _hang(root, timeout_s=120):
        raise subprocess.TimeoutExpired(cmd=["pip-audit"], timeout=timeout_s)

    monkeypatch.setattr(vulns, "run_pip_audit", _hang)
    analysis = analyze_vulnerabilities(tmp_path, timeout_s=5)
    assert analysis.vulnerabilities == []
    assert any("timed out" in note for note in analysis.notes)


def test_pip_audit_garbage_output(tmp_path: Path, monkeypatch) -> None:
    """Non-JSON output becomes a note, not an exception."""
    monkeypatch.setattr(vulns, "pip_audit_version", lambda: "24.0.0")
    monkeypatch.setattr(vulns, "run_pip_audit",
                        lambda root, timeout_s=120: _completed("not json", 2))
    analysis = analyze_vulnerabilities(tmp_path)
    assert analysis.vulnerabilities == []
    assert any("not valid JSON" in note for note in analysis.notes)


def test_descriptions_bounded() -> None:
    """Over-long descriptions are truncated."""
    payload = json.dumps({"dependencies": [
        {"name": "x", "version": "1.0", "vulns": [
            {"id": "V", "description": "d" * 5000}]},
    ]})
    found, error = parse_pip_audit_json(payload)
    assert error is None
    assert len(found[0].description) <= vulns.MAX_DESC_CHARS


def test_malformed_payload_rejected() -> None:
    """Unexpected JSON shapes are reported, not crashed on."""
    for bad in ('[1, 2]', '{"dependencies": "nope"}', '{"nope": 1}'):
        found, error = parse_pip_audit_json(bad)
        assert found == []
    _, error = parse_pip_audit_json("[1, 2]")
    assert error is not None


def test_to_dict_shape(tmp_path: Path, monkeypatch) -> None:
    """Vulnerability payload serializes with all required fields."""
    monkeypatch.setattr(vulns, "pip_audit_version", lambda: "24.0.0")
    monkeypatch.setattr(vulns, "run_pip_audit",
                        lambda root, timeout_s=120: _completed(AUDIT_JSON, 1))
    payload = analyze_vulnerabilities(tmp_path).to_dict()
    assert set(payload) == {"vulnerabilities", "pip_audit_version", "notes", "skipped"}
    vuln = payload["vulnerabilities"][0]
    assert set(vuln) == {"package", "installed_version", "vuln_id",
                         "aliases", "fix_versions", "description"}
