"""Read-only static security analysis (AST + redacted secret heuristics).

Scans project Python files for risky patterns (eval/exec, shell usage,
unsafe deserialization) and obvious hard-coded secrets. Secret VALUES are
never stored: findings carry `VAR = "[REDACTED]"` placeholders only.

Never reads `.env*` files. Never leaves the project tree.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from devdoctor.diagnostics.models import SecurityAnalysis, SecurityFinding

MAX_FINDINGS = 50
MAX_EVIDENCE_CHARS = 200

# Assignment to a suspicious variable name with a quoted literal value.
_SECRET_ASSIGN_RE = re.compile(
    r"""(?i)^\s*(?P<var>[A-Za-z_][\w.]*)\s*=\s*["'](?P<val>[^"'#]{1,200})["']"""
)
_SECRET_NAME_RE = re.compile(
    r"(?i)(password|passwd|pwd|secret|api[_-]?key|api[_-]?token|access[_-]?token"
    r"|auth[_-]?token|client[_-]?secret|private[_-]?key|aws[_-]?secret)"
)
_AWS_KEY_RE = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
_GITHUB_TOKEN_RE = re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")
_PRIVATE_KEY_RE = re.compile(r"-----BEGIN (?:RSA )?PRIVATE KEY-----")
_ENV_LOOKUP_RE = re.compile(r"os\.environ|os\.getenv|getenv\s*\(")

# Values that are clearly placeholders, not real secrets.
_PLACEHOLDERS = {
    "", "xxx", "changeme", "password", "example", "test", "testing",
    "dummy", "none", "null", "***", "...", "placeholder",
}

_REDACTED = "[REDACTED]"


def _looks_placeholder(value: str) -> bool:
    """Check for dummy/example values that must not raise findings."""
    lowered = value.strip().lower()
    if lowered in _PLACEHOLDERS:
        return True
    return lowered.startswith(("your-", "test-", "example-", "xxx")) or "here" in lowered


def _resolve_call_name(node: ast.AST, aliases: dict[str, str]) -> str:
    """Resolve a call's func to a dotted name using tracked import aliases."""
    if isinstance(node, ast.Name):
        return aliases.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        base = _resolve_call_name(node.value, aliases)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def _keyword_true(call: ast.Call, name: str) -> bool:
    """Check whether a keyword argument is literally True."""
    for keyword in call.keywords:
        if keyword.arg == name and isinstance(keyword.value, ast.Constant):
            return keyword.value.value is True
    return False


def _evidence(text: str, node: ast.AST) -> str:
    """Extract a bounded source segment for a node."""
    try:
        segment = ast.get_source_segment(text, node) or ""
    except (ValueError, TypeError):
        segment = ""
    segment = " ".join(segment.split())
    return segment[:MAX_EVIDENCE_CHARS]


class _SecurityVisitor(ast.NodeVisitor):
    """AST visitor collecting risky-call findings with import-alias tracking."""

    def __init__(self, rel_path: str, text: str, findings: list[SecurityFinding]) -> None:
        self.rel_path = rel_path
        self.text = text
        self.findings = findings
        self.aliases: dict[str, str] = {}

    def _add(self, rule_id: str, severity: str, title: str,
             node: ast.AST, recommendation: str) -> None:
        lineno = getattr(node, "lineno", None)
        self.findings.append(SecurityFinding(
            rule_id=rule_id, severity=severity, title=title,
            file=self.rel_path, line=lineno,
            evidence=_evidence(self.text, node), recommendation=recommendation,
        ))

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            local = alias.asname or alias.name.split(".")[0]
            self.aliases[local] = alias.name
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level:
            for alias in node.names:  # relative import: local code, not a risk
                self.aliases[alias.asname or alias.name] = ""
            self.generic_visit(node)
            return
        module = node.module or ""
        for alias in node.names:
            self.aliases[alias.asname or alias.name] = f"{module}.{alias.name}"
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        dotted = _resolve_call_name(node.func, self.aliases)
        if dotted in ("eval", "builtins.eval"):
            self._add("PY-EVAL", "high", "Use of eval()",
                      node, "Avoid eval(); parse data with ast.literal_eval or json instead.")
        elif dotted in ("exec", "builtins.exec"):
            self._add("PY-EXEC", "high", "Use of exec()",
                      node, "Avoid exec(); refactor into explicit functions or imports.")
        elif dotted in ("os.system", "os.popen"):
            self._add("PY-OS-SYSTEM", "high", f"Use of {dotted}()",
                      node, "Use subprocess.run() with shell=False and an argument list.")
        elif dotted in ("subprocess.run", "subprocess.call", "subprocess.check_call",
                        "subprocess.check_output", "subprocess.Popen"):
            if _keyword_true(node, "shell"):
                self._add("PY-SHELL-TRUE", "high", f"{dotted}() with shell=True",
                          node, "Drop shell=True and pass the command as a list of arguments.")
        elif dotted in ("pickle.loads", "pickle.load", "cPickle.loads", "cPickle.load"):
            self._add("PY-PICKLE", "high", f"Unsafe pickle deserialization ({dotted})",
                      node, "Never unpickle untrusted data; use json or another safe format.")
        elif dotted == "yaml.load":
            loader_srcs = []
            for kw in node.keywords:
                if kw.arg == "Loader":
                    try:
                        loader_srcs.append(ast.unparse(kw.value))
                    except (ValueError, TypeError):
                        loader_srcs.append("?")
            if not any("Safe" in src for src in loader_srcs):
                self._add("PY-YAML-LOAD", "medium", "yaml.load() without SafeLoader",
                          node, "Use yaml.safe_load() or pass Loader=yaml.SafeLoader.")
        self.generic_visit(node)


