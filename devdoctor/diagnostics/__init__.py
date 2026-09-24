"""DevDoctor diagnostics - deterministic, read-only inspection layer."""

from devdoctor.diagnostics.dependencies import (
    analyze_dependencies,
    classify_import,
    constraint_satisfied,
    get_installed_packages,
    normalize_name,
)
from devdoctor.diagnostics.environment import inspect_environment
from devdoctor.diagnostics.inspect import inspect
from devdoctor.diagnostics.models import (
    DeclaredDependency,
    DependencyAnalysis,
    DependencyIssue,
    EnvironmentInfo,
    ImportedPackage,
    InspectionResult,
    InstalledDependency,
    ProjectInfo,
    PythonSourceInfo,
)
from devdoctor.diagnostics.project import EXCLUDE_DIRS, KNOWN_FILES, inspect_project
from devdoctor.diagnostics.source import extract_imports, inspect_python_sources

__all__ = [
    "EXCLUDE_DIRS",
    "KNOWN_FILES",
    "DeclaredDependency",
    "DependencyAnalysis",
    "DependencyIssue",
    "EnvironmentInfo",
    "ImportedPackage",
    "InspectionResult",
    "InstalledDependency",
    "ProjectInfo",
    "PythonSourceInfo",
    "analyze_dependencies",
    "classify_import",
    "constraint_satisfied",
    "extract_imports",
    "get_installed_packages",
    "inspect",
    "inspect_environment",
    "inspect_project",
    "inspect_python_sources",
    "normalize_name",
]