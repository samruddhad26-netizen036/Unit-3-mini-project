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


def compare_dependency_states(before: dict[str, Any], after: dict[str, Any]) -> VerificationResult:
    """Compare pre/post-repair diagnostic states (shared verification logic).

    Both states use InspectionResult.to_dict() shape. Success requires strict
    improvement: fewer test failures, more passing tests, or fewer
    dependency issues. Identical state is not success.
    """
    tests_before = before.get("tests", {}).get("result", {}).get("summary", {})
    tests_after = after.get("tests", {}).get("result", {}).get("summary", {})
    deps_before = before.get("dependencies", {})
    deps_after = after.get("dependencies", {})

    passed_before = tests_before.get("passed", 0)
    failed_before = tests_before.get("failed", 0)
    passed_after = tests_after.get("passed", 0)
    failed_after = tests_after.get("failed", 0)

    issues_before = len(deps_before.get("issues", []))
    issues_after = len(deps_after.get("issues", []))

    test_improved = failed_after < failed_before or passed_after > passed_before
    deps_improved = issues_after < issues_before
    success = test_improved or deps_improved

    message_parts = []
    if test_improved:
        message_parts.append(
            f"Tests: {passed_before}P/{failed_before}F -> {passed_after}P/{failed_after}F")
    if deps_improved:
        message_parts.append(f"Dependency issues: {issues_before} -> {issues_after}")
    if not success:
        message_parts.append("No improvement detected")

    return VerificationResult(
        success=success,
        before={"tests": tests_before, "dependency_issues": issues_before},
        after={"tests": tests_after, "dependency_issues": issues_after},
        message="; ".join(message_parts) if message_parts else "No significant change",
    )


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


def load_repair_plan(data: object) -> RepairPlan:
    """Validate an external repair plan (e.g. from a plan file) and return it.

    Only registry actions with valid package/version values are accepted.
    Raises ValueError with a clear message for anything else.
    """
    # Uniform ValueError contract keeps CLI handling simple (not TypeError).
    if not isinstance(data, dict):
        raise ValueError("repair plan must be a JSON object")  # noqa: TRY004
    raw_actions = data.get("actions")
    if raw_actions is None:
        raise ValueError("repair plan must contain an 'actions' list")
    if not isinstance(raw_actions, list):
        raise ValueError("repair plan 'actions' must be a list")  # noqa: TRY004
    actions: list[RepairAction] = []
    for index, raw in enumerate(raw_actions):
        if not isinstance(raw, dict):
            raise ValueError(  # noqa: TRY004
                f"repair plan action #{index + 1} must be an object")
        action = RepairAction.from_dict(raw)
        if not is_valid_repair_action(action.action):
            raise ValueError(
                f"repair plan action #{index + 1} uses unknown action: {action.action!r}")
        if action.action == "update_requirements":
            actions.append(RepairAction(
                action=action.action, reason=action.reason, extra=action.extra))
            continue
        if not action.package:
            raise ValueError(
                f"repair plan action #{index + 1} ({action.action}) needs a package name")
        if not validate_package_name(action.package):
            raise ValueError(
                f"repair plan action #{index + 1} has invalid package name: "
                f"{action.package!r}")
        if action.version and not validate_version(action.version):
            raise ValueError(
                f"repair plan action #{index + 1} has invalid version: "
                f"{action.version!r}")
        actions.append(action)
    reasoning = data.get("reasoning", "")
    if reasoning is not None and not isinstance(reasoning, str):
        raise ValueError("repair plan 'reasoning' must be a string")
    return RepairPlan(actions=actions, reasoning=reasoning or "")