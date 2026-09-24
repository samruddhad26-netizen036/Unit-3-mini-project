import { describe, it } from "node:test";
import assert from "node:assert";
import { partitionEcosystems, unsupportedNotice } from "../ecosystems";
import type { EcosystemInfo } from "../engine";

function entry(id: string, supported: boolean, manifests: string[] = []): EcosystemInfo {
  return {
    ecosystem_id: id,
    display_name: id,
    manifests_found: manifests,
    supported,
    message: "",
  };
}

describe("partitionEcosystems", () => {
  it("splits supported from unsupported", () => {
    const { supported, unsupported } = partitionEcosystems([
      entry("python", true, ["requirements.txt"]),
      entry("javascript", false, ["package.json"]),
      entry("go", false, ["go.mod"]),
    ]);
    assert.deepStrictEqual(
      supported.map((e) => e.ecosystem_id),
      ["python"]
    );
    assert.deepStrictEqual(
      unsupported.map((e) => e.ecosystem_id),
      ["javascript", "go"]
    );
  });
  it("treats missing data as empty", () => {
    assert.deepStrictEqual(partitionEcosystems(undefined), { supported: [], unsupported: [] });
    assert.deepStrictEqual(partitionEcosystems(null), { supported: [], unsupported: [] });
    assert.deepStrictEqual(partitionEcosystems([]), { supported: [], unsupported: [] });
  });
});

describe("unsupportedNotice", () => {
  it("returns null when everything is supported", () => {
    assert.strictEqual(unsupportedNotice([]), null);
  });
  it("names each unsupported ecosystem with its manifests", () => {
    const notice = unsupportedNotice([
      entry("JavaScript/TypeScript", false, ["package.json"]),
      entry("Go", false, ["go.mod"]),
    ]);
    assert.ok(notice?.includes("JavaScript/TypeScript"));
    assert.ok(notice?.includes("package.json"));
    assert.ok(notice?.includes("Go"));
    assert.ok(notice?.includes("not"));
  });
});
