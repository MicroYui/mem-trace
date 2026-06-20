import type { MemTraceClient } from "@memtrace/sdk";
import type { ListMemoriesParams, ListMemoryConflictsParams, ObservabilitySummaryParams } from "@memtrace/sdk";
import { useQuery } from "@tanstack/react-query";
import { showcaseFixture } from "../fixtures/showcase";
import { validateShowcaseFixture } from "../fixtures/validation";
import {
  classifyRequestError,
  normalizeAccessReplay,
  normalizeBenchmarkLab,
  normalizeDashboardTables,
  normalizeMemoryAtlas,
  normalizeOpsReadOnly,
  normalizeRunExplorer,
} from "./normalizers";
import type {
  AccessReplayResult,
  BenchmarkLabResult,
  DashboardMode,
  DashboardOverviewResult,
  MemoryAtlasResult,
  OpsReadOnlyResult,
  RequestState,
  RunExplorerResult,
} from "./viewModels";

export const dashboardQueryKeys = {
  dashboardTables: (workspaceId: string | undefined) => ["dashboard-tables", workspaceId ?? "all"] as const,
  observabilitySummary: (params: ObservabilitySummaryParams) => [
    "observability-summary",
    params.workspaceId ?? "all",
    params.runId ?? "all",
  ] as const,
  runTimeline: (runId: string | undefined) => ["run-timeline", runId ?? "missing"] as const,
  stateTree: (runId: string | undefined) => ["state-tree", runId ?? "missing"] as const,
  runSteps: (runId: string | undefined) => ["run-steps", runId ?? "missing"] as const,
  runProfile: (runId: string | undefined) => ["run-profile", runId ?? "missing"] as const,
  accessInspection: (accessId: string | undefined) => ["access-inspection", accessId ?? "missing"] as const,
  replayAccess: (accessId: string | undefined) => ["replay-access", accessId ?? "missing"] as const,
  replayRun: (runId: string | undefined) => ["replay-run", runId ?? "missing"] as const,
  memories: (params: ListMemoriesParams) => [
    "memories",
    params.workspaceId ?? "all",
    params.runId ?? "all",
  ] as const,
  memoryVersions: (memoryId: string | undefined) => ["memory-versions", memoryId ?? "missing"] as const,
  memoryConflicts: (params: ListMemoryConflictsParams) => [
    "memory-conflicts",
    params.workspaceId,
    params.memoryId ?? "all",
    params.status ?? "all",
  ] as const,
};

export interface UseDashboardOverviewArgs {
  client: MemTraceClient;
  mode: DashboardMode;
  workspaceId?: string | undefined;
}

export function useDashboardOverview({
  client,
  mode,
  workspaceId,
}: UseDashboardOverviewArgs): DashboardOverviewResult {
  const query = useQuery({
    enabled: mode === "live",
    queryKey: dashboardQueryKeys.dashboardTables(workspaceId),
    queryFn: () => client.dashboardTables(workspaceId),
  });

  if (mode === "fixture") {
    const fixture = validateShowcaseFixture(showcaseFixture);
    return {
      data: normalizeDashboardTables(fixture.dashboard, "fixture"),
      requestState: { kind: "success", message: "Fixture mode" },
      source: "fixture",
    };
  }

  if (query.isLoading) {
    return { requestState: { kind: "loading", message: "Loading dashboard tables" }, source: "live" };
  }
  if (query.isError) {
    return {
      requestState: classifyRequestError(query.error),
      source: "live",
      error: query.error instanceof Error ? query.error : new Error("Unknown request failure"),
    };
  }
  if (query.data !== undefined) {
    const state: RequestState = query.isStale
      ? { kind: "stale", message: "Showing stale live data" }
      : { kind: "success", message: "Live API connected" };
    return {
      data: normalizeDashboardTables(query.data, "live"),
      requestState: state,
      source: "live",
    };
  }

  return { requestState: { kind: "idle", message: "Connect to a MemTrace API" }, source: "live" };
}

