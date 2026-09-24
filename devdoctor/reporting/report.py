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

    if result.errors:
        lines.append("")
        lines.append("Errors:")
        for err in result.errors:
            lines.append(f"  - {err}")

    return "\n".join(lines)


def format_json(result: InspectionResult) -> str:
    """Render the inspection result as indented JSON."""
    return json.dumps(result.to_dict(), indent=2)
