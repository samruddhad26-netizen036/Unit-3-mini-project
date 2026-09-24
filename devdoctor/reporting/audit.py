"""Append-only JSONL audit logging for DevDoctor operations.

Records who-did-what style events (diagnosis, scans, repair lifecycle)
with bounded, secret-free metadata. The log lives outside any target
project (default `~/.devdoctor/audit.jsonl`) so auditing never modifies
a diagnosed project.

Test hygiene: logging is a no-op when `DEVDOCTOR_AUDIT_DISABLED=1`, or
when running under pytest without an explicit `DEVDOCTOR_AUDIT_LOG`
override. `audit_event()` never raises.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

MAX_METADATA_CHARS = 2000
MAX_STRING_CHARS = 500
MAX_LIST_ITEMS = 20

_SECRET_KEY_RE_PARTS = ("password", "passwd", "secret", "token", "api_key",
                        "apikey", "private_key", "privatekey", "auth", "credential")


def _is_secret_key(key: str) -> bool:
    """Check whether a metadata key looks secret-bearing."""
    lowered = key.lower()
    return any(part in lowered for part in _SECRET_KEY_RE_PARTS)


def _scrub_string(value: str) -> str:
    """Truncate long strings."""
    return value[:MAX_STRING_CHARS] if len(value) > MAX_STRING_CHARS else value


_REDACTED_VALUE = "[REDACTED]"


def _scrub(value, depth: int = 0):
    """Recursively redact secret keys and bound sizes. Never raises."""
    try:
        if depth > 4:
            return "[TRUNCATED]"
        if isinstance(value, dict):
            items = list(value.items())[:MAX_LIST_ITEMS]
            return {
                str(key)[:100]: (_REDACTED_VALUE if _is_secret_key(str(key))
                                 else _scrub(item, depth + 1))
                for key, item in items
            }
        if isinstance(value, (list, tuple)):
            return [_scrub(item, depth + 1) for item in list(value)[:MAX_LIST_ITEMS]]
        if isinstance(value, str):
            return _scrub_string(value)
        if isinstance(value, (int, float, bool)) or value is None:
            return value
        return _scrub_string(str(value))
    except (ValueError, TypeError, AttributeError):
        return "[UNREPRESENTABLE]"


def audit_log_path() -> Path:
    """Resolve the audit log path (override via DEVDOCTOR_AUDIT_LOG)."""
    override = os.environ.get("DEVDOCTOR_AUDIT_LOG", "").strip()
    if override:
        return Path(override)
    return Path.home() / ".devdoctor" / "audit.jsonl"


def audit_enabled() -> bool:
    """Check whether audit logging is active."""
    if os.environ.get("DEVDOCTOR_AUDIT_DISABLED", "") == "1":
        return False
    return not (os.environ.get("PYTEST_CURRENT_TEST")
                and not os.environ.get("DEVDOCTOR_AUDIT_LOG"))


def audit_event(event: str, project: str = "", status: str = "",
                metadata: dict | None = None) -> dict | None:
    """Append one audit record. Returns the record, or None when disabled.

    Never raises; never stores secrets, .env contents, or model responses.
    """
    if not audit_enabled():
        return None
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event[:100],
        "project": project[:500],
        "status": status[:100],
        "metadata": _scrub(metadata or {}),
    }
    try:
        encoded = json.dumps(record)
        if len(encoded) > MAX_METADATA_CHARS + 1000:
            record["metadata"] = {"note": "[metadata too large, dropped]"}
            encoded = json.dumps(record)
    except (ValueError, TypeError):
        return None
    try:
        path = audit_log_path()
        parent = path.parent
        if parent and str(parent):
            parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(encoded + "\n")
    except OSError:
        return None
    return record


def read_audit_events(project: str = "", limit: int = 5) -> list[dict]:
    """Read the most recent audit events for a project (bounded, read-only)."""
    path = audit_log_path()
    try:
        if not path.is_file():
            return []
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    events: list[dict] = []
    for line in reversed(lines[-200:]):
        try:
            record = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(record, dict) and (not project or record.get("project") == project):
            events.append(record)
        if len(events) >= limit:
            break
    return events
