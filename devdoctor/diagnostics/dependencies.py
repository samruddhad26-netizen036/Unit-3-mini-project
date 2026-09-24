"""Deterministic, read-only dependency analysis.

Compares declared dependencies (requirements.txt, pyproject.toml,
setup.cfg, setup.py) against installed packages and actual project
imports. Uses only the standard library:

* `importlib.metadata` for installed packages (never `pip` text output)
* `ast` for import analysis (never regex) and static setup.py reading
* `tomllib` / `configparser` for declarative config files

Version constraints are only evaluated when both sides are simple
numeric dotted versions; anything else is reported as a limitation
note instead of guessed.
"""

from __future__ import annotations

import ast
import configparser
import re
import sys
from importlib import metadata
from pathlib import Path

from devdoctor.diagnostics.models import (
    DeclaredDependency,
    DependencyAnalysis,
    DependencyIssue,
    ImportedPackage,
    InstalledDependency,
)

try:
    import tomllib
except ImportError:  # Python 3.10 fallback (tomllib is 3.11+)
    tomllib = None  # type: ignore[assignment]

# Small maintainable map for well-known distribution/import name differences.
# Keys and values are PEP 503-normalized distribution names; lookup uses the
# normalized import name.
IMPORT_TO_DIST = {
    "sklearn": "scikit-learn",
    "pil": "pillow",
    "yaml": "pyyaml",
    "bs4": "beautifulsoup4",
    "dateutil": "python-dateutil",
    "dotenv": "python-dotenv",
    "jwt": "pyjwt",
    "crypto": "pycryptodome",
    "serial": "pyserial",
    "cv2": "opencv-python",
    "docx": "python-docx",
    "pptx": "python-pptx",
    "attr": "attrs",
    "magic": "python-magic",
    "gi": "pygobject",
    "wx": "wxpython",
    "usb": "pyusb",
    "fle": "flexmock",
}

_SPEC_OPS = ("===", "~=", "==", "!=", ">=", "<=", ">", "<")


def normalize_name(name: str) -> str:
    """Normalize a distribution name per PEP 503."""
    return re.sub(r"[-_.]+", "-", name).strip().lower()


def _split_requirement(line: str) -> tuple[str, str] | None:
    """Split a requirement string into (name, constraint).

    Returns None for direct references (`pkg @ url`), which carry no
    interpretable version constraint.
    """
    text = line.strip()
    if "@" in text.split(";")[0] and "://" in text:
        # Direct reference (PEP 508): `name @ url`. Keep the name only.
        name = text.split("@")[0].strip()
        return (name, "") if name else None
    # Strip environment markers; the marker itself is out of scope.
    text = text.split(";")[0].strip()
    # Strip extras: `requests[security]>=2` -> `requests>=2`.
    bracket = text.find("[")
    if bracket != -1:
        closing = text.find("]", bracket)
        if closing != -1:
            text = text[:bracket] + text[closing + 1 :]
    # Name ends where the version specifier (or whitespace) begins.
    end = len(text)
    for i, char in enumerate(text):
        if char in "<>=!~ " or char == "\t":
            end = i
            break
    name = text[:end].strip()
    constraint = text[end:].strip()
    if not name:
        return None
    return name, constraint


def parse_requirements_file(path: Path) -> tuple[list[DeclaredDependency], list[str]]:
    """Parse a requirements.txt file. Returns (declared, notes)."""
    declared: list[DeclaredDependency] = []
    notes: list[str] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return [], [f"requirements.txt: cannot read file ({exc.strerror or exc})"]
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(("-r ", "--requirement", "-c ", "--constraint", "-e ", "--editable")):
            notes.append(f"requirements.txt line {lineno}: nested/include option skipped")
            continue
        if line.startswith("-"):
            notes.append(f"requirements.txt line {lineno}: pip option skipped")
            continue
        # Strip inline comments (safe: direct URLs handled inside _split_requirement).
        if "://" not in line:
            line = line.split("#")[0].strip()
            if not line:
                continue
        parsed = _split_requirement(line)
        if parsed is None:
            notes.append(f"requirements.txt line {lineno}: unsupported entry skipped")
            continue
        name, constraint = parsed
        declared.append(
            DeclaredDependency(name=normalize_name(name), constraint=constraint,
                               source="requirements.txt")
        )
    return declared, notes