export function useBenchmarkLab({
  client,
  mode,
  workspaceId,
}: UseDashboardOverviewArgs): BenchmarkLabResult {
  const query = useQuery({
    enabled: mode === "live",
    queryKey: dashboardQueryKeys.dashboardTables(workspaceId),
    queryFn: () => client.dashboardTables(workspaceId),
  });

  if (mode === "fixture") {
    const fixture = validateShowcaseFixture(showcaseFixture);
    return {
      data: normalizeBenchmarkLab(fixture.dashboard, "fixture"),
      requestState: { kind: "success", message: "Fixture mode" },
      source: "fixture",
    };
  }

  if (query.isLoading) {
    return { requestState: { kind: "loading", message: "Loading benchmark rows" }, source: "live" };
  }
  if (query.isError) {
    return {
      requestState: classifyRequestError(query.error),
      source: "live",
      error: query.error instanceof Error ? query.error : new Error("Unknown request failure"),
    };
  }
  if (query.data !== undefined) {
    const state: RequestState = query.isStale
      ? { kind: "stale", message: "Showing stale live data" }
      : { kind: "success", message: "Live API connected" };
    return {
      data: normalizeBenchmarkLab(query.data, "live"),
      requestState: state,
      source: "live",
    };
  }

  return { requestState: { kind: "idle", message: "Benchmark rows are unavailable" }, source: "live" };
}

export function useDashboardTablesQuery(client: MemTraceClient, workspaceId?: string | undefined) {
  return useQuery({
    queryKey: dashboardQueryKeys.dashboardTables(workspaceId),
    queryFn: () => client.dashboardTables(workspaceId),
  });
}

interface RouteQueryOptions {
  enabled?: boolean;
}

export function useObservabilitySummaryQuery(client: MemTraceClient, params: ObservabilitySummaryParams = {}) {
  return useQuery({
    queryKey: dashboardQueryKeys.observabilitySummary(params),
    queryFn: () => client.observabilitySummary(params),
  });
}

export function useRunTimelineQuery(client: MemTraceClient, runId?: string | undefined, options: RouteQueryOptions = {}) {
  return useQuery({
    enabled: (options.enabled ?? true) && hasId(runId),
    queryKey: dashboardQueryKeys.runTimeline(runId),
    queryFn: () => client.getTimeline(requireId(runId, "runId")),
  });
}

export function useStateTreeQuery(client: MemTraceClient, runId?: string | undefined, options: RouteQueryOptions = {}) {
  return useQuery({
    enabled: (options.enabled ?? true) && hasId(runId),
    queryKey: dashboardQueryKeys.stateTree(runId),
    queryFn: () => client.getStateTree(requireId(runId, "runId")),
  });
}

export function useRunStepsQuery(client: MemTraceClient, runId?: string | undefined, options: RouteQueryOptions = {}) {
  return useQuery({
    enabled: (options.enabled ?? true) && hasId(runId),
    queryKey: dashboardQueryKeys.runSteps(runId),
    queryFn: () => client.getSteps(requireId(runId, "runId")),
  });
}

export function useRunProfileQuery(client: MemTraceClient, runId?: string | undefined, options: RouteQueryOptions = {}) {
  return useQuery({
    enabled: (options.enabled ?? true) && hasId(runId),
    queryKey: dashboardQueryKeys.runProfile(runId),
    queryFn: () => client.getProfile(requireId(runId, "runId")),
  });
}

export function useAccessInspectionQuery(client: MemTraceClient, accessId?: string | undefined, options: RouteQueryOptions = {}) {
  return useQuery({
    enabled: (options.enabled ?? true) && hasId(accessId),
    queryKey: dashboardQueryKeys.accessInspection(accessId),
    queryFn: () => client.inspectAccess(requireId(accessId, "accessId")),
  });
}

export function useReplayAccessQuery(client: MemTraceClient, accessId?: string | undefined, options: RouteQueryOptions = {}) {
  return useQuery({
    enabled: (options.enabled ?? true) && hasId(accessId),
    queryKey: dashboardQueryKeys.replayAccess(accessId),
    queryFn: () => client.replayAccess(requireId(accessId, "accessId")),
  });
}

export function useRunReplayQuery(client: MemTraceClient, runId?: string | undefined) {
  return useQuery({
    enabled: hasId(runId),
    queryKey: dashboardQueryKeys.replayRun(runId),
    queryFn: () => client.replayRun(requireId(runId, "runId")),
  });
}

