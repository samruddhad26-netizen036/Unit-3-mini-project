"""Tests for Phase 4 test analysis.

Process execution is mocked (except CLI integration, which uses tiny
real projects in tmp dirs) so tests stay deterministic and never depend
on this repository's own test state.
"""

import json
import subprocess
import sys
from pathlib import Path

from devdoctor.diagnostics import inspect, testing
from devdoctor.diagnostics.models import ProjectInfo
from devdoctor.diagnostics.testing import (
    analyze_tests,
    parse_junit_xml,
    parse_pytest_text,
    select_python,
)

PASS_XML = """<testsuite tests="2" failures="0" errors="0" skipped="0" time="0.42">
  <testcase classname="tests.test_a" file="tests/test_a.py" line="3" name="test_one" time="0.2"/>
  <testcase classname="tests.test_a" file="tests/test_a.py" line="7" name="test_two" time="0.22"/>
</testsuite>"""

FAIL_XML = """<testsuite tests="4" failures="1" errors="1" skipped="1" time="1.23">
  <testcase classname="tests.test_a" file="tests/test_a.py" line="3" name="test_ok" time="0.1"/>
  <testcase classname="tests.test_a" name="test_fail" time="0.2">
    <failure message="assert 200 == 401">tests/test_a.py:12: in test_fail
E   AssertionError: assert 200 == 401</failure>
  </testcase>
  <testcase classname="tests.test_b" file="tests/test_b.py" line="4" name="test_conn" time="0.3">
    <error message="connection refused">E   ConnectionError: connection refused</error>
  </testcase>
  <testcase classname="tests.test_b" file="tests/test_b.py" line="9" name="test_skip" time="0.0">
    <skipped message="not today"/>
  </testcase>
</testsuite>"""


def _project_info(root: Path, with_tests: bool = True) -> ProjectInfo:
    return ProjectInfo(
        path=str(root), exists=True, is_directory=True, name=root.name,
        test_files=["tests/test_a.py"] if with_tests else [],
        test_dirs=["tests/"] if with_tests else [],
    )


def _fake_run(xml_text=None, returncode=0, stdout="", stderr=""):
    def _run(python, root, targets, junit_path, timeout_s):
        if xml_text is not None:
            junit_path.write_text(xml_text, encoding="utf-8")
        return subprocess.CompletedProcess(
            args=["pytest"], returncode=returncode, stdout=stdout, stderr=stderr)
    return _run


def _patch(monkeypatch, run=None):
    monkeypatch.setattr(testing, "pytest_version", lambda python: "8.3.0")
    if run is not None:
        monkeypatch.setattr(testing, "run_pytest", run)


# --- discovery / availability ---


def test_no_tests_detected(tmp_path: Path, monkeypatch) -> None:
    """Projects without tests skip execution entirely (no subprocess)."""
    def _boom(*args, **kwargs):
        raise AssertionError("pytest must not run")
    monkeypatch.setattr(testing, "run_pytest", _boom)
    run = analyze_tests(tmp_path, _project_info(tmp_path, with_tests=False))
    assert run.status == "no-tests"
    assert run.exit_code is None
    assert run.result.summary.total == 0


def test_pytest_unavailable(tmp_path: Path, monkeypatch) -> None:
    """Missing pytest is reported, not crashed."""
    monkeypatch.setattr(testing, "pytest_version", lambda python: None)
    def _boom(*args, **kwargs):
        raise AssertionError("pytest must not run")
    monkeypatch.setattr(testing, "run_pytest", _boom)
    run = analyze_tests(tmp_path, _project_info(tmp_path))
    assert run.status == "unavailable"
    assert run.result.notes == ["pytest is not available."]


def test_invalid_project_skipped(tmp_path: Path) -> None:
    """Invalid projects get a skipped marker instead of execution."""
    info = ProjectInfo(path=str(tmp_path / "ghost"), exists=False, is_directory=False,
                       error="Path does not exist")
    run = analyze_tests(tmp_path, info)
    assert run.status == "skipped"
    assert run.skipped is not None


