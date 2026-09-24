"""Tests for Phase 9 language-agnostic adapter architecture."""

import json
from pathlib import Path

import pytest

from devdoctor.adapters import (
    DEFAULT_REGISTRY,
    ECOSYSTEMS,
    AdapterRegistry,
    EcosystemResult,
    LanguageAdapter,
    PythonAdapter,
    detect_ecosystems,
)
from devdoctor.adapters.registry import ensure_builtin_adapters
from devdoctor.diagnostics import inspect
from devdoctor.diagnostics.dependencies import analyze_dependencies
from devdoctor.diagnostics.models import DependencyIssue
from devdoctor.reporting import format_human


@pytest.fixture(autouse=True)
def _builtins():
    ensure_builtin_adapters()


def _project(root: Path, files: dict[str, str]) -> Path:
    root.mkdir(exist_ok=True)
    for name, content in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return root


# --- interface ---


def test_python_adapter_implements_interface() -> None:
    """PythonAdapter satisfies the LanguageAdapter contract."""
    assert issubclass(PythonAdapter, LanguageAdapter)
    adapter = PythonAdapter()
    assert adapter.id == "python"
    assert adapter.display_name
    assert "requirements.txt" in adapter.manifest_files
    assert "pyproject.toml" in adapter.manifest_files
    for method in ("detect", "analyze_dependencies", "get_installed_dependencies",
                   "plan_installation", "install", "verify"):
        assert callable(getattr(adapter, method))


def test_base_cannot_instantiate() -> None:
    """The abstract base enforces the contract."""
    with pytest.raises(TypeError):
        LanguageAdapter()  # type: ignore[abstract]


# --- registry ---


def test_registry_registration_and_lookup() -> None:
    """Registration, lookup, order, and validation."""
    registry = AdapterRegistry()
    first = PythonAdapter()
    registry.register(first)
    assert registry.get("python") is first
    assert registry.get("nope") is None
    assert registry.ids() == ["python"]

    class FakeAdapter(LanguageAdapter):
        id = "fake"
        display_name = "Fake"
        manifest_files = ("fake.txt",)

        def detect(self, root: Path) -> bool:
            return False

        def analyze_dependencies(self, root: Path):
            raise NotImplementedError

        def get_installed_dependencies(self, root: Path):
            raise NotImplementedError

        def plan_installation(self, issues):
            raise NotImplementedError

        def install(self, root, plan, snapshot=None):
            raise NotImplementedError

        def verify(self, root, before):
            raise NotImplementedError

    registry.register(FakeAdapter())
    assert registry.ids() == ["python", "fake"]


def test_registry_rejects_empty_id() -> None:
    """Adapters without an id cannot register (no silent misrouting)."""
    registry = AdapterRegistry()

    class BadAdapter(PythonAdapter):
        id = ""

    with pytest.raises(ValueError):
        registry.register(BadAdapter())


def test_for_project_deterministic(tmp_path: Path) -> None:
    """for_project returns matching adapters in registration order."""
    _project(tmp_path / "p", {"requirements.txt": "requests\n"})
    matched = DEFAULT_REGISTRY.for_project(tmp_path / "p")
    assert [a.id for a in matched] == ["python"]
    assert DEFAULT_REGISTRY.for_project(tmp_path / "empty") == []


# --- python detection ---


def test_python_detected_by_each_manifest(tmp_path: Path) -> None:
    """Every Python manifest format triggers detection."""
    adapter = PythonAdapter()
    for manifest in ("requirements.txt", "pyproject.toml", "setup.cfg", "setup.py"):
        root = _project(tmp_path / manifest.replace(".", "_"), {manifest: "# marker\n"})
        assert adapter.detect(root) is True


def test_python_detected_by_source_only(tmp_path: Path) -> None:
    """Manifest-less script directories keep working (Phase 3 behavior)."""
    root = _project(tmp_path / "scripts", {"tool.py": "import os\n"})
    assert PythonAdapter().detect(root) is True


def test_python_not_detected_elsewhere(tmp_path: Path) -> None:
    """Non-Python projects do not match the Python adapter."""
    root = _project(tmp_path / "js", {"package.json": "{}\n"})
    assert PythonAdapter().detect(root) is False
    assert PythonAdapter().detect(tmp_path / "missing") is False


