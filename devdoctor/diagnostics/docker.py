"""Read-only Dockerfile / Compose analysis (line-based heuristics).

Detects common security/configuration issues without building images,
running containers, or changing Docker state. Compose checks are
deliberate line-based heuristics, not a full YAML parse. Secret VALUES
are never stored: findings carry `KEY=[REDACTED]` placeholders only.
"""

from __future__ import annotations

import re
from pathlib import Path

from devdoctor.diagnostics.models import DockerAnalysis, DockerFinding

MAX_FINDINGS = 30
MAX_EVIDENCE_CHARS = 200

_FROM_LATEST_RE = re.compile(r"(?i)^\s*FROM\s+\S+:latest(?:\s|$)")
_FROM_UNTAGGED_RE = re.compile(r"(?i)^\s*FROM\s+([^\s:@]+)(?:\s+AS\s+\S+)?\s*$")
_COPY_BROAD_RE = re.compile(r"(?i)^\s*COPY\s+\.\s+\S+")
_ADD_RE = re.compile(r"(?i)^\s*ADD\s+(\S+)")
_ENV_SECRET_RE = re.compile(
    r"(?i)^\s*(?:ENV|ARG)\s+([A-Za-z_][\w]*)"
    r"(?:\s*=\s*|\s+)([\"']?)(?P<val>[^\"'#\s][^\"'#]{0,120})"
)
_SECRET_NAME_RE = re.compile(
    r"(?i)(password|passwd|secret|api[_-]?key|token|private[_-]?key)"
)
_PRIVILEGED_RE = re.compile(r"(?i)^\s*privileged\s*:\s*true\s*(?:#.*)?$")
_HOST_NETWORK_RE = re.compile(r"(?i)^\s*network_mode\s*:\s*[\"']?host[\"']?\s*(?:#.*)?$")
_DOCKER_SOCK_RE = re.compile(r"/var/run/docker\.sock")
_ROOT_MOUNT_RE = re.compile(r"""^\s*-\s*["']?/:""")
_HOST_MOUNT_RE = re.compile(
    r"^\s*-\s*[\"']?/(etc|root|var/run|usr|bin|sbin|home|proc|sys|dev)([/:\s\"']|$)")
_CRED_RE = re.compile(
    r"(?i)^\s*[-]?\s*(?:[\"']?[\w.]*"
    r"(?:PASSWORD|PASSWD|SECRET|API[_-]?KEY|TOKEN)[\w.]*[\"']?\s*[:=]\s*)"
    r"[\"']?(?P<val>[^\"'#$\s}][^\"'#]{0,120})"
)

_REDACTED = "[REDACTED]"


def _bounded(text: str) -> str:
    """Bound evidence length."""
    text = " ".join(text.split())
    return text[:MAX_EVIDENCE_CHARS]


def _add(findings: list[DockerFinding], severity: str, title: str,
         location: str, evidence: str, recommendation: str) -> None:
    findings.append(DockerFinding(
        severity=severity, title=title, location=location,
        evidence=_bounded(evidence), recommendation=recommendation,
    ))


def _secret_value_ok(value: str) -> bool:
    """Ignore empty values, variable references, and obvious placeholders."""
    stripped = value.strip().strip("\"'")
    if not stripped or len(stripped) < 4:
        return False
    lowered = stripped.lower()
    return not (
        lowered.startswith(("$", "${", "your-", "example-", "test-", "changeme"))
        or lowered in {"xxx", "...", "***", "changeme", "none", "null"}
    )


