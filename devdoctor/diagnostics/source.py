"""Python source file inspection using the stdlib `ast` module.

Counts files/lines and collects reliably-determinable top-level imports.
No dependency resolution is attempted here (that belongs to Phase 3).
"""

from __future__ import annotations

import ast
from pathlib import Path

from devdoctor.diagnostics.models import PythonSourceInfo


def extract_imports(source: str) -> set[str]:
    """Return top-level package names imported in the given source.

    Uses AST parsing. Relative imports without a module name (e.g.
    `from . import x`) carry no package information and are skipped.
    Returns an empty set if the source cannot be parsed.
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return set()
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0].strip()
                if top:
                    imports.add(top)
        elif isinstance(node, ast.ImportFrom) and node.module:
            top = node.module.split(".")[0].strip()
            if top:
                imports.add(top)
    return imports


def inspect_python_sources(base_dir: Path, relative_files: list[str]) -> PythonSourceInfo:
    """Inspect Python files (paths relative to base_dir) without modifying them."""
    info = PythonSourceInfo()
    all_imports: set[str] = set()

    for rel in sorted(relative_files):
        info.files.append(rel)
        abs_path = base_dir / rel
        try:
            text = abs_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            info.errors.append(f"{rel}: cannot read file ({exc.strerror or exc})")
            continue
        info.file_count += 1
        info.total_lines += len(text.splitlines())
        all_imports.update(extract_imports(text))

    info.imports = sorted(all_imports)
    return info
