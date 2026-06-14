import { describe, expect, test } from "bun:test";
import { fileURLToPath } from "node:url";

import { loadMcpConfig, McpConfigError } from "../src/config";
import { unknownToolResult } from "../src/server";
import { MAX_TOOL_TEXT_CHARS, createMemTraceTools, redactToolText } from "../src/tools";

import type { MemTraceMcpTool, MemTraceToolClient } from "../src/tools";

function toolRecord(client: MemTraceToolClient): Record<string, MemTraceMcpTool> {
  return Object.fromEntries(createMemTraceTools(client).map((tool) => [tool.name, tool])) as Record<string, MemTraceMcpTool>;
}

function getTool(tools: Record<string, MemTraceMcpTool>, name: string): MemTraceMcpTool {
  const tool = tools[name];
  if (tool === undefined) throw new Error(`missing tool ${name}`);
  return tool;
}

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
}

function sourcePath(fileName: string): string {
  return fileURLToPath(new URL(`../src/${fileName}`, import.meta.url));
}

function makeMockClient(): MemTraceToolClient & { calls: Array<{ method: string; args: unknown[] }> } {
  const calls: Array<{ method: string; args: unknown[] }> = [];
  return {
    calls,
    async startRun(req) {
      calls.push({ method: "startRun", args: [req] });
      return {
        run_id: "run-1",
        workspace_id: req.workspace_id ?? "default",
        session_id: req.session_id,
        task: req.task ?? null,
        status: "running",
        started_at: "2026-06-14T00:00:00Z",
        finished_at: null,
        metadata: {},
        created_at: "2026-06-14T00:00:00Z",
        updated_at: "2026-06-14T00:00:00Z",
      };
    },
    async startStep(req) {
      calls.push({ method: "startStep", args: [req] });
      return {
        step_id: "step-1",
        workspace_id: "workspace-1",
        run_id: req.run_id,
        parent_step_id: null,
        recovery_from_step_id: null,
        state_node_id: "node-1",
        intent: req.intent ?? null,
        status: "active",
        started_at: "2026-06-14T00:00:00Z",
        finished_at: null,
        error_message: null,
        metadata: {},
        created_at: "2026-06-14T00:00:00Z",
        updated_at: "2026-06-14T00:00:00Z",
      };
    },
    async writeEvent(req) {
      calls.push({ method: "writeEvent", args: [req] });
      return {
        event: {
          event_id: "event-1",
          workspace_id: "workspace-1",
          session_id: "session-1",
          run_id: req.run_id,
          step_id: req.step_id,
          state_node_id: "node-1",
          sequence_no: 1,
          event_source: "mcp",
          visibility: "normal",
          role: req.role ?? "user",
          event_type: req.event_type ?? "message",
          content: req.content ?? null,
          content_digest: null,
          raw_payload_ref: null,
          redaction_status: "none",
          causality_id: null,
          tool_name: req.tool_name ?? null,
          tool_args_digest: null,
          status: req.status ?? null,
          token_input: req.token_input ?? 0,
          token_output: req.token_output ?? 0,
          latency_ms: req.latency_ms ?? 0,
          metadata: {},
          created_at: "2026-06-14T00:00:00Z",
        },
        created_memory_ids: ["mem-1"],
        buffered: false,
        queued: false,
        task_id: null,
        warnings: [],
      };
    },
    async retrieveContext(req) {
      calls.push({ method: "retrieveContext", args: [req] });
      return {
        access_id: "access-1",
        query: req.query,
        context_blocks: [{ type: "project", content: "Use bun", source: "memory", tokens: 2 }],
        warnings: ["safe warning"],
        profile: { candidate_count: 3 },
      };
    },
    async inspectAccess(accessId) {
      calls.push({ method: "inspectAccess", args: [accessId] });
      return {
        access_id: accessId,
        query: "how to test",
        task_intent: null,
        retrieval_strategy: "variant_2",
        candidates: [],
        gate_decisions: [],
        context_blocks: [],
        profile: {},
        warnings: [],
        policy_version: "retrieval-policy-v2",
        policy_hash: "hash",
        policy_snapshot: {},
      };
    },
    async finishStep(req) {
      calls.push({ method: "finishStep", args: [req] });
      return {
        step: {
          step_id: req.step_id,
          workspace_id: "workspace-1",
          run_id: req.run_id,
          parent_step_id: null,
          recovery_from_step_id: null,
          state_node_id: "node-1",
          intent: null,
          status: req.status ?? "completed",
          started_at: "2026-06-14T00:00:00Z",
          finished_at: "2026-06-14T00:00:01Z",
          error_message: req.error_message ?? null,
          metadata: {},
          created_at: "2026-06-14T00:00:00Z",
          updated_at: "2026-06-14T00:00:01Z",
        },
        state_node: {
          node_id: "node-1",
          workspace_id: "workspace-1",
          run_id: req.run_id,
          parent_id: null,
          step_id: req.step_id,
          node_type: "step",
          status: "completed",
          goal: null,
          summary: req.summary ?? null,
          raw_event_ids: [],
          memory_refs: [],
          branch_reason: {},
          failure_reason: null,
          depth: 1,
          path: "/root/node-1",
          created_at: "2026-06-14T00:00:00Z",
          updated_at: "2026-06-14T00:00:01Z",
        },
        created_memory_ids: ["mem-summary"],
      };
    },
    async replayAccess(accessId) {
      calls.push({ method: "replayAccess", args: [accessId] });
      return {
        access_id: accessId,
        run_id: "run-1",
        step_id: "step-1",
        workspace_id: "workspace-1",
        query: "debug",
        strategy: "variant_2",
        token_budget: 2000,
        top_k: 8,
        original_candidates: [],
        original_gate_decisions: [],
        original_context_blocks_reconstructed: [],
        replayed_candidates: [],
        replayed_gate_decisions: [],
        replayed_context_blocks: [],
        compaction_logs: [],
        diffs: [],
        metrics: { raw: "rm -rf /prod with sk-123 password Authorization raw_payload_ref" },
        warnings: [],
      };
    },
    async writeObservabilityReport(req) {
      calls.push({ method: "writeObservabilityReport", args: [req] });
      return {
        json_path: "reports/observability_report.json",
        markdown_path: "reports/observability_report.md",
        html_path: "reports/observability_report.html",
        summary: {
          workspace_id: req.workspace_id ?? null,
          run_id: req.run_id ?? null,
          access_count: 1,
          candidate_count: 2,
          accepted_count: 1,
          rejected_count: 1,
          failed_branch_rejected: 0,
          failed_branch_injected: 0,
          degraded_negative_evidence_count: 0,
          sanitized_failure_notice_count: 0,
          negative_evidence_block_count: 0,
          retained_negative_evidence_count: 0,
          sanitized_retained_negative_evidence_count: 0,
          stale_rejected: 0,
          stale_injected: 0,
          tool_sensitive_blocked: 0,
          destructive_command_blocked: 0,
          risk_blocked: 0,
          workspace_mismatch_rejected: 0,
          workspace_leakage: 0,
          superseded_injected: 0,
          avg_latency_ms: 1,
          avg_actual_tokens: 2,
          compaction_trigger_rate: 0,
          avg_compression_ratio: 0,
          total_dropped_blocks: 0,
          history_summary_count: 0,
          by_strategy: {},
        },
      };
    },
  };
}