def analyze_dockerfile(path: Path, findings: list[DockerFinding]) -> None:
    """Analyze a Dockerfile's instructions."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        findings.append(DockerFinding(
            severity="low", title="Dockerfile unreadable", location="Dockerfile",
            evidence=str(exc.strerror or exc)[:MAX_EVIDENCE_CHARS],
            recommendation="Ensure the Dockerfile is readable.",
        ))
        return
    has_user = False
    has_healthcheck = False
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        where = f"Dockerfile:{lineno}"
        upper = line.upper()
        if upper.startswith("USER "):
            has_user = True
        elif upper.startswith("HEALTHCHECK"):
            has_healthcheck = True
        if _FROM_LATEST_RE.match(line) or _FROM_UNTAGGED_RE.match(line):
            _add(findings, "high", "Unpinned base image (`:latest` or untagged)",
                 where, line,
                 "Pin the base image to an immutable tag or digest.")
        elif _COPY_BROAD_RE.match(line):
            _add(findings, "medium", "Broad COPY of build context",
                 where, line,
                 "Copy only needed paths and add a .dockerignore file.")
        elif (match := _ADD_RE.match(line)) and not match.group(1).startswith("."):
            _add(findings, "low", "ADD used instead of COPY",
                 where, line,
                 "Prefer COPY; use ADD only for tar auto-extraction.")
        secret = _ENV_SECRET_RE.match(line)
        if secret and _SECRET_NAME_RE.search(secret.group(1)):
            value = secret.group("val")
            if _secret_value_ok(value):
                _add(findings, "high",
                     f"Embedded secret in {secret.group(1)}",
                     where, f"{secret.group(1)}={_REDACTED}",
                     "Inject secrets at runtime (build secrets, env files, or a manager).")
    if not has_user:
        _add(findings, "medium", "No USER instruction (runs as root)",
             "Dockerfile", "no USER instruction found",
             "Add a non-root USER for runtime.")
    if not has_healthcheck:
        _add(findings, "low", "No HEALTHCHECK instruction",
             "Dockerfile", "no HEALTHCHECK instruction found",
             "Add HEALTHCHECK so orchestrators can detect unhealthy containers.")


def analyze_compose(path: Path, rel: str, findings: list[DockerFinding]) -> None:
    """Analyze a Compose file with line-based heuristics."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        findings.append(DockerFinding(
            severity="low", title=f"Unreadable Compose file ({rel})", location=rel,
            evidence=str(exc.strerror or exc)[:MAX_EVIDENCE_CHARS],
            recommendation="Ensure the Compose file is readable.",
        ))
        return
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        where = f"{rel}:{lineno}"
        if _PRIVILEGED_RE.match(line):
            _add(findings, "critical", "Privileged container",
                 where, line, "Drop `privileged: true`; grant only needed capabilities.")
        elif _HOST_NETWORK_RE.match(line):
            _add(findings, "high", "Host networking enabled",
                 where, line, "Use bridge networks instead of host networking.")
        elif _DOCKER_SOCK_RE.search(line):
            _add(findings, "critical", "Docker socket mounted into container",
                 where, _bounded(line),
                 "Avoid mounting the Docker socket; use a least-privilege proxy if needed.")
        elif _ROOT_MOUNT_RE.match(line):
            _add(findings, "critical", "Host root filesystem mounted",
                 where, _bounded(line),
                 "Never mount `/`; mount only the specific data directories needed.")
        elif _HOST_MOUNT_RE.match(line):
            _add(findings, "high", "Sensitive host path mounted",
                 where, _bounded(line),
                 "Mount only the data the container needs; prefer named volumes.")
        else:
            cred = _CRED_RE.match(line)
            if cred and _secret_value_ok(cred.group("val")):
                key = line.split(":", 1)[0].strip(" -\"'")
                _add(findings, "high", "Credential embedded in Compose file",
                     where, f"{key}={_REDACTED}",
                     "Use an env_file or Docker secrets instead of inline credentials.")


def analyze_docker(root: Path, files_present: dict[str, bool],
                   docker_available: bool, docker_version: str | None) -> DockerAnalysis:
    """Analyze Dockerfile/Compose files. Read-only; values redacted."""
    analysis = DockerAnalysis(docker_available=docker_available,
                              docker_version=docker_version)
    if not docker_available:
        analysis.notes.append("Docker engine not detected; config files still analyzed.")
    dockerfile = root / "Dockerfile"
    analysis.dockerfile_found = bool(files_present.get("Dockerfile")) and dockerfile.is_file()
    if analysis.dockerfile_found:
        analyze_dockerfile(dockerfile, analysis.findings)
    for name in ("docker-compose.yml", "compose.yml"):
        candidate = root / name
        if files_present.get(name) and candidate.is_file():
            analysis.compose_files.append(name)
            analyze_compose(candidate, name, analysis.findings)
    if analysis.compose_files:
        analysis.notes.append("Compose checks are line-based heuristics, not a full YAML parse.")
    if len(analysis.findings) >= MAX_FINDINGS:
        analysis.findings = analysis.findings[:MAX_FINDINGS]
        analysis.notes.append(f"Finding cap reached ({MAX_FINDINGS}).")
    return analysis
