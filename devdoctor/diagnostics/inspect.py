"""Combined inspection entry point: environment + project + dependencies + tests."""

from __future__ import annotations

from pathlib import Path

from devdoctor.diagnostics.dependencies import analyze_dependencies
from devdoctor.diagnostics.docker import analyze_docker
from devdoctor.diagnostics.environment import inspect_environment
from devdoctor.diagnostics.models import (
    DependencyAnalysis,
    DockerAnalysis,
    InspectionResult,
    SecurityAnalysis,
    TestRun,
    VulnAnalysis,
)
from devdoctor.diagnostics.project import inspect_project
from devdoctor.diagnostics.security import analyze_security
from devdoctor.diagnostics.testing import analyze_tests
from devdoctor.diagnostics.vulnerabilities import analyze_vulnerabilities


def inspect(path: str | Path, run_tests: bool = True, run_security: bool = True,
            run_docker: bool = True) -> InspectionResult:
    """Run full read-only inspection of the environment and a target project."""
    environment = inspect_environment()
    project = inspect_project(path)
    errors: list[str] = []
    if project.error:
        errors.append(project.error)
    if project.error or not project.is_directory:
        reason = project.error or "invalid project"
        dependencies = DependencyAnalysis(skipped=f"dependency analysis skipped: {reason}")
        tests = TestRun(status="skipped", skipped=f"test analysis skipped: {reason}")
        security = SecurityAnalysis(skipped=f"security scan skipped: {reason}")
        vulnerabilities = VulnAnalysis(skipped=f"vulnerability scan skipped: {reason}")
        docker = DockerAnalysis(skipped=f"docker analysis skipped: {reason}")
    else:
        root = Path(project.path)
        imports = project.source.imports if project.source else []
        dependencies = analyze_dependencies(root, project.python_files, imports)
        if run_tests:
            tests = analyze_tests(root, project)
        else:
            tests = TestRun(status="skipped", skipped="test execution disabled (--skip-tests)")
        if run_security:
            security = analyze_security(root, project.python_files)
            vulnerabilities = analyze_vulnerabilities(root)
        else:
            security = SecurityAnalysis(skipped="security scan disabled (--skip-security)")
            vulnerabilities = VulnAnalysis(skipped="vulnerability scan disabled (--skip-security)")
        if run_docker:
            docker = analyze_docker(root, project.files_present,
                                    environment.docker_available, environment.docker_version)
        else:
            docker = DockerAnalysis(skipped="docker analysis disabled (--skip-docker)")
    return InspectionResult(
        environment=environment, project=project, errors=errors,
        dependencies=dependencies, tests=tests, security=security,
        vulnerabilities=vulnerabilities, docker=docker)
