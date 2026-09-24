import { describe, it } from "node:test";
import assert from "node:assert";
import * as fs from "fs";
import { setVscode } from "../vscodeApi";
import {
  activate,
  checkDependencies,
  installDependencies,
} from "../extension";
import { createMockVscode, MockVscode } from "./vscodeMock";
import type * as vscode from "vscode";

interface Ctx {
  workspacePath: string;
  output: { appendLine: (line: string) => void; show: () => void; dispose: () => void };
  diagnostics: { clear: () => void; set: (uri: unknown, diags: unknown[]) => void };
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  config: any;
}

function setup(options: { diagnoseQueue: unknown[]; repairResult?: unknown }) {
  const mock: MockVscode = createMockVscode();
  setVscode(mock.vscode as unknown as typeof vscode);
  const extension = { checkDependencies, installDependencies, activate };
  const diagnoseQueue = [...options.diagnoseQueue];
  const repairCalls: unknown[] = [];
  const engine = {
    runDiagnose: async () => {
      const next = diagnoseQueue.shift();
      if (next instanceof Error) {
        throw next;
      }
      return next;
    },
    runRepair: async (opts: unknown) => {
      repairCalls.push(opts);
      return options.repairResult;
    },
  };
  const outputLines: string[] = [];
  const cleared: string[] = [];
  const ctx: Ctx = {
    workspacePath: "/ws",
    output: {
      appendLine: (line: string) => outputLines.push(line),
      show: () => undefined,
      dispose: () => undefined,
    },
    diagnostics: {
      clear: () => cleared.push("cleared"),
      set: () => undefined,
    },
    config: {
      pythonExecutable: "python",
      autoCheckOnOpen: true,
      timeoutMs: 5000,
      runTests: false,
    },
  };
  return { mock, extension, engine, ctx, outputLines, cleared, repairCalls };
}

interface DiagnoseData {
  environment: Record<string, unknown>;
  project: {
    path: string;
    name: string;
    exists: boolean;
    is_directory: boolean;
    python_files: string[];
    files_present: Record<string, boolean>;
    error: string | null;
  };
  errors: string[];
  dependencies: {
    declared: unknown[];
    installed: unknown[];
    imports: unknown[];
    issues: unknown[];
    notes: string[];
    skipped: string | null;
  };
  ecosystems?: Array<{
    ecosystem_id: string;
    display_name: string;
    manifests_found: string[];
    supported: boolean;
    message: string;
  }>;
}

function withEcosystems(
  result: { ok: true; data: DiagnoseData },
  ecosystems: NonNullable<DiagnoseData["ecosystems"]>
): { ok: true; data: DiagnoseData } {
  result.data.ecosystems = ecosystems;
  return result;
}

function okDiagnose(issues: unknown[] = []): { ok: true; data: DiagnoseData } {
  return {
    ok: true,
    data: {
      environment: {},
      project: {
        path: "/ws",
        name: "demo",
        exists: true,
        is_directory: true,
        python_files: ["app.py"],
        files_present: { "requirements.txt": true },
        error: null,
      },
      errors: [],
      dependencies: {
        declared: [],
        installed: [],
        imports: [],
        issues,
        notes: [],
        skipped: null,
      },
    },
  };
}

function issue(kind: string, name: string) {
  return { kind, name, detail: `${kind} ${name}`, declared: "==1.0.0", installed: null };
}