export function useMemoriesQuery(client: MemTraceClient, params: ListMemoriesParams = {}) {
  return useQuery({
    queryKey: dashboardQueryKeys.memories(params),
    queryFn: () => client.listMemories(params),
  });
}

export function useMemoryVersionsQuery(client: MemTraceClient, memoryId?: string | undefined) {
  return useQuery({
    enabled: hasId(memoryId),
    queryKey: dashboardQueryKeys.memoryVersions(memoryId),
    queryFn: () => client.listMemoryVersions(requireId(memoryId, "memoryId")),
  });
}

export function useMemoryConflictsQuery(client: MemTraceClient, params: ListMemoryConflictsParams) {
  return useQuery({
    queryKey: dashboardQueryKeys.memoryConflicts(params),
    queryFn: () => client.listMemoryConflicts(params),
  });
}

export interface UseRunExplorerArgs {
  client: MemTraceClient;
  mode: DashboardMode;
  runId?: string | undefined;
}

export function useRunExplorer({
  client,
  mode,
  runId,
}: UseRunExplorerArgs): RunExplorerResult {
  const liveEnabled = mode === "live";
  const timeline = useRunTimelineQuery(client, runId, { enabled: liveEnabled });
  const stateTree = useStateTreeQuery(client, runId, { enabled: liveEnabled });
  const steps = useRunStepsQuery(client, runId, { enabled: liveEnabled });
  const profile = useRunProfileQuery(client, runId, { enabled: liveEnabled });

  if (!hasId(runId)) {
    return { requestState: { kind: "not_found", message: "Run id is required" }, source: mode };
  }

  if (mode === "fixture") {
    validateShowcaseFixture(showcaseFixture);
    const route = showcaseFixture.routes.runs[runId];
    if (route === undefined) {
      return { requestState: { kind: "not_found", message: `Fixture run ${runId} was not found` }, source: "fixture" };
    }
    return {
      data: normalizeRunExplorer({
        runId,
        timeline: route.timeline,
        stateTree: route.stateTree,
        steps: route.steps,
        profile: route.profile,
      }),
      requestState: { kind: "success", message: "Fixture mode" },
      source: "fixture",
    };
  }

  const liveQueries = [timeline, stateTree, steps, profile];
  const error = liveQueries.find((query) => query.isError)?.error;
  if (error !== undefined) {
    return {
      requestState: classifyRequestError(error),
      source: "live",
      error: error instanceof Error ? error : new Error("Unknown request failure"),
    };
  }
  if (liveQueries.some((query) => query.isLoading)) {
    return { requestState: { kind: "loading", message: "Loading run evidence" }, source: "live" };
  }
  if (timeline.data !== undefined && stateTree.data !== undefined && steps.data !== undefined && profile.data !== undefined) {
    return {
      data: normalizeRunExplorer({
        runId,
        timeline: timeline.data,
        stateTree: stateTree.data,
        steps: steps.data,
        profile: profile.data,
      }),
      requestState: { kind: "success", message: "Live API connected" },
      source: "live",
    };
  }

  return { requestState: { kind: "idle", message: "Run evidence is unavailable" }, source: "live" };
}

export interface UseAccessReplayArgs {
  client: MemTraceClient;
  mode: DashboardMode;
  accessId?: string | undefined;
}

export function useAccessReplay({
  accessId,
  client,
  mode,
}: UseAccessReplayArgs): AccessReplayResult {
  const liveEnabled = mode === "live";
  const inspection = useAccessInspectionQuery(client, accessId, { enabled: liveEnabled });
  const replay = useReplayAccessQuery(client, accessId, { enabled: liveEnabled });

  if (!hasId(accessId)) {
    return { requestState: { kind: "not_found", message: "Access id is required" }, source: mode };
  }

  if (mode === "fixture") {
    validateShowcaseFixture(showcaseFixture);
    const route = showcaseFixture.routes.accesses[accessId];
    if (route === undefined) {
      return { requestState: { kind: "not_found", message: `Fixture access ${accessId} was not found` }, source: "fixture" };
    }
    return {
      data: normalizeAccessReplay({
        accessId,
        inspection: route.inspection,
        replay: route.replay,
      }),
      requestState: { kind: "success", message: "Fixture mode" },
      source: "fixture",
    };
  }

  const error = inspection.isError ? inspection.error : replay.isError ? replay.error : undefined;
  if (error !== undefined) {
    return {
      requestState: classifyRequestError(error),
      source: "live",
      error: error instanceof Error ? error : new Error("Unknown request failure"),
    };
  }
  if (inspection.isLoading || replay.isLoading) {
    return { requestState: { kind: "loading", message: "Loading access replay" }, source: "live" };
  }
  if (inspection.data !== undefined && replay.data !== undefined) {
    return {
      data: normalizeAccessReplay({
        accessId,
        inspection: inspection.data,
        replay: replay.data,
      }),
      requestState: { kind: "success", message: "Live API connected" },
      source: "live",
    };
  }

  return { requestState: { kind: "idle", message: "Access replay is unavailable" }, source: "live" };
}

