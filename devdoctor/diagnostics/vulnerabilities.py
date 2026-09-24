"""Optional local dependency vulnerability analysis via `pip-audit`.

Controlled subprocess only: fixed arguments, shell=False, timeout,
bounded output. If pip-audit is not installed, the analysis reports
`pip-audit unavailable` and DevDoctor keeps working normally.
Never installs anything automatically.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from importlib import util as importlib_util
from pathlib import Path

from devdoctor.diagnostics.models import VulnAnalysis, Vulnerability

PIP_AUDIT_TIMEOUT_S = 120
MAX_OUTPUT_CHARS = 20000
MAX_VULNS = 100
MAX_DESC_CHARS = 500


def _pip_audit_base() -> list[str] | None:
    """Return the fixed pip-audit executable prefix, or None if not installed."""
    exe = shutil.which("pip-audit")
    if exe:
        return [exe]
    if importlib_util.find_spec("pip_audit") is not None:
        return [sys.executable, "-m", "pip_audit"]
    return None


def pip_audit_version() -> str | None:
    """Return the pip-audit version, or None when unavailable."""
    base = _pip_audit_base()
    if base is None:
        return None
    try:
        proc = subprocess.run(
            [*base, "--version"],
            capture_output=True, text=True, check=False,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None
    if proc.returncode != 0:
        return None
    output = (proc.stdout or proc.stderr or "").strip()
    return output.splitlines()[0].strip() if output else "unknown"


def run_pip_audit(root: Path, timeout_s: int = PIP_AUDIT_TIMEOUT_S,
                  ) -> subprocess.CompletedProcess[str]:
    """Execute pip-audit in the target dir (module-level seam for tests)."""
    base = _pip_audit_base()
    if base is None:
        raise FileNotFoundError("pip-audit is not installed")
    return subprocess.run(
        [*base, "--format", "json"],
        capture_output=True, text=True, check=False,
        timeout=timeout_s, cwd=str(root),
    )


def _bounded(text: str, limit: int) -> str:
    """Keep the head of over-long text."""
    return text[:limit] if len(text) > limit else text


def parse_pip_audit_json(stdout: str) -> tuple[list[Vulnerability], str | None]:
    """Parse pip-audit JSON output. Returns (vulns, error)."""
    try:
        payload = json.loads(stdout)
    except (json.JSONDecodeError, ValueError):
        return [], "pip-audit output was not valid JSON"
    if not isinstance(payload, dict):
        return [], "pip-audit output had an unexpected shape"
    found: list[Vulnerability] = []
    dependencies = payload.get("dependencies", [])
    if not isinstance(dependencies, list):
        return [], "pip-audit output had an unexpected shape"
    for dep in dependencies:
        if not isinstance(dep, dict):
            continue
        name = str(dep.get("name", "")).strip()
        version = str(dep.get("version", "")).strip()
        vulns = dep.get("vulns", [])
        if not name or not isinstance(vulns, list):
            continue
        for vuln in vulns:
            if not isinstance(vuln, dict):
                continue
            if len(found) >= MAX_VULNS:
                break
            aliases = vuln.get("aliases", [])
            fixes = vuln.get("fix_versions", [])
            found.append(Vulnerability(
                package=name,
                installed_version=version,
                vuln_id=str(vuln.get("id", "")).strip(),
                aliases=[str(a) for a in aliases if isinstance(a, str)][:10],
                fix_versions=[str(f) for f in fixes if isinstance(f, str)][:10],
                description=_bounded(str(vuln.get("description", "") or ""), MAX_DESC_CHARS),
            ))
    return found, None


def analyze_vulnerabilities(root: Path,
                            timeout_s: int = PIP_AUDIT_TIMEOUT_S) -> VulnAnalysis:
    """Run the optional pip-audit scan. Read-only; never installs pip-audit."""
    version = pip_audit_version()
    if version is None:
        return VulnAnalysis(skipped="pip-audit unavailable")
    try:
        proc = run_pip_audit(root, timeout_s)
    except FileNotFoundError:
        return VulnAnalysis(skipped="pip-audit unavailable")
    except subprocess.TimeoutExpired:
        return VulnAnalysis(pip_audit_version=version,
                            notes=[f"pip-audit timed out after {timeout_s}s"])
    except OSError as exc:
        return VulnAnalysis(pip_audit_version=version,
                            notes=[f"pip-audit could not run ({exc.strerror or exc})"])
    stdout = _bounded(proc.stdout or "", MAX_OUTPUT_CHARS)
    vulnerabilities, error = parse_pip_audit_json(stdout)
    notes: list[str] = []
    if error is not None:
        notes.append(error)
        if proc.stderr:
            notes.append(_bounded(proc.stderr.strip().splitlines()[0]
                                  if proc.stderr.strip() else "", MAX_DESC_CHARS))
    elif proc.returncode not in (0, 1):
        notes.append(f"pip-audit exited with code {proc.returncode}")
    if len(vulnerabilities) >= MAX_VULNS:
        notes.append(f"Vulnerability cap reached ({MAX_VULNS})")
    return VulnAnalysis(vulnerabilities=vulnerabilities,
                        pip_audit_version=version, notes=notes)
