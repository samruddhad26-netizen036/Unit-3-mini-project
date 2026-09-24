import { describe, it } from "node:test";
import assert from "node:assert";
import { manifestFile, syncDiagnostics, toProblemEntries } from "../diagnostics";
import { createMockVscode } from "./vscodeMock";
import type * as vscode from "vscode";

function issue(kind: string, name: string) {
  return { kind, name, detail: `${kind} detail`, declared: null, installed: null };
}

describe("manifestFile", () => {
  it("prefers requirements.txt, then pyproject.toml", () => {
    assert.strictEqual(manifestFile({ "requirements.txt": true }), "requirements.txt");
    assert.strictEqual(
      manifestFile({ "requirements.txt": false, "pyproject.toml": true }),
      "pyproject.toml"
    );
    assert.strictEqual(manifestFile({}), null);
  });
});

describe("toProblemEntries", () => {
  it("maps kinds to severities on the manifest file", () => {
    const entries = toProblemEntries(
      [
        issue("missing", "pandas"),
        issue("version-mismatch", "numpy"),
        issue("possibly-unused", "requests"),
      ],
      { "requirements.txt": true }
    );
    assert.strictEqual(entries.length, 3);
    assert.deepStrictEqual(
      entries.map((e) => e.severity),
      ["error", "warning", "info"]
    );
    assert.ok(entries.every((e) => e.file === "requirements.txt" && e.line === 0));
    assert.ok(entries[0].message.includes("pandas"));
  });
  it("returns no entries without a manifest", () => {
    assert.deepStrictEqual(toProblemEntries([issue("missing", "pandas")], {}), []);
  });
  it("bounds long messages", () => {
    const entries = toProblemEntries(
      [{ kind: "missing", name: "x", detail: "d".repeat(1000), declared: null, installed: null }],
      { "requirements.txt": true }
    );
    assert.ok(entries[0].message.length <= 320);
  });
});

describe("syncDiagnostics", () => {
  it("groups entries per file in the collection", () => {
    const mock = createMockVscode();
    const collection = {
      clear_calls: 0,
      set_calls: [] as Array<{ uri: string; count: number }>,
      clear() {
        this.clear_calls += 1;
      },
      set(uri: { fsPath: string }, diags: unknown[]) {
        this.set_calls.push({ uri: uri.fsPath, count: diags.length });
      },
    };
    syncDiagnostics(
      mock.vscode as unknown as typeof vscode,
      collection as unknown as vscode.DiagnosticCollection,
      "/ws",
      [
        { file: "requirements.txt", line: 0, severity: "error", message: "a" },
        { file: "requirements.txt", line: 0, severity: "warning", message: "b" },
      ]
    );
    assert.strictEqual(collection.clear_calls, 1);
    assert.strictEqual(collection.set_calls.length, 1);
    assert.ok(collection.set_calls[0].uri.endsWith("requirements.txt"));
    assert.strictEqual(collection.set_calls[0].count, 2);
  });
});
