/**
 * Accessor for the VS Code API.
 *
 * Production code calls getVscode(), which requires the real `vscode`
 * module (only present in the Extension Host). Tests inject a mock via
 * setVscode(), so no module-loader hooks are needed.
 */
import type * as vscode from "vscode";

let impl: typeof vscode | null = null;

export function setVscode(mock: typeof vscode): void {
  impl = mock;
}

export function getVscode(): typeof vscode {
  if (impl) {
    return impl;
  }
  // Only reachable inside the Extension Host.
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  return require("vscode") as typeof vscode;
}
