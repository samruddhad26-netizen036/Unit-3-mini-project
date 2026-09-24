"""Language/package-manager adapters (Phase 9)."""

from devdoctor.adapters.base import LanguageAdapter
from devdoctor.adapters.ecosystems import ECOSYSTEMS, EcosystemResult, EcosystemSpec
from devdoctor.adapters.python import PythonAdapter
from devdoctor.adapters.registry import DEFAULT_REGISTRY, AdapterRegistry, detect_ecosystems

__all__ = [
    "DEFAULT_REGISTRY",
    "ECOSYSTEMS",
    "AdapterRegistry",
    "EcosystemResult",
    "EcosystemSpec",
    "LanguageAdapter",
    "PythonAdapter",
    "detect_ecosystems",
]