# --- python analysis (reuse, not duplication) ---


def test_adapter_analysis_matches_direct_call(tmp_path: Path) -> None:
    """Adapter analysis is byte-identical to the Phase 3 implementation."""
    from devdoctor.diagnostics.project import inspect_project

    root = _project(tmp_path / "p", {
        "requirements.txt": "requests==2.31.0\n",
        "app.py": "import os\nimport requests\n",
    })
    project = inspect_project(root)
    expected = analyze_dependencies(
        root, project.python_files, project.source.imports).to_dict()
    assert PythonAdapter().analyze_dependencies(root).to_dict() == expected


def test_adapter_installed_matches_metadata(tmp_path: Path) -> None:
    """Installed list mirrors importlib.metadata (sorted, normalized)."""
    from devdoctor.diagnostics.dependencies import get_installed_packages

    installed = PythonAdapter().get_installed_dependencies(tmp_path)
    expected = get_installed_packages()
    assert {i.name for i in installed} == set(expected)
    assert [i.name for i in installed] == sorted(expected)
    assert all(i.version for i in installed)


def test_adapter_plan_installation() -> None:
    """Only safely auto-installable kinds become plan actions."""
    issues = [
        DependencyIssue(kind="missing", name="pandas", detail="x",
                        declared="==2.2.3"),
        DependencyIssue(kind="declared-not-installed", name="numpy", detail="y",
                        declared=">=2.0"),
        DependencyIssue(kind="version-mismatch", name="scipy", detail="z",
                        declared="==1.0"),
        DependencyIssue(kind="imported-not-declared", name="flask", detail="w"),
        DependencyIssue(kind="possibly-unused", name="requests", detail="v"),
        DependencyIssue(kind="missing", name="PANDAS", detail="dup",
                        declared="==2.2.3"),
    ]
    plan = PythonAdapter().plan_installation(issues)
    assert [(a.action, a.package, a.version) for a in plan.actions] == [
        ("install_package", "pandas", "2.2.3"),
        ("install_package", "numpy", ""),
        ("upgrade_package", "scipy", "1.0"),
    ]


def test_adapter_install_unknown_action(tmp_path: Path) -> None:
    """Actions outside the registry fail safely at execution time."""
    from devdoctor.agent.repair_models import RepairAction, RepairPlan

    root = _project(tmp_path / "p", {"app.py": "x = 1\n"})
    plan = RepairPlan(actions=[RepairAction(action="exec", package="x")])
    results = PythonAdapter().install(root, plan)
    assert len(results) == 1
    assert results[0].success is False
    assert "Unknown repair action" in results[0].error


def test_adapter_install_delegates_to_tools(tmp_path: Path, monkeypatch) -> None:
    """Install executes through the controlled repair tools."""
    from devdoctor.agent import repair_tools
    from devdoctor.agent.repair_models import (
        RepairAction,
        RepairPlan,
        RepairResult,
    )

    calls: list[str] = []

    def _fake_tool(root, action, snapshot=None):
        calls.append(action.package)
        return RepairResult(action=action, success=True, message="ok")

    monkeypatch.setitem(repair_tools.REPAIR_TOOLS, "install_package", _fake_tool)
    root = _project(tmp_path / "p", {"app.py": "x = 1\n"})
    plan = RepairPlan(actions=[RepairAction(action="install_package", package="pandas")])
    results = PythonAdapter().install(root, plan)
    assert calls == ["pandas"]
    assert results[0].success is True


def test_adapter_verify_uses_shared_logic(tmp_path: Path, monkeypatch) -> None:
    """Adapter verification delegates to the shared compare function."""
    import devdoctor.diagnostics as diagnostics_mod

    class _FakeResult:
        def to_dict(self):
            return {
                "tests": {"result": {"summary": {"passed": 13, "failed": 0}}},
                "dependencies": {"issues": []},
                "errors": [],
            }

    monkeypatch.setattr(diagnostics_mod, "inspect",
                        lambda path, run_tests=True: _FakeResult())
    before = {"tests": {"result": {"summary": {"passed": 10, "failed": 3}}},
              "dependencies": {"issues": [{"kind": "x"}]}, "errors": []}
    result = PythonAdapter().verify(tmp_path, before)
    assert result.success is True
    assert "Dependency issues: 1 -> 0" in result.message


