"""DevDoctor Agent - local LLM-powered diagnostic agent."""

from devdoctor.agent.core import Agent, AgentConfig, diagnose_with_ai
from devdoctor.agent.ollama import OllamaClient, OllamaError
from devdoctor.agent.repair_agent import RepairAgent, RepairConfig, run_repair
from devdoctor.agent.repair_models import (
    RepairAction,
    RepairPlan,
    RepairReport,
    RepairResult,
    Snapshot,
    VerificationResult,
)
from devdoctor.agent.repair_tools import (
    REPAIR_TOOL_SCHEMAS,
    get_repair_tool,
    is_valid_repair_action,
    is_within_project,
    validate_package_name,
    validate_version,
)

__all__ = [
    "REPAIR_TOOL_SCHEMAS",
    "Agent",
    "AgentConfig",
    "OllamaClient",
    "OllamaError",
    "RepairAction",
    "RepairAgent",
    "RepairConfig",
    "RepairPlan",
    "RepairReport",
    "RepairResult",
    "Snapshot",
    "VerificationResult",
    "diagnose_with_ai",
    "get_repair_tool",
    "is_valid_repair_action",
    "is_within_project",
    "run_repair",
    "validate_package_name",
    "validate_version",
]