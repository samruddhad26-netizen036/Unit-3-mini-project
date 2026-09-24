import { describe, it } from "node:test";
import assert from "node:assert";
import { buildInstallPlan, exactPin, planFilePayload, summarizePlan } from "../installPlan";
import type { DependencyIssue } from "../engine";

function issue(kind: string, name: string, declared = "", detail = ""): DependencyIssue {
  return { kind, name, detail: detail || kind, declared, installed: null };
}

describe("exactPin", () => {
  it("extracts exact pins", () => {
    assert.strictEqual(exactPin("==2.2.3"), "2.2.3");
    assert.strictEqual(exactPin(""), "");
    assert.strictEqual(exactPin(null), "");
  });
  it("rejects ranges and wildcards", () => {
    assert.strictEqual(exactPin(">=2.0"), "");
    assert.strictEqual(exactPin(">=2.0,<3"), "");
    assert.strictEqual(exactPin("==2.*"), "");
    assert.strictEqual(exactPin("~=2.2"), "");
  });
});

describe("buildInstallPlan", () => {
  it("plans installs for missing and declared-not-installed", () => {
    const plan = buildInstallPlan([
      issue("missing", "pandas", "==2.2.3", "imported but not installed"),
      issue("declared-not-installed", "numpy", "", "declared but missing"),
    ]);
    assert.strictEqual(plan.length, 2);
    assert.deepStrictEqual(plan[0], {
      action: "install_package",
      package: "pandas",
      version: "2.2.3",
      reason: "imported but not installed",
    });
    assert.strictEqual(plan[1].version, "");
  });
  it("plans upgrades for version mismatches", () => {
    const plan = buildInstallPlan([issue("version-mismatch", "numpy", "==1.26.4")]);
    assert.strictEqual(plan.length, 1);
    assert.strictEqual(plan[0].action, "upgrade_package");
    assert.strictEqual(plan[0].version, "1.26.4");
  });
  it("skips undeclared imports and possibly-unused packages", () => {
    const plan = buildInstallPlan([
      issue("imported-not-declared", "flask"),
      issue("possibly-unused", "requests"),
    ]);
    assert.deepStrictEqual(plan, []);
  });
  it("dedupes repeated packages", () => {
    const plan = buildInstallPlan([
      issue("missing", "Pandas", "==2.2.3"),
      issue("declared-not-installed", "pandas", "==2.2.3"),
    ]);
    assert.strictEqual(plan.length, 1);
  });
});

describe("summarizePlan", () => {
  it("summarizes empty and non-empty plans", () => {
    assert.strictEqual(summarizePlan([]), "No packages to install.");
    assert.strictEqual(
      summarizePlan([
        { action: "install_package", package: "pandas", version: "2.2.3", reason: "x" },
        { action: "install_package", package: "numpy", version: "", reason: "y" },
      ]),
      "Install pandas==2.2.3, numpy"
    );
  });
});

describe("planFilePayload", () => {
  it("serializes to the repair --plan-file format", () => {
    const text = planFilePayload(
      [{ action: "install_package", package: "pandas", version: "2.2.3", reason: "missing" }],
      "Approved in VS Code"
    );
    const parsed = JSON.parse(text) as {
      actions: Array<Record<string, string>>;
      reasoning: string;
    };
    assert.strictEqual(parsed.actions.length, 1);
    assert.strictEqual(parsed.actions[0]["package"], "pandas");
    assert.strictEqual(parsed.reasoning, "Approved in VS Code");
  });
});
