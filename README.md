# DevDoctor

A local-first developer assistant for Python environment diagnostics.

## Description

DevDoctor is a tool designed to help developers diagnose and fix Python environment and dependency problems. It uses a local open-source LLM to autonomously analyze issues, perform safe corrective actions, and verify the results.

## Current Status

**Phase 7 - Security + Docker + Audit + Reporting Complete**
- Deterministic, read-only declared ↔ installed ↔ imported comparison (no LLM)
- Declared parsing: `requirements.txt`, PEP 621 `pyproject.toml`, `setup.cfg`, static `setup.py`
- Installed packages via `importlib.metadata`; imports classified stdlib/third-party/local
- Issue detection: missing, declared-not-installed, imported-not-declared,
  possibly-unused, version-mismatch (safe numeric constraints only)
- Read-only pytest execution with structured evidence (counts, failures, bounded
  output); `diagnose` shows a TESTS section, `--skip-tests` opts out
- Local LLM agent via Ollama (read-only): `devdoctor diagnose ./project --ai`
  - Agent loop: Observe → Reason → Select Tool → Execute → Observe → Diagnose
  - Tools: inspect_environment, inspect_project, analyze_dependencies, run_tests
  - Bounded iterations, structured diagnosis output

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

# AI-powered diagnosis (requires Ollama running locally)
devdoctor diagnose ./my-project --ai

# Skip test execution for faster deterministic diagnosis
devdoctor diagnose ./my-project --skip-tests

# Skip security/vulnerability scanning or Docker analysis
devdoctor diagnose ./my-project --skip-security --skip-docker

# Preview repairs without making changes
devdoctor repair ./my-project --dry-run

# Repair with explicit confirmation
devdoctor repair ./my-project

# Repair without prompting (use with caution)
devdoctor repair ./my-project --yes
```

## AI Mode (Phase 5)

DevDoctor's AI mode uses a local LLM via [Ollama](https://ollama.ai/) to reason over
diagnostic evidence and produce a structured diagnosis.

### Requirements

- Ollama installed and running (`ollama serve`)
- A compatible model installed (e.g., `ollama pull qwen2.5-coder:7b`)
- No API keys required - fully local

### Configuration

Set the model via environment variable:

```bash
export DEVDOCTOR_MODEL=qwen2.5-coder:7b
# or
export DEVDOCTOR_OLLAMA_URL=http://custom-host:11434
```

### Usage

```bash
# AI diagnosis with human-readable output
devdoctor diagnose ./my-project --ai

# AI diagnosis with JSON output
devdoctor diagnose ./my-project --ai --json
```

### Read-Only Guarantee

AI mode is strictly read-only in Phase 5. The agent can only:
- Inspect the environment (OS, Python, Git, Docker)
- Inspect the project structure and files
- Analyze declared vs installed vs imported dependencies
- Run tests and extract failure evidence

The agent CANNOT:
- Install or remove packages
- Modify source files or requirements
- Create or modify environments
- Execute arbitrary shell commands

### Diagnosis Output

The AI diagnosis includes:
- Overall status (healthy / issues-found / repair-required)
- Identified problems with supporting evidence
- Likely root cause analysis
- Recommended next actions
- Confidence levels (high/medium/low)

Example output:
```
AI DIAGNOSIS

Status: ISSUES-FOUND

Summary: Missing dependency causes test failures.

Problems Found:

  1. pandas imported but not installed
     Likely Cause: Missing project dependency declaration
     Recommended Action: Add pandas to requirements.txt or pyproject.toml
     Confidence: high
     Evidence:
       - app.py imports pandas
       - pandas absent from installed packages
       - tests fail with ModuleNotFoundError: pandas
```

## Repair Mode (Phase 6)

Repair mode extends the AI agent so it can fix a limited set of
environment/dependency problems. Workflow:

**Diagnose → Plan → Confirm → Snapshot → Repair → Test → Verify → Re-plan**

### Supported repairs

- Create a virtual environment (`.venv`) inside the project
- Install a specific package/version
- Upgrade / downgrade a package
- Remove a package flagged as possibly unused
- Update `requirements.txt` when justified by the repair

Source-code modification is NOT supported.

### Dry-run and confirmation

```bash
# Show the proposed plan, change nothing
devdoctor repair ./my-project --dry-run

# Ask before changing anything (default; empty input cancels)
devdoctor repair ./my-project

# Skip the prompt (explicit opt-in only)
devdoctor repair ./my-project --yes
```

### Safety restrictions

- The model only selects actions from a fixed registry; it never runs shell commands
- Package/environment names and versions are validated; paths are confined to the target project
- Operations target the project's interpreter (project `.venv` when present)
- Snapshot of `requirements.txt`/venv markers is taken before changes; failed repairs roll back
- Verification re-runs inspection, dependency analysis, and tests; at most 3 repair cycles
- The deterministic `diagnose` command stays fully read-only

## Security, Docker & Audit (Phase 7)

Deterministic `diagnose` now also reports SECURITY, DOCKER, and AUDIT sections
(all read-only; no images built, no containers run, no state changed).

### Security analysis

Static AST scan of project Python files detects `eval`/`exec`, `os.system`,
`subprocess(..., shell=True)`, unsafe `pickle`/`yaml.load`, and hard-coded
secrets (passwords, API keys, tokens, private keys). Secret values are always
redacted (`[REDACTED]`); `.env` files are never read.

### Dependency vulnerabilities (optional pip-audit)

If the local `pip-audit` tool is installed, DevDoctor runs it
(`--format json`, fixed args, timeout, bounded output) and reports structured
vulnerabilities. If absent, the report says `pip-audit unavailable` and
everything else works normally. Nothing is ever installed automatically.

### Docker analysis

Reads `Dockerfile`, `docker-compose.yml`, `compose.yml` and flags e.g.
`:latest` base images, missing `USER`, broad `COPY .`, embedded secrets,
privileged containers, host networking, Docker-socket mounts, dangerous host
mounts, and inline credentials (all redacted). Reports whether the Docker
engine is available.

### Audit logging

Important events (diagnosis, scans, repair lifecycle, verification, rollback)
append to `~/.devdoctor/audit.jsonl` (override: `DEVDOCTOR_AUDIT_LOG`;
disable: `DEVDOCTOR_AUDIT_DISABLED=1`). Records hold timestamp, event,
project, status, and bounded secret-free metadata only — never secrets,
`.env` contents, environment variables, or model responses.

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