describe("checkDependencies", () => {
  it("shows an error when the engine is unavailable", async () => {
    const { mock, extension, engine, ctx } = setup({
      diagnoseQueue: [{ ok: false, error: { code: "unavailable", message: "no engine" } }],
    });
    const issues = await extension.checkDependencies(
      mock.vscode as unknown as typeof vscode,
      engine as never,
      ctx as never
    );
    assert.deepStrictEqual(issues, []);
    assert.ok(
      mock.calls.some(
        (c) => c.method === "showErrorMessage" && String(c.args[0]).includes("engine")
      )
    );
  });

  it("reports a clean project", async () => {
    const { mock, extension, engine, ctx } = setup({ diagnoseQueue: [okDiagnose([])] });
    const issues = await extension.checkDependencies(
      mock.vscode as unknown as typeof vscode,
      engine as never,
      ctx as never
    );
    assert.deepStrictEqual(issues, []);
    assert.ok(
      mock.calls.some(
        (c) =>
          c.method === "showInformationMessage" &&
          String(c.args[0]).includes("all dependencies satisfied")
      )
    );
  });

  it("offers review on actionable issues but does not install on dismiss", async () => {
    const { mock, extension, engine, ctx, repairCalls } = setup({
      diagnoseQueue: [okDiagnose([issue("missing", "pandas")])],
      repairResult: { ok: true, data: { status: "success" } },
    });
    mock.respondWith.set("showWarningMessage", ["Dismiss"]);
    const issues = await extension.checkDependencies(
      mock.vscode as unknown as typeof vscode,
      engine as never,
      ctx as never
    );
    assert.strictEqual(issues.length, 1);
    assert.strictEqual(repairCalls.length, 0);
  });

  it("reports unusable project paths", async () => {
    const broken = okDiagnose([]);
    broken.data.project.exists = false;
    broken.data.project.error = "Path does not exist";
    const { mock, extension, engine, ctx } = setup({ diagnoseQueue: [broken] });
    await extension.checkDependencies(
      mock.vscode as unknown as typeof vscode,
      engine as never,
      ctx as never
    );
    assert.ok(mock.calls.some((c) => c.method === "showErrorMessage"));
  });

  it("informs about unsupported ecosystems without an install flow", async () => {
    const data = withEcosystems(okDiagnose([]), [
      {
        ecosystem_id: "javascript",
        display_name: "JavaScript/TypeScript",
        manifests_found: ["package.json"],
        supported: false,
        message: "not yet supported",
      },
    ]);
    const { mock, extension, engine, ctx, repairCalls } = setup({
      diagnoseQueue: [data],
      repairResult: { ok: true, data: { status: "success" } },
    });
    const issues = await extension.checkDependencies(
      mock.vscode as unknown as typeof vscode,
      engine as never,
      ctx as never
    );
    assert.deepStrictEqual(issues, []);
    assert.strictEqual(repairCalls.length, 0);
    assert.ok(
      mock.calls.some(
        (c) =>
          c.method === "showInformationMessage" &&
          String(c.args[0]).includes("JavaScript/TypeScript")
      )
    );
    // No misleading "all satisfied" message when other ecosystems exist.
    assert.ok(
      !mock.calls.some(
        (c) =>
          c.method === "showInformationMessage" &&
          String(c.args[0]).includes("all dependencies satisfied")
      )
    );
  });

  it("shows mixed supported and unsupported ecosystems separately", async () => {
    const data = withEcosystems(okDiagnose([issue("missing", "pandas")]), [
      {
        ecosystem_id: "python",
        display_name: "Python/Pip",
        manifests_found: ["requirements.txt"],
        supported: true,
        message: "supported",
      },
      {
        ecosystem_id: "go",
        display_name: "Go",
        manifests_found: ["go.mod"],
        supported: false,
        message: "not yet supported",
      },
    ]);
    const { mock, extension, engine, ctx, repairCalls, outputLines } = setup({
      diagnoseQueue: [data],
      repairResult: { ok: true, data: { status: "success" } },
    });
    mock.respondWith.set("showWarningMessage", ["Dismiss"]);
    const issues = await extension.checkDependencies(
      mock.vscode as unknown as typeof vscode,
      engine as never,
      ctx as never
    );
    assert.strictEqual(issues.length, 1);
    assert.strictEqual(repairCalls.length, 0);
    assert.ok(
      mock.calls.some(
        (c) =>
          c.method === "showInformationMessage" &&
          String(c.args[0]).includes("Go (go.mod)")
      )
    );
    assert.ok(outputLines.some((line) => line.includes("Python/Pip")));
  });
});