def _scan_secrets(rel_path: str, text: str, findings: list[SecurityFinding]) -> None:
    """Line-based secret heuristics; only redacted placeholders are stored."""
    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#") or _ENV_LOOKUP_RE.search(line):
            continue
        if _PRIVATE_KEY_RE.search(line):
            findings.append(SecurityFinding(
                rule_id="SECRET-PRIVATE-KEY", severity="high",
                title="Embedded private key material", file=rel_path, line=lineno,
                evidence=f"private key header at line {lineno} [{_REDACTED}]",
                recommendation="Remove the key; load it from a secret manager at runtime.",
            ))
            continue
        if _AWS_KEY_RE.search(line) or _GITHUB_TOKEN_RE.search(line):
            findings.append(SecurityFinding(
                rule_id="SECRET-TOKEN", severity="high",
                title="Hard-coded access token", file=rel_path, line=lineno,
                evidence=f"token-like value at line {lineno} [{_REDACTED}]",
                recommendation="Revoke the token and inject it via environment at runtime.",
            ))
            continue
        match = _SECRET_ASSIGN_RE.match(raw_line)
        if match and _SECRET_NAME_RE.search(match.group("var")):
            value = match.group("val").strip()
            if len(value) >= 4 and not _looks_placeholder(value):
                findings.append(SecurityFinding(
                    rule_id="SECRET-ASSIGN", severity="high",
                    title=f"Hard-coded secret in '{match.group('var').strip()}'",
                    file=rel_path, line=lineno,
                    evidence=f"{match.group('var').strip()} = \"{_REDACTED}\"",
                    recommendation="Read the value from the environment instead of hard-coding it.",
                ))


def _is_env_file(name: str) -> bool:
    """Never inspect .env file contents."""
    return name == ".env" or name.startswith(".env.")


def analyze_security(root: Path, python_files: list[str]) -> SecurityAnalysis:
    """Statically scan project Python files. Read-only; secrets redacted."""
    analysis = SecurityAnalysis()
    scanned = 0
    for rel in sorted(set(python_files)):
        if len(analysis.findings) >= MAX_FINDINGS:
            analysis.notes.append(
                f"Finding cap reached ({MAX_FINDINGS}); remaining files skipped.")
            break
        if _is_env_file(Path(rel).name):
            continue
        target = root / rel
        try:
            resolved = target.resolve()
        except (OSError, ValueError):
            continue
        try:
            inside = resolved.is_relative_to(root.resolve())
        except (OSError, ValueError):
            continue
        if not inside or not target.is_file():
            continue
        try:
            text = target.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            analysis.notes.append(f"{rel}: cannot read file ({exc.strerror or exc})")
            continue
        scanned += 1
        try:
            tree = ast.parse(text)
        except (SyntaxError, ValueError):
            analysis.notes.append(f"{rel}: cannot parse, AST rules skipped")
            _scan_secrets(rel, text, analysis.findings)
            continue
        visitor = _SecurityVisitor(rel, text, analysis.findings)
        visitor.visit(tree)
        _scan_secrets(rel, text, analysis.findings)
    analysis.files_scanned = scanned
    return analysis
