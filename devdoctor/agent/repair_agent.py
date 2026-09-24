"""Repair agent for DevDoctor Phase 6.

Coordinates diagnosis, repair planning, execution, verification, and rollback.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from devdoctor.agent.ollama import OllamaClient, OllamaError
from devdoctor.agent.repair_models import (
    RepairAction,
    RepairPlan,
    RepairReport,
    RepairResult,
    Snapshot,
    VerificationResult,
    compare_dependency_states,
    is_valid_repair_action,
)
from devdoctor.agent.repair_tools import (
    REPAIR_TOOL_SCHEMAS,
    get_repair_tool,
    validate_package_name,
)
from devdoctor.diagnostics import inspect


@dataclass
class RepairConfig:
    """Configuration for repair operations."""

    max_repair_cycles: int = 3
    auto_approve: bool = False
    dry_run: bool = False
    model: str | None = None
    ollama_url: str | None = None


class RepairAgent:
    """Agent that can diagnose, plan, and execute repairs on a Python project."""

    def __init__(self, project_path: str, config: RepairConfig | None = None):
        self.project_path = Path(project_path).resolve()
        self.config = config or RepairConfig()
        self.client = OllamaClient(
            base_url=self.config.ollama_url or "http://localhost:11434",
            model=self.config.model or os.environ.get("DEVDOCTOR_MODEL", "qwen2.5-coder:7b"),
        )
        self.snapshot = Snapshot(project_path=str(self.project_path))
        self.report = RepairReport()

    def _build_repair_system_prompt(self) -> str:
        """Build system prompt for repair planning."""
        tool_descriptions = "\n".join(
            f"- {name}: {schema.get('description', '')}" for name, schema in REPAIR_TOOL_SCHEMAS.items()
        )
        return f"""You are DevDoctor, a local-first developer assistant for Python environment repair.

Your task is to analyze a Python project's health, propose a repair plan, and execute repairs safely.

AVAILABLE REPAIR ACTIONS:
{tool_descriptions}

IMPORTANT RULES:
1. You can ONLY propose actions from the list above. No arbitrary commands.
2. Each action must have a clear reason based on diagnostic evidence.
3. Package names and versions must be valid.
4. Prefer install_package for missing dependencies.
5. Use upgrade_package/downgrade_package for version mismatches.
6. Use remove_package ONLY for packages identified as "possibly unused".
7. Use create_virtualenv if no venv exists and packages need isolation.
8. Use update_requirements to sync requirements.txt after changes.
9. Actions must be ordered logically (e.g., create venv before install).

OUTPUT FORMAT:
When ready to propose a repair plan, respond with JSON:
{{
  "repair_plan": {{
    "actions": [
      {{"action": "install_package", "package": "pandas", "version": "2.2.3", "reason": "Required by project but not installed"}}
    ],
    "reasoning": "Explanation of the plan..."
  }}
}}

