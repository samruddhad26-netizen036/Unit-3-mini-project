"""Structured data models for DevDoctor inspection results.

Lightweight dataclasses only - no frameworks. These are the factual
evidence objects that will later be passed to the agentic AI layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field


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

    def to_dict(self) -> dict:
        """Return a JSON-serializable dict."""
        return {
            "environment": self.environment.to_dict(),
            "project": self.project.to_dict(),
            "errors": self.errors,
            "dependencies": self.dependencies.to_dict() if self.dependencies else None,
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
