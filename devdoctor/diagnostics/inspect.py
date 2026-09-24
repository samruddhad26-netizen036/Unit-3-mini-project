"""Combined inspection entry point: environment + project."""

from __future__ import annotations

from pathlib import Path

from devdoctor.diagnostics.environment import inspect_environment
from devdoctor.diagnostics.models import InspectionResult
from devdoctor.diagnostics.project import inspect_project


def inspect(path: str | Path) -> InspectionResult:
    """Run full read-only inspection of the environment and a target project."""
    environment = inspect_environment()
    project = inspect_project(path)
    errors: list[str] = []
    if project.error:
        errors.append(project.error)
    return InspectionResult(environment=environment, project=project, errors=errors)
