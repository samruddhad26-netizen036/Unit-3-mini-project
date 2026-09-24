"""Human-readable and JSON report rendering for inspection results."""

from __future__ import annotations

import json

from devdoctor.diagnostics.models import InspectionResult


def _ver(version: str | None) -> str:
    """Render an optional version, using 'unavailable' for missing tools."""
    return version if version else "unavailable"


def format_human(result: InspectionResult) -> str:
    """Render a concise human-readable inspection report."""
    env = result.environment
    proj = result.project
    lines: list[str] = []

    lines.append(f"DevDoctor inspection: {proj.name or proj.path}")
    lines.append("")
    lines.append("Environment:")
    lines.append(f"  OS: {env.os_name} {env.os_version} ({env.architecture})")
    lines.append(f"  Python: {env.python_version} ({env.python_executable})")
    lines.append(f"  pip: {_ver(env.pip_version)}")
    if env.is_venv:
        lines.append(f"  Virtualenv: yes ({env.venv_path})")
    else:
        lines.append("  Virtualenv: no")
    lines.append(f"  Git: {_ver(env.git_version)}")
    lines.append(f"  Docker: {_ver(env.docker_version)}")
    lines.append("")

    lines.append(f"Project: {proj.path}")
    if proj.error:
        lines.append(f"  Error: {proj.error}")
        return "\n".join(lines)
    lines.append(f"  Name: {proj.name}")
    lines.append(f"  Git repo: {'yes' if proj.is_git_repo else 'no'}")
    if proj.is_git_repo:
        lines.append(f"  Branch: {proj.git_branch or 'unknown'}")
        if proj.git_clean is None:
            lines.append("  Working tree: unknown")
        else:
            lines.append(f"  Working tree: {'clean' if proj.git_clean else 'dirty'}")
    lines.append("")

    lines.append("Project files:")
    found = [name for name, present in proj.files_present.items() if present]
    missing = [name for name, present in proj.files_present.items() if not present]
    lines.append(f"  Found: {', '.join(found) if found else 'none'}")
    lines.append(f"  Missing: {', '.join(missing) if missing else 'none'}")
    if proj.env_files:
        lines.append(f"  .env files: {', '.join(proj.env_files)}")
    lines.append("")

    if proj.source:
        src = proj.source
        lines.append("Python sources:")
        lines.append(f"  Files: {src.file_count} ({src.total_lines} lines)")
        lines.append(f"  Imports: {', '.join(src.imports) if src.imports else 'none'}")
        if src.errors:
            lines.append("  Source errors:")
            for err in src.errors:
                lines.append(f"    - {err}")
        lines.append("")

    if proj.test_dirs or proj.test_files:
        lines.append("Tests:")
        if proj.test_dirs:
            lines.append(f"  Dirs: {', '.join(proj.test_dirs)}")
        if proj.test_files:
            lines.append(f"  Files: {', '.join(proj.test_files)}")
        lines.append("")

    lines.append("Project tree:")
    if proj.project_tree:
        for entry in proj.project_tree[:50]:
            lines.append(f"  {entry}")
        if len(proj.project_tree) > 50:
            lines.append(f"  ... ({len(proj.project_tree) - 50} more entries)")
    else:
        lines.append("  (empty)")
    lines.append("")

    lines.extend(_format_dependencies(result))
    lines.append("")
    lines.extend(_format_tests(result))

    if result.errors:
        lines.append("")
        lines.append("Errors:")
        for err in result.errors:
            lines.append(f"  - {err}")

    return "\n".join(lines)


_ISSUE_HEADERS = {
    "missing": "MISSING",
    "declared-not-installed": "DECLARED BUT NOT INSTALLED",
    "imported-not-declared": "IMPORTED BUT NOT DECLARED",
    "version-mismatch": "VERSION MISMATCH",
    "possibly-unused": "POSSIBLY UNUSED",
}

_ISSUE_ORDER = [
    "missing",
    "declared-not-installed",
    "imported-not-declared",
    "version-mismatch",
    "possibly-unused",
]


def _format_dependencies(result: InspectionResult) -> list[str]:
    """Render the DEPENDENCIES section of the human-readable report."""
    lines: list[str] = ["DEPENDENCIES", ""]
    deps = result.dependencies
    if deps is None or deps.skipped:
        lines.append(f"  Skipped: {deps.skipped if deps and deps.skipped else 'no data'}")
        return lines
    third_party = [i.name for i in deps.imports if i.classification == "third-party"]
    lines.append(f"  Declared: {len(deps.declared)}")
    lines.append(f"  Installed: {len(deps.installed)}")
    lines.append(f"  Third-party imports: {len(third_party)}"
                 + (f" ({', '.join(third_party)})" if third_party else ""))
    lines.append("")
    if not deps.issues:
        lines.append("  Issues: none")
    else:
        lines.append("  Issues:")
        lines.append("")
        for kind in _ISSUE_ORDER:
            kind_issues = [i for i in deps.issues if i.kind == kind]
            if not kind_issues:
                continue
            lines.append(f"  {_ISSUE_HEADERS[kind]}")
            for issue in kind_issues:
                lines.append(f"    {issue.name}")
                if kind == "version-mismatch":
                    lines.append(f"      declared: {issue.declared}")
                    lines.append(f"      installed: {issue.installed}")
            lines.append("")
    if deps.notes:
        lines.append("  Notes:")
        for note in deps.notes:
            lines.append(f"    - {note}")
    return lines


def format_json(result: InspectionResult) -> str:
    """Render the inspection result as indented JSON."""
    return json.dumps(result.to_dict(), indent=2)


def _format_tests(result: InspectionResult) -> list[str]:
    """Render the TESTS section of the human-readable report."""
    from devdoctor.diagnostics.testing import MAX_HUMAN_FAILURES

    lines: list[str] = ["TESTS", ""]
    run = result.tests
    if run is None:
        lines.append("  No test data.")
        return lines
    if run.status == "no-tests":
        lines.append("  No tests detected.")
        return lines
    if run.status == "unavailable":
        lines.append("  pytest unavailable.")
        return lines
    if run.status == "skipped":
        lines.append(f"  Skipped: {run.skipped or 'no reason given'}")
        return lines
    summary = run.result.summary
    lines.append(f"  Status: {run.status.upper()}")
    lines.append("")
    lines.append(f"  Passed: {summary.passed}")
    lines.append(f"  Failed: {summary.failed}")
    lines.append(f"  Skipped: {summary.skipped}")
    lines.append(f"  Errors: {summary.errors}")
    lines.append(f"  Duration: {summary.duration_s:.2f}s")
    if run.result.failures:
        lines.append("")
        lines.append("  Failures:")
        lines.append("")
        for number, failure in enumerate(run.result.failures[:MAX_HUMAN_FAILURES], start=1):
            lines.append(f"  {number}. {failure.test_id}")
            lines.append(f"   {failure.failure_type}")
            for message_line in failure.message.splitlines():
                lines.append(f"   {message_line.strip()}")
            lines.append("")
        omitted = len(run.result.failures) - MAX_HUMAN_FAILURES + run.result.failures_omitted
        if omitted > 0:
            lines.append(f"  ... ({omitted} more failures, see JSON output)")
    if run.result.notes:
        lines.append("  Notes:")
        for note in run.result.notes:
            lines.append(f"    - {note}")
    return lines
