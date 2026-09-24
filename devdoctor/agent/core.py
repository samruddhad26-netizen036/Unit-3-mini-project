"""DevDoctor Agent - local LLM-powered diagnostic agent.

Provides a read-only agent that can reason over diagnostic evidence
and use controlled tools to investigate a Python project.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from devdoctor.agent.ollama import OllamaClient, OllamaError


@dataclass
class ToolCall:
    """A single tool invocation request from the model."""

    name: str
    arguments: dict


@dataclass
class ToolResult:
    """Result of executing a tool."""

    name: str
    success: bool
    data: Any = None
    error: str | None = None


@dataclass
class AgentConfig:
    """Agent runtime configuration."""

    max_iterations: int = 8
    model: str | None = None
    ollama_url: str | None = None


class AgentTool:
    """Wrapper for a read-only diagnostic tool."""

    def __init__(
        self,
        name: str,
        description: str,
        parameters: dict,
        function: Callable[..., Any],
    ):
        self.name = name
        self.description = description
        self.parameters = parameters  # JSON Schema
        self.function = function

    def to_ollama_tool(self) -> dict:
        """Convert to Ollama tool definition format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def execute(self, **kwargs) -> ToolResult:
        """Execute the tool with given arguments."""
        try:
            result = self.function(**kwargs)
            return ToolResult(name=self.name, success=True, data=result)
        except (ValueError, TypeError, KeyError, AttributeError, RuntimeError) as exc:
            return ToolResult(name=self.name, success=False, error=str(exc))


