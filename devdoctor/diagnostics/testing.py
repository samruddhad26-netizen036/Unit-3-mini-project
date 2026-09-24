"""Deterministic, read-only test execution and result analysis.

Runs the target project's pytest suite as a subprocess and extracts
structured evidence (counts, failures, bounded output). Evidence only:
no root-cause reasoning, no fixes, no installs, no modifications.

Read-only safeguards for the target project:
* `-p no:cacheprovider` so no `.pytest_cache` is written into it
* `PYTHONDONTWRITEBYTECODE=1` so no `__pycache__` is written into it
* `--junitxml` points at a temp file outside the target directory
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from devdoctor.diagnostics.models import (
    ProjectInfo,
    TestFailure,
    TestResult,
    TestRun,
    TestSummary,
)

DEFAULT_TIMEOUT_S = 120
PYTEST_VERSION_TIMEOUT_S = 15
MAX_OUTPUT_CHARS = 6000
MAX_FAILURES = 20
MAX_HUMAN_FAILURES = 10
MAX_TRACEBACK_CHARS = 2000
MAX_MESSAGE_CHARS = 500

_EXCEPTION_RE = re.compile(r"^(?:E\s+)?([\w.]+(?:Error|Exception|Failure|Exit|Interrupt|Warning|Skip))")


def select_python(root: Path) -> str:
    """Choose the interpreter: target venv python if present, else current."""
    candidates = [
        root / ".venv" / "Scripts" / "python.exe",
        root / ".venv" / "bin" / "python",
        root / "venv" / "Scripts" / "python.exe",
        root / "venv" / "bin" / "python",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return sys.executable


def pytest_version(python: str) -> str | None:
    """Return the pytest version for an interpreter, or None if unavailable."""
    try:
        proc = subprocess.run(
            [python, "-m", "pytest", "--version"],
            capture_output=True, text=True, check=False,
            timeout=PYTEST_VERSION_TIMEOUT_S,
        )
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None
    if proc.returncode != 0:
        return None
    output = (proc.stdout or proc.stderr or "").strip()
    return output.splitlines()[0].strip() if output else "unknown"


def run_pytest(
    python: str,
    root: Path,
    targets: list[str],
    junit_path: Path,
    timeout_s: int,
) -> subprocess.CompletedProcess[str]:
    """Execute pytest in the target dir (module-level seam for tests to mock)."""
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [python, "-m", "pytest", *targets, "-q", "--tb=short",
         "-p", "no:cacheprovider", f"--junitxml={junit_path}"],
        capture_output=True, text=True, check=False,
        timeout=timeout_s, cwd=str(root), env=env,
    )


def _exception_from_text(body: str) -> str:
    """Extract an exception type name from traceback text (evidence only)."""
    fallback: str | None = None
    for line in reversed(body.splitlines()):
        stripped = line.strip()
        if not stripped:
            continue
        match = _EXCEPTION_RE.match(stripped)
        if match:
            return match.group(1).split(".")[-1]
        if fallback is None:
            if stripped.startswith("E   assert"):
                # Bare pytest assertion line: only rewritten asserts look like this.
                fallback = "AssertionError"
            elif stripped.startswith("E   Failed"):
                fallback = "Failed"
    return fallback or "unknown"


def _resolve_file(root: Path, classname: str) -> str | None:
    """Map a junit classname to a project-relative file path, if it exists."""
    parts = classname.split(".") if classname else []
    for width in range(len(parts), 0, -1):
        candidate = root.joinpath(*parts[:width]).with_suffix(".py")
        try:
            if candidate.is_file():
                return candidate.relative_to(root).as_posix()
        except (OSError, ValueError):
            return None
    return None


def _bounded(text: str, limit: int) -> str:
    """Keep the tail of over-long text (most recent output matters most)."""
    return text[-limit:] if len(text) > limit else text


def parse_junit_xml(path: Path, root: Path) -> tuple[TestSummary, list[TestFailure]] | None:
    """Parse pytest junit XML into a summary and failures. None if unusable."""
    try:
        tree = ET.parse(path)
    except (OSError, ET.ParseError, ValueError):
        return None
    suite = tree.getroot()
    if suite.tag == "testsuites":
        suites = suite.findall("testsuite")
        suite = suites[0] if suites else None
    if suite is None:
        return None

    def _int(value: str | None) -> int:
        return int(value) if value and value.isdigit() else 0

    def _float(value: str | None) -> float:
        try:
            return float(value) if value else 0.0
        except (TypeError, ValueError):
            return 0.0

    total = _int(suite.get("tests"))
    failures = _int(suite.get("failures"))
    errors = _int(suite.get("errors"))
    skipped = _int(suite.get("skipped"))
    passed = max(total - failures - errors - skipped, 0)
    summary = TestSummary(
        total=total, passed=passed, failed=failures, skipped=skipped,
        errors=errors, duration_s=_float(suite.get("time")),
    )

    found: list[TestFailure] = []
    for case in suite.iter("testcase"):
        child = case.find("failure")
        kind = "failure"
        if child is None:
            child = case.find("error")
            kind = "error"
        if child is None:
            continue
        classname = case.get("classname") or ""
        name = case.get("name") or ""
        test_id = f"{classname}::{name}" if classname else name
        body = (child.text or "").strip()
        first_line = body.splitlines()[0].strip() if body.splitlines() else ""
        message = (child.get("message") or "").strip() or first_line
        failure_type = (child.get("type") or _exception_from_text(body)).split(".")[-1]
        if failure_type == "unknown" and kind == "error":
            failure_type = "error"
        found.append(TestFailure(
            test_id=test_id or "unknown",
            file=case.get("file") or _resolve_file(root, classname),
            line=_junit_line(case.get("line")),
            failure_type=failure_type,
            message=_bounded(message, MAX_MESSAGE_CHARS),
            traceback=_bounded(body, MAX_TRACEBACK_CHARS),
        ))
    return summary, found


def _junit_line(value: str | None) -> int | None:
    """Parse a junit line attribute, tolerating missing values."""
    return int(value) if value and value.isdigit() else None


_SUMMARY_RE = re.compile(r"=+\s+(.*?)\s+in\s+([\d.]+)s\s*=+")
_COUNT_RE = re.compile(r"(\d+)\s+(failed|passed|skipped|errors?|warnings?)")


def parse_pytest_text(stdout: str) -> tuple[TestSummary, list[TestFailure]]:
    """Fallback evidence extraction from `-q` console output (no junit XML)."""
    summary = TestSummary()
    found: list[TestFailure] = []
    lines = stdout.splitlines()
    for line in reversed(lines):
        match = _SUMMARY_RE.search(line)
        if not match:
            continue
        for count, word in _COUNT_RE.findall(match.group(1)):
            number = int(count)
            if word == "failed":
                summary.failed = number
            elif word == "passed":
                summary.passed = number
            elif word == "skipped":
                summary.skipped = number
            elif word in ("error", "errors"):
                summary.errors = number
        try:
            summary.duration_s = float(match.group(2))
        except ValueError:
            summary.duration_s = 0.0
        summary.total = summary.passed + summary.failed + summary.skipped + summary.errors
        break
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("FAILED "):
            continue
        rest = stripped[len("FAILED "):]
        nodeid, _, message = rest.partition(" - ")
        found.append(TestFailure(
            test_id=nodeid.strip() or "unknown",
            file=nodeid.split("::")[0].strip() or None,
            failure_type="unknown",
            message=_bounded(message.strip(), MAX_MESSAGE_CHARS),
        ))
        if len(found) >= MAX_FAILURES:
            break
    return summary, found


def analyze_tests(
    root: Path,
    project: ProjectInfo,
    timeout_s: int = DEFAULT_TIMEOUT_S,
) -> TestRun:
    """Run the target project's tests with pytest and collect evidence."""
    if project.error or not project.is_directory:
        reason = project.error or "invalid project"
        return TestRun(status="skipped", skipped=f"test analysis skipped: {reason}",
                       result=TestResult(notes=[f"test analysis skipped: {reason}"]))
    if not project.test_files and not project.test_dirs:
        return TestRun(status="no-tests",
                       result=TestResult(notes=["No tests detected."]))

    python = select_python(root)
    version = pytest_version(python)
    if version is None:
        return TestRun(status="unavailable", python=python,
                       result=TestResult(notes=["pytest is not available."]))

    targets = [*project.test_dirs, *project.test_files]
    junit_file: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
                suffix=".xml", prefix="devdoctor-junit-", delete=False) as handle:
            junit_file = Path(handle.name)
        command = [python, "-m", "pytest", *targets, "-q", "--tb=short",
                   "-p", "no:cacheprovider", f"--junitxml={junit_file}"]
        try:
            proc = run_pytest(python, root, targets, junit_file, timeout_s)
        except subprocess.TimeoutExpired:
            return TestRun(status="timeout", command=command, python=python,
                           pytest_version=version,
                           result=TestResult(notes=[
                               f"pytest timed out after {timeout_s}s."]))
        output = proc.stdout or ""
        if proc.stderr:
            output += "\n[stderr]\n" + proc.stderr
        output_truncated = len(output) > MAX_OUTPUT_CHARS
        output = _bounded(output, MAX_OUTPUT_CHARS)

        parsed = parse_junit_xml(junit_file, root) if junit_file else None
        if parsed is None:
            summary, failures = parse_pytest_text(proc.stdout or "")
        else:
            summary, failures = parsed

        failures_omitted = max(len(failures) - MAX_FAILURES, 0)
        failures = failures[:MAX_FAILURES]
        notes: list[str] = []
        if parsed is None:
            notes.append("junit XML unavailable; evidence parsed from console output.")

        if proc.returncode == 0:
            status = "passed"
        elif proc.returncode == 5:
            status = "no-tests"
            notes.append("pytest collected no tests.")
        elif proc.returncode == 2:
            status = "error"
            notes.append("pytest reported a collection or usage error (exit code 2).")
        elif proc.returncode == 1:
            status = "failed"
        else:
            status = "error"
            notes.append(f"pytest exited with code {proc.returncode}.")

        return TestRun(
            status=status, exit_code=proc.returncode, command=command,
            python=python, pytest_version=version, output=output,
            output_truncated=output_truncated,
            result=TestResult(summary=summary, failures=failures,
                              failures_omitted=failures_omitted, notes=notes),
        )
    finally:
        if junit_file is not None:
            try:
                junit_file.unlink(missing_ok=True)
            except OSError:
                pass
