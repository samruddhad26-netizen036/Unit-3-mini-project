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
    "Agent",
    "AgentConfig",
    "OllamaClient",
    "OllamaError",
    "diagnose_with_ai",
    "RepairAgent",
    "RepairConfig",
    "run_repair",
    "RepairAction",
    "RepairPlan",
    "RepairReport",
    "RepairResult",
    "Snapshot",
    "VerificationResult",
    "REPAIR_TOOL_SCHEMAS",
    "get_repair_tool",
    "is_valid_repair_action",
    "is_within_project",
    "validate_package_name",
    "validate_version",
]