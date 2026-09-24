"""Tests for Phase 6 safe autonomous repair.

Never touches the real environment: pip/venv/subprocess calls are mocked,
LLM planning is stubbed, and all projects live in tmp dirs.
"""

import json
import subprocess
import sys
from pathlib import Path

from devdoctor.agent import (
    RepairAction,
    RepairAgent,
    RepairConfig,
    RepairPlan,
    Snapshot,
    get_repair_tool,
    is_valid_repair_action,
    is_within_project,
    repair_agent,
    repair_tools,
    validate_package_name,
    validate_version,
)


def _project(root: Path, requirements: str = "requests==2.31.0\n") -> Path:
    root.mkdir(exist_ok=True)
    (root / "app.py").write_text("import os\n", encoding="utf-8")
    (root / "requirements.txt").write_text(requirements, encoding="utf-8")
    return root


def _fake_pip(stdout: str = "", returncode: int = 0):
    def _run(python, args, cwd):
        return subprocess.CompletedProcess(
            args=["pip", *args], returncode=returncode, stdout=stdout, stderr="")
    return _run


# --- plan/action validation ---


def test_valid_repair_actions() -> None:
    """Only the six controlled actions are allowed."""
    for name in ("create_virtualenv", "install_package", "upgrade_package",
                 "downgrade_package", "remove_package", "update_requirements"):
        assert is_valid_repair_action(name) is True
        assert get_repair_tool(name) is not None


def test_blocked_actions_rejected() -> None:
    """Arbitrary model-generated commands are never executable tools."""
    for name in ("exec", "run_shell", "rm -rf", "install", "pip install x",
                 "", "diagnose", "inspect_project"):
        assert is_valid_repair_action(name) is False
        assert get_repair_tool(name) is None


def test_package_name_validation() -> None:
    """Malformed package names are rejected."""
    assert validate_package_name("requests") is True
    assert validate_package_name("scikit-learn") is True
    assert validate_package_name("my_pkg.extra") is True
    assert validate_package_name("") is False
    assert validate_package_name("a;b") is False
    assert validate_package_name("a/b") is False
    assert validate_package_name("a b") is False
    assert validate_package_name("../evil") is False
    assert validate_version("2.2.3") is True
    assert validate_version("") is True
    assert validate_version("a;b") is False


def test_repair_action_serialization() -> None:
    """Repair plans round-trip through JSON for the agent protocol."""
    plan = RepairPlan(
        actions=[RepairAction(action="install_package", package="pandas",
                              version="2.2.3", reason="missing")],
        reasoning="pandas is imported but not installed",
    )
    payload = json.loads(json.dumps(plan.to_dict()))
    assert payload["actions"][0]["package"] == "pandas"
    assert payload["reasoning"].startswith("pandas")


# --- path restrictions ---


def test_paths_confined_to_project(tmp_path: Path) -> None:
    """Path traversal outside the project is rejected."""
    root = _project(tmp_path / "p")
    assert is_within_project(root, root / "requirements.txt") is True
    assert is_within_project(root, root / ".." / "outside.txt") is False
    escape = RepairAction(action="create_virtualenv", package="..", reason="evil")
    result = repair_tools.create_virtualenv(root, escape)
    assert result.success is False
    assert "escapes" in result.error


def test_snapshot_ignores_outside_files(tmp_path: Path) -> None:
    """Snapshot never records files outside the project tree."""
    root = _project(tmp_path / "p")
    outside = tmp_path / "secret.txt"
    outside.write_text("s3cret", encoding="utf-8")
    snap = Snapshot(project_path=str(root))
    snap.save_file(str(outside))
    assert snap.files == {}
    snap.save_file(str(root / "requirements.txt"))
    assert str(root / "requirements.txt") in snap.files


# --- repair tools (mocked pip) ---


def test_install_package_success(tmp_path: Path, monkeypatch) -> None:
    """Successful install updates requirements.txt from freeze output."""
    root = _project(tmp_path / "p", "pandas\n")
    monkeypatch.setattr(repair_tools, "run_pip_command",
                        _fake_pip(stdout="pandas==2.2.3\n", returncode=0))
    action = RepairAction(action="install_package", package="pandas",
                          version="2.2.3", reason="missing")
    result = repair_tools.install_package(root, action, Snapshot(project_path=str(root)))
    assert result.success is True
    assert "pandas==2.2.3" in (root / "requirements.txt").read_text(encoding="utf-8")


