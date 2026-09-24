/**
 * Map engine dependency issues onto VS Code Problems-panel entries.
 *
 * Issues are file-scoped to the dependency manifest (requirements.txt or
 * pyproject.toml) because dependency findings have no source line of their
 * own. When no manifest exists, entries are output-channel only.
 */

import type * as vscode from "vscode";
import type { DependencyIssue } from "./engine";

export type ProblemSeverity = "error" | "warning" | "info";

export interface ProblemEntry {
  file: string;
  line: number;
  severity: ProblemSeverity;
  message: string;
}

const KIND_SEVERITY: Record<string, ProblemSeverity> = {
  "missing": "error",
  "declared-not-installed": "error",
  "version-mismatch": "warning",
  "imported-not-declared": "warning",
  "possibly-unused": "info",
};

const MAX_MESSAGE_CHARS = 300;

/** Pick the manifest file issues attach to, or null when there is none. */
export function manifestFile(filesPresent: Record<string, boolean>): string | null {
  if (filesPresent["requirements.txt"]) {
    return "requirements.txt";
  }
  if (filesPresent["pyproject.toml"]) {
    return "pyproject.toml";
  }
  return null;
}

export function toProblemEntries(
  issues: DependencyIssue[],
  filesPresent: Record<string, boolean>
): ProblemEntry[] {
  const manifest = manifestFile(filesPresent);
  if (!manifest) {
    return [];
  }
  return issues.map((issue) => {
    const text = `${issue.name}: ${issue.detail || issue.kind}`;
    return {
      file: manifest,
      line: 0,
      severity: KIND_SEVERITY[issue.kind] ?? "info",
      message: text.length > MAX_MESSAGE_CHARS ? text.slice(0, MAX_MESSAGE_CHARS) : text,
    };
  });
}

function toVsSeverity(
  vscodeApi: typeof import("vscode"),
  severity: ProblemSeverity
): vscode.DiagnosticSeverity {
  switch (severity) {
    case "error":
      return vscodeApi.DiagnosticSeverity.Error;
    case "warning":
      return vscodeApi.DiagnosticSeverity.Warning;
    default:
      return vscodeApi.DiagnosticSeverity.Information;
  }
}

/** Replace the collection contents for this workspace with fresh entries. */
export function syncDiagnostics(
  vscodeApi: typeof import("vscode"),
  collection: vscode.DiagnosticCollection,
  workspacePath: string,
  entries: ProblemEntry[]
): void {
  collection.clear();
  const byFile = new Map<string, ProblemEntry[]>();
  for (const entry of entries) {
    const list = byFile.get(entry.file) ?? [];
    list.push(entry);
    byFile.set(entry.file, list);
  }
  for (const [file, list] of byFile) {
    const uri = vscodeApi.Uri.file(`${workspacePath}/${file}`);
    collection.set(
      uri,
      list.map((entry) => new vscodeApi.Diagnostic(
        new vscodeApi.Range(entry.line, 0, entry.line, 0),
        entry.message,
        toVsSeverity(vscodeApi, entry.severity)
      ))
    );
  }
}
