import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import type { DashboardTables } from "@memtrace/sdk";
import { normalizeDashboardTables } from "../src/api/normalizers";
import type { DashboardOverviewResult } from "../src/api/viewModels";
import { OverviewDashboard } from "../src/components/dashboard/OverviewDashboard";
import { showcaseFixture } from "../src/fixtures/showcase";

describe("WEB-D overview dashboard", () => {
  test("renders the run gallery, safety signals, compaction, and benchmark comparison from view models", () => {
    const overview: DashboardOverviewResult = {
      data: normalizeDashboardTables(showcaseFixture.dashboard, "fixture"),
      requestState: { kind: "success", message: "Fixture mode" },
      source: "fixture",
    };

    const html = renderToStaticMarkup(<OverviewDashboard overview={overview} />);

    expect(html).toContain("Run gallery");
    expect(html).toContain("Safety signals");
    expect(html).toContain("Compaction evidence");
    expect(html).toContain("Negative evidence");
    expect(html).toContain("Token pressure");
    expect(html).toContain("Open run details");
    expect(html).toContain("Recover from failed npm branch and keep Bun constraint");
    expect(html).toContain("State-aware + gate");
    expect(html).toContain("baseline_1");
    expect(html).not.toContain("Unsafe leakage: 0");
  });

  test("renders explicit empty states for a fresh workspace", () => {
    const overview: DashboardOverviewResult = {
      data: normalizeDashboardTables(emptyDashboard, "live"),
      requestState: { kind: "success", message: "Live API connected" },
      source: "live",
    };

    const html = renderToStaticMarkup(<OverviewDashboard overview={overview} />);

    expect(html).toContain("No runs returned");
    expect(html).toContain("No retrieval accesses returned");
  });
});

const emptyDashboard: DashboardTables = {
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
  maintenance_runs: [],
  maintenance_task_attempts: [],
  admin_action_audits: [],
  quota_limits: [],
  benchmark_summary: {},
};