describe("config", () => {
  test("requires MEMTRACE_BASE_URL", () => {
    expect(() => loadMcpConfig({})).toThrow(McpConfigError);
    expect(() => loadMcpConfig({ MEMTRACE_API_KEY: "secret-token" })).toThrow("MEMTRACE_BASE_URL is required");
  });

  test("loads base url and optional api key without logging secrets", () => {
    const config = loadMcpConfig({ MEMTRACE_BASE_URL: " http://127.0.0.1:8000 ", MEMTRACE_API_KEY: " secret-token " });
    expect(config).toEqual({ baseUrl: "http://127.0.0.1:8000", apiKey: "secret-token" });
  });

  test("rejects invalid base url", () => {
    expect(() => loadMcpConfig({ MEMTRACE_BASE_URL: "not a url", MEMTRACE_API_KEY: "sk-real-secret" })).toThrow(
      "MEMTRACE_BASE_URL must be a valid URL",
    );
  });

  test("rejects non-http base urls and embedded credentials", () => {
    expect(() => loadMcpConfig({ MEMTRACE_BASE_URL: "file:///tmp/memtrace.sock" })).toThrow(
      "MEMTRACE_BASE_URL must use http or https",
    );
    expect(() => loadMcpConfig({ MEMTRACE_BASE_URL: "https://user:pass@example.com" })).toThrow(
      "MEMTRACE_BASE_URL must not include credentials",
    );
  });
});

