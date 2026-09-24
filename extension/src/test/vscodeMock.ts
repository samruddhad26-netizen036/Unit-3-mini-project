/**
 * Minimal in-memory mock of the VS Code API surface used by DevDoctor.
 * Scripted responses let tests drive notification/action flows.
 */

export interface RecordedCall {
  method: string;
  args: unknown[];
}

export interface MockVscode {
  vscode: Record<string, unknown>;
  calls: RecordedCall[];
  respondWith: Map<string, unknown[]>;
  outputLines: string[];
  diagnosticsSet: Array<{ uri: string; messages: string[] }>;
}

class MockUri {
  constructor(public readonly fsPath: string) {}
  static file(p: string): MockUri {
    return new MockUri(p);
  }
  toString(): string {
    return this.fsPath;
  }
}

class MockRange {
  constructor(
    public readonly startLine: number,
    public readonly startChar: number,
    public readonly endLine: number,
    public readonly endChar: number
  ) {}
}

class MockDiagnostic {
  constructor(
    public readonly range: MockRange,
    public readonly message: string,
    public readonly severity: number
  ) {}
}

const DiagnosticSeverity = {
  Error: 0,
  Warning: 1,
  Information: 2,
  Hint: 3,
};

export function createMockVscode(): MockVscode {
  const calls: RecordedCall[] = [];
  const respondWith = new Map<string, unknown[]>();
  const outputLines: string[] = [];
  const diagnosticsSet: Array<{ uri: string; messages: string[] }> = [];

  const take = (method: string): unknown => {
    const queue = respondWith.get(method);
    if (queue && queue.length > 0) {
      return queue.shift();
    }
    return undefined;
  };

  const collection = {
    clear() {
      calls.push({ method: "diagnostics.clear", args: [] });
      diagnosticsSet.length = 0;
    },
    set(uri: MockUri, diags: MockDiagnostic[]) {
      calls.push({ method: "diagnostics.set", args: [uri.fsPath, diags.length] });
      diagnosticsSet.push({ uri: uri.fsPath, messages: diags.map((d) => d.message) });
    },
    dispose() {
      calls.push({ method: "diagnostics.dispose", args: [] });
    },
  };

  const outputChannel = {
    appendLine(line: string) {
      outputLines.push(line);
    },
    show() {
      calls.push({ method: "output.show", args: [] });
    },
    dispose() {
      calls.push({ method: "output.dispose", args: [] });
    },
  };

  const window = {
    showWarningMessage(message: string, ...args: unknown[]) {
      calls.push({ method: "showWarningMessage", args: [message, ...args] });
      return Promise.resolve(take("showWarningMessage"));
    },
    showInformationMessage(message: string, ...args: unknown[]) {
      calls.push({ method: "showInformationMessage", args: [message, ...args] });
      return Promise.resolve(take("showInformationMessage"));
    },
    showErrorMessage(message: string, ...args: unknown[]) {
      calls.push({ method: "showErrorMessage", args: [message, ...args] });
      return Promise.resolve(take("showErrorMessage"));
    },
    createOutputChannel(_name: string) {
      calls.push({ method: "createOutputChannel", args: [_name] });
      return outputChannel;
    },
  };

  const vscode: Record<string, unknown> = {
    window,
    workspace: {
      workspaceFolders: undefined as unknown,
      getConfiguration(_section: string) {
        return { get: (_key: string, def: unknown) => def };
      },
    },
    languages: {
      createDiagnosticCollection(_name: string) {
        calls.push({ method: "createDiagnosticCollection", args: [_name] });
        return collection;
      },
    },
    commands: {
      registerCommand(id: string, _fn: unknown) {
        calls.push({ method: "registerCommand", args: [id] });
        return { dispose() {} };
      },
    },
    Uri: MockUri,
    Range: MockRange,
    Diagnostic: MockDiagnostic,
    DiagnosticSeverity,
    ExtensionContext: class {},
  };

  return { vscode, calls, respondWith, outputLines, diagnosticsSet };
}
