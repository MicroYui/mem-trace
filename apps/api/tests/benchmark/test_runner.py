"""P1 benchmark runner tests."""
from __future__ import annotations

import json

from app.benchmark.evaluator import CaseMetrics, contaminated, decide_action, evaluate_case
from app.benchmark.runner import _acceptance, _summarize, run_benchmark
from app.runtime.models import (
    CompactionKind,
    CompactionProvider,
    ContextBlock,
    ContextCompactionLog,
    MemoryContext,
    RetainedFact,
    RetrievalStrategy,
)
from app.runtime.repository import InMemoryRepository


async def test_run_benchmark_writes_markdown_and_json_reports(tmp_path):
    report = await run_benchmark(output_dir=tmp_path)

    assert len(report["cases"]) == 11
    assert {c["case_id"] for c in report["cases"]} == {
        "case_1_project_preference",
        "case_2_failed_branch",
        "case_3_workspace_isolation",
        "case_4_tool_safety",
        "case_5_explicit_correction",
        "case_6_completed_run_reuse",
        "case_7_stale_rejection",
        "case_8_no_memory_baseline",
        "case_9_over_budget_compaction",
        "case_10_avoid_repeating_failed_attempt",
        "case_11_sanitized_failed_destructive_attempt",
    }
    assert len(report["results"]) == 44  # 11 cases x 4 strategies

    json_path = tmp_path / "benchmark_results.json"
    md_path = tmp_path / "benchmark_report.md"
    assert json_path.exists()
    assert md_path.exists()

    saved = json.loads(json_path.read_text())
    assert saved["summary"]["variant_2"]["cross_workspace_leakage_rate"] == 0
    assert saved["summary"]["variant_2"]["tool_sensitive_blocked_rate"] == 1
    assert saved["summary"]["variant_2"]["compaction_trigger_rate"] > 0
    assert saved["summary"]["variant_2"]["constraint_retention_hit_rate"] == 1
    assert saved["summary"]["variant_2"]["unsafe_compaction_leakage_rate"] == 0
    assert saved["summary"]["variant_2"]["avg_compression_ratio"] > 0
    assert saved["summary"]["variant_2"]["positive_contamination_rate"] == 0
    assert saved["summary"]["variant_2"]["negative_lesson_retained_rate"] == 1
    assert saved["summary"]["variant_2"]["correct_action_rate"] == 1
    assert saved["summary"]["variant_2"]["unsafe_negative_leakage_rate"] == 0
    assert saved["summary"]["variant_2"]["sanitized_notice_rate"] == 1
    assert (
        saved["summary"]["variant_2"]["failed_branch_contamination_rate"]
        < saved["summary"]["baseline_1"]["failed_branch_contamination_rate"]
    )
    assert "failed_branch_contamination_rate" in md_path.read_text()


async def test_run_benchmark_meets_mvp_acceptance(tmp_path):
    report = await run_benchmark(output_dir=tmp_path)
    acc = report["acceptance"]
    assert acc["passed"] is True
    assert acc["checks"]["variant_2_contamination_below_baseline_1"] is True
    assert acc["checks"]["variant_2_zero_cross_workspace_leakage"] is True
    assert acc["checks"]["variant_2_blocks_tool_sensitive"] is True
    assert acc["checks"]["variant_2_reuses_procedural_memory"] is True
    assert acc["checks"]["variant_2_excludes_superseded_memory"] is True
    assert acc["checks"]["variant_2_excludes_stale_memory"] is True
    assert acc["checks"]["variant_2_succeeds_where_no_memory_baseline_fails"] is True
    assert acc["checks"]["variant_2_retains_constraints_under_compaction"] is True
    assert acc["checks"]["variant_2_learns_from_failure_without_repeating"] is True
    assert acc["checks"]["variant_2_sanitizes_destructive_failure_without_leakage"] is True


