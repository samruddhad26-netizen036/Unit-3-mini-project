"""Repair data models for DevDoctor Phase 6.

Structured data for repair planning, execution, and verification.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RepairAction:
    """A single repair action from the agent's fix plan."""

    action: str  # install_package | upgrade_package | downgrade_package | remove_package | create_virtualenv | update_requirements
    package: str = ""
    version: str = ""
    reason: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Return a JSON-serializable dict."""
        return {
            "action": self.action,
            "package": self.package,
            "version": self.version,
            "reason": self.reason,
            "extra": self.extra,
        }

    @classmethod
    def from_dict(cls, data: dict) -> RepairAction:
        """Create from dict."""
        return cls(
            action=data.get("action", ""),
            package=data.get("package", ""),
            version=data.get("version", ""),
            reason=data.get("reason", ""),
            extra=data.get("extra", {}),
        )


@dataclass
class RepairResult:
    """Result of executing a repair action."""

    action: RepairAction
    success: bool
    message: str = ""
    error: str | None = None
    modified_files: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Return a JSON-serializable dict."""
        return {
            "action": self.action.to_dict(),
            "success": self.success,
            "message": self.message,
            "error": self.error,
            "modified_files": self.modified_files,
        }


@dataclass
class Snapshot:
    """Lightweight snapshot of files before modification."""

    project_path: str
    files: dict[str, str] = field(default_factory=dict)  # path -> content

    def save_file(self, path: str) -> None:
        """Save a file's current content to the snapshot.

        Paths outside the project tree are ignored (never snapshotted,
        never restored) to enforce the project boundary.
        """
        from pathlib import Path

        if path not in self.files:
            try:
                resolved = Path(path).resolve()
                if not resolved.is_relative_to(Path(self.project_path).resolve()):
                    return
            except (OSError, ValueError):
                return
            try:
                with open(path, "r", encoding="utf-8") as f:
                    self.files[path] = f.read()
            except (OSError, UnicodeDecodeError):
                self.files[path] = ""

    def restore(self) -> list[str]:
        """Restore all saved files. Returns list of restored files."""
        restored = []
        for path, content in self.files.items():
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(content)
                restored.append(path)
            except OSError:
                pass
        return restored

    def to_dict(self) -> dict:
        """Return a JSON-serializable dict."""
        return {
            "project_path": self.project_path,
            "files": list(self.files.keys()),
        }


@dataclass
class RepairPlan:
    """Structured repair plan from the AI."""

    actions: list[RepairAction] = field(default_factory=list)
    reasoning: str = ""

    def to_dict(self) -> dict:
        """Return a JSON-serializable dict."""
        return {
            "actions": [a.to_dict() for a in self.actions],
            "reasoning": self.reasoning,
        }


@dataclass
class VerificationResult:
    """Result of post-repair verification."""

    success: bool
    before: dict[str, Any] = field(default_factory=dict)
    after: dict[str, Any] = field(default_factory=dict)
    message: str = ""

    def to_dict(self) -> dict:
        """Return a JSON-serializable dict."""
        return {
            "success": self.success,
            "before": self.before,
            "after": self.after,
            "message": self.message,
        }


@dataclass
class RepairReport:
    """Complete repair report including all phases."""

    initial_diagnosis: dict[str, Any] = field(default_factory=dict)
    repair_plan: RepairPlan | None = None
    user_approved: bool = False
    dry_run: bool = False
    actions_attempted: list[RepairResult] = field(default_factory=list)
    snapshot: Snapshot | None = None
    rollback_performed: bool = False
    rollback_success: bool = False
    verification: VerificationResult | None = None
    status: str = "pending"  # success | failed | cancelled | rolled-back | verification-failed | pending
    cycles: int = 0

    def to_dict(self) -> dict:
        """Return a JSON-serializable dict."""
        return {
            "initial_diagnosis": self.initial_diagnosis,
            "repair_plan": self.repair_plan.to_dict() if self.repair_plan else None,
            "user_approved": self.user_approved,
            "dry_run": self.dry_run,
            "actions_attempted": [a.to_dict() for a in self.actions_attempted],
            "snapshot": self.snapshot.to_dict() if self.snapshot else None,
            "rollback_performed": self.rollback_performed,
            "rollback_success": self.rollback_success,
            "verification": self.verification.to_dict() if self.verification else None,
            "status": self.status,
            "cycles": self.cycles,
        }


# Valid repair actions
VALID_REPAIR_ACTIONS = frozenset({
    "create_virtualenv",
    "install_package",
    "upgrade_package",
    "downgrade_package",
    "remove_package",
    "update_requirements",
})

# Final repair statuses
REPAIR_STATUSES = frozenset({
    "success",
    "failed",
    "cancelled",
    "rolled-back",
    "verification-failed",
    "pending",
})


def is_valid_repair_action(action: str) -> bool:
    """Check if an action is a valid repair action."""
    return action in VALID_REPAIR_ACTIONS


def validate_package_name(name: str) -> bool:
    """Validate package name format (leading dot allowed for names like .venv)."""
    import re
    pattern = re.compile(r"^[a-zA-Z0-9.][a-zA-Z0-9._-]*$")
    return bool(pattern.match(name)) if name else False


def validate_version(version: str) -> bool:
    """Validate version string format."""
    import re
    pattern = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._+-]*$")
    return bool(pattern.match(version)) if version else True