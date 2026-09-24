"""Known ecosystems and their manifest files (Phase 9).

Detection is presence-based at the project root. Only ecosystems with a
registered adapter are analyzed; the rest are reported as detected but
unsupported. No package manager is ever executed for unsupported ecosystems.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EcosystemSpec:
    """Static description of one language/package-manager ecosystem."""

    ecosystem_id: str
    display_name: str
    manifest_files: tuple[str, ...]
    adapter_id: str | None  # None means detected-but-unsupported


# Deterministic order: Python first, then the rest alphabetically by id.
ECOSYSTEMS: tuple[EcosystemSpec, ...] = (
    EcosystemSpec(
        ecosystem_id="python",
        display_name="Python/Pip",
        manifest_files=("requirements.txt", "pyproject.toml", "setup.cfg", "setup.py"),
        adapter_id="python",
    ),
    EcosystemSpec(
        ecosystem_id="go",
        display_name="Go",
        manifest_files=("go.mod",),
        adapter_id=None,
    ),
    EcosystemSpec(
        ecosystem_id="java",
        display_name="Java/Maven/Gradle",
        manifest_files=("pom.xml", "build.gradle", "build.gradle.kts"),
        adapter_id=None,
    ),
    EcosystemSpec(
        ecosystem_id="javascript",
        display_name="JavaScript/TypeScript",
        manifest_files=("package.json",),
        adapter_id=None,
    ),
    EcosystemSpec(
        ecosystem_id="rust",
        display_name="Rust/Cargo",
        manifest_files=("Cargo.toml",),
        adapter_id=None,
    ),
)


@dataclass
class EcosystemResult:
    """Detection outcome for one ecosystem in a project."""

    ecosystem_id: str
    display_name: str
    manifests_found: list[str] = field(default_factory=list)
    supported: bool = False
    message: str = ""

    def to_dict(self) -> dict:
        """Return a JSON-serializable dict."""
        return {
            "ecosystem_id": self.ecosystem_id,
            "display_name": self.display_name,
            "manifests_found": self.manifests_found,
            "supported": self.supported,
            "message": self.message,
        }