def test_install_package_failure(tmp_path: Path, monkeypatch) -> None:
    """Failed pip runs return structured errors and leave files alone."""
    root = _project(tmp_path / "p", "pandas==2.2.3\n")
    before = (root / "requirements.txt").read_text(encoding="utf-8")
    monkeypatch.setattr(repair_tools, "run_pip_command",
                        _fake_pip(stdout="ERROR: not found", returncode=1))
    action = RepairAction(action="install_package", package="pandas", reason="x")
    result = repair_tools.install_package(root, action)
    assert result.success is False
    assert result.error
    assert (root / "requirements.txt").read_text(encoding="utf-8") == before


def test_install_rejects_bad_name(tmp_path: Path) -> None:
    """No subprocess runs for invalid package names."""
    root = _project(tmp_path / "p")
    action = RepairAction(action="install_package", package="a;b", reason="x")
    result = repair_tools.install_package(root, action)
    assert result.success is False
    assert "Invalid package name" in result.error


def test_downgrade_requires_version(tmp_path: Path) -> None:
    """Downgrade without a version is rejected before any subprocess."""
    root = _project(tmp_path / "p")
    action = RepairAction(action="downgrade_package", package="numpy", reason="x")
    result = repair_tools.downgrade_package(root, action)
    assert result.success is False
    assert "requires a version" in result.error


def test_remove_package_updates_requirements(tmp_path: Path, monkeypatch) -> None:
    """Remove uninstalls and drops the line from requirements.txt."""
    root = _project(tmp_path / "p", "requests==2.31.0\nflask==2.0\n")
    monkeypatch.setattr(repair_tools, "run_pip_command", _fake_pip(returncode=0))
    action = RepairAction(action="remove_package", package="flask", reason="possibly unused")
    result = repair_tools.remove_package(root, action)
    assert result.success is True
    content = (root / "requirements.txt").read_text(encoding="utf-8")
    assert "flask" not in content
    assert "requests==2.31.0" in content


def test_create_virtualenv_mocked(tmp_path: Path, monkeypatch) -> None:
    """Venv creation stays inside the project and is fast when mocked."""
    import venv as venv_module

    root = _project(tmp_path / "p")

    class FakeBuilder:
        def __init__(self, with_pip=True):
            pass

        def create(self, path):
            target = Path(path)
            target.mkdir(parents=True)
            (target / "pyvenv.cfg").write_text("home = x\n", encoding="utf-8")

    monkeypatch.setattr(venv_module, "EnvBuilder", FakeBuilder)
    action = RepairAction(action="create_virtualenv", package=".venv", reason="isolation")
    result = repair_tools.create_virtualenv(root, action)
    assert result.success is True
    assert (root / ".venv" / "pyvenv.cfg").is_file()


# --- snapshot / rollback ---


def test_snapshot_restore(tmp_path: Path) -> None:
    """Snapshot restores pre-repair file contents."""
    root = _project(tmp_path / "p", "pandas==1.0\n")
    snap = Snapshot(project_path=str(root))
    snap.save_file(str(root / "requirements.txt"))
    (root / "requirements.txt").write_text("pandas==9.9\n", encoding="utf-8")
    restored = snap.restore()
    assert restored == [str(root / "requirements.txt")]
    assert (root / "requirements.txt").read_text(encoding="utf-8") == "pandas==1.0\n"


# --- confirmation handling ---


def _agent(root: Path, **overrides) -> RepairAgent:
    config = RepairConfig(**overrides)
    return RepairAgent(str(root), config)


def test_confirmation_accepts_explicit_yes(tmp_path: Path, monkeypatch) -> None:
    """Only explicit y/yes proceeds."""
    root = _project(tmp_path / "p")
    agent = _agent(root)
    plan = RepairPlan(actions=[RepairAction(action="install_package", package="x")])
    for answer in ("y", "yes", "Y", "YES"):
        monkeypatch.setattr("builtins.input", lambda *a, answer=answer, **k: answer)
        assert agent._get_user_confirmation(plan) is True


def test_confirmation_rejects_anything_else(tmp_path: Path, monkeypatch) -> None:
    """Empty input, 'n', and EOF all cancel."""
    root = _project(tmp_path / "p")
    agent = _agent(root)
    plan = RepairPlan(actions=[RepairAction(action="install_package", package="x")])
    for answer in ("", "n", "no", "yess"):
        monkeypatch.setattr("builtins.input", lambda *a, answer=answer, **k: answer)
        assert agent._get_user_confirmation(plan) is False
    monkeypatch.setattr("builtins.input", lambda *a, **k: (_ for _ in ()).throw(EOFError))
    assert agent._get_user_confirmation(plan) is False


