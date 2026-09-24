"""Tests for Phase 7 static security analysis.

Uses tmp fixtures only. Verifies dangerous-pattern detection, safe
patterns, secret redaction, and .env exclusion.
"""

import json
from pathlib import Path

from devdoctor.diagnostics.security import analyze_security

RISKY_APP = """import os
import pickle
import subprocess
import subprocess as sp
from os import popen
from os import system as sys_cmd

eval(user_input)
exec("x = 1")
os.system("ls " + user_input)
sys_cmd("id")
popen("ps")
subprocess.run("ls " + user_input, shell=True)
sp.run(["ls"], shell=False)
pickle.loads(data)
"""

SAFE_APP = """import json
import os
import subprocess
import yaml

API_KEY = os.environ.get("API_KEY")
password = os.getenv("DB_PASSWORD", "")


def load_config(path):
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def main():
    subprocess.run(["ls", "-la"], check=False)
    return json.dumps({"ok": True})
"""


def _write(root: Path, name: str, content: str) -> str:
    (root / name).write_text(content, encoding="utf-8")
    return name


def _rule_ids(analysis) -> set[str]:
    return {f.rule_id for f in analysis.findings}


def test_dangerous_patterns_detected(tmp_path: Path) -> None:
    """eval/exec/shell/pickle patterns produce findings with locations."""
    rel = _write(tmp_path, "app.py", RISKY_APP)
    analysis = analyze_security(tmp_path, [rel])
    rules = _rule_ids(analysis)
    assert {"PY-EVAL", "PY-EXEC", "PY-OS-SYSTEM", "PY-SHELL-TRUE", "PY-PICKLE"} <= rules
    for finding in analysis.findings:
        assert finding.file == "app.py"
        assert finding.line is not None and finding.line > 0
        assert finding.severity in {"critical", "high", "medium", "low"}
        assert finding.evidence
        assert finding.recommendation


def test_aliased_imports_tracked(tmp_path: Path) -> None:
    """Import aliases (sp.run, from-imports) do not hide risky calls."""
    rel = _write(tmp_path, "app.py", RISKY_APP)
    analysis = analyze_security(tmp_path, [rel])
    shell_hits = [f for f in analysis.findings if f.rule_id == "PY-SHELL-TRUE"]
    assert len(shell_hits) == 1  # only shell=True, not shell=False
    os_hits = [f for f in analysis.findings if f.rule_id == "PY-OS-SYSTEM"]
    assert len(os_hits) == 3  # os.system, sys_cmd, popen


def test_safe_patterns_clean(tmp_path: Path) -> None:
    """Safe equivalents raise no findings."""
    rel = _write(tmp_path, "app.py", SAFE_APP)
    analysis = analyze_security(tmp_path, [rel])
    assert analysis.findings == []
    assert analysis.files_scanned == 1


def test_yaml_unsafe_load(tmp_path: Path) -> None:
    """yaml.load without SafeLoader is flagged; safe_load is not."""
    rel = _write(tmp_path, "app.py", "import yaml\nyaml.load(data)\n")
    assert "PY-YAML-LOAD" in _rule_ids(analyze_security(tmp_path, [rel]))
    rel2 = _write(tmp_path, "safe.py", "import yaml\nyaml.safe_load(data)\n")
    assert _rule_ids(analyze_security(tmp_path, [rel2])) == set()


def test_secret_redaction(tmp_path: Path) -> None:
    """Hard-coded secrets are flagged with redacted evidence."""
    secret = "sk-live-9f8e7d6c5b4a394857"
    rel = _write(tmp_path, "app.py", f'API_KEY = "{secret}"\n')
    analysis = analyze_security(tmp_path, [rel])
    assert len(analysis.findings) == 1
    finding = analysis.findings[0]
    assert finding.rule_id == "SECRET-ASSIGN"
    assert "[REDACTED]" in finding.evidence
    blob = json.dumps(analysis.to_dict())
    assert secret not in blob
    assert secret not in finding.evidence


def test_secret_placeholders_and_env_lookups_ignored(tmp_path: Path) -> None:
    """Placeholders and os.environ lookups are not findings."""
    content = ('API_KEY = os.environ.get("API_KEY")\n'
               'password = os.getenv("DB_PASS", "")\n'
               'secret = "changeme"\n'
               'api_token = ""\n')
    rel = _write(tmp_path, "app.py", content)
    assert analyze_security(tmp_path, [rel]).findings == []


def test_known_token_formats(tmp_path: Path) -> None:
    """AWS keys and private key headers are detected without storing values."""
    content = ('key = "AKIAIOSFODNN7EXAMPLE"\n'
               '-----BEGIN RSA PRIVATE KEY-----\n')
    rel = _write(tmp_path, "app.py", content)
    analysis = analyze_security(tmp_path, [rel])
    rules = _rule_ids(analysis)
    assert "SECRET-TOKEN" in rules
    assert "SECRET-PRIVATE-KEY" in rules
    assert "AKIAIOSFODNN7EXAMPLE" not in json.dumps(analysis.to_dict())


def test_env_files_never_read(tmp_path: Path) -> None:
    """.env contents are excluded from scanning entirely."""
    (tmp_path / ".env").write_text('DB_PASSWORD="supersecret123"\nAPI_KEY="zzz"\n',
                                   encoding="utf-8")
    rel = _write(tmp_path, "app.py", "x = 1\n")
    analysis = analyze_security(tmp_path, [rel, ".env"])
    assert analysis.findings == []
    assert analysis.files_scanned == 1
    assert "supersecret" not in json.dumps(analysis.to_dict())


def test_unparseable_file_noted(tmp_path: Path) -> None:
    """Syntax-broken files are noted, not crashed on."""
    rel = _write(tmp_path, "bad.py", "def broken(:\n")
    analysis = analyze_security(tmp_path, [rel])
    assert analysis.files_scanned == 1
    assert any("cannot parse" in note for note in analysis.notes)


def test_outside_project_ignored(tmp_path: Path) -> None:
    """Paths escaping the project tree are skipped."""
    analysis = analyze_security(tmp_path, ["../outside.py", "missing.py"])
    assert analysis.findings == []
    assert analysis.files_scanned == 0


def test_to_dict_shape(tmp_path: Path) -> None:
    """Security payload serializes with all required finding fields."""
    rel = _write(tmp_path, "app.py", "eval(x)\n")
    payload = analyze_security(tmp_path, [rel]).to_dict()
    assert set(payload) == {"findings", "files_scanned", "notes", "skipped"}
    finding = payload["findings"][0]
    assert set(finding) == {"rule_id", "severity", "title", "file",
                            "line", "evidence", "recommendation"}