@dataclass
class Agent:
    """Local LLM agent for diagnostic reasoning.

    The agent receives diagnostic evidence and can invoke read-only
    tools to gather more information before producing a diagnosis.
    """

    project_path: str
    config: AgentConfig = field(default_factory=AgentConfig)
    client: OllamaClient | None = None
    tools: dict[str, AgentTool] = field(default_factory=dict)
    messages: list[dict] = field(default_factory=list)

    def __post_init__(self):
        # Initialize Ollama client
        self.client = OllamaClient(
            base_url=self.config.ollama_url or "http://localhost:11434",
            model=self.config.model or "qwen2.5-coder:7b",
        )
        # Register built-in tools
        self._register_tools()

    def _register_tools(self):
        """Register built-in read-only diagnostic tools."""
        from devdoctor.diagnostics import (
            inspect_environment,
            inspect_project,
        )

        self.tools["inspect_environment"] = AgentTool(
            name="inspect_environment",
            description="Inspect the local development environment (OS, Python, Git, Docker, etc.)",
            parameters={
                "type": "object",
                "properties": {},
                "required": [],
            },
            function=lambda: inspect_environment().to_dict(),
        )

        self.tools["inspect_project"] = AgentTool(
            name="inspect_project",
            description="Inspect the target project structure, files, and git status",
            parameters={
                "type": "object",
                "properties": {},
                "required": [],
            },
            function=lambda: inspect_project(self.project_path).to_dict(),
        )

        self.tools["analyze_dependencies"] = AgentTool(
            name="analyze_dependencies",
            description="Analyze declared vs installed vs imported dependencies",
            parameters={
                "type": "object",
                "properties": {},
                "required": [],
            },
            function=lambda: self._run_dependency_analysis(),
        )

        self.tools["run_tests"] = AgentTool(
            name="run_tests",
            description="Run the project's test suite and extract failure evidence",
            parameters={
                "type": "object",
                "properties": {},
                "required": [],
            },
            function=lambda: self._run_test_analysis(),
        )

    def _run_dependency_analysis(self) -> dict:
        """Run dependency analysis on the target project."""
        from pathlib import Path

        from devdoctor.diagnostics import analyze_dependencies, inspect_project

        project = inspect_project(self.project_path)
        if project.error or not project.is_directory:
            return {"error": project.error or "invalid project"}
        root = Path(project.path)
        imports = project.source.imports if project.source else []
        return analyze_dependencies(root, project.python_files, imports).to_dict()

    def _run_test_analysis(self) -> dict:
        """Run test analysis on the target project."""
        from pathlib import Path

        from devdoctor.diagnostics import analyze_tests, inspect_project

        project = inspect_project(self.project_path)
        if project.error or not project.is_directory:
            return {"error": project.error or "invalid project"}
        return analyze_tests(Path(project.path), project).to_dict()

    def _build_system_prompt(self) -> str:
        """Build the system prompt with available tools and instructions."""
        tool_descriptions = "\n".join(
            f"- {t.name}: {t.description}" for t in self.tools.values()
        )
        return f"""You are DevDoctor, a local-first developer assistant for Python environment diagnostics.

Your task is to analyze a Python project's health by examining diagnostic evidence.
You have access to the following read-only tools:

{tool_descriptions}

IMPORTANT RULES:
1. You are READ-ONLY. Never modify files, install packages, or execute arbitrary commands.
2. Use tools to gather evidence when you need more information.
3. Base your diagnosis on evidence, not assumptions.
4. Distinguish between confirmed facts (from tools) and your reasoning.
5. When you have enough evidence, provide a structured diagnosis.

OUTPUT FORMAT:
When ready to diagnose, respond with a JSON object containing:
{{
  "diagnosis": {{
    "status": "healthy | issues-found | repair-required",
    "problems": [
      {{
        "title": "Brief problem description",
        "evidence": ["Evidence point 1", "Evidence point 2"],
        "likely_cause": "Root cause analysis",
        "recommended_action": "Next step to resolve",
        "confidence": "high | medium | low"
      }}
    ],
    "summary": "Overall assessment"
  }}
}}

If you need to use a tool, respond with a tool call in the format the system expects.
You have a maximum of {self.config.max_iterations} iterations."""

    def _extract_tool_calls(self, response: dict) -> list[ToolCall]:
        """Extract tool calls from Ollama response."""
        calls = []
        message = response.get("message", {})
        # Ollama tool call format
        if "tool_calls" in message:
            for tc in message["tool_calls"]:
                func = tc.get("function", {})
                calls.append(ToolCall(name=func.get("name", ""), arguments=func.get("arguments", {})))
        return calls

    def _build_initial_context(self) -> dict:
        """Build initial diagnostic context from deterministic inspection."""
        from devdoctor.diagnostics import inspect

        result = inspect(self.project_path)
        # Return a bounded summary for the model context
        return {
            "environment": result.environment.to_dict(),
            "project": {
                "path": result.project.path,
                "name": result.project.name,
                "exists": result.project.exists,
                "is_directory": result.project.is_directory,
                "python_files": result.project.python_files[:20],
                "test_files": result.project.test_files[:20],
                "test_dirs": result.project.test_dirs,
                "files_present": result.project.files_present,
                "is_git_repo": result.project.is_git_repo,
                "git_branch": result.project.git_branch,
                "git_clean": result.project.git_clean,
                "error": result.project.error,
            },
            "dependencies": result.dependencies.to_dict() if result.dependencies else None,
            "tests": result.tests.to_dict() if result.tests else None,
            "errors": result.errors,
        }

    def run(self) -> dict:
        """Run the agent loop and return the diagnosis."""
        if not self.client.is_available():
            raise OllamaError(
                f"Ollama is not available at {self.client.base_url}. "
                "Ensure Ollama is running and a model is installed."
            )

        # Initial context
        context = self._build_initial_context()
        self.messages = [
            {"role": "system", "content": self._build_system_prompt()},
            {
                "role": "user",
                "content": f"Analyze the following diagnostic evidence for project: {self.project_path}\n\n"
                f"{json.dumps(context, indent=2)}",
            },
        ]

        for iteration in range(self.config.max_iterations):
            # Get available tool definitions
            ollama_tools = [t.to_ollama_tool() for t in self.tools.values()]

            try:
                response = self.client.chat(self.messages, tools=ollama_tools)
            except OllamaError as exc:
                raise OllamaError(f"Model communication failed: {exc}")

            message = response.get("message", {})
            content = message.get("content", "")

            # Check for tool calls
            tool_calls = self._extract_tool_calls(response)
            if not tool_calls:
                # No tool calls - check if it's a diagnosis
                try:
                    parsed = json.loads(content)
                    if "diagnosis" in parsed:
                        return parsed
                except json.JSONDecodeError:
                    # Not JSON - might be reasoning, continue
                    pass
                # Model didn't call tools or produce diagnosis - add to context
                self.messages.append({"role": "assistant", "content": content})
                continue

            # Execute tool calls
            self.messages.append({"role": "assistant", "content": content, "tool_calls": message.get("tool_calls", [])})
            for call in tool_calls:
                tool = self.tools.get(call.name)
                if not tool:
                    result = ToolResult(
                        name=call.name, success=False, error=f"Unknown tool: {call.name}"
                    )
                else:
                    result = tool.execute(**call.arguments)
                self.messages.append(
                    {
                        "role": "tool",
                        "content": json.dumps(result.__dict__, default=str),
                        "name": call.name,
                    }
                )

        raise OllamaError(f"Agent exceeded maximum iterations ({self.config.max_iterations})")

    def diagnose(self) -> dict:
        """Run diagnosis and return structured result."""
        try:
            return self.run()
        except OllamaError as exc:
            return {
                "diagnosis": {
                    "status": "error",
                    "problems": [
                        {
                            "title": "Agent execution failed",
                            "evidence": [str(exc)],
                            "likely_cause": "Ollama communication or configuration issue",
                            "recommended_action": "Check Ollama is running and model is available",
                            "confidence": "high",
                        }
                    ],
                    "summary": str(exc),
                }
            }


def diagnose_with_ai(project_path: str, config: AgentConfig | None = None) -> dict:
    """Convenience function to run AI diagnosis on a project."""
    agent = Agent(project_path=project_path, config=config or AgentConfig())
    return agent.diagnose()