def test_select_python_prefers_venv(tmp_path: Path) -> None:
    """A target .venv interpreter wins over the current one."""
    venv_python = tmp_path / ".venv" / "Scripts" / "python.exe"
    venv_python.parent.mkdir(parents=True)
    venv_python.write_text("", encoding="utf-8")
    assert select_python(tmp_path) == str(venv_python)
    assert select_python(tmp_path / "elsewhere") == sys.executable


# --- outcomes ---


def test_successful_run(tmp_path: Path, monkeypatch) -> None:
    """A green suite reports passed with counts and duration."""
    _patch(monkeypatch, _fake_run(xml_text=PASS_XML, returncode=0, stdout="2 passed"))
    run = analyze_tests(tmp_path, _project_info(tmp_path))
    assert run.status == "passed"
    assert run.exit_code == 0
    assert run.pytest_version == "8.3.0"
    summary = run.result.summary
    assert (summary.total, summary.passed, summary.failed) == (2, 2, 0)
    assert summary.duration_s == 0.42
    assert run.result.failures == []


def test_failed_run_extracts_failures(tmp_path: Path, monkeypatch) -> None:
    """Failures carry id, file, line, type, message, and traceback."""
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_a.py").write_text("x = 1\n", encoding="utf-8")
    (tests_dir / "test_b.py").write_text("y = 2\n", encoding="utf-8")
    _patch(monkeypatch, _fake_run(xml_text=FAIL_XML, returncode=1, stdout="1 failed"))
    run = analyze_tests(tmp_path, _project_info(tmp_path))
    assert run.status == "failed"
    summary = run.result.summary
    assert (summary.total, summary.passed, summary.failed,
            summary.errors, summary.skipped) == (4, 1, 1, 1, 1)
    by_id = {f.test_id: f for f in run.result.failures}
    assert set(by_id) == {"tests.test_a::test_fail", "tests.test_b::test_conn"}
    fail = by_id["tests.test_a::test_fail"]
    assert fail.file == "tests/test_a.py"  # resolved from classname (no file attr)
    assert fail.line is None  # no line attr in this fixture
    assert fail.failure_type == "AssertionError"
    assert fail.message == "assert 200 == 401"
    assert "AssertionError" in fail.traceback
    err = by_id["tests.test_b::test_conn"]
    assert err.file == "tests/test_b.py"
    assert err.line == 4
    assert err.failure_type == "ConnectionError"


def test_collection_error(tmp_path: Path, monkeypatch) -> None:
    """Exit code 2 without junit XML becomes status error with a note."""
    stdout = "ERROR collecting tests/test_broken.py\n2 errors in 0.10s\n"
    _patch(monkeypatch, _fake_run(xml_text=None, returncode=2, stdout=stdout))
    run = analyze_tests(tmp_path, _project_info(tmp_path))
    assert run.status == "error"
    assert run.exit_code == 2
    assert any("exit code 2" in n for n in run.result.notes)


def test_timeout(tmp_path: Path, monkeypatch) -> None:
    """A hung suite reports timeout instead of hanging diagnosis."""
    def _hang(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=["pytest"], timeout=5)
    _patch(monkeypatch, _hang)
    run = analyze_tests(tmp_path, _project_info(tmp_path), timeout_s=5)
    assert run.status == "timeout"
    assert any("timed out" in n for n in run.result.notes)


def test_malformed_junit_falls_back_to_text(tmp_path: Path, monkeypatch) -> None:
    """Garbage junit XML falls back to console-output parsing."""
    stdout = ("tests/test_a.py F\nFAILED tests/test_a.py::test_x - assert 1 == 2\n"
              "===== 1 failed, 2 passed in 0.50s =====")
    _patch(monkeypatch, _fake_run(xml_text="<not xml", returncode=1, stdout=stdout))
    run = analyze_tests(tmp_path, _project_info(tmp_path))
    assert run.status == "failed"
    assert (run.result.summary.failed, run.result.summary.passed) == (1, 2)
    assert run.result.failures[0].test_id == "tests/test_a.py::test_x"
    assert any("console output" in n for n in run.result.notes)


