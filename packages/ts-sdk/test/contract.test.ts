import { describe, expect, test } from "bun:test";
import { MemTraceClient } from "../src";
import { createMockFetch, jsonResponse, sampleEvent, sampleRun, sampleStep } from "./test-utils";

describe("mocked cross-language contract smoke", () => {
  test("represents start-run/start-step/write/retrieve/inspect sequence", async () => {
    const fetch = createMockFetch([
      jsonResponse(sampleRun),
      jsonResponse(sampleStep),
      jsonResponse({ event: sampleEvent, created_memory_ids: [], buffered: false, queued: false, task_id: null, warnings: [] }),
      jsonResponse({ access_id: "acc_1", query: "Which runtime?", context_blocks: [{ type: "project_constraint", content: "Use Bun", source: "memory", memory_id: "mem_1", reason: "accepted", provenance: null, tokens: 2 }], warnings: [], profile: {} }),
      jsonResponse({ access_id: "acc_1", query: "Which runtime?", task_intent: null, retrieval_strategy: "variant_2", candidates: [], gate_decisions: [], context_blocks: [], profile: {}, warnings: [], policy_version: null, policy_hash: null, policy_snapshot: {} }),
    ]);
    const client = new MemTraceClient({ baseUrl: "http://api", fetch });

    const run = await client.startRun({ session_id: "session_1", task: "Pick runtime", workspace_id: "ws_1" });
    const step = await client.startStep({ run_id: run.run_id, intent: "setup" });
    const write = await client.writeEvent({ run_id: run.run_id, step_id: step.step_id, role: "user", content: "Use Bun", event_source: "ts-sdk" });
    const context = await client.retrieveContext({ run_id: run.run_id, step_id: step.step_id, query: "Which runtime?" });
    const access = await client.inspectAccess(context.access_id);

    expect(write.event.event_source).toBe("ts-sdk");
    expect(context.context_blocks[0]?.content).toContain("Bun");
    expect(access.access_id).toBe("acc_1");
  });
});

const httpUrl = process.env.MEMTRACE_TEST_HTTP_URL;

if (httpUrl === undefined || httpUrl.length === 0) {
  test.skip("optional real-service smoke requires MEMTRACE_TEST_HTTP_URL", () => {});
} else {
  test("optional real-service smoke can start a run", async () => {
    const options: ConstructorParameters<typeof MemTraceClient>[0] = { baseUrl: httpUrl };
    if (process.env.MEMTRACE_API_KEY !== undefined) {
      options.apiKey = process.env.MEMTRACE_API_KEY;
    }
    const client = new MemTraceClient(options);
    const run = await client.startRun({
      workspace_id: process.env.MEMTRACE_WORKSPACE_ID ?? "default",
      session_id: `ts-sdk-smoke-${Date.now()}`,
      task: "TypeScript SDK real-service smoke",
    });

    expect(run.run_id).toStartWith("run_");
    expect(run.session_id).toStartWith("ts-sdk-smoke-");
  });
}
