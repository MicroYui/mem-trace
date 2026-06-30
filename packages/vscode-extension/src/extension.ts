// MemTrace VS Code extension (ROADMAP §6, thin layer over /v1).
//
// This extension does NOT reimplement any MemTrace runtime semantics. It is a
// thin client that calls the MemTrace HTTP API through `@memtrace/sdk` and shows
// the results in VS Code. All memory / state-tree / gate / replay behavior lives
// in the Python runtime; the editor only renders what `/v1` returns.
//
// The `vscode` module is provided by the editor host at activation time, so this
// file is excluded from the workspace `tsc` typecheck (it requires `@types/vscode`
// and a VS Code runtime). The package-shape test validates the manifest instead.

import * as vscode from "vscode";
import { MemTraceClient } from "@memtrace/sdk";

function makeClient(): MemTraceClient {
  const config = vscode.workspace.getConfiguration("memtrace");
  const baseUrl = config.get<string>("baseUrl") ?? "http://localhost:8000";
  // Prefer the environment for secrets; fall back to settings.
  const apiKey = process.env.MEMTRACE_API_KEY || config.get<string>("apiKey") || undefined;
  return new MemTraceClient({ baseUrl, apiKey });
}

async function prompt(message: string): Promise<string | undefined> {
  return vscode.window.showInputBox({ prompt: message });
}

export function activate(context: vscode.ExtensionContext): void {
  const output = vscode.window.createOutputChannel("MemTrace");

  const retrieveContext = vscode.commands.registerCommand("memtrace.retrieveContext", async () => {
    const runId = await prompt("MemTrace run id");
    if (!runId) return;
    const query = (await prompt("Query / task intent")) ?? "";
    try {
      const ctx = await makeClient().retrieveContext({ runId, query });
      output.clear();
      output.appendLine(`# Context for run ${runId}`);
      output.appendLine(JSON.stringify(ctx, null, 2));
      output.show(true);
    } catch (err) {
      vscode.window.showErrorMessage(`MemTrace retrieve failed: ${String(err)}`);
    }
  });

  const showRunTimeline = vscode.commands.registerCommand("memtrace.showRunTimeline", async () => {
    const runId = await prompt("MemTrace run id");
    if (!runId) return;
    try {
      const events = await makeClient().getTimeline(runId);
      output.clear();
      output.appendLine(`# Timeline for run ${runId} (${events.length} events)`);
      for (const e of events) {
        output.appendLine(JSON.stringify(e));
      }
      output.show(true);
    } catch (err) {
      vscode.window.showErrorMessage(`MemTrace timeline failed: ${String(err)}`);
    }
  });

  const inspectAccess = vscode.commands.registerCommand("memtrace.inspectAccess", async () => {
    const accessId = await prompt("MemTrace access id");
    if (!accessId) return;
    try {
      const inspection = await makeClient().inspectAccess(accessId);
      output.clear();
      output.appendLine(`# Access inspection ${accessId}`);
      output.appendLine(JSON.stringify(inspection, null, 2));
      output.show(true);
    } catch (err) {
      vscode.window.showErrorMessage(`MemTrace inspect failed: ${String(err)}`);
    }
  });

  context.subscriptions.push(retrieveContext, showRunTimeline, inspectAccess, output);
}

export function deactivate(): void {
  // no-op: the SDK client holds no persistent resources.
}
