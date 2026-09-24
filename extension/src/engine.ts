/**
 * Controlled bridge to the DevDoctor Python engine.
 *
 * Safety rules (never relaxed):
 * - child_process.spawn with an argv array; `shell` is never enabled.
 * - Fixed argument templates; only the workspace path, plan file, and
 *   configured python executable vary, and all are validated first.
 * - Timeouts kill the child process; stdout is bounded.
 * - Engine output is treated as untrusted: JSON shape is validated.
 */

import * as child_process from "child_process";
import * as fs from "fs";
import * as path from "path";

export interface DependencyIssue {
  kind: string;
  name: string;
  detail: string;
  declared: string | null;
  installed: string | null;
}

export interface EngineDependencies {
  declared: Array<{ name: string; constraint: string; source: string }>;
  installed: Array<{ name: string; version: string }>;
  imports: Array<{ name: string; classification: string }>;
  issues: DependencyIssue[];
  notes: string[];
  skipped: string | null;
}

export interface EngineProject {
  path: string;
  name: string;
  exists: boolean;
  is_directory: boolean;
  python_files: string[];
  files_present: Record<string, boolean>;
  error: string | null;
}

export interface EcosystemInfo {
  ecosystem_id: string;
  display_name: string;
  manifests_found: string[];
  supported: boolean;
  message: string;
}

export interface EngineResult {
  environment: Record<string, unknown>;
  project: EngineProject;
  errors: string[];
  dependencies: EngineDependencies | null;
  tests?: unknown;
  security?: unknown;
  vulnerabilities?: unknown;
  docker?: unknown;
  ecosystems?: EcosystemInfo[];
}

export interface RepairReportData {
  status: string;
  error?: string;
  initial_diagnosis?: unknown;
  repair_plan?: { actions: Array<Record<string, unknown>> } | null;
  actions_attempted?: Array<Record<string, unknown>>;
  verification?: { success: boolean; message: string } | null;
  rollback_performed?: boolean;
  rollback_success?: boolean;
  cycles?: number;
  [key: string]: unknown;
}

export type EngineErrorCode = "unavailable" | "timeout" | "malformed" | "failed";

export interface EngineError {
  code: EngineErrorCode;
  message: string;
}

export type EngineOutcome =
  | { ok: true; data: EngineResult }
  | { ok: false; error: EngineError };

export type RepairOutcome =
  | { ok: true; data: RepairReportData }
  | { ok: false; error: EngineError };

export interface SpawnFn {
  (
    command: string,
    args: string[],
    options: child_process.SpawnOptions
  ): child_process.ChildProcess;
}

export interface RunOptions {
  pythonExecutable: string;
  workspacePath: string;
  timeoutMs: number;
  runTests: boolean;
  spawn?: SpawnFn;
}

export interface RepairOptions {
  pythonExecutable: string;
  workspacePath: string;
  planFile: string;
  timeoutMs: number;
  maxCycles?: number;
  spawn?: SpawnFn;
}

export const MAX_OUTPUT_BYTES = 5 * 1024 * 1024;

function fail(code: EngineErrorCode, message: string): { ok: false; error: EngineError } {
  return { ok: false, error: { code, message } };
}

function validateWorkspace(workspacePath: string): string | null {
  if (!workspacePath || !path.isAbsolute(workspacePath)) {
    return "workspace path must be an absolute directory path";
  }
  let stat: fs.Stats;
  try {
    stat = fs.statSync(workspacePath);
  } catch {
    return `workspace path does not exist: ${workspacePath}`;
  }
  if (!stat.isDirectory()) {
    return `workspace path is not a directory: ${workspacePath}`;
  }
  return null;
}

function validatePython(pythonExecutable: string): string | null {
  if (!pythonExecutable || !pythonExecutable.trim()) {
    return "python executable must be a non-empty string";
  }
  return null;
}

interface CollectedOutput {
  stdout: string;
  code: number | null;
  signal: string | null;
  error?: Error;
  timedOut: boolean;
  tooLarge: boolean;
}

