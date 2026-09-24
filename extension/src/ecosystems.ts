/**
 * Multi-ecosystem helpers (Phase 9).
 *
 * The engine reports every detected ecosystem; only some have adapters.
 * These pure helpers split supported from unsupported so the UI can show
 * each group separately. Python keeps the normal workflow; anything else
 * gets a clear informational message and no install flow.
 */

import type { EcosystemInfo } from "./engine";

export interface EcosystemPartition {
  supported: EcosystemInfo[];
  unsupported: EcosystemInfo[];
}

export function partitionEcosystems(
  list: EcosystemInfo[] | null | undefined
): EcosystemPartition {
  const supported: EcosystemInfo[] = [];
  const unsupported: EcosystemInfo[] = [];
  for (const entry of list ?? []) {
    if (entry.supported) {
      supported.push(entry);
    } else {
      unsupported.push(entry);
    }
  }
  return { supported, unsupported };
}

/** Informational notice for unsupported ecosystems, or null when none. */
export function unsupportedNotice(unsupported: EcosystemInfo[]): string | null {
  if (unsupported.length === 0) {
    return null;
  }
  const parts = unsupported.map((entry) => {
    const manifests = entry.manifests_found.join(", ");
    return `${entry.display_name}${manifests ? ` (${manifests})` : ""}`;
  });
  return (
    `Detected ${parts.join("; ")} — DevDoctor analyzes Python only, ` +
    `so these ecosystems are reported but not installed from.`
  );
}