describe("installDependencies", () => {
  it("does nothing when there is no installable plan", async () => {
    const { mock, extension, engine, ctx, repairCalls } = setup({
      diagnoseQueue: [okDiagnose([issue("possibly-unused", "requests")])],
      repairResult: { ok: true, data: { status: "success" } },
    });
    const result = await extension.installDependencies(
      mock.vscode as unknown as typeof vscode,
      engine as never,
      ctx as never
    );
    assert.strictEqual(repairCalls.length, 0);
    assert.strictEqual(result.installed, false);
    assert.ok(mock.calls.some((c) => c.method === "showInformationMessage"));
  });

  it("cancels cleanly without calling repair", async () => {
    const { mock, extension, engine, ctx, repairCalls } = setup({
      diagnoseQueue: [okDiagnose([issue("missing", "pandas")])],
      repairResult: { ok: true, data: { status: "success" } },
    });
    mock.respondWith.set("showWarningMessage", ["Cancel"]);
    const result = await extension.installDependencies(
      mock.vscode as unknown as typeof vscode,
      engine as never,
      ctx as never
    );
    assert.strictEqual(result.installed, false);
    assert.strictEqual(repairCalls.length, 0);
    assert.ok(
      mock.calls.some(
        (c) =>
          c.method === "showInformationMessage" &&
          String(c.args[0]).includes("cancelled")
      )
    );
  });

  it("installs on approval, cleans the plan file, and verifies", async () => {
    const { mock, extension, engine, ctx, repairCalls } = setup({
      diagnoseQueue: [okDiagnose([issue("missing", "pandas")]), okDiagnose([])],
      repairResult: { ok: true, data: { status: "success" } },
    });
    mock.respondWith.set("showWarningMessage", ["Install"]);
    const result = await extension.installDependencies(
      mock.vscode as unknown as typeof vscode,
      engine as never,
      ctx as never
    );
    assert.strictEqual(result.installed, true);
    assert.strictEqual(result.remaining, 0);
    assert.strictEqual(repairCalls.length, 1);
    const planFile = (repairCalls[0] as { planFile: string }).planFile;
    assert.ok(planFile.endsWith(".json"));
    assert.strictEqual(fs.existsSync(planFile), false);
    assert.ok(
      mock.calls.some(
        (c) =>
          c.method === "showInformationMessage" &&
          String(c.args[0]).includes("All required dependencies are now satisfied")
      )
    );
  });

  it("reports verification failures without claiming success", async () => {
    const { mock, extension, engine, ctx } = setup({
      diagnoseQueue: [
        okDiagnose([issue("missing", "pandas")]),
        okDiagnose([issue("missing", "numpy")]),
      ],
      repairResult: { ok: true, data: { status: "success" } },
    });
    mock.respondWith.set("showWarningMessage", ["Install"]);
    const result = await extension.installDependencies(
      mock.vscode as unknown as typeof vscode,
      engine as never,
      ctx as never
    );
    assert.strictEqual(result.installed, true);
    assert.strictEqual(result.remaining, 1);
    assert.ok(mock.calls.some((c) => c.method === "showWarningMessage"));
  });

  it("surfaces engine repair errors without claiming success", async () => {
    const { mock, extension, engine, ctx, repairCalls } = setup({
      diagnoseQueue: [
        okDiagnose([issue("missing", "pandas")]),
        okDiagnose([issue("missing", "pandas")]),
      ],
      repairResult: { ok: true, data: { status: "failed", verification: null } },
    });
    mock.respondWith.set("showWarningMessage", ["Install", "Dismiss"]);
    const result = await extension.installDependencies(
      mock.vscode as unknown as typeof vscode,
      engine as never,
      ctx as never
    );
    assert.strictEqual(result.installed, false);
    assert.strictEqual(repairCalls.length, 1);
  });
});

describe("activate", () => {
  it("registers commands and runs the startup check", async () => {
    const mock: MockVscode = createMockVscode();
    setVscode(mock.vscode as unknown as typeof vscode);
    const extension = { checkDependencies, installDependencies, activate };
    const api = mock.vscode as unknown as typeof vscode;
    (api.workspace as unknown as { workspaceFolders: unknown }).workspaceFolders = [
      { uri: { fsPath: "/ws" } },
    ];
    const context = { subscriptions: [] as { dispose(): void }[] };
    extension.activate(context as unknown as vscode.ExtensionContext);
    const registered = mock.calls
      .filter((c) => c.method === "registerCommand")
      .map((c) => c.args[0]);
    assert.deepStrictEqual(registered, [
      "devdoctor.checkDependencies",
      "devdoctor.installDependencies",
      "devdoctor.showOutput",
    ]);
    // Allow the fire-and-forget startup check to settle (no engine stub here
    // would spawn a real process, so only assert registration happened).
    await new Promise((resolve) => setTimeout(resolve, 50));
  });
});
