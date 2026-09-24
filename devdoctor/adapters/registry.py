"""Adapter registry and ecosystem detection (Phase 9).

No giant if/elif dispatcher: adapters self-register by ecosystem id, and
detection walks the declarative ECOSYSTEMS table. Order is deterministic
(registration order for adapters, table order for detection).
"""

from __future__ import annotations

import os
from pathlib import Path

from devdoctor.adapters.base import LanguageAdapter
from devdoctor.adapters.ecosystems import ECOSYSTEMS, EcosystemResult


class AdapterRegistry:
    """Maps ecosystem ids to adapter instances."""

    def __init__(self) -> None:
        self._adapters: dict[str, LanguageAdapter] = {}

    def register(self, adapter: LanguageAdapter) -> None:
        """Register an adapter, keyed by its ecosystem id."""
        if not adapter.id:
            raise ValueError("adapter must define a non-empty id")
        self._adapters[adapter.id] = adapter

    def get(self, ecosystem_id: str) -> LanguageAdapter | None:
        """Look up an adapter by ecosystem id."""
        return self._adapters.get(ecosystem_id)

    def ids(self) -> list[str]:
        """Registered ecosystem ids in registration order."""
        return list(self._adapters)

    def for_project(self, root: str | Path) -> list[LanguageAdapter]:
        """Adapters whose detect() matches, in registration order."""
        base = Path(root)
        return [adapter for adapter in self._adapters.values() if adapter.detect(base)]


_builtins_registered = False


def ensure_builtin_adapters() -> None:
    """Register built-in adapters once (lazy: avoids import-time cycles)."""
    global _builtins_registered
    if _builtins_registered:
        return
    from devdoctor.adapters.python import PythonAdapter

    DEFAULT_REGISTRY.register(PythonAdapter())
    _builtins_registered = True


def detect_ecosystems(root: str | Path,
                      registry: AdapterRegistry | None = None) -> list[EcosystemResult]:
    """Detect ecosystems by root-level manifests (never executes anything).

    Returns one result per ecosystem with at least one manifest present.
    Unsupported ecosystems carry an explanatory message and trigger no
    analysis, installation, or package-manager execution.
    """
    if registry is None:
        ensure_builtin_adapters()
        registry = DEFAULT_REGISTRY
    base = Path(root)
    try:
        entries = {entry.name for entry in os.scandir(base) if entry.is_file()}
    except OSError:
        return []
    active = registry
    results: list[EcosystemResult] = []
    for spec in ECOSYSTEMS:
        found = [name for name in spec.manifest_files if name in entries]
        if not found:
            continue
        adapter = active.get(spec.adapter_id) if spec.adapter_id else None
        if adapter is not None:
            results.append(EcosystemResult(
                ecosystem_id=spec.ecosystem_id,
                display_name=spec.display_name,
                manifests_found=found,
                supported=True,
                message=f"supported via {adapter.display_name} adapter",
            ))
        else:
            results.append(EcosystemResult(
                ecosystem_id=spec.ecosystem_id,
                display_name=spec.display_name,
                manifests_found=found,
                supported=False,
                message=(f"{spec.display_name} detected ({', '.join(found)}) "
                         "but is not yet supported: no analysis or installation performed"),
            ))
    return results


# Shared registry. Built-in adapters register lazily via
# ensure_builtin_adapters() (called by detect_ecosystems() and inspect()),
# which keeps module import order cycle-free. Accessing .ids()/.get()
# directly before any detection may show an empty registry.
DEFAULT_REGISTRY = AdapterRegistry()