# --- bounds ---


def test_output_bounded(tmp_path: Path, monkeypatch) -> None:
    """Huge console output is truncated to a bounded tail."""
    _patch(monkeypatch, _fake_run(xml_text=PASS_XML, returncode=0, stdout="x" * 20000))
    run = analyze_tests(tmp_path, _project_info(tmp_path))
    assert len(run.output) <= testing.MAX_OUTPUT_CHARS
    assert run.output_truncated is True
    assert run.output == "x" * testing.MAX_OUTPUT_CHARS


def test_traceback_bounded(tmp_path: Path, monkeypatch) -> None:
    """Huge tracebacks are bounded per failure."""
    big = "E   ValueError: " + "y" * 5000
    xml = (f'<testsuite tests="1" failures="1" errors="0" skipped="0" time="0.1">'
           f'<testcase classname="t" file="t.py" name="test_big">'
           f'<failure message="boom">{big}</failure></testcase></testsuite>')
    _patch(monkeypatch, _fake_run(xml_text=xml, returncode=1))
    run = analyze_tests(tmp_path, _project_info(tmp_path))
    assert len(run.result.failures[0].traceback) <= testing.MAX_TRACEBACK_CHARS


def test_failures_capped(tmp_path: Path, monkeypatch) -> None:
    """Only the first MAX_FAILURES failures are stored, with an omitted count."""
    cases = "".join(
        f'<testcase classname="t" file="t.py" name="test_{i}">'
        f'<failure message="m{i}">E   AssertionError: m{i}</failure></testcase>'
        for i in range(testing.MAX_FAILURES + 5))
    xml = (f'<testsuite tests="30" failures="25" errors="0" skipped="0" time="1.0">'
           f'{cases}</testsuite>')
    _patch(monkeypatch, _fake_run(xml_text=xml, returncode=1))
    run = analyze_tests(tmp_path, _project_info(tmp_path))
    assert len(run.result.failures) == testing.MAX_FAILURES
    assert run.result.failures_omitted == 5


# --- parsing units ---


def test_parse_junit_resolves_file(tmp_path: Path) -> None:
    """Classnames resolve to real project files when no file attr exists."""
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text("x = 1\n", encoding="utf-8")
    xml_path = tmp_path / "out.xml"
    xml_path.write_text(FAIL_XML, encoding="utf-8")
    summary, failures = parse_junit_xml(xml_path, tmp_path)
    assert summary is not None and failures is not None
    assert failures[0].file == "tests/test_a.py"


def test_parse_junit_unusable(tmp_path: Path) -> None:
    """Missing or garbage XML files yield None."""
    assert parse_junit_xml(tmp_path / "ghost.xml", tmp_path) is None
    bad = tmp_path / "bad.xml"
    bad.write_text("not xml at all", encoding="utf-8")
    assert parse_junit_xml(bad, tmp_path) is None


def test_parse_pytest_text_counts() -> None:
    """Console summary lines yield counts and duration."""
    stdout = ("FAILED tests/test_a.py::test_x - boom\n"
              "===== 1 failed, 12 passed, 1 skipped in 1.84s =====")
    summary, failures = parse_pytest_text(stdout)
    assert (summary.failed, summary.passed, summary.skipped) == (1, 12, 1)
    assert summary.duration_s == 1.84
    assert failures[0].test_id == "tests/test_a.py::test_x"
    assert failures[0].file == "tests/test_a.py"


# --- serialization ---


