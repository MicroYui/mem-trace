import type {
  AccessInspection,
  AgentEvent,
  AgentStep,
  DashboardTables,
  MemoryItem,
  ProfileEvent,
  ReplayRetrievalResult,
  StateNode,
} from "@memtrace/sdk";

export interface ShowcaseFixture {
  fixture_schema_version: 1;
  generated_from: string;
  generated_at: string;
  dashboard: DashboardTables;
  routes: {
    runs: Record<string, ShowcaseRunRouteFixture>;
    accesses: Record<string, ShowcaseAccessRouteFixture>;
    memories: MemoryItem[];
  };
}

export interface ShowcaseRunRouteFixture {
  timeline: AgentEvent[];
  stateTree: StateNode[];
  steps: AgentStep[];
  profile: ProfileEvent[];
}

export interface ShowcaseAccessRouteFixture {
  inspection: AccessInspection;
  replay: ReplayRetrievalResult;
}
