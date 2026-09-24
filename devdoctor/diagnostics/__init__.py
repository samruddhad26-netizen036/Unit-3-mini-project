"""DevDoctor diagnostics - deterministic, read-only inspection layer."""

from devdoctor.diagnostics.dependencies import (
    analyze_dependencies,
    classify_import,
    constraint_satisfied,
    get_installed_packages,
    normalize_name,
)
from devdoctor.diagnostics.docker import analyze_docker
from devdoctor.diagnostics.environment import inspect_environment
from devdoctor.diagnostics.inspect import inspect
from devdoctor.diagnostics.models import (
    DeclaredDependency,
    DependencyAnalysis,
    DependencyIssue,
    DockerAnalysis,
    DockerFinding,
    EnvironmentInfo,
    ImportedPackage,
    InspectionResult,
    InstalledDependency,
    ProjectInfo,
    PythonSourceInfo,
    SecurityAnalysis,
    SecurityFinding,
    TestFailure,
    TestResult,
    TestRun,
    TestSummary,
    VulnAnalysis,
    Vulnerability,
)
from devdoctor.diagnostics.project import EXCLUDE_DIRS, KNOWN_FILES, inspect_project
from devdoctor.diagnostics.security import analyze_security
from devdoctor.diagnostics.source import extract_imports, inspect_python_sources
from devdoctor.diagnostics.testing import analyze_tests
from devdoctor.diagnostics.vulnerabilities import analyze_vulnerabilities

__all__ = [
    "EXCLUDE_DIRS",
    "KNOWN_FILES",
    "DeclaredDependency",
    "DependencyAnalysis",
    "DependencyIssue",
    "DockerAnalysis",
    "DockerFinding",
    "EnvironmentInfo",
    "ImportedPackage",
    "InspectionResult",
    "InstalledDependency",
    "ProjectInfo",
    "PythonSourceInfo",
    "SecurityAnalysis",
    "SecurityFinding",
    "TestFailure",
    "TestResult",
    "TestRun",
    "TestSummary",
    "VulnAnalysis",
    "Vulnerability",
    "analyze_dependencies",
    "analyze_docker",
    "analyze_security",
    "analyze_tests",
    "analyze_vulnerabilities",
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