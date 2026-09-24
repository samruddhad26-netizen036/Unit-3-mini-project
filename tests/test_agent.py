"""Tests for DevDoctor Agent (Phase 5).

All tests mock the Ollama client to avoid requiring a real Ollama installation.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from devdoctor.agent import Agent, AgentConfig, OllamaClient, OllamaError, diagnose_with_ai
from devdoctor.agent.ollama import DEFAULT_MODEL


class MockOllamaResponse:
    """Mock response from Ollama chat."""

    def __init__(self, content: str = "", tool_calls: list | None = None):
        self.response = {"message": {"content": content, "tool_calls": tool_calls or []}}


def test_ollama_client_creation() -> None:
    """OllamaClient can be created with defaults and custom values."""
    client = OllamaClient()
    assert client.base_url == "http://localhost:11434"
    assert client.model == DEFAULT_MODEL
    assert client.timeout_s == 120.0

    custom = OllamaClient(base_url="http://custom:11434", model="custom-model", timeout_s=30.0)
    assert custom.base_url == "http://custom:11434"
    assert custom.model == "custom-model"
    assert custom.timeout_s == 30.0


def test_ollama_error_includes_status() -> None:
    """OllamaError carries status code when available."""
    err = OllamaError("test error", status_code=500)
    assert str(err) == "test error"
    assert err.status_code == 500


def test_agent_config_defaults() -> None:
    """AgentConfig has sensible defaults."""
    config = AgentConfig()
    assert config.max_iterations == 8
    assert config.model is None
    assert config.ollama_url is None

    config2 = AgentConfig(max_iterations=5, model="test", ollama_url="http://test:11434")
    assert config2.max_iterations == 5
    assert config2.model == "test"
    assert config2.ollama_url == "http://test:11434"


def test_agent_tool_registration(tmp_path) -> None:
    """Agent registers all four built-in tools."""
    agent = Agent(project_path=str(tmp_path))
    assert set(agent.tools.keys()) == {
        "inspect_environment",
        "inspect_project",
        "analyze_dependencies",
        "run_tests",
    }
    for tool in agent.tools.values():
        assert hasattr(tool, "to_ollama_tool")
        assert hasattr(tool, "execute")


def test_agent_tool_execution_success(tmp_path) -> None:
    """Tool execution returns structured ToolResult on success."""
    agent = Agent(project_path=str(tmp_path))
    tool = agent.tools["inspect_environment"]
    result = tool.execute()
    assert result.name == "inspect_environment"
    assert result.success is True
    assert isinstance(result.data, dict)
    assert "os_name" in result.data


def test_agent_tool_execution_failure(tmp_path) -> None:
    """Tool execution handles errors gracefully."""
    agent = Agent(project_path=str(tmp_path))

    # Create a tool that will fail
    def failing_func(**kwargs):
        raise ValueError("intentional error")

    bad_tool = agent.tools["inspect_environment"]
    bad_tool.function = failing_func
    result = bad_tool.execute()
    assert result.success is False
    assert "intentional error" in result.error


@patch("devdoctor.agent.core.OllamaClient")
def test_agent_run_calls_ollama(mock_client_class, tmp_path) -> None:
    """Agent.run() calls Ollama client and handles response."""
    mock_client = MagicMock()
    mock_client.is_available.return_value = True
    # First call: model returns a diagnosis directly
    mock_client.chat.return_value = {
        "message": {
            "content": json.dumps({
                "diagnosis": {
                    "status": "healthy",
                    "problems": [],
                    "summary": "All good"
                }
            })
        }
    }
    mock_client_class.return_value = mock_client

    agent = Agent(project_path=str(tmp_path), config=AgentConfig(max_iterations=1))
    result = agent.run()

    assert "diagnosis" in result
    assert result["diagnosis"]["status"] == "healthy"
    mock_client.chat.assert_called_once()


@patch("devdoctor.agent.core.OllamaClient")
def test_agent_handles_tool_calls(mock_client_class, tmp_path) -> None:
    """Agent executes tool calls and feeds results back to model."""
    mock_client = MagicMock()
    mock_client.is_available.return_value = True
    # First response: tool call
    # Second response: diagnosis
    mock_client.chat.side_effect = [
        {
            "message": {
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "inspect_environment",
                            "arguments": {}
                        }
                    }
                ]
            }
        },
        {
            "message": {
                "content": json.dumps({
                    "diagnosis": {
                        "status": "issues-found",
                        "problems": [{"title": "Test", "evidence": ["env"], "likely_cause": "x", "recommended_action": "y", "confidence": "high"}],
                        "summary": "Done"
                    }
                })
            }
        },
    ]
    mock_client_class.return_value = mock_client

    agent = Agent(project_path=str(tmp_path), config=AgentConfig(max_iterations=3))
    result = agent.run()

    assert result["diagnosis"]["status"] == "issues-found"
    assert mock_client.chat.call_count == 2


@patch("devdoctor.agent.core.OllamaClient")
def test_agent_max_iterations_enforced(mock_client_class, tmp_path) -> None:
    """Agent stops after max_iterations without producing diagnosis."""
    mock_client = MagicMock()
    mock_client.is_available.return_value = True
    # Model keeps returning non-diagnosis content
    mock_client.chat.return_value = {
        "message": {"content": "still thinking...", "tool_calls": []}
    }
    mock_client_class.return_value = mock_client

    agent = Agent(project_path=str(tmp_path), config=AgentConfig(max_iterations=2))
    with pytest.raises(OllamaError, match="exceeded maximum iterations"):
        agent.run()


@patch("devdoctor.agent.core.OllamaClient")
def test_agent_ollama_unavailable(mock_client_class, tmp_path) -> None:
    """Agent raises clear error when Ollama is not available."""
    mock_client = MagicMock()
    mock_client.is_available.return_value = False
    mock_client_class.return_value = mock_client

    agent = Agent(project_path=str(tmp_path))
    with pytest.raises(OllamaError, match="Ollama is not available"):
        agent.run()


@patch("devdoctor.agent.core.OllamaClient")
def test_diagnose_with_ai_convenience_function(mock_client_class, tmp_path) -> None:
    """diagnose_with_ai() is a working convenience function."""
    mock_client = MagicMock()
    mock_client.is_available.return_value = True
    mock_client.chat.return_value = {
        "message": {
            "content": json.dumps({
                "diagnosis": {
                    "status": "healthy",
                    "problems": [],
                    "summary": "OK"
                }
            })
        }
    }
    mock_client_class.return_value = mock_client

    result = diagnose_with_ai(str(tmp_path), AgentConfig(max_iterations=1))
    assert result["diagnosis"]["status"] == "healthy"


def test_diagnose_with_ai_handles_error(tmp_path) -> None:
    """diagnose_with_ai() returns error diagnosis on failure."""
    with patch("devdoctor.agent.core.OllamaClient") as mock_client_class:
        mock_client = MagicMock()
        mock_client.is_available.return_value = False
        mock_client_class.return_value = mock_client

        result = diagnose_with_ai(str(tmp_path))
        assert result["diagnosis"]["status"] == "error"
        assert "Ollama is not available" in result["diagnosis"]["summary"]


# --- CLI integration tests ---


def test_cli_diagnose_ai_flag_requires_ollama(tmp_path) -> None:
    """CLI --ai shows clear error when Ollama unavailable."""
    import subprocess
    import sys

    proc = subprocess.run(
        [sys.executable, "-m", "devdoctor.cli.main", "diagnose", str(tmp_path), "--ai"],
        capture_output=True, text=True, check=False,
    )
    # Should fail with clear message about Ollama
    assert proc.returncode != 0
    assert "Ollama" in proc.stdout or "Ollama" in proc.stderr


# --- Tool result structure tests ---


def test_inspect_environment_tool_returns_bounded_data(tmp_path) -> None:
    """Environment tool returns expected fields."""
    agent = Agent(project_path=str(tmp_path))
    result = agent.tools["inspect_environment"].execute()
    data = result.data
    assert "os_name" in data
    assert "python_version" in data
    assert "git_available" in data


def test_inspect_project_tool_returns_bounded_data(tmp_path) -> None:
    """Project tool returns expected fields without huge trees."""
    agent = Agent(project_path=str(tmp_path))
    result = agent.tools["inspect_project"].execute()
    data = result.data
    assert "path" in data
    assert "name" in data
    assert "files_present" in data
    assert "python_files" in data


def test_analyze_dependencies_tool_returns_bounded_data(tmp_path) -> None:
    """Dependency tool returns expected fields without full package list."""
    agent = Agent(project_path=str(tmp_path))
    result = agent.tools["analyze_dependencies"].execute()
    data = result.data
    assert "declared" in data
    assert "installed" in data
    assert "imports" in data
    assert "issues" in data


def test_run_tests_tool_returns_bounded_data(tmp_path) -> None:
    """Test tool returns expected fields."""
    agent = Agent(project_path=str(tmp_path))
    result = agent.tools["run_tests"].execute()
    data = result.data
    assert "status" in data
    assert "exit_code" in data
    assert "result" in data
    assert "summary" in data["result"]


# --- Agent context building tests ---


def test_build_initial_context_includes_all_sections(tmp_path) -> None:
    """Initial context contains environment, project, deps, tests."""
    agent = Agent(project_path=str(tmp_path))
    context = agent._build_initial_context()
    assert "environment" in context
    assert "project" in context
    assert "dependencies" in context
    assert "tests" in context
    assert "errors" in context


# --- Tool schema validation ---


def test_tool_schemas_are_valid_json() -> None:
    """All tool schemas are valid JSON Schema objects."""
    agent = Agent(project_path="/tmp")
    for tool in agent.tools.values():
        schema = tool.parameters
        assert schema["type"] == "object"
        assert "properties" in schema
        assert "required" in schema
        # Convert to JSON to ensure serializable
        json.dumps(tool.to_ollama_tool())


if __name__ == "__main__":
    pytest.main([__file__, "-v"])