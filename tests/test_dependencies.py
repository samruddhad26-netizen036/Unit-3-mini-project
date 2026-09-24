"""Tests for Phase 3 dependency intelligence.

All tests use tmp fixtures and injected installed-package maps so they
never depend on the developer's real environment.
"""

import json
import subprocess
import sys
from pathlib import Path

from devdoctor.diagnostics import inspect
from devdoctor.diagnostics.dependencies import (
    analyze_dependencies,
    classify_import,
    constraint_satisfied,
    get_installed_packages,
    normalize_name,
    parse_pyproject_file,
    parse_requirements_file,
    parse_setup_cfg_file,
    parse_setup_py_file,
)

FAKE_INSTALLED = {
    "requests": "2.31.0",
    "numpy": "1.26.4",
    "pandas": "2.2.3",
    "scikit-learn": "1.3.0",
    "pyyaml": "6.0",
}


def _project(root: Path, requirements: str | None = None) -> Path:
    root.mkdir(exist_ok=True)
    (root / "app.py").write_text("import os\n", encoding="utf-8")
    if requirements is not None:
        (root / "requirements.txt").write_text(requirements, encoding="utf-8")
    return root


def _kinds(analysis) -> set[str]:
    return {i.kind for i in analysis.issues}


# --- parsing: requirements.txt ---


def test_parse_requirements_basic(tmp_path: Path) -> None:
    """Comments, pins, ranges, extras, and markers are parsed."""
    req = tmp_path / "requirements.txt"
    req.write_text(
        "# comment\n\nrequests==2.31.0\nnumpy>=1.20\n"
        "flask[async]>=2.0\ntqdm; python_version > '3.8'\n",
        encoding="utf-8",
    )
    declared, notes = parse_requirements_file(req)
    by_name = {d.name: d for d in declared}
    assert by_name["requests"].constraint == "==2.31.0"
    assert by_name["numpy"].constraint == ">=1.20"
    assert by_name["flask"].constraint == ">=2.0"
    assert by_name["tqdm"].constraint == ""
    assert all(d.source == "requirements.txt" for d in declared)
    assert notes == []


def test_parse_requirements_skips_options(tmp_path: Path) -> None:
    """Includes and pip options are skipped with a note, not parsed."""
    req = tmp_path / "requirements.txt"
    req.write_text("-r other.txt\n--index-url https://x\n-e .\nrequests\n", encoding="utf-8")
    declared, notes = parse_requirements_file(req)
    assert [d.name for d in declared] == ["requests"]
    assert len(notes) == 3


def test_parse_requirements_direct_reference(tmp_path: Path) -> None:
    """Direct URL references keep the name with no version constraint."""
    req = tmp_path / "requirements.txt"
    req.write_text("mypkg @ https://example.com/mypkg.tar.gz\n", encoding="utf-8")
    declared, _notes = parse_requirements_file(req)
    assert len(declared) == 1
    assert declared[0].name == "mypkg"
    assert declared[0].constraint == ""


def test_normalize_name() -> None:
    """Distribution names follow PEP 503 normalization."""
    assert normalize_name("Scikit-Learn") == "scikit-learn"
    assert normalize_name("my_pkg") == "my-pkg"
    assert normalize_name("Pillow") == "pillow"


# --- parsing: pyproject.toml / setup.cfg / setup.py ---


def test_parse_pyproject_dependencies(tmp_path: Path) -> None:
    """PEP 621 [project] dependencies are parsed."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "demo"\ndependencies = [\n'
        '  "requests>=2",\n  "numpy==1.26.4",\n  "tqdm; python_version > \'3.8\'",\n]\n',
        encoding="utf-8",
    )
    declared, notes = parse_pyproject_file(pyproject)
    by_name = {d.name: d for d in declared}
    assert by_name["requests"].constraint == ">=2"
    assert by_name["numpy"].constraint == "==1.26.4"
    assert by_name["tqdm"].constraint == ""
    assert all(d.source == "pyproject.toml" for d in declared)
    assert notes == []


def test_parse_pyproject_malformed(tmp_path: Path) -> None:
    """Malformed TOML is reported as a limitation, not a crash."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[project\nbroken = =\n", encoding="utf-8")
    declared, notes = parse_pyproject_file(pyproject)
    assert declared == []
    assert len(notes) == 1
    assert "malformed" in notes[0]


