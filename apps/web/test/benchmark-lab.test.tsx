import { describe, expect, test } from "bun:test";
import { renderToStaticMarkup } from "react-dom/server";
import type { DashboardTables } from "@memtrace/sdk";
import { normalizeBenchmarkLab } from "../src/api/normalizers";
import { App } from "../src/App";
import { BenchmarkLabPageContent } from "../src/features/benchmark/BenchmarkLabPage";
import { showcaseFixture } from "../src/fixtures/showcase";

describe("WEB-G benchmark lab", () => {
  test("normalizes returned cases across all six strategies without inferring missing rows", () => {
    const view = normalizeBenchmarkLab(benchmarkDashboard, "fixture");

    expect(view.caseCount).toBe(3);
    expect(view.strategyIds).toEqual([
      "baseline_0",
      "long_context",
      "baseline_1",
      "variant_1",
      "variant_2",
      "variant_3",
    ]);
    expect(view.cases.map((caseRow) => caseRow.caseId)).toEqual([
      "case_1_project_preference",
      "case_10_avoid_repeating_failed_attempt",
      "case_12_reflection_retention",
    ]);
    const firstCase = view.cases[0];
    if (firstCase === undefined) throw new Error("expected first benchmark case");
    expect(firstCase.cells.variant_2?.state).toBe("passed");
    expect(firstCase.cells.variant_3?.state).toBe("not_run");
    expect(firstCase.cells.variant_3?.metric.kind).toBe("unavailable");
    expect(view.caseDrawer.caseId).toBe("case_1_project_preference");
    expect(view.caseDrawer.links).toEqual([
      { href: "/runs/run_case_1_v2", label: "Open run" },
      { href: "/access/acc_case_1_v2", label: "Replay access" },
    ]);
  });

  test("preserves explicit metric semantics and comparator-unavailable states", () => {
    const missingComparator = normalizeBenchmarkLab(withoutLongContextRows(benchmarkDashboard), "fixture");

    expect(missingComparator.contamination.baseline?.metric.kind).toBe("available");
    expect(missingComparator.contamination.variantTwo?.metric.kind).toBe("available");
    expect(missingComparator.tokenBloat.state).toBe("comparator_unavailable");
    expect(missingComparator.tokenBloat.longContext.kind).toBe("unavailable");
    expect(missingComparator.reflectionRetention.metric.kind).toBe("available");
    expect(missingComparator.negativeEvidence.promptBlocks.metric.kind).toBe("available");
    expect(missingComparator.negativeEvidence.retainedMetadata.metric.kind).toBe("available");
    expect(missingComparator.compaction.retainedNegativeUnsafeLeakage.metric.kind).toBe("available");
  });

  test("renders matrix, panels, and detail links from normalized view models", () => {
    const view = normalizeBenchmarkLab(withoutLongContextRows(benchmarkDashboard), "fixture");
    const html = renderToStaticMarkup(<BenchmarkLabPageContent view={view} />);

    expect(html).toContain("Benchmark Lab");
    expect(html).toContain("3 cases returned");
    expect(html).toContain("No memory baseline");
    expect(html).toContain("Long-context");
    expect(html).toContain("State-aware + gate");
    expect(html).toContain("Gate + reflection signal");
    expect(html).toContain("Positive contamination");
    expect(html).toContain("Long-context token bloat");
    expect(html).toContain("Reflection retention");
    expect(html).toContain("Compaction retention");
    expect(html).toContain("Negative evidence retention");
    expect(html).toContain("Comparator unavailable");
    expect(html).toContain("/access/acc_case_1_v2");
    expect(html).not.toContain("Missing metric: 0");
  });

  test("loads the fixture-backed benchmark lab from a direct route", () => {
    const html = renderToStaticMarkup(
      <App initialMode="fixture" initialPath="/benchmark" />,
    );

    expect(html).toContain("Benchmark Lab");
    expect(html).toContain("Fixture mode");
    expect(html).toContain("case_13_compaction_retains_negative_lesson");
    expect(html).toContain(`${showcaseFixture.dashboard.eval_cases.length} cases returned`);
  });
});

