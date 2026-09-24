"""Structured data models for DevDoctor inspection results.

Lightweight dataclasses only - no frameworks. These are the factual
evidence objects that will later be passed to the agentic AI layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from devdoctor.adapters.ecosystems import EcosystemResult


@dataclass
class EnvironmentInfo:
    """Information about the local development environment."""

    os_name: str
    os_version: str
    architecture: str
    python_executable: str
    python_version: str
    pip_version: str | None
    is_venv: bool
    venv_path: str | None
    git_available: bool
    git_version: str | None
    docker_available: bool
    docker_version: str | None

    def to_dict(self) -> dict:
        """Return a JSON-serializable dict."""
        return {
            "os_name": self.os_name,
            "os_version": self.os_version,
            "architecture": self.architecture,
            "python_executable": self.python_executable,
            "python_version": self.python_version,
            "pip_version": self.pip_version,
            "is_venv": self.is_venv,
            "venv_path": self.venv_path,
            "git_available": self.git_available,
            "git_version": self.git_version,
            "docker_available": self.docker_available,
            "docker_version": self.docker_version,
        }


@dataclass
class PythonSourceInfo:
    """Aggregate information about Python source files in a project."""

    file_count: int = 0
    total_lines: int = 0
    imports: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Return a JSON-serializable dict."""
        return {
            "file_count": self.file_count,
            "total_lines": self.total_lines,
            "imports": self.imports,
            "files": self.files,
            "errors": self.errors,
        }


@dataclass
class ProjectInfo:
    """Information about a target project directory (read-only inspection)."""

    path: str
    exists: bool
    is_directory: bool
    name: str = ""
    python_files: list[str] = field(default_factory=list)
    test_files: list[str] = field(default_factory=list)
    test_dirs: list[str] = field(default_factory=list)
    files_present: dict[str, bool] = field(default_factory=dict)
    env_files: list[str] = field(default_factory=list)
    is_git_repo: bool = False
    git_branch: str | None = None
    git_clean: bool | None = None
    project_tree: list[str] = field(default_factory=list)
    source: PythonSourceInfo | None = None
    error: str | None = None

    def to_dict(self) -> dict:
        """Return a JSON-serializable dict."""
        return {
            "path": self.path,
            "exists": self.exists,
            "is_directory": self.is_directory,
            "name": self.name,
            "python_files": self.python_files,
            "test_files": self.test_files,
            "test_dirs": self.test_dirs,
            "files_present": self.files_present,
            "env_files": self.env_files,
            "is_git_repo": self.is_git_repo,
            "git_branch": self.git_branch,
            "git_clean": self.git_clean,
            "project_tree": self.project_tree,
            "source": self.source.to_dict() if self.source else None,
            "error": self.error,
        }