function collect(
  child: child_process.ChildProcess,
  timeoutMs: number
): Promise<CollectedOutput> {
  return new Promise((resolve) => {
    let stdout = "";
    let size = 0;
    let tooLarge = false;
    let timedOut = false;
    let settled = false;

    const finish = (code: number | null, signal: string | null, error?: Error) => {
      if (settled) {
        return;
      }
      settled = true;
      clearTimeout(timer);
      resolve({ stdout, code, signal, error, timedOut, tooLarge });
    };

    const timer = setTimeout(() => {
      timedOut = true;
      try {
        child.kill("SIGKILL");
      } catch {
        // Child may already have exited; finish below handles it.
      }
      finish(null, null);
    }, timeoutMs);

    child.stdout?.on("data", (chunk: Buffer | string) => {
      const text = chunk.toString();
      size += Buffer.byteLength(text);
      if (size > MAX_OUTPUT_BYTES) {
        tooLarge = true;
        try {
          child.kill("SIGKILL");
        } catch {
          // Ignored; finish on close.
        }
        return;
      }
      stdout += text;
    });
    child.stderr?.on("data", () => {
      // stderr is informational only; engine errors surface via exit code.
    });
    child.on("error", (error: Error) => {
      finish(null, null, error);
    });
    child.on("close", (code: number | null, signal: string | null) => {
      finish(code, signal);
    });
  });
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function validateDiagnoseShape(data: unknown): data is EngineResult {
  if (!isRecord(data)) {
    return false;
  }
  const project = data["project"];
  if (!isRecord(project)) {
    return false;
  }
  const deps = data["dependencies"];
  if (deps !== null && deps !== undefined) {
    if (!isRecord(deps) || !Array.isArray(deps["issues"])) {
      return false;
    }
  }
  return true;
}

function spawnEngine(
  spawn: SpawnFn,
  command: string,
  args: string[],
  timeoutMs: number
): Promise<CollectedOutput> {
  let child: child_process.ChildProcess;
  try {
    child = spawn(command, args, {
      stdio: ["ignore", "pipe", "pipe"],
      // NOTE: shell is intentionally never enabled.
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return Promise.resolve({
      stdout: "",
      code: null,
      signal: null,
      error: new Error(message),
      timedOut: false,
      tooLarge: false,
    });
  }
  return collect(child, timeoutMs);
}

/**
 * Run deterministic dependency diagnosis via the DevDoctor CLI.
 * Never installs or modifies anything (engine runs read-only here).
 */
export async function runDiagnose(options: RunOptions): Promise<EngineOutcome> {
  const badPython = validatePython(options.pythonExecutable);
  if (badPython) {
    return fail("unavailable", badPython);
  }
  const badWorkspace = validateWorkspace(options.workspacePath);
  if (badWorkspace) {
    return fail("failed", badWorkspace);
  }
  const spawn = options.spawn ?? child_process.spawn;
  const args = [
    "-m",
    "devdoctor.cli.main",
    "diagnose",
    options.workspacePath,
    "--json",
    "--skip-security",
    "--skip-docker",
  ];
  if (!options.runTests) {
    args.push("--skip-tests");
  }
  const out = await spawnEngine(spawn, options.pythonExecutable, args, options.timeoutMs);
  if (out.error) {
    return fail("unavailable", `DevDoctor engine could not start: ${out.error.message}`);
  }
  if (out.timedOut) {
    return fail("timeout", `DevDoctor engine timed out after ${options.timeoutMs}ms`);
  }
  if (out.tooLarge) {
    return fail("failed", "DevDoctor engine output exceeded the size limit");
  }
  let data: unknown;
  try {
    data = JSON.parse(out.stdout);
  } catch {
    return fail("malformed", "DevDoctor engine returned output that is not valid JSON");
  }
  if (!validateDiagnoseShape(data)) {
    return fail("malformed", "DevDoctor engine returned JSON with an unexpected shape");
  }
  return { ok: true, data };
}

/**
 * Execute a user-approved repair plan via the DevDoctor CLI.
 * The plan file is produced from the reviewed install plan; --yes carries
 * the explicit VS Code approval. Single cycle; no LLM involved.
 */
export async function runRepair(options: RepairOptions): Promise<RepairOutcome> {
  const badPython = validatePython(options.pythonExecutable);
  if (badPython) {
    return fail("unavailable", badPython);
  }
  const badWorkspace = validateWorkspace(options.workspacePath);
  if (badWorkspace) {
    return fail("failed", badWorkspace);
  }
  if (!options.planFile || !path.isAbsolute(options.planFile)) {
    return fail("failed", "plan file must be an absolute path");
  }
  const spawn = options.spawn ?? child_process.spawn;
  const args = [
    "-m",
    "devdoctor.cli.main",
    "repair",
    options.workspacePath,
    "--plan-file",
    options.planFile,
    "--yes",
    "--json",
    "--max-cycles",
    String(options.maxCycles ?? 1),
  ];
  const out = await spawnEngine(spawn, options.pythonExecutable, args, options.timeoutMs);
  if (out.error) {
    return fail("unavailable", `DevDoctor engine could not start: ${out.error.message}`);
  }
  if (out.timedOut) {
    return fail("timeout", `DevDoctor repair timed out after ${options.timeoutMs}ms`);
  }
  if (out.tooLarge) {
    return fail("failed", "DevDoctor engine output exceeded the size limit");
  }
  let data: unknown;
  try {
    data = JSON.parse(out.stdout);
  } catch {
    return fail("malformed", "DevDoctor engine returned output that is not valid JSON");
  }
  if (!isRecord(data) || typeof data["status"] !== "string") {
    return fail("malformed", "DevDoctor engine returned JSON with an unexpected shape");
  }
  return { ok: true, data: data as RepairReportData };
}