def test_testrun_to_dict_json(tmp_path: Path, monkeypatch) -> None:
    """Full test evidence round-trips through JSON."""
    _patch(monkeypatch, _fake_run(xml_text=FAIL_XML, returncode=1, stdout="x"))
    run = analyze_tests(tmp_path, _project_info(tmp_path))
    payload = json.loads(json.dumps(run.to_dict()))
    assert payload["status"] == "failed"
    assert payload["exit_code"] == 1
    assert payload["result"]["summary"]["failed"] == 1
    assert payload["result"]["failures"][0]["failure_type"] == "AssertionError"
    assert isinstance(payload["result"]["notes"], list)


def test_inspect_includes_tests(tmp_path: Path) -> None:
    """inspect() attaches the tests section; --skip-tests disables execution."""
    (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
    result = inspect(tmp_path)
    assert result.tests is not None
    assert result.tests.status == "no-tests"
    payload = json.loads(json.dumps(result.to_dict()))
    assert payload["tests"]["status"] == "no-tests"

    skipped = inspect(tmp_path, run_tests=False)
    assert skipped.tests is not None
    assert skipped.tests.status == "skipped"


# --- CLI integration (tiny real projects) ---


def _tiny_project(root: Path, body: str) -> Path:
    root.mkdir(exist_ok=True)
    (root / "app.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    tests_dir = root / "tests"
    tests_dir.mkdir(exist_ok=True)
    (tests_dir / "test_app.py").write_text(body, encoding="utf-8")
    return root


def _diagnose(*args: str):
    return subprocess.run(
        [sys.executable, "-m", "devdoctor.cli.main", "diagnose", *args],
        capture_output=True, text=True, check=False)


def _assert_read_only(root: Path) -> None:
    leftovers = list(root.rglob(".pytest_cache")) + list(root.rglob("__pycache__"))
    assert leftovers == []


def test_cli_diagnose_passing_project(tmp_path: Path) -> None:
    """A green project reports Status: PASSED and stays unmodified."""
    root = _tiny_project(tmp_path / "green", "def test_add():\n    assert True\n")
    proc = _diagnose(str(root))
    assert proc.returncode == 0
    assert "TESTS" in proc.stdout
    assert "Status: PASSED" in proc.stdout
    assert "Passed: 1" in proc.stdout
    _assert_read_only(root)


def test_cli_diagnose_failing_project(tmp_path: Path) -> None:
    """A red project reports Status: FAILED with structured failure lines."""
    root = _tiny_project(
        tmp_path / "red",
        "def test_login():\n    assert 200 == 401\n")
    proc = _diagnose(str(root))
    assert proc.returncode == 0  # test failures are evidence, not CLI errors
    assert "Status: FAILED" in proc.stdout
    assert "test_login" in proc.stdout
    assert "AssertionError" in proc.stdout
    _assert_read_only(root)


def test_cli_diagnose_no_tests(tmp_path: Path) -> None:
    """A project without tests prints the exact no-tests message."""
    root = tmp_path / "plain"
    root.mkdir()
    (root / "app.py").write_text("x = 1\n", encoding="utf-8")
    proc = _diagnose(str(root))
    assert proc.returncode == 0
    assert "No tests detected." in proc.stdout


def test_cli_diagnose_json_tests(tmp_path: Path) -> None:
    """--json carries structured tests evidence."""
    root = _tiny_project(
        tmp_path / "red",
        "def test_login():\n    assert 200 == 401\n")
    proc = _diagnose(str(root), "--json")
    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    tests = payload["tests"]
    assert tests["status"] == "failed"
    assert tests["result"]["summary"]["failed"] == 1
    assert "test_login" in tests["result"]["failures"][0]["test_id"]
    _assert_read_only(root)


def test_cli_diagnose_skip_tests(tmp_path: Path) -> None:
    """--skip-tests avoids subprocess execution entirely."""
    root = _tiny_project(tmp_path / "green", "def test_add():\n    assert True\n")
    proc = _diagnose(str(root), "--skip-tests")
    assert proc.returncode == 0
    assert "Skipped:" in proc.stdout