async def test_run_benchmark_persists_cases_and_results(tmp_path):
    repo = InMemoryRepository()

    await run_benchmark(output_dir=tmp_path, repo=repo)

    cases = await repo.list_benchmark_cases()
    results = await repo.list_benchmark_results()
    assert len(cases) == 11
    assert len(results) == 44
    assert {r.strategy for r in results} == {"baseline_0", "baseline_1", "variant_1", "variant_2"}
    assert any(
        r.case_id == "case_4_tool_safety" and r.strategy == "variant_2"
        and r.metrics["tool_sensitive_blocked"] == 1
        for r in results
    )
    assert any(
        r.case_id == "case_9_over_budget_compaction" and r.strategy == "variant_2"
        and r.metrics["constraint_retention_hit"] == 1
        and r.metrics["unsafe_compaction_leakage"] == 0
        for r in results
    )
    assert any(
        r.case_id == "case_10_avoid_repeating_failed_attempt" and r.strategy == "variant_2"
        and r.metrics["positive_contamination"] == 0
        and r.metrics["negative_lesson_retained"] == 1
        and r.metrics["correct_action"] == 1
        for r in results
    )
    assert any(
        r.case_id == "case_10_avoid_repeating_failed_attempt" and r.strategy == "variant_1"
        and r.metrics["negative_lesson_retained"] == 0
        for r in results
    )
    assert any(
        r.case_id == "case_11_sanitized_failed_destructive_attempt" and r.strategy == "variant_2"
        and r.metrics["unsafe_negative_leakage"] == 0
        and r.metrics["sanitized_notice_present"] == 1
        for r in results
    )


def test_evaluator_keeps_negative_evidence_out_of_positive_contamination_and_action():
    ctx = MemoryContext(
        access_id="acc_failure_learning",
        context_blocks=[
            ContextBlock(type="project_memory", content="This project uses Bun."),
            ContextBlock(
                type="avoided_attempts",
                source="negative_evidence",
                content="AVOIDED — a previous attempt failed; do NOT re-execute: npm test failed.",
            ),
        ],
        profile={},
        warnings=[],
    )

    assert contaminated(ctx) is False
    assert decide_action(ctx) == "bun test"

    metrics = evaluate_case(
        case_id="case_10_avoid_repeating_failed_attempt",
        strategy=RetrievalStrategy.variant_2,
        ctx=ctx,
        access=None,
        profile_events=[],
        negative_lesson_markers=["npm"],
        failure_learning_case=True,
    )

    assert metrics.positive_contamination == 0
    assert metrics.negative_lesson_retained == 1
    assert metrics.correct_action == 1


def test_evaluator_scores_sanitized_negative_notice_without_raw_marker_leakage():
    ctx = MemoryContext(
        access_id="acc_sanitized_failure",
        context_blocks=[
            ContextBlock(
                type="avoided_attempts",
                source="negative_evidence",
                content="A previous failed attempt involved a destructive operation and has been redacted. Do not repeat destructive operations of this kind.",
            ),
        ],
        profile={},
        warnings=[],
    )

    metrics = evaluate_case(
        case_id="case_11_sanitized_failed_destructive_attempt",
        strategy=RetrievalStrategy.variant_2,
        ctx=ctx,
        access=None,
        profile_events=[],
        unsafe_negative_markers=["rm -rf", "--force", "git push --force"],
        sanitized_failure_case=True,
    )

    assert metrics.unsafe_negative_leakage == 0
    assert metrics.sanitized_notice_present == 1


def test_compaction_retention_metric_uses_durable_log_facts_when_context_is_truncated():
    ctx = MemoryContext(
        access_id="acc_eval",
        context_blocks=[ContextBlock(type="project_memory", content="This project uses Bun.")],
        warnings=["context budget exceeded: omitted 2 blocks"],
        profile={},
    )
    logs = [
        ContextCompactionLog(
            access_id="acc_eval",
            workspace_id="ws_eval",
            kind=CompactionKind.budget_notice,
            provider=CompactionProvider.rule,
            pre_tokens=40,
            post_tokens=10,
            dropped_block_count=2,
            compression_ratio=0.25,
            retained_facts=[
                RetainedFact(key="project.database", value="postgres"),
                RetainedFact(key="endpoint.current", value="/v2/users"),
            ],
        )
    ]

    metrics = evaluate_case(
        case_id="case_9_over_budget_compaction",
        strategy=RetrievalStrategy.variant_2,
        ctx=ctx,
        access=None,
        profile_events=[],
        compaction_positive_constraints=[
            "project.runtime=bun",
            "project.database=postgres",
            "endpoint.current=/v2/users",
        ],
        unsafe_compaction_markers=["secret_token"],
        compaction_logs=logs,
    )

    assert metrics.constraint_retention_hit == 1
    assert metrics.compaction_triggered == 1
    assert metrics.compression_ratio == 0.25