describe("tools", () => {
  test("exposes all INT-B tool schemas", () => {
    const tools = createMemTraceTools(makeMockClient());
    expect(tools.map((tool) => tool.name).sort()).toEqual([
      "memtrace_finish_step",
      "memtrace_inspect_access",
      "memtrace_replay_access",
      "memtrace_report",
      "memtrace_retrieve_context",
      "memtrace_start_run",
      "memtrace_start_step",
      "memtrace_write_event",
    ]);
    for (const tool of tools) {
      expect(tool.description.length).toBeGreaterThan(0);
      expect(tool.inputSchema.type).toBe("object");
      expect(typeof tool.handler).toBe("function");
    }
  });

  test("tools call the matching SDK methods", async () => {
    const client = makeMockClient();
    const tools = toolRecord(client);

    await getTool(tools, "memtrace_start_run").handler({ session_id: "session-1", task: "task", workspace_id: "workspace-1" });
    await getTool(tools, "memtrace_start_step").handler({ run_id: "run-1", intent: "setup" });
    await getTool(tools, "memtrace_write_event").handler({ run_id: "run-1", step_id: "step-1", content: "hello" });
    await getTool(tools, "memtrace_retrieve_context").handler({ run_id: "run-1", step_id: "step-1", query: "test" });
    await getTool(tools, "memtrace_inspect_access").handler({ access_id: "access-1" });
    await getTool(tools, "memtrace_finish_step").handler({ run_id: "run-1", step_id: "step-1", status: "completed" });
    await getTool(tools, "memtrace_replay_access").handler({ access_id: "access-1" });
    await getTool(tools, "memtrace_report").handler({ workspace_id: "workspace-1", include_replay: true });

    expect(client.calls.map((call) => call.method)).toEqual([
      "startRun",
      "startStep",
      "writeEvent",
      "retrieveContext",
      "inspectAccess",
      "finishStep",
      "replayAccess",
      "writeObservabilityReport",
    ]);
  });

  test("tool responses are concise text content", async () => {
    const tools = toolRecord(makeMockClient());
    const result = await getTool(tools, "memtrace_retrieve_context").handler({ run_id: "run-1", query: "how" });
    expect(result.content).toHaveLength(1);
    expect(result.content[0]!.type).toBe("text");
    expect(result.content[0]!.text).toContain("access-1");
    expect(result.content[0]!.text).toContain("blocks=1");
  });

  test("redacts unsafe output markers", async () => {
    const text = redactToolText("Authorization: Bearer sk-abcdef password=hunter2 raw_payload_ref rm -rf /prod");
    expect(text).not.toContain("Authorization");
    expect(text).not.toContain("sk-");
    expect(text).not.toContain("hunter2");
    expect(text).not.toContain("raw_payload_ref");
    expect(text).not.toContain("rm -rf");
    expect(text).not.toContain("/prod");
  });

  test("redacts JSON-style secret-like key values before returning MCP text", async () => {
    const text = redactToolText(JSON.stringify({ password: "hunter2", api_key: "plain-token", nested: { access_token: "tok-123" } }));
    expect(text).not.toContain("hunter2");
    expect(text).not.toContain("plain-token");
    expect(text).not.toContain("tok-123");
    expect(text).toContain("[REDACTED]");
  });

  test("redacts broader JSON and key-value secret names", async () => {
    const jsonText = redactToolText(JSON.stringify({
      authorization: "plain-auth",
      token: "bare-token",
      client_secret: "client-secret-value",
      secret_key: "secret-key-value",
      nested: { id_token: "id-token-value", session_token: "session-token-value" },
      token_budget: 2000,
    }));
    expect(jsonText).not.toContain("plain-auth");
    expect(jsonText).not.toContain("bare-token");
    expect(jsonText).not.toContain("client-secret-value");
    expect(jsonText).not.toContain("secret-key-value");
    expect(jsonText).not.toContain("id-token-value");
    expect(jsonText).not.toContain("session-token-value");
    expect(jsonText).toContain("token_budget");
    expect(jsonText).toContain("2000");

    const text = redactToolText("authorization=plain-auth token=bare-token client_secret=client-secret-value secret_key=secret-key-value");
    expect(text).not.toContain("plain-auth");
    expect(text).not.toContain("bare-token");
    expect(text).not.toContain("client-secret-value");
    expect(text).not.toContain("secret-key-value");
  });

  test("SDK errors are redacted and do not expose API keys", async () => {
    const client = makeMockClient();
    client.startRun = async () => {
      throw new Error("Authorization Bearer sk-real-secret password=hunter2 failed");
    };
    const tools = toolRecord(client);
    const result = await getTool(tools, "memtrace_start_run").handler({ session_id: "session-1" });
    const text = result.content[0]!.text;
    expect(text).toContain("MemTrace tool error");
    expect(text).not.toContain("sk-real-secret");
    expect(text).not.toContain("hunter2");
    expect(text).not.toContain("Authorization");
  });

  test("unknown tool errors are redacted and capped", () => {
    const result = unknownToolResult(`sk-secret password=hunter2 raw_payload_ref rm -rf /prod ${"x".repeat(9000)}`);
    const content = result.content as Array<{ type: "text"; text: string }>;
    const text = content[0]!.text;
    expect(result.isError).toBe(true);
    expect(text.length).toBeLessThanOrEqual(MAX_TOOL_TEXT_CHARS);
    expect(text).not.toContain("sk-secret");
    expect(text).not.toContain("hunter2");
    expect(text).not.toContain("raw_payload_ref");
    expect(text).not.toContain("rm -rf");
    expect(text).not.toContain("/prod");
  });

  test("replay output is capped and sanitized", async () => {
    const client = makeMockClient();
    client.replayAccess = async (accessId) => ({
      access_id: accessId,
      run_id: "run-1",
      step_id: "step-1",
      workspace_id: "workspace-1",
      query: "debug",
      strategy: "variant_2",
      token_budget: 2000,
      top_k: 8,
      original_candidates: [],
      original_gate_decisions: [],
      original_context_blocks_reconstructed: [],
      replayed_candidates: [],
      replayed_gate_decisions: [],
      replayed_context_blocks: [],
      compaction_logs: [],
      diffs: [],
      metrics: { large: "safe ".repeat(3000), unsafe: "rm -rf /prod sk-abcdef password raw_payload_ref Authorization" },
      warnings: [],
    });
    const tools = toolRecord(client);
    const result = await getTool(tools, "memtrace_replay_access").handler({ access_id: "access-1" });
    const text = result.content[0]!.text;
    expect(text.length).toBeLessThanOrEqual(MAX_TOOL_TEXT_CHARS);
    expect(text).toContain("truncated");
    expect(text).not.toContain("rm -rf");
    expect(text).not.toContain("/prod");
    expect(text).not.toContain("sk-");
    expect(text).not.toContain("password");
    expect(text).not.toContain("Authorization");
    expect(text).not.toContain("raw_payload_ref");
  });

  test("report output is capped and summarized", async () => {
    const client = makeMockClient();
    client.writeObservabilityReport = async () => ({
      json_path: "reports/observability_report.json",
      markdown_path: "reports/observability_report.md",
      html_path: "reports/observability_report.html",
      summary: {
        workspace_id: "workspace-1",
        run_id: null,
        access_count: 1,
        candidate_count: 2,
        accepted_count: 1,
        rejected_count: 1,
        failed_branch_rejected: 0,
        failed_branch_injected: 0,
        degraded_negative_evidence_count: 0,
        sanitized_failure_notice_count: 0,
        negative_evidence_block_count: 0,
        retained_negative_evidence_count: 0,
        sanitized_retained_negative_evidence_count: 0,
        stale_rejected: 0,
        stale_injected: 0,
        tool_sensitive_blocked: 0,
        destructive_command_blocked: 0,
        risk_blocked: 0,
        workspace_mismatch_rejected: 0,
        workspace_leakage: 0,
        superseded_injected: 0,
        avg_latency_ms: 1,
        avg_actual_tokens: 2,
        compaction_trigger_rate: 0,
        avg_compression_ratio: 0,
        total_dropped_blocks: 0,
        history_summary_count: 0,
        by_strategy: { unsafe: { marker: 1 } },
        huge: "safe ".repeat(3000),
      },
    });
    const tools = toolRecord(client);
    const result = await getTool(tools, "memtrace_report").handler({ workspace_id: "workspace-1", include_replay: true });
    const text = result.content[0]!.text;
    expect(text.length).toBeLessThanOrEqual(MAX_TOOL_TEXT_CHARS);
    expect(text).toContain("reports/observability_report.json");
    expect(text).toContain("truncated");
  });

  test("MCP source does not import Python runtime or database modules", async () => {
    const sourceFiles = [
      sourcePath("config.ts"),
      sourcePath("tools.ts"),
      sourcePath("server.ts"),
      sourcePath("index.ts"),
    ];
    const forbidden = ["apps/api", "memtrace_sdk", "sqlalchemy", "psycopg", "runtime/memory_runtime", "storage/sql_repository"];
    for (const file of sourceFiles) {
      const content = await Bun.file(file).text();
      for (const marker of forbidden) {
        expect(content).not.toContain(marker);
      }
    }
  });

  test("MCP package imports the TypeScript SDK through the workspace package boundary", async () => {
    const sourceFiles = [sourcePath("tools.ts"), sourcePath("server.ts")];
    for (const file of sourceFiles) {
      const content = await Bun.file(file).text();
      expect(content).toContain("@memtrace/sdk");
      expect(content).not.toContain("../../ts-sdk/src");
    }
  });
});
