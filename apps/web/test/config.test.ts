import { describe, expect, test } from "bun:test";
import { createDashboardClient, resolveApiBaseUrl } from "../src/api/client";

describe("dashboard API client boundary", () => {
  test("defaults to same-origin API calls and keeps API keys in Authorization headers", async () => {
    const requests: Array<{ url: string; init: RequestInit }> = [];
    const fetch = (async (input: RequestInfo | URL, init: RequestInit = {}) => {
      requests.push({ url: String(input), init });
      return new Response(JSON.stringify({
        runs: [],
        accesses: [],
        profile_events: [],
        benchmark_cases: [],
        benchmark_results: [],
        eval_cases: [],
        eval_runs: [],
        eval_results: [],
        memory_versions: [],
        memory_conflicts: [],
        benchmark_summary: {},
      }), { headers: { "Content-Type": "application/json" } });
    }) as typeof globalThis.fetch;

    const client = createDashboardClient({ baseUrl: resolveApiBaseUrl(undefined), apiKey: "secret-token", fetch });

    await client.dashboardTables("ws_1");

    expect(requests).toHaveLength(1);
    expect(requests[0]?.url).toBe("/v1/dashboard/tables?workspace_id=ws_1");
    expect(new Headers(requests[0]?.init.headers).get("Authorization")).toBe("Bearer secret-token");
    expect(requests[0]?.url).not.toContain("secret-token");
  });

  test("normalizes configured API origins without accepting embedded credentials", () => {
    expect(resolveApiBaseUrl(" https://api.example.test/ ")).toBe("https://api.example.test");
    expect(resolveApiBaseUrl(" / ")).toBe("");
    expect(resolveApiBaseUrl(" /memtrace/ ")).toBe("/memtrace");
    expect(() => resolveApiBaseUrl("https://user:pass@api.example.test")).toThrow("must not include credentials");
    expect(() => resolveApiBaseUrl("//api.example.test")).toThrow("must not use protocol-relative URLs");
  });
});