export function useMemoryAtlas({
  client,
  mode,
  workspaceId,
}: UseDashboardOverviewArgs): MemoryAtlasResult {
  const memoryParams: ListMemoriesParams = workspaceId === undefined ? {} : { workspaceId };
  const dashboard = useQuery({
    enabled: mode === "live",
    queryKey: dashboardQueryKeys.dashboardTables(workspaceId),
    queryFn: () => client.dashboardTables(workspaceId),
  });
  const memories = useQuery({
    enabled: mode === "live",
    queryKey: dashboardQueryKeys.memories(memoryParams),
    queryFn: () => client.listMemories(memoryParams),
  });

  if (mode === "fixture") {
    const fixture = validateShowcaseFixture(showcaseFixture);
    return {
      data: normalizeMemoryAtlas({
        dashboard: fixture.dashboard,
        memories: showcaseFixture.routes.memories,
        source: "fixture",
      }),
      requestState: { kind: "success", message: "Fixture mode" },
      source: "fixture",
    };
  }

  const error = dashboard.isError ? dashboard.error : memories.isError ? memories.error : undefined;
  if (error !== undefined) {
    return {
      requestState: classifyRequestError(error),
      source: "live",
      error: error instanceof Error ? error : new Error("Unknown request failure"),
    };
  }
  if (dashboard.isLoading || memories.isLoading) {
    return { requestState: { kind: "loading", message: "Loading memory atlas" }, source: "live" };
  }
  if (dashboard.data !== undefined && memories.data !== undefined) {
    return {
      data: normalizeMemoryAtlas({
        dashboard: dashboard.data,
        memories: memories.data,
        source: "live",
      }),
      requestState: { kind: "success", message: "Live API connected" },
      source: "live",
    };
  }

  return { requestState: { kind: "idle", message: "Memory atlas is unavailable" }, source: "live" };
}

export function useOpsReadOnly({
  client,
  mode,
  workspaceId,
}: UseDashboardOverviewArgs): OpsReadOnlyResult {
  const dashboard = useQuery({
    enabled: mode === "live",
    queryKey: dashboardQueryKeys.dashboardTables(workspaceId),
    queryFn: () => client.dashboardTables(workspaceId),
  });

  if (mode === "fixture") {
    const fixture = validateShowcaseFixture(showcaseFixture);
    return {
      data: normalizeOpsReadOnly(fixture.dashboard, "fixture"),
      requestState: { kind: "success", message: "Fixture mode" },
      source: "fixture",
    };
  }

  if (dashboard.isError) {
    return {
      requestState: classifyRequestError(dashboard.error),
      source: "live",
      error: dashboard.error instanceof Error ? dashboard.error : new Error("Unknown request failure"),
    };
  }
  if (dashboard.isLoading) {
    return { requestState: { kind: "loading", message: "Loading operations tables" }, source: "live" };
  }
  if (dashboard.data !== undefined) {
    return {
      data: normalizeOpsReadOnly(dashboard.data, "live"),
      requestState: { kind: "success", message: "Live API connected" },
      source: "live",
    };
  }

  return { requestState: { kind: "idle", message: "Operations tables are unavailable" }, source: "live" };
}

function hasId(value: string | undefined): value is string {
  return value !== undefined && value.length > 0;
}

function requireId(value: string | undefined, label: string): string {
  if (!hasId(value)) {
    throw new Error(`${label} is required`);
  }
  return value;
}
