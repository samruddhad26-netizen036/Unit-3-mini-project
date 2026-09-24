# DevDoctor

A local-first developer assistant for Python environment diagnostics.

## Description

DevDoctor is a tool designed to help developers diagnose and fix Python environment and dependency problems. It uses a local open-source LLM to autonomously analyze issues, perform safe corrective actions, and verify the results.

## Current Status

**Phase 4 - Test Analysis & Diagnostic Evidence Complete**
- Deterministic, read-only declared ↔ installed ↔ imported comparison (no LLM)
- Declared parsing: `requirements.txt`, PEP 621 `pyproject.toml`, `setup.cfg`, static `setup.py`
- Installed packages via `importlib.metadata`; imports classified stdlib/third-party/local
- Issue detection: missing, declared-not-installed, imported-not-declared,
  possibly-unused, version-mismatch (safe numeric constraints only)
- `devdoctor diagnose <path>` shows a DEPENDENCIES section; `--json` carries full data
- Read-only pytest execution with structured evidence (counts, failures, bounded
  output); `diagnose` shows a TESTS section, `--skip-tests` opts out

## Installation

```bash
# From source
pip install -e .

# Or with development dependencies
pip install -e ".[dev]"
```

## CLI Usage

```bash
# Show help
devdoctor --help

# Show version
devdoctor --version

# Diagnose a project (human-readable report)
devdoctor diagnose ./my-project

# Diagnose with machine-readable JSON output
devdoctor diagnose ./my-project --json

# Repair (not yet implemented)
devdoctor repair
```

## Development

```bash
# Run tests
pytest

# Run with coverage
pytest --cov=devdoctor

# Lint
ruff check .
```

## License

MIT License - see LICENSE file for details.