"""Language/package-manager adapter interface (Phase 9).

Defines the contract every ecosystem adapter implements. Only Python has
a concrete adapter in this phase; other detected ecosystems report as
unsupported without analysis or modification.
"""

from __future__ import annotations

import abc
from pathlib import Path
from typing import Any


class LanguageAdapter(abc.ABC):
    """Contract for one language/package-manager ecosystem."""

    #: Stable machine-readable id, e.g. "python".
    id: str = ""
    #: Human-readable name, e.g. "Python/Pip".
    display_name: str = ""
    #: Manifest filenames probed at the project root, in priority order.
    manifest_files: tuple[str, ...] = ()

    @abc.abstractmethod
    def detect(self, root: Path) -> bool:
        """Check whether this ecosystem applies to the project."""

    @abc.abstractmethod
    def analyze_dependencies(self, root: Path) -> Any:
        """Run dependency analysis. Read-only; returns a DependencyAnalysis."""

    @abc.abstractmethod
    def get_installed_dependencies(self, root: Path) -> list[Any]:
        """List installed packages. Read-only; returns InstalledDependency list."""

    @abc.abstractmethod
    def plan_installation(self, issues: list[Any]) -> Any:
        """Build a deterministic install plan from dependency issues."""

    @abc.abstractmethod
    def install(self, root: Path, plan: Any, snapshot: Any | None = None) -> list[Any]:
        """Execute an approved plan. Returns one RepairResult per action."""

    @abc.abstractmethod
    def verify(self, root: Path, before: dict[str, Any]) -> Any:
        """Compare post-install state against a captured before-state."""
