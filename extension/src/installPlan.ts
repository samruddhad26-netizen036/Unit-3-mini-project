/**
 * Deterministic install-plan builder.
 *
 * Pure logic over Phase 3 dependency issues: only problems with a known,
 * declared package become install/upgrade actions. Nothing here executes
 * anything or touches the environment.
 */

import type { DependencyIssue } from "./engine";

export interface PlanAction {
  action: "install_package" | "upgrade_package";
  package: string;
  version: string;
  reason: string;
}

/** Extract an exact pinned version (`==x.y.z`) or "" when not pinnable. */
export function exactPin(constraint: string | null): string {
  if (!constraint) {
    return "";
  }
  const match = /^==([^,]+)$/.exec(constraint.trim());
  if (!match) {
    return "";
  }
  const version = match[1].trim();
  return /^[A-Za-z0-9][A-Za-z0-9._+-]*$/.test(version) ? version : "";
}

/**
 * Build the install plan. Skips kinds that are not safely auto-installable:
 * - imported-not-declared (nothing declared to pin a version from)
 * - possibly-unused (removal is destructive; never auto-proposed)
 */
export function buildInstallPlan(issues: DependencyIssue[]): PlanAction[] {
  const plan: PlanAction[] = [];
  const seen = new Set<string>();
  for (const issue of issues) {
    if (issue.kind !== "missing" &&
        issue.kind !== "declared-not-installed" &&
        issue.kind !== "version-mismatch") {
      continue;
    }
    const key = issue.name.toLowerCase();
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    const version = exactPin(issue.declared);
    plan.push({
      action: issue.kind === "version-mismatch" ? "upgrade_package" : "install_package",
      package: issue.name,
      version,
      reason: issue.detail || issue.kind,
    });
  }
  return plan;
}

/** One-line human summary, e.g. "Install pandas==2.2.3, numpy". */
export function summarizePlan(actions: PlanAction[]): string {
  if (actions.length === 0) {
    return "No packages to install.";
  }
  const parts = actions.map((a) => (a.version ? `${a.package}==${a.version}` : a.package));
  return `Install ${parts.join(", ")}`;
}

/** Serialize the plan to the repair --plan-file format. */
export function planFilePayload(actions: PlanAction[], reasoning: string): string {
  return JSON.stringify(
    {
      actions: actions.map((a) => ({
        action: a.action,
        package: a.package,
        version: a.version,
        reason: a.reason,
      })),
      reasoning,
    },
    null,
    2
  );
}