# --- ecosystem detection ---


def test_multi_language_detection(tmp_path: Path) -> None:
    """All manifests are reported; scanning never stops at the first."""
    root = _project(tmp_path / "poly", {
        "requirements.txt": "requests\n",
        "package.json": "{}\n",
        "go.mod": "module demo\n",
        "pom.xml": "<project/>\n",
        "Cargo.toml": "[package]\n",
    })
    results = detect_ecosystems(root)
    by_id = {r.ecosystem_id: r for r in results}
    assert set(by_id) == {"python", "go", "java", "javascript", "rust"}
    assert by_id["python"].supported is True
    assert by_id["python"].manifests_found == ["requirements.txt"]
    for eco_id in ("go", "java", "javascript", "rust"):
        assert by_id[eco_id].supported is False
        assert "not yet supported" in by_id[eco_id].message
    # Deterministic table order.
    assert [r.ecosystem_id for r in results] == [spec.ecosystem_id for spec in ECOSYSTEMS]


def test_unsupported_ecosystem_reported(tmp_path: Path) -> None:
    """JS-only projects report unsupported with no adapter match."""
    root = _project(tmp_path / "js", {"package.json": "{}\n"})
    results = detect_ecosystems(root)
    assert len(results) == 1
    assert results[0].ecosystem_id == "javascript"
    assert results[0].supported is False
    assert "package.json" in results[0].manifests_found
    assert DEFAULT_REGISTRY.for_project(root) == []


def test_no_recognized_ecosystem(tmp_path: Path) -> None:
    """Unknown projects yield no results (not an error)."""
    root = _project(tmp_path / "plain", {"notes.txt": "hi\n"})
    assert detect_ecosystems(root) == []


def test_detection_invalid_root(tmp_path: Path) -> None:
    """Missing roots yield no results instead of raising."""
    assert detect_ecosystems(tmp_path / "ghost") == []


def test_custom_registry_isolation(tmp_path: Path) -> None:
    """Explicit registries stay custom; builtins are never injected."""
    root = _project(tmp_path / "p", {"requirements.txt": "x\n"})
    custom = AdapterRegistry()
    results = detect_ecosystems(root, custom)
    assert len(results) == 1
    assert results[0].supported is False  # no adapter in the custom registry
    assert DEFAULT_REGISTRY.get("python") is not None  # default untouched


# --- inspect() integration ---


def test_inspect_reports_ecosystems(tmp_path: Path) -> None:
    """inspect() attaches ecosystem results with full payload shape."""
    root = _project(tmp_path / "p", {
        "requirements.txt": "requests\n",
        "package.json": "{}\n",
    })
    result = inspect(root, run_tests=False, run_security=False, run_docker=False)
    payload = json.loads(json.dumps(result.to_dict()))
    assert "ecosystems" in payload
    by_id = {e["ecosystem_id"]: e for e in payload["ecosystems"]}
    assert by_id["python"]["supported"] is True
    assert by_id["javascript"]["supported"] is False
    entry = payload["ecosystems"][0]
    assert set(entry) == {"ecosystem_id", "display_name", "manifests_found",
                          "supported", "message"}
    # Python analysis still runs normally through the adapter.
    assert result.dependencies is not None
    assert result.dependencies.skipped is None


def test_inspect_ecosystems_in_human_output(tmp_path: Path) -> None:
    """Human report renders a concise ECOSYSTEMS section."""
    root = _project(tmp_path / "p", {
        "requirements.txt": "requests\n",
        "package.json": "{}\n",
    })
    text = format_human(inspect(root, run_tests=False, run_security=False,
                                run_docker=False))
    assert "ECOSYSTEMS" in text
    assert "Python/Pip: supported" in text
    assert "not yet supported" in text


def test_ecosystem_result_serialization() -> None:
    """EcosystemResult round-trips through JSON."""
    payload = json.loads(json.dumps(EcosystemResult(
        ecosystem_id="go", display_name="Go", manifests_found=["go.mod"],
        supported=False, message="x").to_dict()))
    assert payload["ecosystem_id"] == "go"
    assert payload["supported"] is False
