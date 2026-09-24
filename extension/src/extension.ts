/**
 * DevDoctor VS Code extension entry point.
 *
 * Thin UI layer over the DevDoctor Python engine: automatic read-only
 * dependency checks on startup, Problems-panel diagnostics, an explicit
 * user-approved install flow, and post-install verification.
 *
 * Scanning may run automatically. Installation NEVER runs without the
 * user explicitly selecting Install.
 */

import * as fs from "fs";
import * as os from "os";
import * as path from "path";
import type * as vscode from "vscode";
import {
  EngineOutcome,
  RepairOutcome,
  runDiagnose as defaultRunDiagnose,
  runRepair as defaultRunRepair,
} from "./engine";
import { syncDiagnostics, toProblemEntries } from "./diagnostics";
import { partitionEcosystems, unsupportedNotice } from "./ecosystems";
import { buildInstallPlan, planFilePayload, summarizePlan } from "./installPlan";
import { getVscode } from "./vscodeApi";

export interface EngineApi {
  runDiagnose: typeof defaultRunDiagnose;
  runRepair: typeof defaultRunRepair;
}

export interface ExtensionConfig {
  pythonExecutable: string;
  autoCheckOnOpen: boolean;
  timeoutMs: number;
  runTests: boolean;
}

export interface HandlerContext {
  workspacePath: string;
  output: vscode.OutputChannel;
  diagnostics: vscode.DiagnosticCollection;
  config: ExtensionConfig;
}

type Vscode = typeof vscode;

const ACTIONABLE_KINDS = new Set(["missing", "declared-not-installed", "version-mismatch"]);

export function readConfig(vscodeApi: Vscode): ExtensionConfig {
  const config = vscodeApi.workspace.getConfiguration("devdoctor");
  return {
    pythonExecutable: config.get<string>("pythonExecutable", "python"),
    autoCheckOnOpen: config.get<boolean>("autoCheckOnOpen", true),
    timeoutMs: Math.max(1, config.get<number>("timeoutSeconds", 120)) * 1000,
    runTests: config.get<boolean>("runTests", false),
  };
}

function engineErrorMessage(outcome: { ok: false; error: { code: string; message: string } }): string {
  const { code, message } = outcome.error;
  if (code === "unavailable") {
    return `DevDoctor engine not available. Install it with: pip install devdoctor (${message})`;
  }
  if (code === "timeout") {
    return `DevDoctor engine timed out. Increase devdoctor.timeoutSeconds. (${message})`;
  }
  if (code === "malformed") {
    return `DevDoctor engine returned unexpected output. (${message})`;
  }
  return `DevDoctor engine failed: ${message}`;
}

/** Run a read-only check and sync the Problems panel. Returns raw issues. */
export async function checkDependencies(
  vscodeApi: Vscode,
  engine: EngineApi,
  ctx: HandlerContext
): Promise<Array<{ kind: string; name: string; detail: string }>> {
  ctx.output.appendLine(`DevDoctor: checking dependencies in ${ctx.workspacePath} ...`);
  const outcome: EngineOutcome = await engine.runDiagnose({
    pythonExecutable: ctx.config.pythonExecutable,
    workspacePath: ctx.workspacePath,
    timeoutMs: ctx.config.timeoutMs,
    runTests: ctx.config.runTests,
  });
  if (!outcome.ok) {
    ctx.diagnostics.clear();
    const message = engineErrorMessage(outcome);
    ctx.output.appendLine(`DevDoctor: ${message}`);
    await vscodeApi.window.showErrorMessage(message);
    return [];
  }
  const data = outcome.data;
  if (data.project.error || !data.project.exists) {
    const message = `DevDoctor: cannot inspect project: ${data.project.error ?? "unknown error"}`;
    ctx.output.appendLine(message);
    await vscodeApi.window.showErrorMessage(message);
    return [];
  }
  const issues = data.dependencies?.issues ?? [];
  const { supported, unsupported } = partitionEcosystems(data.ecosystems);
  if (supported.length > 0) {
    ctx.output.appendLine(
      `DevDoctor: supported ecosystem(s): ${supported.map((s) => s.display_name).join(", ")}.`
    );
  }
  syncDiagnostics(
    vscodeApi,
    ctx.diagnostics,
    ctx.workspacePath,
    toProblemEntries(issues, data.project.files_present ?? {})
  );
  const actionable = issues.filter((i) => ACTIONABLE_KINDS.has(i.kind));
  ctx.output.appendLine(
    `DevDoctor: ${issues.length} dependency issue(s), ${actionable.length} installable.`
  );
  for (const issue of issues) {
    ctx.output.appendLine(`  - [${issue.kind}] ${issue.name}: ${issue.detail || "no detail"}`);
  }
  if (actionable.length > 0) {
    const choice = await vscodeApi.window.showWarningMessage(
      `DevDoctor found ${actionable.length} installable dependency issue(s) in ${data.project.name || ctx.workspacePath}.`,
      "Review and Install",
      "Dismiss"
    );
    if (choice === "Review and Install") {
      await installDependencies(vscodeApi, engine, ctx);
    }
  } else if (issues.length === 0 && unsupported.length === 0) {
    await vscodeApi.window.showInformationMessage("DevDoctor: all dependencies satisfied.");
  }
  const notice = unsupportedNotice(unsupported);
  if (notice) {
    ctx.output.appendLine(`DevDoctor: ${notice}`);
    await vscodeApi.window.showInformationMessage(`DevDoctor: ${notice}`);
  }
  return issues;
}

