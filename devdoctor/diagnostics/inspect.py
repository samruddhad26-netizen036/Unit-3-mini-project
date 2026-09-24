"""Combined inspection entry point: environment + project + dependencies."""

from __future__ import annotations

from pathlib import Path

from devdoctor.diagnostics.dependencies import analyze_dependencies
from devdoctor.diagnostics.environment import inspect_environment
from devdoctor.diagnostics.models import DependencyAnalysis, InspectionResult
from devdoctor.diagnostics.project import inspect_project


def inspect(path: str | Path) -> InspectionResult:
    """Run full read-only inspection of the environment and a target project."""
    environment = inspect_environment()
    project = inspect_project(path)
    errors: list[str] = []
    if project.error:
        errors.append(project.error)
    if project.error or not project.is_directory:
        dependencies = DependencyAnalysis(
            skipped=f"dependency analysis skipped: {project.error or 'invalid project'}")
    else:
        root = Path(project.path)
        imports = project.source.imports if project.source else []
        dependencies = analyze_dependencies(root, project.python_files, imports)
    return InspectionResult(
        environment=environment, project=project, errors=errors, dependencies=dependencies)
