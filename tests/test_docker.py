"""Tests for Phase 7 Dockerfile/Compose analysis (no Docker operations)."""

import json
from pathlib import Path

from devdoctor.diagnostics.docker import analyze_docker

INSECURE_DOCKERFILE = """FROM python:latest
COPY . .
ENV DB_PASSWORD=s3cr3tvalue123
RUN pip install -r requirements.txt
CMD ["python", "app.py"]
"""

SAFE_DOCKERFILE = """FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .
USER appuser
HEALTHCHECK CMD python -c "import urllib.request" || exit 1
CMD ["python", "app.py"]
"""

INSECURE_COMPOSE = """services:
  web:
    image: myapp:1.0
    privileged: true
    network_mode: host
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - /etc:/host-etc:ro
    environment:
      POSTGRES_PASSWORD: s3cretpassw0rd!
"""

SAFE_COMPOSE = """services:
  web:
    image: myapp:1.0.0
    volumes:
      - app-data:/data
    environment:
      POSTGRES_PASSWORD: ${DB_PASSWORD}
volumes:
  app-data:
"""


def _files(root: Path, dockerfile: str | None = None, compose: str | None = None,
           name: str = "docker-compose.yml") -> dict[str, bool]:
    present = {"Dockerfile": False, "docker-compose.yml": False, "compose.yml": False}
    if dockerfile is not None:
        (root / "Dockerfile").write_text(dockerfile, encoding="utf-8")
        present["Dockerfile"] = True
    if compose is not None:
        (root / name).write_text(compose, encoding="utf-8")
        present[name] = True
    return present


def _titles(analysis) -> set[str]:
    return {f.title for f in analysis.findings}


def test_insecure_dockerfile(tmp_path: Path) -> None:
    """latest tag, root user, broad COPY, and secrets are all flagged."""
    present = _files(tmp_path, dockerfile=INSECURE_DOCKERFILE)
    analysis = analyze_docker(tmp_path, present, docker_available=False,
                              docker_version=None)
    assert analysis.dockerfile_found is True
    titles = _titles(analysis)
    assert any("Unpinned" in t for t in titles)
    assert any("root" in t for t in titles)
    assert any("COPY" in t for t in titles)
    assert any("secret" in t.lower() for t in titles)
    blob = json.dumps(analysis.to_dict())
    assert "s3cr3tvalue123" not in blob
    assert "[REDACTED]" in blob


def test_safe_dockerfile(tmp_path: Path) -> None:
    """Pinned, non-root, narrow-copy Dockerfiles are clean."""
    present = _files(tmp_path, dockerfile=SAFE_DOCKERFILE)
    analysis = analyze_docker(tmp_path, present, docker_available=True,
                              docker_version="Docker version 1.0")
    assert analysis.findings == []
    assert analysis.docker_available is True


def test_insecure_compose(tmp_path: Path) -> None:
    """privileged/host-net/socket/mounts/credentials are flagged."""
    present = _files(tmp_path, compose=INSECURE_COMPOSE)
    analysis = analyze_docker(tmp_path, present, docker_available=False,
                              docker_version=None)
    assert analysis.compose_files == ["docker-compose.yml"]
    severities = {f.severity for f in analysis.findings}
    assert "critical" in severities
    titles = _titles(analysis)
    assert any("Privileged" in t for t in titles)
    assert any("Host networking" in t for t in titles)
    assert any("socket" in t.lower() for t in titles)
    assert any("Credential" in t for t in titles)
    blob = json.dumps(analysis.to_dict())
    assert "s3cretpassw0rd" not in blob


def test_safe_compose(tmp_path: Path) -> None:
    """Variable-based credentials and named volumes are clean."""
    present = _files(tmp_path, compose=SAFE_COMPOSE)
    analysis = analyze_docker(tmp_path, present, docker_available=False,
                              docker_version=None)
    assert analysis.findings == []
    assert any("line-based heuristics" in n for n in analysis.notes)


def test_no_docker_files(tmp_path: Path) -> None:
    """Projects without Docker files report absence, not errors."""
    analysis = analyze_docker(
        tmp_path,
        {"Dockerfile": False, "docker-compose.yml": False, "compose.yml": False},
        docker_available=False, docker_version=None)
    assert analysis.dockerfile_found is False
    assert analysis.compose_files == []
    assert analysis.findings == []
    assert any("not detected" in n for n in analysis.notes)


def test_compose_yml_variant(tmp_path: Path) -> None:
    """The compose.yml filename variant is also analyzed."""
    present = _files(tmp_path, compose=INSECURE_COMPOSE, name="compose.yml")
    analysis = analyze_docker(tmp_path, present, docker_available=False,
                              docker_version=None)
    assert analysis.compose_files == ["compose.yml"]
    assert len(analysis.findings) > 0


def test_to_dict_shape(tmp_path: Path) -> None:
    """Docker payload serializes with all required fields."""
    present = _files(tmp_path, dockerfile=INSECURE_DOCKERFILE)
    payload = analyze_docker(tmp_path, present, docker_available=False,
                             docker_version=None).to_dict()
    assert set(payload) == {"docker_available", "docker_version", "dockerfile_found",
                            "compose_files", "findings", "notes", "skipped"}
    finding = payload["findings"][0]
    assert set(finding) == {"severity", "title", "location", "evidence",
                            "recommendation"}
