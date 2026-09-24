"""Tests for AST-based Python source inspection."""

from pathlib import Path

from devdoctor.diagnostics import extract_imports, inspect_python_sources


def test_extract_imports_basic() -> None:
    """Standard import forms are detected with top-level package names."""
    source = "import os\nimport numpy.linalg\nfrom pathlib import Path\nfrom . import local\n"
    imports = extract_imports(source)
    assert imports == {"os", "numpy", "pathlib"}


def test_extract_imports_syntax_error() -> None:
    """Unparseable source yields an empty set, not an exception."""
    assert extract_imports("def broken(:\n") == set()


def test_extract_imports_empty() -> None:
    """Empty source has no imports."""
    assert extract_imports("") == set()


def test_inspect_python_sources_counts(tmp_path: Path) -> None:
    """File counts and line totals are aggregated."""
    (tmp_path / "a.py").write_text("import os\nimport sys\n\nx = 1\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("from pathlib import Path\n", encoding="utf-8")
    info = inspect_python_sources(tmp_path, ["a.py", "b.py"])
    assert info.file_count == 2
    assert info.total_lines == 5
    assert info.imports == ["os", "pathlib", "sys"]
    assert info.files == ["a.py", "b.py"]
    assert info.errors == []


def test_inspect_python_sources_unreadable(tmp_path: Path) -> None:
    """Missing files are recorded as errors, not crashes."""
    info = inspect_python_sources(tmp_path, ["ghost.py"])
    assert info.file_count == 0
    assert len(info.errors) == 1
    assert "ghost.py" in info.errors[0]


def test_inspect_python_sources_bad_syntax_still_counted(tmp_path: Path) -> None:
    """Files with syntax errors still count toward lines but yield no imports."""
    (tmp_path / "bad.py").write_text("def broken(:\nline2\n", encoding="utf-8")
    info = inspect_python_sources(tmp_path, ["bad.py"])
    assert info.file_count == 1
    assert info.total_lines == 2
    assert info.imports == []
