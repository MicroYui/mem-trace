import type { FetchLike } from "../src/client";

export interface RecordedRequest {
  url: string;
  init: RequestInit;
  jsonBody: unknown;
}

export function jsonResponse(body: unknown, init: ResponseInit = {}): Response {
  const responseInit: ResponseInit = {
    status: init.status ?? 200,
    headers: { "Content-Type": "application/json", ...(init.headers ?? {}) },
  };
  if (init.statusText !== undefined) {
    responseInit.statusText = init.statusText;
  }
  return new Response(JSON.stringify(body), responseInit);
}

export function textResponse(body: string, init: ResponseInit): Response {
  return new Response(body, init);
}

export function createMockFetch(responses: Response[] | ((request: RecordedRequest) => Response | Promise<Response>)):
  FetchLike & { requests: RecordedRequest[] } {
  const requests: RecordedRequest[] = [];
  const queue = Array.isArray(responses) ? [...responses] : undefined;
  const responder = Array.isArray(responses) ? undefined : responses;
  const fetchImpl = (async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const rawBody = typeof init.body === "string" ? init.body : undefined;
    const request: RecordedRequest = {
      url: String(input),
      init,
      jsonBody: rawBody === undefined ? undefined : JSON.parse(rawBody),
    };
    requests.push(request);
    if (queue !== undefined) {
      const response = queue.shift();
      if (response === undefined) throw new Error("mock fetch response queue exhausted");
      return response;
    }
    if (responder === undefined) {
      throw new Error("mock fetch responder missing");
    }
    return responder(request);
  }) as FetchLike & { requests: RecordedRequest[] };
  fetchImpl.requests = requests;
  return fetchImpl;
}

export const sampleRun = {
  run_id: "run_1",
  workspace_id: "ws_1",
  session_id: "tenant/session",
  task: "demo",
  status: "running",
  started_at: "2026-06-14T00:00:00Z",
  finished_at: null,
  metadata: {},
  created_at: "2026-06-14T00:00:00Z",
  updated_at: "2026-06-14T00:00:00Z",
};

export const sampleStep = {
  step_id: "step_1",
  workspace_id: "ws_1",
  run_id: "run_1",
  parent_step_id: null,
  recovery_from_step_id: null,
  state_node_id: "node_1",
  intent: "setup",
  status: "active",
  started_at: "2026-06-14T00:00:00Z",
  finished_at: null,
  error_message: null,
  metadata: {},
  created_at: "2026-06-14T00:00:00Z",
  updated_at: "2026-06-14T00:00:00Z",
};

export const sampleEvent = {
  event_id: "evt_1",
  workspace_id: "ws_1",
  session_id: "tenant/session",
  run_id: "run_1",
  step_id: "step_1",
  state_node_id: "node_1",
  sequence_no: 1,
  event_source: "ts-sdk",
  visibility: "visible",
  role: "user",
  event_type: "message",
  content: "Use Bun",
  content_digest: null,
  raw_payload_ref: null,
  redaction_status: "none",
  causality_id: null,
  tool_name: null,
  tool_args_digest: null,
  status: null,
  token_input: 0,
  token_output: 0,
  latency_ms: 0,
  metadata: {},
  created_at: "2026-06-14T00:00:00Z",
};