def test_auto_approve_skips_prompt(tmp_path: Path, monkeypatch) -> None:
    """--yes approves without prompting."""
    root = _project(tmp_path / "p")
    agent = _agent(root, auto_approve=True)

    def _boom(*args, **kwargs):
        raise AssertionError("must not prompt")

    monkeypatch.setattr("builtins.input", _boom)
    plan = RepairPlan(actions=[RepairAction(action="install_package", package="x")])
    assert agent._get_user_confirmation(plan) is True


def test_dry_run_never_prompts_nor_modifies(tmp_path: Path, monkeypatch) -> None:
    """Dry-run short-circuits before execution and leaves files alone."""
    root = _project(tmp_path / "p", "pandas==1.0\n")
    agent = _agent(root, dry_run=True)

    def _boom(*args, **kwargs):
        raise AssertionError("must not prompt or execute")

    monkeypatch.setattr("builtins.input", _boom)
    plan = RepairPlan(actions=[RepairAction(action="install_package", package="pandas",
                                            version="2.0", reason="x")])
    assert agent.run_repair_cycle(plan) is False
    assert agent.report.dry_run is True
    assert agent.report.actions_attempted == []
    assert (root / "requirements.txt").read_text(encoding="utf-8") == "pandas==1.0\n"


# --- verification ---


class _FakeSection:
    def __init__(self, payload):
        self._payload = payload

    def to_dict(self):
        return self._payload


class _FakeInspectResult:
    """Mimics InspectionResult for stubbed verification (tests/deps/errors)."""

    def __init__(self, passed, failed, issues):
        tests = {"result": {"summary": {"passed": passed, "failed": failed}}}
        deps = {"issues": [{"kind": "x"}] * issues}
        self.tests = _FakeSection(tests)
        self.dependencies = _FakeSection(deps)
        self.errors = []

    def to_dict(self):
        return {
            "tests": self.tests.to_dict(),
            "dependencies": self.dependencies.to_dict(),
            "errors": self.errors,
        }


def _fake_inspect(passed, failed, issues):
    def _inspect(path, run_tests=True):
        return _FakeInspectResult(passed, failed, issues)
    return _inspect


def _state(passed, failed, issues):
    return {
        "tests": {"result": {"summary": {"passed": passed, "failed": failed}}},
        "dependencies": {"issues": [{"kind": "x"}] * issues},
        "errors": [],
    }


def test_verification_success(tmp_path: Path, monkeypatch) -> None:
    """Improved tests/issues verify as success."""
    root = _project(tmp_path / "p")
    agent = _agent(root)
    monkeypatch.setattr(repair_agent, "inspect", _fake_inspect(13, 0, 0))
    verification = agent._verify_repair(_state(10, 3, 2))
    assert verification.success is True
    assert verification.before["dependency_issues"] == 2
    assert verification.after["dependency_issues"] == 0


def test_verification_failure(tmp_path: Path, monkeypatch) -> None:
    """No improvement verifies as failure."""
    root = _project(tmp_path / "p")
    agent = _agent(root)
    monkeypatch.setattr(repair_agent, "inspect", _fake_inspect(10, 3, 2))
    verification = agent._verify_repair(_state(10, 3, 2))
    assert verification.success is False


# --- full cycles (stubbed LLM) ---


def test_successful_repair_cycle(tmp_path: Path, monkeypatch) -> None:
    """Approved plan executes, verifies, and reports success."""
    root = _project(tmp_path / "p", "pandas\n")
    monkeypatch.setattr(repair_tools, "run_pip_command",
                        _fake_pip(stdout="pandas==2.2.3\n", returncode=0))
    agent = _agent(root, auto_approve=True)
    states = [(10, 3, 2), (13, 0, 0)]  # before (broken) then after (fixed)

    def _evolving_inspect(path, run_tests=True):
        if len(states) > 1:
            passed, failed, issues = states.pop(0)
        else:
            passed, failed, issues = states[0]
        return _FakeInspectResult(passed, failed, issues)

    monkeypatch.setattr(repair_agent, "inspect", _evolving_inspect)
    plan = RepairPlan(actions=[RepairAction(action="install_package", package="pandas",
                                            version="2.2.3", reason="missing")])
    assert agent.run_repair_cycle(plan) is True
    assert agent.report.status == "success"
    assert agent.report.actions_attempted[0].success is True


