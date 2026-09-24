"""Python/Pip adapter (Phase 9).

Thin wrapper over the existing Phase 3/6 implementation. No parsing or
repair logic is duplicated here: analysis reuses diagnostics/dependencies.py
and diagnostics/source.py, installation reuses agent/repair_tools.py, and
verification reuses the shared compare function in agent/repair_models.py.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from devdoctor.adapters.base import LanguageAdapter
from devdoctor.diagnostics.dependencies import (
    analyze_dependencies,
    get_installed_packages,
)
from devdoctor.diagnostics.project import EXCLUDE_DIRS, inspect_project

if TYPE_CHECKING:
    from devdoctor.agent.repair_models import (
        RepairAction,
        RepairPlan,
        RepairResult,
        Snapshot,
        VerificationResult,
    )
    from devdoctor.diagnostics.models import (
        DependencyAnalysis,
        InstalledDependency,
    )


def _exact_pin(constraint: str) -> str:
    """Extract an exact `==x.y.z` pin, else empty (not safely pinnable)."""
    match = re.fullmatch(r"==([^,]+)", (constraint or "").strip())
    if not match:
        return ""
    version = match.group(1).strip()
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]*", version):
        return version
    return ""


def _has_python_files(root: Path, cap: int = 200) -> bool:
    """Bounded scan for *.py files, skipping excluded directories."""
    import os

    seen = 0
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDE_DIRS)
        for filename in filenames:
            seen += 1
            if seen > cap:
                return False
            if filename.endswith(".py"):
                return True
    return False


class PythonAdapter(LanguageAdapter):
    """Adapter for Python projects managed with Pip."""

    id = "python"
    display_name = "Python/Pip"
    manifest_files = ("requirements.txt", "pyproject.toml", "setup.cfg", "setup.py")

    def detect(self, root: Path) -> bool:
        """Check for Python manifests or Python source files.

        Manifest-less script directories keep working exactly as before
        (Phase 3 analyzed every directory with Python files).
        """
        if any((root / name).is_file() for name in self.manifest_files):
            return True
        return _has_python_files(root)

    def analyze_dependencies(self, root: Path) -> DependencyAnalysis:
        """Run the Phase 3 declared/installed/imported comparison (read-only)."""
        from devdoctor.diagnostics.models import DependencyAnalysis

        project = inspect_project(root)
        if project.error or not project.is_directory:
            return DependencyAnalysis(
                skipped=f"dependency analysis skipped: {project.error or 'invalid project'}")
        imports = project.source.imports if project.source else []
        return analyze_dependencies(root, project.python_files, imports)

    def get_installed_dependencies(self, root: Path) -> list[InstalledDependency]:
        """List installed distributions via importlib.metadata (read-only)."""
        from devdoctor.diagnostics.models import InstalledDependency

        del root  # environment-wide query; path kept for interface symmetry
        installed = get_installed_packages()
        return [InstalledDependency(name=name, version=installed[name])
                for name in sorted(installed)]

    def plan_installation(self, issues: list[Any]) -> RepairPlan:
        """Build a deterministic install plan from dependency issues.

        Only safely auto-installable kinds become actions; removals and
        undeclared imports are never auto-proposed.
        """
        from devdoctor.agent.repair_models import RepairAction, RepairPlan

        actions: list[RepairAction] = []
        seen: set[str] = set()
        for issue in issues:
            kind = issue.kind if hasattr(issue, "kind") else issue.get("kind", "")
            name = issue.name if hasattr(issue, "name") else issue.get("name", "")
            if kind not in ("missing", "declared-not-installed", "version-mismatch"):
                continue
            key = name.lower()
            if not key or key in seen:
                continue
            seen.add(key)
            declared = issue.declared if hasattr(issue, "declared") else issue.get("declared")
            version = _exact_pin(declared or "")
            detail = issue.detail if hasattr(issue, "detail") else issue.get("detail", "")
            action = "upgrade_package" if kind == "version-mismatch" else "install_package"
            actions.append(RepairAction(action=action, package=name,
                                        version=version, reason=detail or kind))
        return RepairPlan(
            actions=actions,
            reasoning=(f"{len(actions)} package(s) to install/upgrade "
                       "based on dependency analysis"),
        )

    def install(self, root: Path, plan: RepairPlan,
                snapshot: Snapshot | None = None) -> list[RepairResult]:
        """Execute an approved plan with the controlled repair tools."""
        from devdoctor.agent.repair_models import RepairResult, is_valid_repair_action
        from devdoctor.agent.repair_tools import get_repair_tool

        results: list[RepairResult] = []
        for action in plan.actions:
            tool_func = get_repair_tool(action.action)
            if tool_func is None or not is_valid_repair_action(action.action):
                results.append(RepairResult(
                    action=action, success=False,
                    error=f"Unknown repair action: {action.action}"))
                continue
            try:
                results.append(tool_func(root, action, snapshot))
            except (OSError, RuntimeError, ValueError) as exc:
                results.append(RepairResult(
                    action=action, success=False,
                    error=f"Tool execution failed: {exc}"))
        return results

    def verify(self, root: Path, before: dict[str, Any]) -> VerificationResult:
        """Compare post-install state against a captured before-state."""
        from devdoctor.agent.repair_models import compare_dependency_states
        from devdoctor.diagnostics import inspect as _inspect

        after = _inspect(root, run_tests=True).to_dict()
        return compare_dependency_states(before, after)