When the user confirms, you will execute the plan step by step.
After each action, you'll receive the result and can re-plan if needed.
Maximum {self.config.max_repair_cycles} repair cycles."""

    def _capture_pre_repair_state(self) -> dict[str, Any]:
        """Capture pre-repair diagnostic state for verification."""
        result = inspect(self.project_path, run_tests=True)
        return {
            "tests": result.tests.to_dict() if result.tests else None,
            "dependencies": result.dependencies.to_dict() if result.dependencies else None,
            "errors": result.errors,
        }

    def _verify_repair(self, before: dict[str, Any]) -> VerificationResult:
        """Compare pre- and post-repair state (shared logic in repair_models)."""
        after = inspect(self.project_path, run_tests=True).to_dict()
        return compare_dependency_states(before, after)

    def _audit(self, event: str, status: str = "", metadata: dict | None = None) -> None:
        """Emit an audit event (never raises; no-op when auditing is disabled)."""
        from devdoctor.reporting.audit import audit_event

        audit_event(event, project=str(self.project_path), status=status,
                    metadata=metadata or {})

    def _execute_action(self, action: RepairAction) -> RepairResult:
        """Execute a single repair action."""
        tool_func = get_repair_tool(action.action)
        if not tool_func:
            return RepairResult(
                action=action,
                success=False,
                error=f"Unknown repair action: {action.action}",
            )

        try:
            return tool_func(self.project_path, action, self.snapshot)
        except (OSError, RuntimeError, ValueError) as exc:
            return RepairResult(
                action=action,
                success=False,
                error=f"Tool execution failed: {exc}",
            )

    def _get_user_confirmation(self, plan: RepairPlan) -> bool:
        """Prompt user for confirmation."""
        if self.config.auto_approve:
            return True

        print("\nPROPOSED REPAIR")
        print()
        for i, action in enumerate(plan.actions, 1):
            ver = f"=={action.version}" if action.version else ""
            print(f"  {i}. {action.action} {action.package}{ver}")
            print(f"     Reason: {action.reason}")
        print()

        if self.config.dry_run:
            print("DRY RUN - No changes will be made.")
            print()
            return False

        try:
            response = input("Proceed? [y/N]: ").strip().lower()
            return response in ("y", "yes")
        except (EOFError, KeyboardInterrupt):
            return False

    def diagnose_and_plan(self) -> RepairPlan | None:
        """Run diagnosis and generate repair plan via AI."""
        if not self.client.is_available():
            raise OllamaError(
                f"Ollama is not available at {self.client.base_url}. "
                "Ensure Ollama is running and a model is installed."
            )

        # Get initial diagnostic context
        context = self._capture_pre_repair_state()

        self.messages = [
            {"role": "system", "content": self._build_repair_system_prompt()},
            {
                "role": "user",
                "content": f"Analyze and propose a repair plan for project: {self.project_path}\n\n"
                f"{json.dumps(context, indent=2)}",
            },
        ]

        # Get available tool definitions (for repair tools)
        ollama_tools = [
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": schema.get("description", ""),
                    "parameters": schema,
                },
            }
            for name, schema in REPAIR_TOOL_SCHEMAS.items()
        ]

        try:
            response = self.client.chat(self.messages, tools=ollama_tools)
        except OllamaError as exc:
            raise OllamaError(f"Model communication failed: {exc}")

        message = response.get("message", {})
        content = message.get("content", "")

        # Check for repair plan in response
        try:
            parsed = json.loads(content)
            if "repair_plan" in parsed:
                plan_data = parsed["repair_plan"]
                actions = [RepairAction.from_dict(a) for a in plan_data.get("actions", [])]

                # Validate all actions
                for action in actions:
                    if not is_valid_repair_action(action.action):
                        raise ValueError(f"Invalid repair action: {action.action}")
                    if not validate_package_name(action.package):
                        raise ValueError(f"Invalid package name: {action.package}")

                plan = RepairPlan(
                    actions=actions,
                    reasoning=plan_data.get("reasoning", ""),
                )
                self._audit("repair_plan_generated", status="ok",
                            metadata={"actions": len(actions)})
                return plan
        except (json.JSONDecodeError, ValueError, KeyError) as exc:
            raise OllamaError(f"Invalid repair plan from model: {exc}")

        return None

    def run_repair_cycle(self, plan: RepairPlan) -> bool:
        """Execute a repair plan cycle. Returns True if successful."""
        self.report.repair_plan = plan
        self.report.user_approved = True

        # Capture pre-repair state
        before_state = self._capture_pre_repair_state()
        self.report.initial_diagnosis = before_state

        if self.config.dry_run:
            self.report.dry_run = True
            self.report.status = "cancelled"
            return False

        # Execute each action
        for action in plan.actions:
            self.report.cycles += 1
            print(f"\nExecuting: {action.action} {action.package}" + (f"=={action.version}" if action.version else ""))
            result = self._execute_action(action)
            self.report.actions_attempted.append(result)
            self._audit("repair_action",
                        status="ok" if result.success else "failed",
                        metadata={"action": action.action, "package": action.package,
                                  "version": action.version})

            if not result.success:
                print(f"  FAILED: {result.error}")
                # Attempt rollback
                self._rollback()
                return False
            else:
                print(f"  SUCCESS: {result.message}")
                if result.modified_files:
                    for f in result.modified_files:
                        print(f"  Modified: {f}")

        # Verify repair
        print("\nVerifying repair...")
        verification = self._verify_repair(before_state)
        self.report.verification = verification
        self._audit("verification_result",
                    status="success" if verification.success else "failed",
                    metadata={"message": verification.message})

        if verification.success:
            print(f"VERIFICATION: SUCCESS - {verification.message}")
            self.report.status = "success"
            return True
        else:
            print(f"VERIFICATION: FAILED - {verification.message}")
            self.report.status = "verification-failed"
            return False

    def _rollback(self) -> bool:
        """Rollback changes from snapshot."""
        if not self.snapshot.files:
            self.report.rollback_performed = True
            self.report.rollback_success = True
            self.report.status = "rolled-back"
            self._audit("rollback_result", status="success",
                        metadata={"restored_files": 0})
            return True

        print("\nRolling back changes...")
        self.report.rollback_performed = True
        restored = self.snapshot.restore()
        self._audit("rollback_result",
                    status="success" if restored else "failed",
                    metadata={"restored_files": len(restored)})

        if restored:
            print(f"Restored {len(restored)} files")
            self.report.rollback_success = True
        else:
            print("Rollback failed - no files to restore or restore failed")
            self.report.rollback_success = False

        self.report.status = "rolled-back"
        return self.report.rollback_success

    def _check_backend(self) -> str | None:
        """Fail-fast check: Ollama reachable AND configured model installed.

        Returns an actionable error message, or None when usable.
        Runs before any (slow) project inspection.
        """
        if not self.client.is_available():
            return (
                f"Ollama is not available at {self.client.base_url}. "
                "Ensure Ollama is running and a model is installed."
            )
        return self._check_model()

    def _check_model(self) -> str | None:
        """Check the configured model is pulled. None when OK or indeterminable."""
        import json as json_lib
        import urllib.request

        try:
            with urllib.request.urlopen(
                f"{self.client.base_url.rstrip('/')}/api/tags", timeout=10
            ) as resp:
                data = json_lib.load(resp)
        except (OSError, ValueError):
            return None  # Cannot determine; let the chat attempt surface the error.
        models = [
            entry.get("name", "")
            for entry in data.get("models", [])
            if isinstance(entry, dict)
        ]

        def _base(name: str) -> str:
            return name.removesuffix(":latest")

        want = self.client.model
        if any(_base(entry) == _base(want) for entry in models):
            return None
        return (
            f"Ollama model '{want}' not found. "
            f"Pull it with: ollama pull {want}"
        )

    def run_with_plan(self, plan: RepairPlan) -> RepairReport:
        """Execute a pre-approved plan without LLM planning (single cycle).

        Used by deterministic callers (e.g. the VS Code extension) that build
        the plan from diagnostic evidence and obtain user approval themselves.
        Honors dry-run mode; no LLM re-planning is attempted.
        """
        self.report = RepairReport()
        self.report.repair_plan = plan

        if not plan.actions:
            self.report.status = "success"  # Nothing to do
            self.report.initial_diagnosis = self._capture_pre_repair_state()
            print("No repairs needed.")
            return self.report

        if self.config.dry_run:
            # Reuse the confirmation display for a consistent dry-run preview.
            self._get_user_confirmation(plan)
            self.report.dry_run = True
            self.report.status = "cancelled"
            return self.report

        if not self.config.auto_approve and not self._get_user_confirmation(plan):
            self.report.status = "cancelled"
            self._audit("repair_cancelled", status="cancelled",
                        metadata={"actions": len(plan.actions)})
            print("Repair cancelled.")
            return self.report

        self._audit("repair_approved", status="ok",
                    metadata={"actions": len(plan.actions),
                              "dry_run": self.config.dry_run})
        print(f"Executing approved plan ({len(plan.actions)} actions)...")
        self.run_repair_cycle(plan)
        return self.report

    def run(self) -> RepairReport:
        """Run the full repair workflow."""
        self.report = RepairReport()

        backend_error = self._check_backend()
        if backend_error:
            print(backend_error)
            self.report.status = "failed"
            self.report.initial_diagnosis = {"error": backend_error}
            return self.report

        try:
            # Phase 1: Diagnose and plan
            print(f"Diagnosing project: {self.project_path}")
            plan = self.diagnose_and_plan()

            if not plan or not plan.actions:
                self.report.status = "success"  # No repairs needed
                self.report.initial_diagnosis = self._capture_pre_repair_state()
                print("No repairs needed.")
                return self.report

            # Phase 2: Confirmation
            if not self._get_user_confirmation(plan):
                self.report.status = "cancelled"
                self._audit("repair_cancelled", status="cancelled",
                            metadata={"actions": len(plan.actions)})
                print("Repair cancelled.")
                return self.report
            self._audit("repair_approved", status="ok",
                        metadata={"actions": len(plan.actions),
                                  "dry_run": self.config.dry_run})

            # Phase 3: Repair cycles with re-planning
            for cycle in range(self.config.max_repair_cycles):
                print(f"\n=== Repair Cycle {cycle + 1}/{self.config.max_repair_cycles} ===")
                success = self.run_repair_cycle(plan)

                if success:
                    return self.report

                # Re-plan if verification failed
                if cycle < self.config.max_repair_cycles - 1:
                    print(f"\nRe-planning after cycle {cycle + 1}...")
                    plan = self.diagnose_and_plan()
                    if not plan or not plan.actions:
                        print("No further repairs possible.")
                        break

            # Max cycles reached
            self.report.status = "failed"
            print(f"\nMax repair cycles ({self.config.max_repair_cycles}) reached.")

        except OllamaError as exc:
            self.report.status = "failed"
            self.report.initial_diagnosis = {"error": str(exc)}

        return self.report

    @property
    def messages(self) -> list[dict]:
        """Get or initialize message history."""
        if not hasattr(self, "_messages"):
            self._messages = []
        return self._messages

    @messages.setter
    def messages(self, value: list[dict]):
        self._messages = value


def run_repair(project_path: str, config: RepairConfig | None = None) -> RepairReport:
    """Convenience function to run repair on a project."""
    agent = RepairAgent(project_path, config)
    return agent.run()