/** Review the install plan with the user and, only on approval, install. */
export async function installDependencies(
  vscodeApi: Vscode,
  engine: EngineApi,
  ctx: HandlerContext
): Promise<{ installed: boolean; remaining: number }> {
  ctx.output.appendLine(`DevDoctor: re-scanning ${ctx.workspacePath} before install ...`);
  const outcome: EngineOutcome = await engine.runDiagnose({
    pythonExecutable: ctx.config.pythonExecutable,
    workspacePath: ctx.workspacePath,
    timeoutMs: ctx.config.timeoutMs,
    runTests: ctx.config.runTests,
  });
  if (!outcome.ok) {
    const message = engineErrorMessage(outcome);
    ctx.output.appendLine(`DevDoctor: ${message}`);
    await vscodeApi.window.showErrorMessage(message);
    return { installed: false, remaining: -1 };
  }
  const issues = outcome.data.dependencies?.issues ?? [];
  const plan = buildInstallPlan(issues);
  if (plan.length === 0) {
    await vscodeApi.window.showInformationMessage(
      "DevDoctor: no installable dependency issues found."
    );
    return { installed: false, remaining: issues.length };
  }
  const detail = plan
    .map((a) => `${a.package}${a.version ? `==${a.version}` : ""} — ${a.reason}`)
    .join("\n");
  const choice = await vscodeApi.window.showWarningMessage(
    `Install ${plan.length} package(s)? ${summarizePlan(plan)}.`,
    { modal: true, detail: `DevDoctor will install:\n${detail}\n\nNo other changes will be made.` },
    "Install",
    "Cancel"
  );
  if (choice !== "Install") {
    ctx.output.appendLine("DevDoctor: installation cancelled by user. No changes were made.");
    await vscodeApi.window.showInformationMessage(
      "DevDoctor: installation cancelled. No changes were made."
    );
    return { installed: false, remaining: issues.length };
  }

  // Approval granted: execute the reviewed plan through the engine.
  const planFile = path.join(
    os.tmpdir(),
    `devdoctor-plan-${process.pid}-${Date.now()}.json`
  );
  try {
    fs.writeFileSync(planFile, planFilePayload(plan, "Approved in VS Code"), {
      encoding: "utf-8",
      mode: 0o600,
    });
  } catch (error) {
    const message = `DevDoctor: could not write install plan: ${String(error)}`;
    ctx.output.appendLine(message);
    await vscodeApi.window.showErrorMessage(message);
    return { installed: false, remaining: issues.length };
  }
  let repair: RepairOutcome;
  try {
    ctx.output.appendLine(`DevDoctor: installing ${summarizePlan(plan)} ...`);
    repair = await engine.runRepair({
      pythonExecutable: ctx.config.pythonExecutable,
      workspacePath: ctx.workspacePath,
      planFile,
      timeoutMs: ctx.config.timeoutMs,
      maxCycles: 1,
    });
  } finally {
    try {
      fs.unlinkSync(planFile);
    } catch {
      // Plan file cleanup is best-effort; it contains no secrets.
    }
  }
  if (!repair.ok) {
    const message = engineErrorMessage(repair);
    ctx.output.appendLine(`DevDoctor: ${message}`);
    await vscodeApi.window.showErrorMessage(message);
    return { installed: false, remaining: issues.length };
  }
  const report = repair.data;
  if (report.status !== "success") {
    const message =
      `DevDoctor: installation did not verify ` +
      `(status: ${report.status}). Check the Output panel; ` +
      `rollback ${report.rollback_performed ? "was performed" : "was not needed"}.`;
    ctx.output.appendLine(message);
    ctx.output.appendLine(JSON.stringify(report.verification ?? {}, null, 2));
    await vscodeApi.window.showWarningMessage(message);
    await checkDependencies(vscodeApi, engine, { ...ctx });
    return { installed: false, remaining: -1 };
  }

  // Verification: re-scan and compare.
  const verify = await engine.runDiagnose({
    pythonExecutable: ctx.config.pythonExecutable,
    workspacePath: ctx.workspacePath,
    timeoutMs: ctx.config.timeoutMs,
    runTests: ctx.config.runTests,
  });
  if (verify.ok) {
    const remaining = (verify.data.dependencies?.issues ?? []).filter((i) =>
      ACTIONABLE_KINDS.has(i.kind)
    );
    syncDiagnostics(
      vscodeApi,
      ctx.diagnostics,
      ctx.workspacePath,
      toProblemEntries(
        verify.data.dependencies?.issues ?? [],
        verify.data.project.files_present ?? {}
      )
    );
    if (remaining.length === 0) {
      const message =
        `${plan.length} dependencies installed successfully. ` +
        `All required dependencies are now satisfied.`;
      ctx.output.appendLine(`DevDoctor: ${message}`);
      await vscodeApi.window.showInformationMessage(`DevDoctor: ${message}`);
    } else {
      const message =
        `DevDoctor: installed ${plan.length} package(s), but ` +
        `${remaining.length} issue(s) remain. See the Problems panel.`;
      ctx.output.appendLine(`DevDoctor: ${message}`);
      await vscodeApi.window.showWarningMessage(message);
    }
    return { installed: true, remaining: remaining.length };
  }
  ctx.output.appendLine("DevDoctor: install ran, but verification re-scan failed.");
  await vscodeApi.window.showWarningMessage(
    "DevDoctor: install ran, but verification re-scan failed. Check the Output panel."
  );
  return { installed: true, remaining: -1 };
}

