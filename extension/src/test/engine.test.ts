import { describe, it, beforeEach, afterEach } from "node:test";
import assert from "node:assert";
import { EventEmitter } from "node:events";
import * as fs from "fs";
import * as os from "os";
import * as path from "path";
import type * as child_process from "child_process";
import { runDiagnose, runRepair } from "../engine";
import type { SpawnFn } from "../engine";

let workspace = "";

beforeEach(() => {
  workspace = fs.mkdtempSync(path.join(os.tmpdir(), "dd-ext-"));
});

afterEach(() => {
  fs.rmSync(workspace, { recursive: true, force: true });
});

interface FakeChildOptions {
  stdout?: string;
  code?: number | null;
  syncThrow?: Error;
  neverClose?: boolean;
}

class FakeChild extends EventEmitter {
  stdout = new EventEmitter();
  stderr = new EventEmitter();
  killed = false;
  private options: FakeChildOptions;
  constructor(options: FakeChildOptions) {
    super();
    this.options = options;
  }
  kill(): boolean {
    this.killed = true;
    return true;
  }
  launch(): void {
    if (this.options.syncThrow) {
      return;
    }
    if (this.options.neverClose) {
      return;
    }
    setImmediate(() => {
      if (this.options.stdout) {
        this.stdout.emit("data", Buffer.from(this.options.stdout));
      }
      this.emit("close", this.options.code ?? 0, null);
    });
  }
}

function fakeSpawnFactory(
  child: FakeChild,
  seen: { command?: string; args?: string[]; shell?: unknown }
): SpawnFn {
  const spawn: SpawnFn = (command, args, options) => {
    seen.command = command;
    seen.args = args;
    seen.shell = options.shell;
    child.launch();
    return child as unknown as child_process.ChildProcess;
  };
  return spawn;
}

function diagnoseJson(overrides = {}) {
  return JSON.stringify({
    environment: {},
    project: {
      path: workspace,
      name: "demo",
      exists: true,
      is_directory: true,
      python_files: ["app.py"],
      files_present: { "requirements.txt": true },
      error: null,
      ...overrides,
    },
    errors: [],
    dependencies: {
      declared: [],
      installed: [],
      imports: [],
      issues: [],
      notes: [],
      skipped: null,
    },
  });
}

describe("runDiagnose", () => {
  it("parses valid engine JSON", async () => {
    const child = new FakeChild({ stdout: diagnoseJson(), code: 0 });
    const seen: { command?: string; args?: string[]; shell?: unknown } = {};
    const outcome = await runDiagnose({
      pythonExecutable: "python",
      workspacePath: workspace,
      timeoutMs: 5000,
      runTests: false,
      spawn: fakeSpawnFactory(child, seen),
    });
    assert.strictEqual(outcome.ok, true);
    assert.strictEqual(seen.shell, undefined);
    assert.ok(seen.args?.includes("--json"));
    assert.ok(seen.args?.includes("--skip-tests"));
    assert.ok(!seen.args?.some((a) => a.includes(";") || a.includes("&&")));
  });

  it("rejects relative workspace paths without spawning", async () => {
    let spawned = false;
    const outcome = await runDiagnose({
      pythonExecutable: "python",
      workspacePath: "relative/path",
      timeoutMs: 1000,
      runTests: false,
      spawn: (() => {
        spawned = true;
        throw new Error("must not spawn");
      }) as SpawnFn,
    });
    assert.strictEqual(outcome.ok, false);
    assert.strictEqual(spawned, false);
    if (!outcome.ok) {
      assert.strictEqual(outcome.error.code, "failed");
    }
  });

  it("reports timeouts when the engine hangs", async () => {
    const child = new FakeChild({ neverClose: true });
    const seen: { command?: string; args?: string[]; shell?: unknown } = {};
    const outcome = await runDiagnose({
      pythonExecutable: "python",
      workspacePath: workspace,
      timeoutMs: 40,
      runTests: false,
      spawn: fakeSpawnFactory(child, seen),
    });
    assert.strictEqual(outcome.ok, false);
    if (!outcome.ok) {
      assert.strictEqual(outcome.error.code, "timeout");
    }
    assert.strictEqual(child.killed, true);
  });

  it("reports unavailable when the process cannot start", async () => {
    const outcome = await runDiagnose({
      pythonExecutable: "python",
      workspacePath: workspace,
      timeoutMs: 1000,
      runTests: false,
      spawn: (() => {
        throw new Error("spawn python ENOENT");
      }) as SpawnFn,
    });
    assert.strictEqual(outcome.ok, false);
    if (!outcome.ok) {
      assert.strictEqual(outcome.error.code, "unavailable");
    }
  });

  it("rejects malformed JSON output", async () => {
    const child = new FakeChild({ stdout: "not json {", code: 0 });
    const seen: { command?: string; args?: string[]; shell?: unknown } = {};
    const outcome = await runDiagnose({
      pythonExecutable: "python",
      workspacePath: workspace,
      timeoutMs: 1000,
      runTests: false,
      spawn: fakeSpawnFactory(child, seen),
    });
    assert.strictEqual(outcome.ok, false);
    if (!outcome.ok) {
      assert.strictEqual(outcome.error.code, "malformed");
    }
  });

  it("rejects well-formed JSON with the wrong shape", async () => {
    const child = new FakeChild({ stdout: JSON.stringify({ hello: "world" }), code: 0 });
    const seen: { command?: string; args?: string[]; shell?: unknown } = {};
    const outcome = await runDiagnose({
      pythonExecutable: "python",
      workspacePath: workspace,
      timeoutMs: 1000,
      runTests: false,
      spawn: fakeSpawnFactory(child, seen),
    });
    assert.strictEqual(outcome.ok, false);
    if (!outcome.ok) {
      assert.strictEqual(outcome.error.code, "malformed");
    }
  });
});

describe("runRepair", () => {
  it("parses repair report JSON", async () => {
    const report = JSON.stringify({ status: "success", cycles: 1 });
    const child = new FakeChild({ stdout: report, code: 0 });
    const seen: { command?: string; args?: string[]; shell?: unknown } = {};
    const outcome = await runRepair({
      pythonExecutable: "python",
      workspacePath: workspace,
      planFile: path.join(workspace, "plan.json"),
      timeoutMs: 5000,
      spawn: fakeSpawnFactory(child, seen),
    });
    assert.strictEqual(outcome.ok, true);
    assert.ok(seen.args?.includes("--plan-file"));
    assert.ok(seen.args?.includes("--yes"));
    assert.ok(seen.args?.includes("--json"));
  });

  it("rejects relative plan file paths without spawning", async () => {
    let spawned = false;
    const outcome = await runRepair({
      pythonExecutable: "python",
      workspacePath: workspace,
      planFile: "plan.json",
      timeoutMs: 1000,
      spawn: (() => {
        spawned = true;
        throw new Error("must not spawn");
      }) as SpawnFn,
    });
    assert.strictEqual(outcome.ok, false);
    assert.strictEqual(spawned, false);
  });
});