def test_failed_action_triggers_rollback(tmp_path: Path, monkeypatch) -> None:
    """A failing action rolls back snapshotted files."""
    root = _project(tmp_path / "p", "pandas==1.0\n")
    agent = _agent(root, auto_approve=True)
    agent.snapshot.save_file(str(root / "requirements.txt"))
    (root / "requirements.txt").write_text("pandas==9.9\n", encoding="utf-8")
    monkeypatch.setattr(repair_tools, "run_pip_command",
                        _fake_pip(stdout="boom", returncode=1))
    plan = RepairPlan(actions=[RepairAction(action="install_package", package="pandas",
                                            reason="x")])
    assert agent.run_repair_cycle(plan) is False
    assert agent.report.rollback_performed is True
    assert agent.report.status == "rolled-back"
    assert (root / "requirements.txt").read_text(encoding="utf-8") == "pandas==1.0\n"


def test_max_repair_cycles(tmp_path: Path, monkeypatch) -> None:
    """Agent stops after max cycles and reports failure."""
    root = _project(tmp_path / "p")
    agent = _agent(root, auto_approve=True, max_repair_cycles=2)
    calls = {"plans": 0}

    def _plan():
        calls["plans"] += 1
        return RepairPlan(actions=[RepairAction(action="install_package",
                                                package="x", reason="x")])

    monkeypatch.setattr(agent, "_check_backend", lambda: None)
    monkeypatch.setattr(agent, "diagnose_and_plan", _plan)
    monkeypatch.setattr(agent, "run_repair_cycle", lambda plan: False)
    report = agent.run()
    assert report.status == "failed"
    assert calls["plans"] == 2  # initial + one re-plan


def test_cancelled_repair_makes_no_changes(tmp_path: Path, monkeypatch) -> None:
    """Declining confirmation cancels without touching the project."""
    root = _project(tmp_path / "p", "pandas==1.0\n")
    agent = _agent(root)
    plan = RepairPlan(actions=[RepairAction(action="install_package", package="pandas",
                                            reason="x")])
    monkeypatch.setattr(agent, "_check_backend", lambda: None)
    monkeypatch.setattr(agent, "diagnose_and_plan", lambda: plan)
    monkeypatch.setattr("builtins.input", lambda *a, **k: "n")
    report = agent.run()
    assert report.status == "cancelled"
    assert report.actions_attempted == []
    assert (root / "requirements.txt").read_text(encoding="utf-8") == "pandas==1.0\n"


def test_unknown_action_rejected_at_execution(tmp_path: Path) -> None:
    """Actions outside the registry fail safely at execution time."""
    root = _project(tmp_path / "p")
    agent = _agent(root)
    evil = RepairAction(action="exec", package="rm -rf /", reason="evil")
    result = agent._execute_action(evil)
    assert result.success is False
    assert "Unknown repair action" in result.error


# --- CLI repair behavior ---


def _repair_cli(*args: str):
    return subprocess.run(
        [sys.executable, "-m", "devdoctor.cli.main", "repair", *args],
        capture_output=True, text=True, check=False)


def test_cli_repair_dry_run_makes_no_changes(tmp_path: Path) -> None:
    """Dry-run via CLI (backend failure path) modifies nothing."""
    root = _project(tmp_path / "p", "pandas==1.0\n")
    proc = _repair_cli(str(root), "--dry-run")
    assert proc.returncode == 1  # backend unusable here; must fail, not hang
    assert (root / "requirements.txt").read_text(encoding="utf-8") == "pandas==1.0\n"
    assert not (root / ".venv").exists()


def test_cli_repair_help() -> None:
    """Repair help documents dry-run and approval flags."""
    proc = subprocess.run(
        [sys.executable, "-m", "devdoctor.cli.main", "repair", "--help"],
        capture_output=True, text=True, check=False)
    assert proc.returncode == 0
    assert "--dry-run" in proc.stdout
    assert "--yes" in proc.stdout
    assert "--max-cycles" in proc.stdout


def test_report_serialization(tmp_path: Path) -> None:
    """Repair reports serialize for JSON output."""
    import json as json_lib

    root = _project(tmp_path / "p")
    agent = _agent(root)
    agent.report.status = "cancelled"
    payload = json_lib.loads(json_lib.dumps(agent.report.to_dict()))
    assert payload["status"] == "cancelled"
    assert payload["rollback_performed"] is False
