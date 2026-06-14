import { describe, expect, test } from "bun:test";
import { ForbiddenError, MemTraceClient } from "../src";
import { createMockFetch, jsonResponse, sampleEvent, sampleRun, sampleStep } from "./test-utils";

describe("MemTraceClient core methods", () => {
  test("sends Authorization header and JSON body for core write/retrieve flow", async () => {
    const fetch = createMockFetch([
      jsonResponse(sampleRun),
      jsonResponse(sampleStep),
      jsonResponse({ event: sampleEvent, created_memory_ids: ["mem_1"], buffered: false, queued: true, task_id: "task_1", warnings: [] }),
      jsonResponse({ access_id: "acc_1", query: "Bun", context_blocks: [], warnings: [], profile: {} }),
      jsonResponse({ access_id: "acc_1", query: "Bun", task_intent: null, retrieval_strategy: "variant_2", candidates: [], gate_decisions: [], context_blocks: [], profile: {}, warnings: [], policy_version: null, policy_hash: null, policy_snapshot: {} }),
    ]);
    const client = new MemTraceClient({ baseUrl: "http://api/", apiKey: "test-key", fetch });

    await client.startRun({ session_id: "s1", workspace_id: "ws_1", task: "demo" });
    await client.startStep({ run_id: "run_1", intent: "setup" });
    const writeResult = await client.writeEvent({ run_id: "run_1", step_id: "step_1", role: "user", event_type: "message", content: "Use Bun", extraction_mode: "async" });
    await client.retrieveContext({ run_id: "run_1", query: "Bun", strategy: "variant_2" });
    await client.inspectAccess("acc_1");

    expect(writeResult.queued).toBe(true);
    expect(writeResult.task_id).toBe("task_1");
    expect(fetch.requests.map((request) => new URL(request.url).pathname)).toEqual([
      "/v1/runs",
      "/v1/steps/start",
      "/v1/events",
      "/v1/context/retrieve",
      "/v1/access/acc_1",
    ]);
    for (const request of fetch.requests) {
      expect(new Headers(request.init.headers).get("Authorization")).toBe("Bearer test-key");
    }
    expect(fetch.requests[2]?.jsonBody).toMatchObject({ extraction_mode: "async" });
  });
});

describe("MemTraceClient expanded Phase 4 methods", () => {
  test("uses current paths for lifecycle/read/replay/report/memory APIs", async () => {
    const fetch = createMockFetch(Array.from({ length: 17 }, () => jsonResponse({})));
    const client = new MemTraceClient({ baseUrl: "http://api", fetch });

    await client.finishStep({ run_id: "run_1", step_id: "step_1", status: "completed" });
    await client.rollbackBranch({ run_id: "run_1", step_id: "step_1", reason: "bad branch" });
    await client.completeRun("run/path", { run_id: "ignored", status: "completed" });
    await client.getTimeline("run_1");
    await client.getStateTree("run_1");
    await client.getSteps("run_1");
    await client.getStep("step_1");
    await client.getProfile("run_1");
    await client.flushSession("tenant/session", { workspaceId: "ws_1" });
    await client.replayAccess("acc_1");
    await client.replayRun("run_1");
    await client.observabilitySummary({ workspaceId: "ws_1", runId: "run_1" });
    await client.dashboardTables("ws_1");
    await client.writeObservabilityReport({ workspace_id: "ws_1", output_dir: "reports", include_replay: true });
    await client.listMemories({ workspaceId: "ws_1", runId: "run_1" });
    await client.listMemoryVersions("mem_1");
    await client.listMemoryConflicts({ workspaceId: "ws_1", memoryId: "mem_1", status: "open" });

    const urls = fetch.requests.map((request) => request.url.replace("http://api", ""));
    expect(urls).toEqual([
      "/v1/steps/finish",
      "/v1/branches/rollback",
      "/v1/runs/run%2Fpath/complete",
      "/v1/runs/run_1/timeline",
      "/v1/runs/run_1/state-tree",
      "/v1/runs/run_1/steps",
      "/v1/steps/step_1",
      "/v1/runs/run_1/profile",
      "/v1/sessions/flush?workspace_id=ws_1",
      "/v1/replay/access/acc_1",
      "/v1/replay/runs/run_1",
      "/v1/observability/summary?workspace_id=ws_1&run_id=run_1",
      "/v1/dashboard/tables?workspace_id=ws_1",
      "/v1/observability/reports",
      "/v1/memories?run_id=run_1&workspace_id=ws_1",
      "/v1/memories/mem_1/versions",
      "/v1/memory-conflicts?workspace_id=ws_1&memory_id=mem_1&status=open",
    ]);
    expect(fetch.requests[2]?.jsonBody).toEqual({ run_id: "ignored", status: "completed" });
    expect(fetch.requests[8]?.jsonBody).toEqual({ session_id: "tenant/session" });
  });

  test("maps authorized workspace-wide missing-workspace responses to ForbiddenError", async () => {
    const fetch = createMockFetch([
      jsonResponse({ detail: "workspace_id required" }, { status: 403 }),
      jsonResponse({ detail: "workspace_id required" }, { status: 403 }),
      jsonResponse({ detail: "workspace_id required" }, { status: 403 }),
      jsonResponse({ detail: "workspace_id required for authorized session flush" }, { status: 403 }),
    ]);
    const client = new MemTraceClient({ baseUrl: "http://api", apiKey: "scoped", fetch });

    await expect(client.dashboardTables()).rejects.toThrow(ForbiddenError);
    await expect(client.listMemories()).rejects.toThrow(ForbiddenError);
    await expect(client.observabilitySummary()).rejects.toThrow(ForbiddenError);
    await expect(client.flushSession("tenant/session")).rejects.toThrow("workspace_id required for authorized session flush");
  });
});
