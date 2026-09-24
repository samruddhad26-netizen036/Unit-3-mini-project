# DevDoctor — VS Code Extension

Local-first Python dependency diagnostics and safe repair, inside VS Code.
The extension is a thin UI layer over the existing DevDoctor Python engine —
all analysis and repair logic stays in Python. No external APIs, no API keys.

## Workflow

```
VS Code opens Python project
        ↓
DevDoctor automatically scans (read-only: diagnose --json)
        ↓
Findings shown: Problems panel + notification + Output channel
        ↓
"Review and Install" → install plan shown (package, version, reason)
        ↓
User selects Install  ← nothing installs without this step
        ↓
Controlled repair runs (validated plan file + snapshot + rollback)
        ↓
Dependencies re-scanned, results verified
        ↓
Success/failure reported in VS Code
```

## Requirements

- VS Code 1.80+
- Python with the DevDoctor engine installed, e.g. from the repo root:

  ```bash
  pip install -e .
  ```

- No Ollama/model needed for the extension flow (the install plan is built
  deterministically from `diagnose --json`; `repair --plan-file` is LLM-free).

## Run locally (Extension Development Host)

1. Open the `extension/` folder in VS Code.
2. Run `npm install` (dev dependencies: TypeScript, VS Code API types).
3. Press `F5` (uses `.vscode/launch.json`) — a new window opens with DevDoctor.
4. Open a Python project folder to trigger the automatic check.

To package a `.vsix` (requires `vsce`):

```bash
npm install -g @vscode/vsce
vsce package
```

## Usage

- On startup (Python workspace or manifest present), DevDoctor runs a
  read-only dependency check and reports missing packages,
  declared-but-not-installed packages, version mismatches, and
  imported-but-undeclared packages.
- Command palette:
  - `DevDoctor: Check Dependencies` — manual re-scan.
  - `DevDoctor: Review and Install Missing Dependencies` — show the install
    plan and (only on approval) install.
  - `DevDoctor: Show Output` — open the DevDoctor output channel.

## Configuration (`devdoctor.*`)

| Setting | Default | Meaning |
|---|---|---|
| `pythonExecutable` | `python` | Python used to run the engine |
| `autoCheckOnOpen` | `true` | Read-only scan on startup (never installs) |
| `timeoutSeconds` | `120` | Engine invocation timeout |
| `runTests` | `false` | Include pytest runs in checks (slower) |

## Safety

- Scanning is automatic but strictly read-only.
- Installation requires an explicit **Install** click on a modal dialog that
  lists every package, version, and reason. Dismiss/Cancel changes nothing.
- The plan file is written with `0o600` permissions to the OS temp dir and
  deleted after the run, whether it succeeds or fails.
- Only `install_package`/`upgrade_package` actions for declared problems are
  proposed; removals are never auto-proposed.
- Engine subprocesses use argv arrays (no shell), absolute-path validation,
  timeouts, bounded output, and JSON shape validation. Engine output is
  treated as untrusted data.
- Secret values are never read or displayed (the engine redacts them).

## Development

```bash
npm install     # dev dependencies
npm test        # type-check (tsc) + unit tests (node:test, mocked vscode API)
```

## Multi-ecosystem workspaces (Phase 9)

`diagnose --json` now reports every detected ecosystem. The extension keeps
the full Python workflow, and additionally shows an informational message
for detected-but-unsupported ecosystems (JavaScript/TypeScript, Java, Go,
Rust) — supported and unsupported results are displayed separately, and no
install flow is offered for unsupported ecosystems.

Unit tests live in `src/test/` and run against compiled output in `out/`.
The `vscode` module is injected via `src/vscodeApi.ts`, so tests run with
plain `node --test` — no VS Code download required. For full UI testing,
press `F5` with a local VS Code installation.

## Layout

- `src/extension.ts` — activation, commands, approval + verification flow
- `src/engine.ts` — controlled `devdoctor` CLI subprocess bridge
- `src/diagnostics.ts` — issues → Problems-panel entries
- `src/installPlan.ts` — deterministic install-plan builder
- `src/vscodeApi.ts` — injectable VS Code API accessor (test seam)
- `src/test/` — unit tests + minimal vscode mock