def test_parse_pyproject_no_project_table(tmp_path: Path) -> None:
    """A pyproject without [project] yields a note and no declarations."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[tool.ruff]\nline-length = 100\n", encoding="utf-8")
    declared, notes = parse_pyproject_file(pyproject)
    assert declared == []
    assert notes


def test_parse_setup_cfg(tmp_path: Path) -> None:
    """setup.cfg [options] install_requires is parsed."""
    cfg = tmp_path / "setup.cfg"
    cfg.write_text("[options]\ninstall_requires =\n    requests>=2\n    numpy\n", encoding="utf-8")
    declared, notes = parse_setup_cfg_file(cfg)
    by_name = {d.name: d for d in declared}
    assert by_name["requests"].constraint == ">=2"
    assert by_name["numpy"].constraint == ""
    assert all(d.source == "setup.cfg" for d in declared)
    assert notes == []


def test_parse_setup_py_literal(tmp_path: Path) -> None:
    """setup.py with a literal install_requires list is parsed via AST."""
    setup = tmp_path / "setup.py"
    setup.write_text(
        "from setuptools import setup\nsetup(name='demo', install_requires=['requests>=2'])\n",
        encoding="utf-8",
    )
    declared, notes = parse_setup_py_file(setup)
    assert [(d.name, d.constraint, d.source) for d in declared] == [
        ("requests", ">=2", "setup.py")]
    assert notes == []


def test_parse_setup_py_dynamic(tmp_path: Path) -> None:
    """Dynamic setup.py install_requires is skipped with a note (never executed)."""
    setup = tmp_path / "setup.py"
    setup.write_text(
        "from setuptools import setup\nreqs = open('r.txt').read()\n"
        "setup(name='demo', install_requires=reqs)\n",
        encoding="utf-8",
    )
    declared, notes = parse_setup_py_file(setup)
    assert declared == []
    assert any("dynamic" in n for n in notes)


# --- installed packages ---


def test_get_installed_packages_shape() -> None:
    """Installed-package inspection returns a string-to-string map."""
    installed = get_installed_packages()
    assert isinstance(installed, dict)
    for name, version in installed.items():
        assert isinstance(name, str) and name
        assert isinstance(version, str) and version


# --- classification ---


def test_classify_stdlib() -> None:
    """Standard library modules are recognized without hardcoding."""
    for name in ("os", "sys", "json", "pathlib", "argparse"):
        assert classify_import(name, set()) == "stdlib"


def test_classify_third_party() -> None:
    """Anything neither local nor stdlib is third-party."""
    assert classify_import("pandas", set()) == "third-party"
    assert classify_import("requests", set()) == "third-party"


def test_classify_local() -> None:
    """Top-level project modules/packages win over stdlib names."""
    assert classify_import("myapp", {"myapp"}) == "local"
    assert classify_import("json", {"json"}) == "local"  # local shadow wins


# --- issue detection ---


def test_missing_dependency(tmp_path: Path) -> None:
    """An imported third-party package that is not installed is MISSING."""
    root = _project(tmp_path / "p")
    analysis = analyze_dependencies(root, ["app.py"], ["os", "devdoctor-fake-missing"],
                                    installed={})
    kinds = _kinds(analysis)
    assert "missing" in kinds
    assert "imported-not-declared" in kinds  # also undeclared
    missing = next(i for i in analysis.issues if i.kind == "missing")
    assert missing.name == "devdoctor-fake-missing"


def test_declared_not_installed(tmp_path: Path) -> None:
    """A declared package absent from the environment is flagged."""
    root = _project(tmp_path / "p", "devdoctor-fake-pkg==1.0\n")
    analysis = analyze_dependencies(root, ["app.py"], ["os"], installed={})
    kinds = _kinds(analysis)
    assert "declared-not-installed" in kinds
    assert "possibly-unused" in kinds  # declared and never imported


def test_imported_not_declared(tmp_path: Path) -> None:
    """An installed-but-undeclared import is flagged exactly once that way."""
    root = _project(tmp_path / "p")
    analysis = analyze_dependencies(root, ["app.py"], ["requests"], installed=FAKE_INSTALLED)
    assert [(i.kind, i.name) for i in analysis.issues] == [
        ("imported-not-declared", "requests")]


def test_possibly_unused(tmp_path: Path) -> None:
    """A declared+installed but never-imported package is POSSIBLY UNUSED."""
    root = _project(tmp_path / "p", "requests==2.31.0\n")
    analysis = analyze_dependencies(root, ["app.py"], ["os"], installed=FAKE_INSTALLED)
    assert [(i.kind, i.name) for i in analysis.issues] == [("possibly-unused", "requests")]


def test_version_mismatch_exact(tmp_path: Path) -> None:
    """Declared `==` violated by the installed version is flagged."""
    root = _project(tmp_path / "p", "pandas==2.2.3\n")
    analysis = analyze_dependencies(root, ["app.py"], ["pandas"], installed={"pandas": "1.5.3"})
    assert [(i.kind, i.name) for i in analysis.issues] == [("version-mismatch", "pandas")]
    issue = analysis.issues[0]
    assert issue.declared == "==2.2.3"
    assert issue.installed == "1.5.3"


def test_version_mismatch_range(tmp_path: Path) -> None:
    """Declared `>=` violated by the installed version is flagged."""
    root = _project(tmp_path / "p", "numpy>=2.0\n")
    analysis = analyze_dependencies(root, ["app.py"], ["numpy"], installed={"numpy": "1.26.4"})
    assert [(i.kind, i.name) for i in analysis.issues] == [("version-mismatch", "numpy")]


def test_version_satisfied_no_issue(tmp_path: Path) -> None:
    """A satisfied constraint produces no version issue."""
    root = _project(tmp_path / "p", "pandas==2.2.3\n")
    analysis = analyze_dependencies(root, ["app.py"], ["pandas"],
                                    installed={"pandas": "2.2.3"})
    assert analysis.issues == []


def test_uninterpretable_constraint_skipped(tmp_path: Path) -> None:
    """Non-numeric versions skip the check with a note instead of guessing."""
    root = _project(tmp_path / "p", "devdoctor-fake-pkg==1.0b2\n")
    analysis = analyze_dependencies(root, ["app.py"], ["devdoctor-fake-pkg"],
                                    installed={"devdoctor-fake-pkg": "1.0b2"})
    assert analysis.issues == []
    assert any("cannot be safely interpreted" in n for n in analysis.notes)
    assert "version-mismatch" not in _kinds(analysis)


def test_healthy_state(tmp_path: Path) -> None:
    """Declared + installed + imported with satisfied pins has no issues."""
    root = _project(tmp_path / "p", "requests==2.31.0\n")
    analysis = analyze_dependencies(root, ["app.py"], ["os", "requests"],
                                    installed=FAKE_INSTALLED)
    assert analysis.issues == []
    assert len(analysis.declared) == 1
    assert {p.name for p in analysis.imports} == {"os", "requests"}


def test_dist_import_mapping(tmp_path: Path) -> None:
    """scikit-learn declared covers the sklearn import (and vice versa)."""
    root = _project(tmp_path / "p", "scikit-learn==1.3.0\n")
    analysis = analyze_dependencies(root, ["app.py"], ["sklearn"], installed=FAKE_INSTALLED)
    assert analysis.issues == []


def test_local_imports_ignored(tmp_path: Path) -> None:
    """Local project imports never raise dependency issues."""
    root = tmp_path / "p"
    root.mkdir()
    (root / "myapp.py").write_text("X = 1\n", encoding="utf-8")
    analysis = analyze_dependencies(root, ["myapp.py"], ["myapp"], installed={})
    assert analysis.issues == []
    assert analysis.imports[0].classification == "local"


# --- constraint evaluator units ---


def test_constraint_satisfied_operators() -> None:
    """Version evaluator handles common PEP 440 operators."""
    assert constraint_satisfied("2.2.3", "==2.2.3") is True
    assert constraint_satisfied("1.5.3", "==2.2.3") is False
    assert constraint_satisfied("1.26.4", ">=2.0") is False
    assert constraint_satisfied("2.1.0", ">=2.0,<3") is True
    assert constraint_satisfied("3.0.0", ">=2.0,<3") is False
    assert constraint_satisfied("2.5.0", "~=2.2") is True
    assert constraint_satisfied("3.0.0", "~=2.2") is False
    assert constraint_satisfied("1.0", "!=1.0") is False
    assert constraint_satisfied("2.31.0", "") is True
    assert constraint_satisfied("2.31.0", "==2.*") is True
    assert constraint_satisfied("3.0.0", "==2.*") is False
    assert constraint_satisfied("1.0", ">>1.0") is None  # unknown operator
    assert constraint_satisfied("1.0a1", "==1.0a1") is None  # not safely interpretable


# --- serialization + integration ---


def test_analysis_to_dict_json(tmp_path: Path) -> None:
    """Full analysis payload round-trips through JSON."""
    root = _project(tmp_path / "p", "pandas==2.2.3\n")
    analysis = analyze_dependencies(root, ["app.py"], ["os", "pandas"],
                                    installed={"pandas": "1.5.3"})
    payload = json.loads(json.dumps(analysis.to_dict()))
    assert payload["declared"][0]["source"] == "requirements.txt"
    assert payload["installed"] == [{"name": "pandas", "version": "1.5.3"}]
    assert {i["name"]: i["classification"] for i in payload["imports"]} == {
        "os": "stdlib", "pandas": "third-party"}
    assert payload["issues"][0]["kind"] == "version-mismatch"
    assert isinstance(payload["notes"], list)


def test_inspect_includes_dependencies(tmp_path: Path) -> None:
    """inspect() attaches dependency analysis with valid JSON output."""
    _project(tmp_path / "p", "requests\n")
    result = inspect(tmp_path / "p")
    assert result.dependencies is not None
    payload = json.loads(json.dumps(result.to_dict()))
    assert "dependencies" in payload
    assert "declared" in payload["dependencies"]
    assert "issues" in payload["dependencies"]


def test_inspect_invalid_path_skips_dependencies(tmp_path: Path) -> None:
    """Invalid projects get a skipped marker instead of a crash."""
    result = inspect(tmp_path / "missing")
    assert result.dependencies is not None
    assert result.dependencies.skipped is not None
    assert result.dependencies.issues == []


def test_cli_diagnose_shows_dependencies(tmp_path: Path) -> None:
    """CLI diagnose prints the DEPENDENCIES section deterministically."""
    _project(tmp_path / "p", "devdoctor-fake-pkg==1.0\n")
    proc = subprocess.run(
        [sys.executable, "-m", "devdoctor.cli.main", "diagnose", str(tmp_path / "p")],
        capture_output=True, text=True, check=False)
    assert proc.returncode == 0
    assert "DEPENDENCIES" in proc.stdout
    assert "DECLARED BUT NOT INSTALLED" in proc.stdout
    assert "POSSIBLY UNUSED" in proc.stdout
    assert "devdoctor-fake-pkg" in proc.stdout


def test_cli_diagnose_json_has_dependencies(tmp_path: Path) -> None:
    """CLI --json output carries structured dependency data."""
    _project(tmp_path / "p", "devdoctor-fake-pkg==1.0\n")
    proc = subprocess.run(
        [sys.executable, "-m", "devdoctor.cli.main", "diagnose", str(tmp_path / "p"), "--json"],
        capture_output=True, text=True, check=False)
    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    dep_names = [d["name"] for d in payload["dependencies"]["declared"]]
    assert "devdoctor-fake-pkg" in dep_names