def parse_pyproject_file(path: Path) -> tuple[list[DeclaredDependency], list[str]]:
    """Parse PEP 621 `[project] dependencies` from pyproject.toml."""
    if tomllib is None:
        return [], ["pyproject.toml: TOML parsing needs Python 3.11+ (tomllib)"]
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8", errors="replace"))
    except OSError as exc:
        return [], [f"pyproject.toml: cannot read file ({exc.strerror or exc})"]
    except tomllib.TOMLDecodeError as exc:
        return [], [f"pyproject.toml: malformed TOML, dependencies skipped ({exc})"]
    project = data.get("project")
    if not isinstance(project, dict):
        return [], ["pyproject.toml: no [project] table, nothing declared"]
    deps = project.get("dependencies", [])
    if not isinstance(deps, list):
        return [], ["pyproject.toml: [project] dependencies is malformed, skipped"]
    declared: list[DeclaredDependency] = []
    notes: list[str] = []
    for entry in deps:
        if not isinstance(entry, str):
            notes.append("pyproject.toml: non-string dependency entry skipped")
            continue
        parsed = _split_requirement(entry)
        if parsed is None:
            notes.append(f"pyproject.toml: unsupported entry skipped ({entry!r})")
            continue
        name, constraint = parsed
        declared.append(
            DeclaredDependency(name=normalize_name(name), constraint=constraint,
                               source="pyproject.toml")
        )
    return declared, notes


def parse_setup_cfg_file(path: Path) -> tuple[list[DeclaredDependency], list[str]]:
    """Parse `[options] install_requires` from setup.cfg."""
    parser = configparser.ConfigParser()
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
        parser.read_string(text)
    except OSError as exc:
        return [], [f"setup.cfg: cannot read file ({exc.strerror or exc})"]
    except configparser.Error as exc:
        return [], [f"setup.cfg: malformed config, dependencies skipped ({exc})"]
    if not parser.has_option("options", "install_requires"):
        return [], ["setup.cfg: no [options] install_requires, nothing declared"]
    declared: list[DeclaredDependency] = []
    notes: list[str] = []
    for raw in parser.get("options", "install_requires").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parsed = _split_requirement(line)
        if parsed is None:
            notes.append("setup.cfg: unsupported entry skipped")
            continue
        name, constraint = parsed
        declared.append(
            DeclaredDependency(name=normalize_name(name), constraint=constraint,
                               source="setup.cfg")
        )
    return declared, notes


def _literal_str_list(node: ast.AST) -> list[str] | None:
    """Extract a plain list/tuple of string constants, else None."""
    if not isinstance(node, (ast.List, ast.Tuple)):
        return None
    values: list[str] = []
    for elt in node.elts:
        if not isinstance(elt, ast.Constant) or not isinstance(elt.value, str):
            return None
        values.append(elt.value)
    return values