@dataclass
class InspectionResult:
    """Combined environment + project inspection result."""

    environment: EnvironmentInfo
    project: ProjectInfo
    errors: list[str] = field(default_factory=list)
    dependencies: DependencyAnalysis | None = None
    tests: TestRun | None = None
    security: SecurityAnalysis | None = None
    vulnerabilities: VulnAnalysis | None = None
    docker: DockerAnalysis | None = None
    ecosystems: list[EcosystemResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Return a JSON-serializable dict."""
        return {
            "environment": self.environment.to_dict(),
            "project": self.project.to_dict(),
            "errors": self.errors,
            "dependencies": self.dependencies.to_dict() if self.dependencies else None,
            "tests": self.tests.to_dict() if self.tests else None,
            "security": self.security.to_dict() if self.security else None,
            "vulnerabilities": self.vulnerabilities.to_dict() if self.vulnerabilities else None,
            "docker": self.docker.to_dict() if self.docker else None,
            "ecosystems": [eco.to_dict() for eco in self.ecosystems],
        }


@dataclass
class DeclaredDependency:
    """A dependency declared by the project (name + raw version constraint)."""

    name: str
    constraint: str = ""
    source: str = ""

    def to_dict(self) -> dict:
        """Return a JSON-serializable dict."""
        return {"name": self.name, "constraint": self.constraint, "source": self.source}


@dataclass
class InstalledDependency:
    """A package installed in the current Python environment."""

    name: str
    version: str

    def to_dict(self) -> dict:
        """Return a JSON-serializable dict."""
        return {"name": self.name, "version": self.version}


@dataclass
class ImportedPackage:
    """A top-level import found in project sources with its classification."""

    name: str
    classification: str = "third-party"  # stdlib | third-party | local

    def to_dict(self) -> dict:
        """Return a JSON-serializable dict."""
        return {"name": self.name, "classification": self.classification}


@dataclass
class DependencyIssue:
    """A single detected dependency problem."""

    kind: str  # missing | declared-not-installed | imported-not-declared |
    #            possibly-unused | version-mismatch
    name: str
    detail: str = ""
    declared: str | None = None
    installed: str | None = None

    def to_dict(self) -> dict:
        """Return a JSON-serializable dict."""
        return {
            "kind": self.kind,
            "name": self.name,
            "detail": self.detail,
            "declared": self.declared,
            "installed": self.installed,
        }


@dataclass
class DependencyAnalysis:
    """Declared vs installed vs imported comparison for a project."""

    declared: list[DeclaredDependency] = field(default_factory=list)
    installed: list[InstalledDependency] = field(default_factory=list)
    imports: list[ImportedPackage] = field(default_factory=list)
    issues: list[DependencyIssue] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    skipped: str | None = None

    def to_dict(self) -> dict:
        """Return a JSON-serializable dict."""
        return {
            "declared": [d.to_dict() for d in self.declared],
            "installed": [i.to_dict() for i in self.installed],
            "imports": [i.to_dict() for i in self.imports],
            "issues": [i.to_dict() for i in self.issues],
            "notes": self.notes,
            "skipped": self.skipped,
        }


@dataclass
class TestFailure:
    """Structured evidence for a single failed/errored test (no diagnosis)."""

    test_id: str
    file: str | None = None
    line: int | None = None
    failure_type: str = "unknown"
    message: str = ""
    traceback: str = ""

    def to_dict(self) -> dict:
        """Return a JSON-serializable dict."""
        return {
            "test_id": self.test_id,
            "file": self.file,
            "line": self.line,
            "failure_type": self.failure_type,
            "message": self.message,
            "traceback": self.traceback,
        }


@dataclass
class TestSummary:
    """Aggregate counts and duration for a test run."""

    total: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    errors: int = 0
    duration_s: float = 0.0

    def to_dict(self) -> dict:
        """Return a JSON-serializable dict."""
        return {
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "skipped": self.skipped,
            "errors": self.errors,
            "duration_s": self.duration_s,
        }


@dataclass
class TestResult:
    """The outcome of test analysis: summary, failures, and notes."""

    summary: TestSummary = field(default_factory=TestSummary)
    failures: list[TestFailure] = field(default_factory=list)
    failures_omitted: int = 0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Return a JSON-serializable dict."""
        return {
            "summary": self.summary.to_dict(),
            "failures": [f.to_dict() for f in self.failures],
            "failures_omitted": self.failures_omitted,
            "notes": self.notes,
        }


@dataclass
class SecurityFinding:
    """A single static-analysis security finding (values redacted)."""

    rule_id: str
    severity: str  # critical | high | medium | low
    title: str
    file: str | None = None
    line: int | None = None
    evidence: str = ""
    recommendation: str = ""

    def to_dict(self) -> dict:
        """Return a JSON-serializable dict."""
        return {
            "rule_id": self.rule_id,
            "severity": self.severity,
            "title": self.title,
            "file": self.file,
            "line": self.line,
            "evidence": self.evidence,
            "recommendation": self.recommendation,
        }


@dataclass
class SecurityAnalysis:
    """Result of the read-only static security scan."""

    findings: list[SecurityFinding] = field(default_factory=list)
    files_scanned: int = 0
    notes: list[str] = field(default_factory=list)
    skipped: str | None = None

    def to_dict(self) -> dict:
        """Return a JSON-serializable dict."""
        return {
            "findings": [f.to_dict() for f in self.findings],
            "files_scanned": self.files_scanned,
            "notes": self.notes,
            "skipped": self.skipped,
        }


@dataclass
class Vulnerability:
    """A single dependency vulnerability reported by pip-audit."""

    package: str
    installed_version: str = ""
    vuln_id: str = ""
    aliases: list[str] = field(default_factory=list)
    fix_versions: list[str] = field(default_factory=list)
    description: str = ""

    def to_dict(self) -> dict:
        """Return a JSON-serializable dict."""
        return {
            "package": self.package,
            "installed_version": self.installed_version,
            "vuln_id": self.vuln_id,
            "aliases": self.aliases,
            "fix_versions": self.fix_versions,
            "description": self.description,
        }


@dataclass
class VulnAnalysis:
    """Result of the optional local pip-audit scan."""

    vulnerabilities: list[Vulnerability] = field(default_factory=list)
    pip_audit_version: str | None = None
    notes: list[str] = field(default_factory=list)
    skipped: str | None = None

    def to_dict(self) -> dict:
        """Return a JSON-serializable dict."""
        return {
            "vulnerabilities": [v.to_dict() for v in self.vulnerabilities],
            "pip_audit_version": self.pip_audit_version,
            "notes": self.notes,
            "skipped": self.skipped,
        }


@dataclass
class DockerFinding:
    """A single Dockerfile/Compose configuration finding."""

    severity: str  # critical | high | medium | low
    title: str
    location: str = ""
    evidence: str = ""
    recommendation: str = ""

    def to_dict(self) -> dict:
        """Return a JSON-serializable dict."""
        return {
            "severity": self.severity,
            "title": self.title,
            "location": self.location,
            "evidence": self.evidence,
            "recommendation": self.recommendation,
        }


@dataclass
class DockerAnalysis:
    """Result of the read-only Dockerfile/Compose analysis."""

    docker_available: bool = False
    docker_version: str | None = None
    dockerfile_found: bool = False
    compose_files: list[str] = field(default_factory=list)
    findings: list[DockerFinding] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    skipped: str | None = None

    def to_dict(self) -> dict:
        """Return a JSON-serializable dict."""
        return {
            "docker_available": self.docker_available,
            "docker_version": self.docker_version,
            "dockerfile_found": self.dockerfile_found,
            "compose_files": self.compose_files,
            "findings": [f.to_dict() for f in self.findings],
            "notes": self.notes,
            "skipped": self.skipped,
        }


@dataclass
class TestRun:
    """Full test execution record: how tests ran plus the result."""

    status: str = "skipped"  # passed | failed | no-tests | unavailable |
    #                          timeout | error | skipped
    exit_code: int | None = None
    command: list[str] = field(default_factory=list)
    python: str | None = None
    pytest_version: str | None = None
    output: str = ""
    output_truncated: bool = False
    result: TestResult = field(default_factory=TestResult)
    skipped: str | None = None

    def to_dict(self) -> dict:
        """Return a JSON-serializable dict."""
        return {
            "status": self.status,
            "exit_code": self.exit_code,
            "command": self.command,
            "python": self.python,
            "pytest_version": self.pytest_version,
            "output": self.output,
            "output_truncated": self.output_truncated,
            "result": self.result.to_dict(),
            "skipped": self.skipped,
        }
