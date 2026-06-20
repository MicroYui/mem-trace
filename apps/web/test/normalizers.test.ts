import { describe, expect, test } from "bun:test";
import { ForbiddenError, NotFoundError, RateLimitedError } from "@memtrace/sdk";
import type { DashboardTables } from "@memtrace/sdk";
import { classifyRequestError, normalizeDashboardTables, normalizeMetricNumber } from "../src/api/normalizers";

const dashboard: DashboardTables = {
  runs: [
    {
      run_id: "run_1",
      workspace_id: "ws_1",
      session_id: "session_1",
      task: "Recover from npm failure",
      status: "completed",
      started_at: "2026-06-17T00:00:00Z",
      finished_at: "2026-06-17T00:01:00Z",
      metadata: {},
      created_at: "2026-06-17T00:00:00Z",
      updated_at: "2026-06-17T00:01:00Z",
    },
  ],
  accesses: [
    {
      access_id: "acc_1",
      workspace_id: "ws_1",
      run_id: "run_1",
      step_id: "step_1",
      query: "Which package manager?",
      task_intent: null,
      retrieval_strategy: "variant_2",
      candidate_count: 4,
      accepted_count: 2,
      rejected_count: 2,
      token_budget: 400,
      top_k: 8,
      actual_tokens: 120,
      latency_ms: 9,
      policy_version: "retrieval-policy-v2",
      policy_hash: "hash",
      policy_snapshot: {},
      created_at: "2026-06-17T00:01:00Z",
    },
  ],
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
  observability_summary: {
    workspace_id: "ws_1",
    run_id: null,
    access_count: 1,
    candidate_count: 4,
    accepted_count: 2,
    rejected_count: 2,
    failed_branch_rejected: 1,
    failed_branch_injected: 0,
    degraded_negative_evidence_count: 1,
    sanitized_failure_notice_count: 1,
    negative_evidence_block_count: 1,
    retained_negative_evidence_count: 1,
    sanitized_retained_negative_evidence_count: 1,
    stale_rejected: 0,
    stale_injected: 0,
    tool_sensitive_blocked: 0,
    destructive_command_blocked: 0,
    risk_blocked: 1,
    workspace_mismatch_rejected: 0,
    workspace_leakage: 0,
    superseded_injected: 0,
    avg_latency_ms: 9,
    avg_actual_tokens: 120,
    compaction_trigger_rate: 0.25,
    avg_compression_ratio: 0.75,
    total_dropped_blocks: 2,
    history_summary_count: 1,
    by_strategy: {
      variant_2: { accepted_count: 2, rejected_count: 2 },
    },
  },
  benchmark_summary: {
    variant_2: { task_success_rate: 1, positive_contamination_rate: 0 },
    baseline_1: { task_success_rate: 0.5 },
  },
};

describe("dashboard normalizers", () => {
  test("converts live dashboard DTOs into explicit view-model states", () => {
    const model = normalizeDashboardTables(dashboard);

    expect(model.workspaceIds).toEqual(["ws_1"]);
    expect(model.metrics.accesses).toEqual({ kind: "available", value: 1, label: "Accesses" });
    expect(model.metrics.compactionEvents).toEqual({ kind: "available", value: 1, label: "Compaction" });
    expect(model.recentRuns[0]?.eventCount.kind).toBe("unavailable");
    expect(model.runGallery[0]?.latestAccess?.accessId).toBe("acc_1");
    expect(model.runGallery[0]?.dominantStrategy?.strategy).toBe("variant_2");
    expect(model.safetySignals.map((signal) => signal.id)).toContain("failed_branch_rejected");
    expect(model.compactionSignals.map((signal) => signal.id)).toEqual([
      "history_summary_count",
      "total_dropped_blocks",
      "compaction_trigger_rate",
      "avg_compression_ratio",
    ]);
    expect(model.negativeEvidenceSignals.map((signal) => signal.id)).toEqual([
      "degraded_negative_evidence_count",
      "negative_evidence_block_count",
      "retained_negative_evidence_count",
      "sanitized_failure_notice_count",
      "sanitized_retained_negative_evidence_count",
    ]);
    expect(model.benchmarkStrategies.map((strategy) => strategy.strategy)).toEqual(["baseline_1", "variant_2"]);
    expect(model.benchmarkStrategies[0]?.metrics.positive_contamination_rate?.kind).toBe("unavailable");
    expect(model.opsCapability.kind).toBe("owner_only_unavailable");
  });

  test("never converts missing numeric metrics into zero", () => {
    expect(normalizeMetricNumber(undefined, "Unsafe leakage")).toEqual({
      kind: "unavailable",
      label: "Unsafe leakage",
      reason: "not provided",
    });
  });

  test("maps SDK and network errors to user-facing request states", () => {
    expect(classifyRequestError(new ForbiddenError("missing API key", errorOptions(401)))).toEqual({
      kind: "unauthorized",
      message: "missing API key",
    });
    expect(classifyRequestError(new ForbiddenError("owner credentials required", errorOptions(403)))).toEqual({
      kind: "forbidden",
      message: "owner credentials required",
    });
    expect(classifyRequestError(new NotFoundError("run not found", errorOptions(404)))).toEqual({
      kind: "not_found",
      message: "run not found",
    });
    expect(classifyRequestError(new RateLimitedError("quota exceeded", errorOptions(429)))).toEqual({
      kind: "quota_limited",
      message: "quota exceeded",
    });
    expect(classifyRequestError(new TypeError("fetch failed"))).toEqual({
      kind: "connection_failed",
      message: "fetch failed",
    });
  });
});

function errorOptions(status: number) {
  return { status, code: String(status), responseBody: { detail: "test" } };
}