def test_compaction_acceptance_requires_triggered_compaction():
    summary = {
        "baseline_0": {"task_success_rate": 0.0},
        "baseline_1": {"failed_branch_contamination_rate": 1.0, "stale_memory_injection_rate": 1.0},
        "variant_2": {
            "failed_branch_contamination_rate": 0.0,
            "cross_workspace_leakage_rate": 0.0,
            "tool_sensitive_blocked_rate": 1.0,
            "procedural_reuse_hit_rate": 1.0,
            "superseded_injection_rate": 0.0,
            "stale_memory_injection_rate": 0.0,
            "task_success_rate": 1.0,
            "compaction_trigger_rate": 0.0,
            "constraint_retention_hit_rate": 1.0,
            "unsafe_compaction_leakage_rate": 0.0,
        },
    }

    acceptance = _acceptance(summary, results=[])

    assert acceptance["checks"]["variant_2_retains_constraints_under_compaction"] is False
    assert acceptance["passed"] is False


def test_acceptance_requires_present_rows_for_failure_learning_checks():
    summary = {
        "baseline_1": {"failed_branch_contamination_rate": 1.0, "stale_memory_injection_rate": 1.0},
        "variant_2": {
            "failed_branch_contamination_rate": 0.0,
            "cross_workspace_leakage_rate": 0.0,
            "tool_sensitive_blocked_rate": 1.0,
            "procedural_reuse_hit_rate": 1.0,
            "superseded_injection_rate": 0.0,
            "stale_memory_injection_rate": 0.0,
            "compaction_trigger_rate": 1.0,
            "constraint_retention_hit_rate": 1.0,
            "unsafe_compaction_leakage_rate": 0.0,
            # These rates look passing, but without case_10/case_11 rows they
            # must not satisfy acceptance.
            "positive_contamination_rate": 0.0,
            "negative_lesson_retained_rate": 1.0,
            "correct_action_rate": 1.0,
            "unsafe_negative_leakage_rate": 0.0,
            "sanitized_notice_rate": 1.0,
        },
    }
    results = [
        CaseMetrics(case_id="case_8_no_memory_baseline", strategy="baseline_0", task_success=0),
        CaseMetrics(case_id="case_8_no_memory_baseline", strategy="variant_2", task_success=1),
        CaseMetrics(case_id="case_3_workspace_isolation", strategy="variant_2", cross_workspace_leakage=0, cross_workspace_leakage_present=1),
        CaseMetrics(case_id="case_4_tool_safety", strategy="variant_2", tool_sensitive_blocked=1, tool_sensitive_present=1),
        CaseMetrics(case_id="case_6_completed_run_reuse", strategy="variant_2", procedural_reuse_hit=1, procedural_reuse_present=1),
        CaseMetrics(case_id="case_5_explicit_correction", strategy="variant_2", superseded_injection=0, superseded_injection_present=1),
        CaseMetrics(case_id="case_7_stale_rejection", strategy="baseline_1", stale_memory_injection=1, stale_memory_injection_present=1),
        CaseMetrics(case_id="case_7_stale_rejection", strategy="variant_2", stale_memory_injection=0, stale_memory_injection_present=1),
        CaseMetrics(case_id="case_9_over_budget_compaction", strategy="variant_2", compaction_triggered=1, compaction_triggered_present=1, constraint_retention_hit=1, constraint_retention_hit_present=1, unsafe_compaction_leakage=0, unsafe_compaction_leakage_present=1),
    ]

    acceptance = _acceptance(summary, results=results)

    assert acceptance["checks"]["variant_2_learns_from_failure_without_repeating"] is False
    assert acceptance["checks"]["variant_2_sanitizes_destructive_failure_without_leakage"] is False
    assert acceptance["passed"] is False