const benchmarkDashboard: DashboardTables = {
  runs: [],
  accesses: [],
  profile_events: [],
  benchmark_cases: [
    {
      case_id: "case_1_project_preference",
      name: "Project preference persistence",
      description: "Bun project preference should survive retrieval.",
      config: { strategies: ["baseline_0", "long_context", "baseline_1", "variant_1", "variant_2", "variant_3"] },
      created_at: "2026-06-20T00:00:00Z",
    },
    {
      case_id: "case_10_avoid_repeating_failed_attempt",
      name: "Avoid repeating failed attempt",
      description: "Safe failure should appear only as negative evidence.",
      config: { strategies: ["baseline_1", "variant_2"] },
      created_at: "2026-06-20T00:00:00Z",
    },
  ],
  benchmark_results: [
    {
      result_id: "bench_case_1_base",
      case_id: "case_1_project_preference",
      strategy: "baseline_1",
      metrics: {
        task_success: 0,
        positive_contamination: 1,
        positive_contamination_present: 1,
        actual_tokens: 96,
      },
      created_at: "2026-06-20T00:00:00Z",
    },
    {
      result_id: "bench_case_1_v2",
      case_id: "case_1_project_preference",
      strategy: "variant_2",
      metrics: {
        task_success: 1,
        positive_contamination: 0,
        positive_contamination_present: 1,
        negative_lesson_retained: 1,
        negative_lesson_retained_present: 1,
        actual_tokens: 120,
      },
      created_at: "2026-06-20T00:00:00Z",
    },
    {
      result_id: "bench_case_12_v3",
      case_id: "case_12_reflection_retention",
      strategy: "variant_3",
      metrics: {
        task_success: 1,
        reflection_retention_hit: 1,
        reflection_retention_hit_present: 1,
        actual_tokens: 118,
      },
      created_at: "2026-06-20T00:00:00Z",
    },
    {
      result_id: "bench_case_1_long",
      case_id: "case_1_project_preference",
      strategy: "long_context",
      metrics: {
        task_success: 1,
        actual_tokens: 410,
      },
      created_at: "2026-06-20T00:00:00Z",
    },
  ],
  eval_cases: [
    {
      eval_case_id: "case_10_avoid_repeating_failed_attempt",
      name: "Avoid repeating failed attempt",
      description: "Safe failed attempt becomes warning-only negative evidence.",
      tags: ["benchmark", "negative-evidence"],
      config: { strategies: ["baseline_1", "variant_2"] },
      created_at: "2026-06-20T00:00:00Z",
    },
    {
      eval_case_id: "case_12_reflection_retention",
      name: "Reflection-lite retention",
      description: "Variant 3 keeps the critical reflection marker.",
      tags: ["benchmark", "reflection"],
      config: { strategies: ["variant_2", "variant_3"] },
      created_at: "2026-06-20T00:00:00Z",
    },
  ],
  eval_runs: [
    {
      eval_run_id: "evalrun_1",
      name: "deterministic_benchmark",
      workspace_id: "ws_showcase",
      status: "completed",
      config: {},
      started_at: "2026-06-20T00:00:00Z",
      finished_at: "2026-06-20T00:01:00Z",
      created_at: "2026-06-20T00:00:00Z",
    },
  ],
  eval_results: [
    {
      eval_result_id: "evalres_case_1_v2",
      eval_run_id: "evalrun_1",
      eval_case_id: "case_1_project_preference",
      run_id: "run_case_1_v2",
      access_id: "acc_case_1_v2",
      strategy: "variant_2",
      metrics: {
        task_success: 1,
        compaction_triggered: 1,
        compaction_triggered_present: 1,
        constraint_retention_hit: 1,
        constraint_retention_hit_present: 1,
        unsafe_compaction_leakage: 0,
        unsafe_compaction_leakage_present: 1,
        compression_ratio: 0.62,
        compression_ratio_present: 1,
        retained_negative_evidence_count: 1,
        retained_negative_evidence_count_present: 1,
        compaction_negative_lesson_retained: 1,
        compaction_negative_lesson_retained_present: 1,
        compaction_retained_negative_unsafe_leakage: 0,
        compaction_retained_negative_unsafe_leakage_present: 1,
      },
      passed: true,
      created_at: "2026-06-20T00:00:00Z",
    },
  ],
  memory_versions: [],
  memory_conflicts: [],
  maintenance_runs: [],
  maintenance_task_attempts: [],
  admin_action_audits: [],
  quota_limits: [],
  benchmark_summary: {
    baseline_1: {
      task_success_rate: 0.5,
      positive_contamination_rate: 0.25,
      avg_memory_token_overhead: 96,
    },
    long_context: {
      task_success_rate: 1,
      avg_memory_token_overhead: 410,
    },
    variant_2: {
      task_success_rate: 1,
      positive_contamination_rate: 0,
      negative_lesson_retained_rate: 1,
      avg_memory_token_overhead: 120,
      compaction_trigger_rate: 1,
      constraint_retention_hit_rate: 1,
      unsafe_compaction_leakage_rate: 0,
      compaction_negative_lesson_retained_rate: 1,
      compaction_retained_negative_unsafe_leakage_rate: 0,
      avg_retained_negative_evidence_count: 1,
    },
    variant_3: {
      task_success_rate: 1,
      reflection_retention_hit_rate: 1,
      avg_memory_token_overhead: 118,
    },
  },
};

function withoutLongContextRows(dashboard: DashboardTables): DashboardTables {
  return {
    ...dashboard,
    benchmark_results: dashboard.benchmark_results.filter((row) => (
      (row as { strategy?: string }).strategy !== "long_context"
    )),
    eval_results: dashboard.eval_results.filter((row) => (
      (row as { strategy?: string }).strategy !== "long_context"
    )),
  };
}
