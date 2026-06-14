import { errorFromResponse } from "./errors";
import type {
  AccessInspection,
  AgentEvent,
  AgentRun,
  AgentStep,
  CompleteRunRequest,
  CompleteRunResult,
  DashboardTables,
  FinishStepRequest,
  FinishStepResult,
  FlushResult,
  ListMemoriesParams,
  ListMemoryConflictsParams,
  MemoryConflictRecord,
  MemoryContext,
  MemoryItem,
  MemoryVersionRecord,
  ObservabilityReportRequest,
  ObservabilityReportResult,
  ObservabilitySummary,
  ObservabilitySummaryParams,
  RetrievalRequest,
  RollbackRequest,
  RollbackResult,
  ReplayRetrievalResult,
  RunReplayResult,
  ProfileEvent,
  StartRunRequest,
  StartStepRequest,
  StateNode,
  WriteEventRequest,
  WriteEventResult,
} from "./types";

export type FetchLike = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

export interface MemTraceClientOptions {
  baseUrl: string;
  apiKey?: string;
  fetch?: FetchLike;
}

function trimTrailingSlash(value: string): string {
  return value.replace(/\/+$/, "");
}

function encodePathSegment(value: string): string {
  return encodeURIComponent(value);
}

function appendQuery(path: string, params: Record<string, string | undefined>): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) query.set(key, value);
  }
  const serialized = query.toString();
  return serialized.length > 0 ? `${path}?${serialized}` : path;
}

export class MemTraceClient {
  private readonly baseUrl: string;
  private readonly apiKey: string | undefined;
  private readonly fetchImpl: FetchLike;

  constructor(options: MemTraceClientOptions) {
    this.baseUrl = trimTrailingSlash(options.baseUrl);
    this.apiKey = options.apiKey;
    this.fetchImpl = options.fetch ?? fetch;
  }

  async startRun(req: StartRunRequest): Promise<AgentRun> {
    return this.request("POST", "/v1/runs", req);
  }

  async startStep(req: StartStepRequest): Promise<AgentStep> {
    return this.request("POST", "/v1/steps/start", req);
  }

  async writeEvent(req: WriteEventRequest): Promise<WriteEventResult> {
    return this.request("POST", "/v1/events", req);
  }

  async finishStep(req: FinishStepRequest): Promise<FinishStepResult> {
    return this.request("POST", "/v1/steps/finish", req);
  }

  async rollbackBranch(req: RollbackRequest): Promise<RollbackResult> {
    return this.request("POST", "/v1/branches/rollback", req);
  }

  async completeRun(runId: string, req: CompleteRunRequest = {}): Promise<CompleteRunResult> {
    return this.request("POST", `/v1/runs/${encodePathSegment(runId)}/complete`, req);
  }

  async retrieveContext(req: RetrievalRequest): Promise<MemoryContext> {
    return this.request("POST", "/v1/context/retrieve", req);
  }

  async flushSession(sessionId: string, options: { workspaceId?: string } = {}): Promise<FlushResult> {
    const path = appendQuery("/v1/sessions/flush", { workspace_id: options.workspaceId });
    return this.request("POST", path, { session_id: sessionId });
  }

  async getTimeline(runId: string): Promise<AgentEvent[]> {
    return this.request("GET", `/v1/runs/${encodePathSegment(runId)}/timeline`);
  }

  async getStateTree(runId: string): Promise<StateNode[]> {
    return this.request("GET", `/v1/runs/${encodePathSegment(runId)}/state-tree`);
  }

  async getSteps(runId: string): Promise<AgentStep[]> {
    return this.request("GET", `/v1/runs/${encodePathSegment(runId)}/steps`);
  }

  async getStep(stepId: string): Promise<AgentStep> {
    return this.request("GET", `/v1/steps/${encodePathSegment(stepId)}`);
  }

  async getProfile(runId: string): Promise<ProfileEvent[]> {
    return this.request("GET", `/v1/runs/${encodePathSegment(runId)}/profile`);
  }

  async inspectAccess(accessId: string): Promise<AccessInspection> {
    return this.request("GET", `/v1/access/${encodePathSegment(accessId)}`);
  }

  async replayAccess(accessId: string): Promise<ReplayRetrievalResult> {
    return this.request("GET", `/v1/replay/access/${encodePathSegment(accessId)}`);
  }

  async replayRun(runId: string): Promise<RunReplayResult> {
    return this.request("GET", `/v1/replay/runs/${encodePathSegment(runId)}`);
  }

  async observabilitySummary(params: ObservabilitySummaryParams = {}): Promise<ObservabilitySummary> {
    const path = appendQuery("/v1/observability/summary", {
      workspace_id: params.workspaceId,
      run_id: params.runId,
    });
    return this.request("GET", path);
  }

  async writeObservabilityReport(req: ObservabilityReportRequest): Promise<ObservabilityReportResult> {
    return this.request("POST", "/v1/observability/reports", req);
  }

  async dashboardTables(workspaceId?: string): Promise<DashboardTables> {
    return this.request("GET", appendQuery("/v1/dashboard/tables", { workspace_id: workspaceId }));
  }

  async listMemories(params: ListMemoriesParams = {}): Promise<MemoryItem[]> {
    const path = appendQuery("/v1/memories", {
      run_id: params.runId,
      workspace_id: params.workspaceId,
    });
    return this.request("GET", path);
  }

  async listMemoryVersions(memoryId: string): Promise<MemoryVersionRecord[]> {
    return this.request("GET", `/v1/memories/${encodePathSegment(memoryId)}/versions`);
  }

  async listMemoryConflicts(params: ListMemoryConflictsParams): Promise<MemoryConflictRecord[]> {
    const path = appendQuery("/v1/memory-conflicts", {
      workspace_id: params.workspaceId,
      memory_id: params.memoryId,
      status: params.status,
    });
    return this.request("GET", path);
  }

  private async request<T>(method: string, path: string, body?: unknown): Promise<T> {
    const headers = new Headers({ Accept: "application/json" });
    if (body !== undefined) headers.set("Content-Type", "application/json");
    if (this.apiKey !== undefined && this.apiKey.length > 0) {
      headers.set("Authorization", `Bearer ${this.apiKey}`);
    }

    const init: RequestInit = { method, headers };
    if (body !== undefined) {
      init.body = JSON.stringify(body);
    }

    const response = await this.fetchImpl(`${this.baseUrl}${path}`, init);

    if (!response.ok) {
      throw await errorFromResponse(response);
    }

    if (response.status === 204) {
      return undefined as T;
    }
    return (await response.json()) as T;
  }
}
