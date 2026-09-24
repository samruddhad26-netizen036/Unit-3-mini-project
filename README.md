# DevDoctor

A local-first developer assistant for Python environment diagnostics.

## Description

DevDoctor is a tool designed to help developers diagnose and fix Python environment and dependency problems. It uses a local open-source LLM to autonomously analyze issues, perform safe corrective actions, and verify the results.

## Current Status

**Phase 2 - Environment & Project Inspection Complete**
- Deterministic, read-only inspection layer (no LLM, no modifications)
- Environment inspection: OS, architecture, Python/pip, virtualenv, git, docker
- Project inspection: layout markers, Python/test files, `.env` files, git status, bounded tree
- Python source inspection via stdlib AST (file/line counts, top-level imports)
- `devdoctor diagnose <path>` with human-readable and `--json` output

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