def test_acceptance_requires_present_rows_for_zero_leakage_checks():
    summary = {
        "baseline_1": {"failed_branch_contamination_rate": 1.0, "stale_memory_injection_rate": 1.0},
        "variant_2": {
            "failed_branch_contamination_rate": 0.0,
            "cross_workspace_leakage_rate": 0.0,
            "tool_sensitive_blocked_rate": 1.0,
            "procedural_reuse_hit_rate": 1.0,
            "superseded_injection_rate": 0.0,
            "stale_memory_injection_rate": 0.0,
            "compaction_trigger_rate": 1.0,
            "constraint_retention_hit_rate": 1.0,
            "unsafe_compaction_leakage_rate": 0.0,
            "positive_contamination_rate": 0.0,
            "negative_lesson_retained_rate": 1.0,
            "correct_action_rate": 1.0,
            "unsafe_negative_leakage_rate": 0.0,
            "sanitized_notice_rate": 1.0,
        },
    }
    results = [
        CaseMetrics(case_id="case_8_no_memory_baseline", strategy="baseline_0", task_success=0),
        CaseMetrics(case_id="case_8_no_memory_baseline", strategy="variant_2", task_success=1),
        # Deliberately omit case_3 cross_workspace_leakage_present row while
        # summary says the leakage rate is zero.
        CaseMetrics(case_id="case_4_tool_safety", strategy="variant_2", tool_sensitive_blocked=1, tool_sensitive_present=1),
        CaseMetrics(case_id="case_6_completed_run_reuse", strategy="variant_2", procedural_reuse_hit=1, procedural_reuse_present=1),
        CaseMetrics(case_id="case_5_explicit_correction", strategy="variant_2", superseded_injection=0, superseded_injection_present=1),
        CaseMetrics(case_id="case_7_stale_rejection", strategy="baseline_1", stale_memory_injection=1, stale_memory_injection_present=1),
        CaseMetrics(case_id="case_7_stale_rejection", strategy="variant_2", stale_memory_injection=0, stale_memory_injection_present=1),
        CaseMetrics(case_id="case_9_over_budget_compaction", strategy="variant_2", compaction_triggered=1, compaction_triggered_present=1, constraint_retention_hit=1, constraint_retention_hit_present=1, unsafe_compaction_leakage=0, unsafe_compaction_leakage_present=1),
        CaseMetrics(case_id="case_10_avoid_repeating_failed_attempt", strategy="variant_2", positive_contamination=0, positive_contamination_present=1, negative_lesson_retained=1, negative_lesson_retained_present=1, correct_action=1, correct_action_present=1),
        CaseMetrics(case_id="case_11_sanitized_failed_destructive_attempt", strategy="variant_2", unsafe_negative_leakage=0, unsafe_negative_leakage_present=1, sanitized_notice_present=1, sanitized_notice_present_present=1),
    ]

    acceptance = _acceptance(summary, results=results)

    assert acceptance["checks"]["variant_2_zero_cross_workspace_leakage"] is False
    assert acceptance["passed"] is False


def test_no_memory_acceptance_is_case_8_specific():
    summary = {
        "baseline_0": {"task_success_rate": 0.1},
        "baseline_1": {"failed_branch_contamination_rate": 1.0, "stale_memory_injection_rate": 1.0},
        "variant_2": {
            "failed_branch_contamination_rate": 0.0,
            "cross_workspace_leakage_rate": 0.0,
            "tool_sensitive_blocked_rate": 1.0,
            "procedural_reuse_hit_rate": 1.0,
            "superseded_injection_rate": 0.0,
            "stale_memory_injection_rate": 0.0,
            "task_success_rate": 0.9,
            "compaction_trigger_rate": 1.0,
            "constraint_retention_hit_rate": 1.0,
            "unsafe_compaction_leakage_rate": 0.0,
        },
    }
    results = [
        CaseMetrics(case_id="case_8_no_memory_baseline", strategy="baseline_0", task_success=1),
        CaseMetrics(case_id="case_8_no_memory_baseline", strategy="variant_2", task_success=0),
    ]

    acceptance = _acceptance(summary, results=results)

    assert acceptance["checks"]["variant_2_succeeds_where_no_memory_baseline_fails"] is False
    assert acceptance["passed"] is False


def test_cross_workspace_summary_is_present_gated():
    rows = [
        CaseMetrics(case_id="case_3_workspace_isolation", strategy="variant_2", cross_workspace_leakage=1, cross_workspace_leakage_present=1),
        CaseMetrics(case_id="case_1_project_preference", strategy="variant_2", cross_workspace_leakage=0, cross_workspace_leakage_present=0),
    ]

    summary = _summarize(rows)

    assert summary["variant_2"]["cross_workspace_leakage_rate"] == 1.0
