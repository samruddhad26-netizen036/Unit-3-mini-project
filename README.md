# DevDoctor

A local-first developer assistant for Python environment diagnostics.

## Description

DevDoctor is a tool designed to help developers diagnose and fix Python environment and dependency problems. It uses a local open-source LLM to autonomously analyze issues, perform safe corrective actions, and verify the results.

## Current Status

**Phase 1 - Foundation Complete**
- Project structure and CLI foundation implemented
- Basic CLI with `--help` and `--version` commands
- Modular architecture ready for extension
- Test structure with pytest

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

# Diagnose (not yet implemented)
devdoctor diagnose

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