def parse_setup_py_file(path: Path) -> tuple[list[DeclaredDependency], list[str]]:
    """Statically extract `install_requires` from setup.py via AST.

    Only literal string lists are accepted. Anything dynamic is reported
    as a limitation instead of executed or guessed.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return [], [f"setup.py: cannot read file ({exc.strerror or exc})"]
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return [], ["setup.py: cannot be parsed, dependencies skipped"]
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        called = func.attr if isinstance(func, ast.Attribute) else (
            func.id if isinstance(func, ast.Name) else "")
        if called != "setup":
            continue
        for keyword in node.keywords:
            if keyword.arg != "install_requires":
                continue
            values = _literal_str_list(keyword.value)
            if values is None:
                return [], ["setup.py: install_requires is dynamic, skipped (not executed)"]
            declared: list[DeclaredDependency] = []
            notes: list[str] = []
            for entry in values:
                parsed = _split_requirement(entry)
                if parsed is None:
                    notes.append("setup.py: unsupported entry skipped")
                    continue
                name, constraint = parsed
                declared.append(
                    DeclaredDependency(name=normalize_name(name), constraint=constraint,
                                       source="setup.py")
                )
            return declared, notes
    return [], ["setup.py: no static install_requires found, nothing declared"]


def _dist_name_version(dist: object) -> tuple[str, str] | None:
    """Safely read (name, version) from a distribution, else None."""
    try:
        raw_name = dist.metadata["Name"] or ""  # type: ignore[union-attr]
        version = dist.version or ""  # type: ignore[union-attr]
    except (KeyError, ValueError, AttributeError, TypeError):
        return None
    name = normalize_name(raw_name)
    if not name or not version:
        return None
    return name, version


def get_installed_packages() -> dict[str, str]:
    """Return {normalized name: version} for installed distributions.

    Uses importlib.metadata (structured); never parses `pip` text output.
    """
    installed: dict[str, str] = {}
    for dist in metadata.distributions():
        parsed = _dist_name_version(dist)
        if parsed is None:
            continue
        name, version = parsed
        if name not in installed:
            installed[name] = version
    return installed


def local_top_levels(python_files: list[str]) -> set[str]:
    """Derive local top-level module/package names from project file paths."""
    tops: set[str] = set()
    for rel in python_files:
        parts = Path(rel).parts
        if not parts:
            continue
        first = parts[0].removesuffix(".py")
        if first and first != "__pycache__":
            tops.add(first)
    return tops


def classify_import(name: str, local_tops: set[str]) -> str:
    """Classify an import as stdlib, third-party, or local (AST names only)."""
    lowered = name.lower()
    if lowered in local_tops or name in local_tops:
        return "local"
    if name in sys.stdlib_module_names:
        return "stdlib"
    return "third-party"


def import_candidate_dists(import_name: str) -> set[str]:
    """Return candidate distribution names for an import name."""
    normalized = normalize_name(import_name)
    candidates = {normalized, normalized.replace("-", "_")}
    mapped = IMPORT_TO_DIST.get(normalized)
    if mapped:
        candidates.add(mapped)
    return candidates


def dist_candidate_imports(dist_name: str) -> set[str]:
    """Return candidate import names for a distribution name."""
    normalized = normalize_name(dist_name)
    candidates = {normalized, normalized.replace("-", "_"), normalized.replace("_", "-")}
    for imp, dist in IMPORT_TO_DIST.items():
        if dist == normalized:
            candidates.add(imp)
    return candidates


def _numeric_key(version: str) -> tuple[int, ...] | None:
    """Parse a simple numeric dotted version, else None (do not guess)."""
    text = version.strip().removesuffix(".*")
    text = text.split("+", 1)[0]  # drop local version
    if "!" in text:  # drop epoch
        epoch, text = text.split("!", 1)
        if not epoch.isdigit():
            return None
    parts = text.split(".")
    numbers: list[int] = []
    for part in parts:
        if not part.isdigit():
            return None
        numbers.append(int(part))
    return tuple(numbers) if numbers else None


def _clause_satisfied(installed: str, op: str, required: str) -> bool | None:
    """Evaluate one version clause. None means it cannot be safely interpreted."""
    required = required.strip()
    if op == "===":
        return installed.strip() == required
    if op == "==" and required.endswith(".*"):
        prefix = required[:-2].rstrip(".")
        return installed.strip() == prefix or installed.strip().startswith(prefix + ".")
    have = _numeric_key(installed)
    want = _numeric_key(required)
    if have is None or want is None:
        return None
    # Zero-pad the shorter side for fair comparison.
    width = max(len(have), len(want))
    have += (0,) * (width - len(have))
    want += (0,) * (width - len(want))
    if op == "==":
        return have == want
    if op == "!=":
        return have != want
    if op == ">=":
        return have >= want
    if op == "<=":
        return have <= want
    if op == ">":
        return have > want
    if op == "<":
        return have < want
    if op == "~=":
        # Compatible release (PEP 440): >= V.N and == V.* (prefix match).
        req_parts = [p for p in required.split(".") if p not in ("", "*")]
        if not req_parts or any(not p.isdigit() for p in req_parts):
            return None
        req = tuple(int(p) for p in req_parts)
        prefix = req[:-1] if len(req) > 1 else req
        width = max(len(have), len(req), len(prefix))
        hp = have + (0,) * (width - len(have))
        rq = req + (0,) * (width - len(req))
        return hp >= rq and hp[: len(prefix)] == prefix
    return None


def constraint_satisfied(installed: str, constraint: str) -> bool | None:
    """Check a full comma-separated constraint. None = cannot interpret safely."""
    text = constraint.strip()
    if not text:
        return True
    for clause in text.split(","):
        clause = clause.strip()
        if not clause:
            continue
        for op in _SPEC_OPS:
            if clause.startswith(op):
                result = _clause_satisfied(installed, op, clause[len(op):])
                if result is None:
                    return None
                if not result:
                    return False
                break
        else:
            return None  # unknown clause format
    return True


def analyze_dependencies(
    root: Path,
    python_files: list[str],
    imports: list[str],
    installed: dict[str, str] | None = None,
) -> DependencyAnalysis:
    """Compare declared vs installed vs imported. Read-only.

    `installed` may be injected (normalized name -> version) for testing;
    when None it is read from importlib.metadata.
    """
    analysis = DependencyAnalysis()
    notes = analysis.notes

    for filename, parser in (
        ("requirements.txt", parse_requirements_file),
        ("pyproject.toml", parse_pyproject_file),
        ("setup.cfg", parse_setup_cfg_file),
        ("setup.py", parse_setup_py_file),
    ):
        candidate = root / filename
        if not candidate.is_file():
            continue
        found, file_notes = parser(candidate)
        analysis.declared.extend(found)
        notes.extend(file_notes)

    if installed is None:
        try:
            installed = get_installed_packages()
        except (OSError, ValueError, KeyError, AttributeError, TypeError) as exc:
            notes.append(f"installed packages: unreadable ({exc})")
            installed = {}
    analysis.installed = [
        InstalledDependency(name=name, version=installed[name]) for name in sorted(installed)
    ]

    local_tops = local_top_levels(python_files)
    imported = [ImportedPackage(name=n, classification=classify_import(n, local_tops))
                for n in sorted(set(imports))]
    analysis.imports = imported

    declared_by_name: dict[str, DeclaredDependency] = {}
    for dep in analysis.declared:
        declared_by_name.setdefault(dep.name, dep)

    def find_declared(import_name: str) -> DeclaredDependency | None:
        for candidate in import_candidate_dists(import_name):
            if candidate in declared_by_name:
                return declared_by_name[candidate]
        return None

    third_party = [p for p in imported if p.classification == "third-party"]

    for pkg in third_party:
        matched = find_declared(pkg.name)
        present = any(c in installed for c in import_candidate_dists(pkg.name))
        if not present:
            detail = f"imported as '{pkg.name}' but not installed"
            if matched:
                detail += f" (declared in {matched.source} as '{matched.name}')"
            analysis.issues.append(DependencyIssue(
                kind="missing", name=pkg.name, detail=detail,
                declared=matched.constraint if matched else None))
        if matched is None:
            analysis.issues.append(DependencyIssue(
                kind="imported-not-declared", name=pkg.name,
                detail=f"imported as '{pkg.name}' but not declared in any supported file"))

    for dep in analysis.declared:
        if dep.name not in installed:
            analysis.issues.append(DependencyIssue(
                kind="declared-not-installed", name=dep.name,
                detail=f"declared in {dep.source} ({dep.constraint or 'any version'}) "
                       "but not installed",
                declared=dep.constraint or None))
            continue
        if dep.constraint:
            verdict = constraint_satisfied(installed[dep.name], dep.constraint)
            if verdict is None:
                notes.append(f"{dep.name}: constraint {dep.constraint!r} "
                             "cannot be safely interpreted, version check skipped")
            elif not verdict:
                analysis.issues.append(DependencyIssue(
                    kind="version-mismatch", name=dep.name,
                    detail=f"declared {dep.constraint}, installed {installed[dep.name]}",
                    declared=dep.constraint, installed=installed[dep.name]))

    imported_names = {p.name for p in imported}
    for dep in analysis.declared:
        if not (set(dist_candidate_imports(dep.name)) & imported_names):
            analysis.issues.append(DependencyIssue(
                kind="possibly-unused", name=dep.name,
                detail=f"declared in {dep.source} but never imported "
                       "(indirect use is still possible)"))

    return analysis
