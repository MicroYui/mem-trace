import { describe, expect, test } from "bun:test";
import { BadRequestError, ForbiddenError, MemTraceError, NotFoundError, RateLimitedError } from "../src/errors";
import { MemTraceClient } from "../src/client";
import { createMockFetch, textResponse, jsonResponse } from "./test-utils";

describe("HTTP error mapping", () => {
  test("maps FastAPI detail to BadRequestError", async () => {
    const fetch = createMockFetch([jsonResponse({ detail: "workspace mismatch" }, { status: 400 })]);
    const client = new MemTraceClient({ baseUrl: "http://api", fetch });

    try {
      await client.getTimeline("run_1");
      throw new Error("expected request to fail");
    } catch (error) {
      expect(error).toBeInstanceOf(BadRequestError);
      expect((error as Error).message).toBe("workspace mismatch");
    }
  });

  test("maps FastAPI validation detail arrays to BadRequestError", async () => {
    const fetch = createMockFetch([
      jsonResponse({ detail: [{ msg: "Field required", loc: ["query", "workspace_id"] }] }, { status: 422 }),
      jsonResponse({ detail: [{ msg: "Field required", loc: ["query", "workspace_id"] }] }, { status: 422 }),
    ]);
    const client = new MemTraceClient({ baseUrl: "http://api", fetch });

    await expect(client.dashboardTables()).rejects.toThrow(BadRequestError);
    await expect(client.dashboardTables()).rejects.toThrow("Field required");
  });

  test("maps 401 and 403 to ForbiddenError with detail message", async () => {
    const fetch = createMockFetch([
      jsonResponse({ detail: "missing API key" }, { status: 401 }),
      jsonResponse({ detail: "workspace_id required" }, { status: 403 }),
    ]);
    const client = new MemTraceClient({ baseUrl: "http://api", fetch });

    await expect(client.listMemories()).rejects.toThrow(ForbiddenError);
    await expect(client.dashboardTables()).rejects.toThrow("workspace_id required");
  });

  test("maps 404 and 429 to dedicated errors", async () => {
    const fetch = createMockFetch([
      jsonResponse({ message: "run not found" }, { status: 404 }),
      jsonResponse({ error: "quota exceeded" }, { status: 429 }),
    ]);
    const client = new MemTraceClient({ baseUrl: "http://api", fetch });

    await expect(client.replayRun("missing")).rejects.toThrow(NotFoundError);
    await expect(client.writeEvent({ run_id: "run_1", step_id: "step_1" })).rejects.toThrow(RateLimitedError);
  });

  test("uses non-JSON body text before status fallback", async () => {
    const fetch = createMockFetch([textResponse("upstream exploded", { status: 502, statusText: "Bad Gateway" })]);
    const client = new MemTraceClient({ baseUrl: "http://api", fetch });

    try {
      await client.inspectAccess("acc_1");
      throw new Error("expected request to fail");
    } catch (error) {
      expect(error).toBeInstanceOf(MemTraceError);
      expect((error as Error).message).toBe("upstream exploded");
    }
  });
});