function firstWorkspacePath(vscodeApi: Vscode): string | null {
  const folders = vscodeApi.workspace.workspaceFolders;
  if (!folders || folders.length === 0) {
    return null;
  }
  return folders[0].uri.fsPath;
}

export function activate(context: vscode.ExtensionContext): void {
  const vscodeApi = getVscode();
  const output = vscodeApi.window.createOutputChannel("DevDoctor");
  const diagnostics = vscodeApi.languages.createDiagnosticCollection("devdoctor");
  const engine: EngineApi = { runDiagnose: defaultRunDiagnose, runRepair: defaultRunRepair };

  const makeContext = (): HandlerContext | null => {
    const workspacePath = firstWorkspacePath(vscodeApi);
    if (!workspacePath) {
      void vscodeApi.window.showInformationMessage(
        "DevDoctor: open a folder to check dependencies."
      );
      return null;
    }
    return { workspacePath, output, diagnostics, config: readConfig(vscodeApi) };
  };

  context.subscriptions.push(
    vscodeApi.commands.registerCommand("devdoctor.checkDependencies", () => {
      const ctx = makeContext();
      if (ctx) {
        void checkDependencies(vscodeApi, engine, ctx).catch((error: unknown) => {
          output.appendLine(`DevDoctor: unexpected error: ${String(error)}`);
        });
      }
    }),
    vscodeApi.commands.registerCommand("devdoctor.installDependencies", () => {
      const ctx = makeContext();
      if (ctx) {
        void installDependencies(vscodeApi, engine, ctx).catch((error: unknown) => {
          output.appendLine(`DevDoctor: unexpected error: ${String(error)}`);
        });
      }
    }),
    vscodeApi.commands.registerCommand("devdoctor.showOutput", () => {
      output.show();
    }),
    output,
    diagnostics
  );

  // Automatic read-only dependency check on startup (never installs).
  const startup = makeContext();
  if (startup && startup.config.autoCheckOnOpen) {
    void checkDependencies(vscodeApi, engine, startup).catch((error: unknown) => {
      output.appendLine(`DevDoctor: startup check failed: ${String(error)}`);
    });
  }
}

export function deactivate(): void {
  // Nothing to clean up: diagnostics/output are disposed via subscriptions.
}
