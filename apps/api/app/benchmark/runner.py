"""Deterministic benchmark runner and report writer.

Runs the MVP plus post-MVP regression cases against the same seeded memory
items for each strategy, then emits `benchmark_report.md` and
`benchmark_results.json` artifacts.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.benchmark.cases import ALL_STRATEGIES, CASES, BenchmarkCase
from app.benchmark.evaluator import CaseMetrics, evaluate_case
from app.providers.factory import deterministic_provider_registry
from app.runtime.memory_runtime import MemoryRuntime
from app.runtime.models import (
    BenchmarkCaseRecord,
    BenchmarkResultRecord,
    EvalCaseRecord,
    EvalResultRecord,
    EvalRunRecord,
    MemoryItem,
    RetrievalRequest,
    RetrievalStrategy,
)
from app.runtime.repository import InMemoryRepository, Repository


_METRIC_FIELDS = [
    "task_success",
    "correct_active_path_hit",
    "failed_branch_contamination",
    "stale_memory_injection",
    "cross_workspace_leakage",
    "tool_sensitive_blocked",
    "procedural_reuse_hit",
    "superseded_injection",
    "compaction_triggered",
    "constraint_retention_hit",
    "unsafe_compaction_leakage",
    "compression_ratio",
    "positive_contamination",
    "negative_lesson_retained",
    "correct_action",
    "unsafe_negative_leakage",
    "sanitized_notice_present",
    "reflection_retention_hit",
    "retrieval_latency_ms",
    "gate_latency_ms",
]


def _average(values: list[float]) -> float:
    if not values:
        return 0.0
    return round(sum(values) / len(values), 4)


def _summarize(results: list[CaseMetrics]) -> dict[str, dict[str, float]]:
    summary: dict[str, dict[str, float]] = {}
    for strategy in ALL_STRATEGIES:
        rows = [r for r in results if r.strategy == strategy.value]
        summary[strategy.value] = {
            "task_success_rate": _average([r.task_success for r in rows]),
            "correct_active_path_hit_rate": _average([r.correct_active_path_hit for r in rows]),
            "failed_branch_contamination_rate": _average([r.failed_branch_contamination for r in rows]),
            "stale_memory_injection_rate": _average(
                [r.stale_memory_injection for r in rows if r.stale_memory_injection_present]
            ),
            "cross_workspace_leakage_rate": _average(
                [r.cross_workspace_leakage for r in rows if r.cross_workspace_leakage_present]
            ),
            "tool_sensitive_blocked_rate": _average(
                [r.tool_sensitive_blocked for r in rows if r.tool_sensitive_present]
            ),
            "procedural_reuse_hit_rate": _average(
                [r.procedural_reuse_hit for r in rows if r.procedural_reuse_present]
            ),
            "superseded_injection_rate": _average(
                [r.superseded_injection for r in rows if r.superseded_injection_present]
            ),
            "compaction_trigger_rate": _average(
                [r.compaction_triggered for r in rows if r.compaction_triggered_present]
            ),
            "constraint_retention_hit_rate": _average(
                [r.constraint_retention_hit for r in rows if r.constraint_retention_hit_present]
            ),
            "unsafe_compaction_leakage_rate": _average(
                [r.unsafe_compaction_leakage for r in rows if r.unsafe_compaction_leakage_present]
            ),
            "avg_compression_ratio": _average(
                [r.compression_ratio for r in rows if r.compression_ratio_present]
            ),
            "positive_contamination_rate": _average(
                [r.positive_contamination for r in rows if r.positive_contamination_present]
            ),
            "negative_lesson_retained_rate": _average(
                [r.negative_lesson_retained for r in rows if r.negative_lesson_retained_present]
            ),
            "correct_action_rate": _average(
                [r.correct_action for r in rows if r.correct_action_present]
            ),
            "unsafe_negative_leakage_rate": _average(
                [r.unsafe_negative_leakage for r in rows if r.unsafe_negative_leakage_present]
            ),
            "sanitized_notice_rate": _average(
                [r.sanitized_notice_present for r in rows if r.sanitized_notice_present_present]
            ),
            "reflection_retention_hit_rate": _average(
                [r.reflection_retention_hit for r in rows if r.reflection_retention_hit_present]
            ),
            "avg_retrieval_latency_ms": _average([r.retrieval_latency_ms for r in rows]),
            "avg_gate_latency_ms": _average([r.gate_latency_ms for r in rows]),
            "avg_memory_token_overhead": _average([r.actual_tokens for r in rows]),
        }
    return summary


def _other_workspace_markers(case: BenchmarkCase) -> list[str]:
    if case.case_id == "case_3_workspace_isolation":
        return ["deno"]
    return []


async def _snapshot_workspace_memories(repo: Repository, workspace_id: str) -> dict[str, MemoryItem]:
    """Capture seed-time workspace memories so each strategy sees identical state."""
    return {mem.memory_id: mem.model_copy(deep=True) for mem in await repo.list_memories(workspace_id=workspace_id)}


async def _restore_workspace_memories(repo: Repository, workspace_id: str, snapshot: dict[str, MemoryItem]) -> None:
    """Restore mutable memory fields and reject retrieval-side memory creation."""
    current = {mem.memory_id: mem for mem in await repo.list_memories(workspace_id=workspace_id)}
    created = sorted(set(current) - set(snapshot))
    if created:
        raise RuntimeError(f"memories created during benchmark retrieval: {created}")
    missing = sorted(set(snapshot) - set(current))
    if missing:
        raise RuntimeError(f"memories missing from benchmark workspace snapshot: {missing}")
    for original in snapshot.values():
        await repo.update_memory(original.model_copy(deep=True))


async def _run_case(case: BenchmarkCase, workspace_id: str, repo: Repository | None = None) -> list[CaseMetrics]:
    repo = repo or InMemoryRepository()
    runtime = MemoryRuntime(
        repo,
        default_workspace_id=workspace_id,
        provider_registry=deterministic_provider_registry(),
    )
    seed = await case.seed(runtime, workspace_id)
    memory_snapshot = await _snapshot_workspace_memories(repo, seed.workspace_id)

    metrics: list[CaseMetrics] = []
    for strategy in ALL_STRATEGIES:
        await _restore_workspace_memories(repo, seed.workspace_id, memory_snapshot)
        ctx = await runtime.retrieve_context(
            RetrievalRequest(
                run_id=seed.run_id,
                step_id=seed.step_id,
                query=seed.query,
                strategy=strategy,
                token_budget=seed.extra.get("token_budget"),
                top_k=seed.extra.get("top_k", 10),
            )
        )
        access = await runtime.inspect_access(ctx.access_id)
        profile_events = await runtime.get_profile(seed.run_id)
        compaction_logs = [
            log
            for log in await repo.list_compaction_logs(access_id=ctx.access_id, workspace_id=seed.workspace_id)
            if log.run_id == seed.run_id
        ]
        metrics.append(
            evaluate_case(
                case_id=case.case_id,
                strategy=strategy,
                ctx=ctx,
                access=access,
                profile_events=profile_events,
                other_workspace_markers=_other_workspace_markers(case),
                procedural_reuse_case=(case.case_id == "case_6_completed_run_reuse"),
                correction_case=(case.case_id == "case_5_explicit_correction"),
                stale_markers=seed.extra.get("stale_markers"),
                compaction_positive_constraints=seed.extra.get("compaction_positive_constraints"),
                unsafe_compaction_markers=seed.extra.get("unsafe_compaction_markers"),
                compaction_logs=compaction_logs,
                negative_lesson_markers=seed.extra.get("negative_lesson_markers"),
                unsafe_negative_markers=seed.extra.get("unsafe_negative_markers"),
                failure_learning_case=seed.extra.get("failure_learning_case", False),
                sanitized_failure_case=seed.extra.get("sanitized_failure_case", False),
                reflection_marker=seed.extra.get("reflection_marker"),
                reflection_case=seed.extra.get("reflection_case", False),
            )
        )
    return metrics


async def _persist_results(repo: Repository, results: list[CaseMetrics]) -> None:
    for case in CASES:
        await repo.add_benchmark_case(
            BenchmarkCaseRecord(
                case_id=case.case_id,
                name=case.name,
                description=case.description,
                config={"strategies": [s.value for s in ALL_STRATEGIES]},
            )
        )
    for row in results:
        await repo.add_benchmark_result(
            BenchmarkResultRecord(
                case_id=row.case_id,
                strategy=row.strategy,
                metrics=row.as_dict(),
            )
        )


async def _persist_eval_records(
    repo: Repository,
    results: list[CaseMetrics],
    summary: dict[str, dict[str, float]],
    acceptance: dict[str, Any],
) -> None:
    """Persist the benchmark run into the eval_* tables (ROADMAP §7 / §2).

    ``passed=True`` records that the row executed; per-strategy task quality is
    in ``metrics["task_success"]`` and the overall verdict is in the run config.
    """
    strategy_values = [s.value for s in ALL_STRATEGIES]
    eval_run = await repo.add_eval_run(
        EvalRunRecord(
            name="deterministic_benchmark",
            status="completed",
            finished_at=datetime.now(timezone.utc),
            config={
                "strategies": strategy_values,
                "summary": summary,
                "acceptance": acceptance,
            },
        )
    )
    for case in CASES:
        await repo.add_eval_case(
            EvalCaseRecord(
                eval_case_id=case.case_id,
                name=case.name,
                description=case.description,
                tags=["benchmark"],
                config={"strategies": strategy_values},
            )
        )
    for row in results:
        await repo.add_eval_result(
            EvalResultRecord(
                eval_run_id=eval_run.eval_run_id,
                eval_case_id=row.case_id,
                run_id=None,
                strategy=row.strategy,
                metrics=row.as_dict(),
                passed=True,
            )
        )


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_markdown(path: Path, payload: dict[str, Any]) -> None:
    lines = [
        "# MemTrace P1 Benchmark Report",
        "",
        "Deterministic benchmark for six retrieval strategies: "
        "`baseline_0`, `long_context`, `baseline_1`, `variant_1`, `variant_2`, and `variant_3`.",
        "",
        "## Summary",
        "",
        "| Strategy | task_success_rate | correct_active_path_hit_rate | failed_branch_contamination_rate | cross_workspace_leakage_rate | tool_sensitive_blocked_rate | procedural_reuse_hit_rate | compaction_trigger_rate | constraint_retention_hit_rate | unsafe_compaction_leakage_rate | negative_lesson_retained_rate | unsafe_negative_leakage_rate | sanitized_notice_rate | reflection_retention_hit_rate | avg_compression_ratio | avg_memory_token_overhead |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for strategy, row in payload["summary"].items():
        lines.append(
            "| {strategy} | {task_success_rate} | {correct_active_path_hit_rate} | "
            "{failed_branch_contamination_rate} | {cross_workspace_leakage_rate} | "
            "{tool_sensitive_blocked_rate} | {procedural_reuse_hit_rate} | {compaction_trigger_rate} | "
            "{constraint_retention_hit_rate} | {unsafe_compaction_leakage_rate} | "
            "{negative_lesson_retained_rate} | {unsafe_negative_leakage_rate} | {sanitized_notice_rate} | "
            "{reflection_retention_hit_rate} | {avg_compression_ratio} | {avg_memory_token_overhead} |".format(
                strategy=strategy,
                **row,
            )
        )
    lines.extend([
        "",
        "## Case Results",
        "",
        "| Case | Strategy | final_action | task_success | failed_branch_contamination | positive_contamination | negative_lesson_retained | unsafe_negative_leakage | sanitized_notice_present | cross_workspace_leakage | tool_sensitive_blocked | compaction_triggered | constraint_retention_hit | unsafe_compaction_leakage | compression_ratio | candidate/accepted/rejected |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for row in payload["results"]:
        lines.append(
            "| {case_id} | {strategy} | {final_action} | {task_success} | "
            "{failed_branch_contamination} | {positive_contamination} | {negative_lesson_retained} | "
            "{unsafe_negative_leakage} | {sanitized_notice_present} | {cross_workspace_leakage} | {tool_sensitive_blocked} | "
            "{compaction_triggered} | {constraint_retention_hit} | {unsafe_compaction_leakage} | "
            "{compression_ratio} | {candidate_count}/{accepted_count}/{rejected_count} |".format(**row)
        )
    acc = payload.get("acceptance", {})
    lines.extend([
        "",
        "## Acceptance (mvp.md section 10.5)",
        "",
        f"**Passed: {acc.get('passed')}**",
        "",
        "| Check | Result |",
        "|---|---:|",
    ])
    for name, ok in acc.get("checks", {}).items():
        lines.append(f"| {name} | {ok} |")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def _case_success(results: list[CaseMetrics], case_id: str, strategy: str) -> int | None:
    for row in results:
        if row.case_id == case_id and row.strategy == strategy:
            return row.task_success
    return None


def _case_metric(results: list[CaseMetrics], case_id: str, strategy: str, metric: str) -> int | float | None:
    for row in results:
        if row.case_id == case_id and row.strategy == strategy:
            return getattr(row, metric)
    return None


def _case_present(results: list[CaseMetrics], case_id: str, strategy: str, present_metric: str) -> bool:
    return _case_metric(results, case_id, strategy, present_metric) == 1


def _acceptance(summary: dict[str, dict[str, float]], results: list[CaseMetrics]) -> dict[str, Any]:
    """Encode the computable mvp.md section 10.5 pass criteria.

    Criteria 4-6 (project constraints, profiler fields, access inspection) are
    covered by unit tests; criteria 1-3 are checked here against the summary.
    """
    b1 = summary.get("baseline_1", {})
    v2 = summary.get("variant_2", {})
    v3 = summary.get("variant_3", {})
    case8_b0 = _case_success(results, "case_8_no_memory_baseline", "baseline_0")
    case8_v2 = _case_success(results, "case_8_no_memory_baseline", "variant_2")
    checks = {
        "variant_2_contamination_below_baseline_1": (
            v2.get("failed_branch_contamination_rate", 1.0)
            < b1.get("failed_branch_contamination_rate", 0.0)
        ),
        "variant_2_zero_cross_workspace_leakage": (
            v2.get("cross_workspace_leakage_rate", 1.0) == 0.0
            and _case_present(results, "case_3_workspace_isolation", "variant_2", "cross_workspace_leakage_present")
            and _case_metric(results, "case_3_workspace_isolation", "variant_2", "cross_workspace_leakage") == 0
        ),
        "variant_2_blocks_tool_sensitive": (
            v2.get("tool_sensitive_blocked_rate", 0.0) == 1.0
            and _case_present(results, "case_4_tool_safety", "variant_2", "tool_sensitive_present")
            and _case_metric(results, "case_4_tool_safety", "variant_2", "tool_sensitive_blocked") == 1
        ),
        "variant_2_reuses_procedural_memory": (
            v2.get("procedural_reuse_hit_rate", 0.0) == 1.0
            and _case_present(results, "case_6_completed_run_reuse", "variant_2", "procedural_reuse_present")
            and _case_metric(results, "case_6_completed_run_reuse", "variant_2", "procedural_reuse_hit") == 1
        ),
        "variant_2_excludes_superseded_memory": (
            v2.get("superseded_injection_rate", 1.0) == 0.0
            and _case_present(results, "case_5_explicit_correction", "variant_2", "superseded_injection_present")
            and _case_metric(results, "case_5_explicit_correction", "variant_2", "superseded_injection") == 0
        ),
        "variant_2_excludes_stale_memory": (
            v2.get("stale_memory_injection_rate", 1.0) == 0.0
            and b1.get("stale_memory_injection_rate", 0.0) > 0.0
            and _case_present(results, "case_7_stale_rejection", "variant_2", "stale_memory_injection_present")
            and _case_present(results, "case_7_stale_rejection", "baseline_1", "stale_memory_injection_present")
            and _case_metric(results, "case_7_stale_rejection", "variant_2", "stale_memory_injection") == 0
            and (_case_metric(results, "case_7_stale_rejection", "baseline_1", "stale_memory_injection") or 0) > 0
        ),
        "variant_2_succeeds_where_no_memory_baseline_fails": (
            case8_b0 == 0 and case8_v2 == 1
        ),
        "variant_2_retains_constraints_under_compaction": (
            v2.get("compaction_trigger_rate", 0.0) == 1.0
            and v2.get("constraint_retention_hit_rate", 0.0) == 1.0
            and v2.get("unsafe_compaction_leakage_rate", 1.0) == 0.0
            and _case_present(results, "case_9_over_budget_compaction", "variant_2", "compaction_triggered_present")
            and _case_present(results, "case_9_over_budget_compaction", "variant_2", "constraint_retention_hit_present")
            and _case_present(results, "case_9_over_budget_compaction", "variant_2", "unsafe_compaction_leakage_present")
            and _case_metric(results, "case_9_over_budget_compaction", "variant_2", "compaction_triggered") == 1
            and _case_metric(results, "case_9_over_budget_compaction", "variant_2", "constraint_retention_hit") == 1
            and _case_metric(results, "case_9_over_budget_compaction", "variant_2", "unsafe_compaction_leakage") == 0
        ),
        "variant_2_learns_from_failure_without_repeating": (
            v2.get("positive_contamination_rate", 1.0) == 0.0
            and v2.get("negative_lesson_retained_rate", 0.0) == 1.0
            and v2.get("correct_action_rate", 0.0) == 1.0
            and _case_present(results, "case_10_avoid_repeating_failed_attempt", "variant_2", "positive_contamination_present")
            and _case_present(results, "case_10_avoid_repeating_failed_attempt", "variant_2", "negative_lesson_retained_present")
            and _case_present(results, "case_10_avoid_repeating_failed_attempt", "variant_2", "correct_action_present")
            and _case_metric(results, "case_10_avoid_repeating_failed_attempt", "variant_2", "positive_contamination") == 0
            and _case_metric(results, "case_10_avoid_repeating_failed_attempt", "variant_2", "negative_lesson_retained") == 1
            and _case_metric(results, "case_10_avoid_repeating_failed_attempt", "variant_2", "correct_action") == 1
        ),
        "variant_2_sanitizes_destructive_failure_without_leakage": (
            v2.get("unsafe_negative_leakage_rate", 1.0) == 0.0
            and v2.get("sanitized_notice_rate", 0.0) == 1.0
            and _case_present(results, "case_11_sanitized_failed_destructive_attempt", "variant_2", "unsafe_negative_leakage_present")
            and _case_present(results, "case_11_sanitized_failed_destructive_attempt", "variant_2", "sanitized_notice_present_present")
            and _case_metric(results, "case_11_sanitized_failed_destructive_attempt", "variant_2", "unsafe_negative_leakage") == 0
            and _case_metric(results, "case_11_sanitized_failed_destructive_attempt", "variant_2", "sanitized_notice_present") == 1
        ),
        "variant_3_retains_high_value_memory_under_budget": (
            v3.get("reflection_retention_hit_rate", 0.0) == 1.0
            and v2.get("reflection_retention_hit_rate", 1.0) == 0.0
            and _case_present(results, "case_12_reflection_retention", "variant_3", "reflection_retention_hit_present")
            and _case_present(results, "case_12_reflection_retention", "variant_2", "reflection_retention_hit_present")
            and _case_metric(results, "case_12_reflection_retention", "variant_3", "reflection_retention_hit") == 1
            and _case_metric(results, "case_12_reflection_retention", "variant_2", "reflection_retention_hit") == 0
        ),
        "long_context_shows_token_bloat": (
            "long_context" in summary
            and "variant_2" in summary
            and summary["long_context"].get("avg_memory_token_overhead", 0.0)
            == max(row.get("avg_memory_token_overhead", 0.0) for row in summary.values())
            and summary["long_context"].get("avg_memory_token_overhead", 0.0)
            > summary["variant_2"].get("avg_memory_token_overhead", 0.0)
        ),
    }
    return {"passed": all(checks.values()), "checks": checks}


async def run_benchmark(output_dir: str | Path = "reports", repo: Repository | None = None) -> dict[str, Any]:
    """Run all P1 benchmark cases and write JSON/Markdown reports."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    workspace_prefix = f"bench_{uuid4().hex}" if repo is not None else "bench"
    results: list[CaseMetrics] = []
    for index, case in enumerate(CASES, start=1):
        results.extend(await _run_case(case, workspace_id=f"{workspace_prefix}_ws_{index}", repo=repo))

    summary = _summarize(results)
    acceptance = _acceptance(summary, results)
    if repo is not None:
        await _persist_results(repo, results)
        await _persist_eval_records(repo, results, summary, acceptance)

    payload: dict[str, Any] = {
        "cases": [
            {"case_id": c.case_id, "name": c.name, "description": c.description}
            for c in CASES
        ],
        "strategies": [s.value for s in ALL_STRATEGIES],
        "summary": summary,
        "results": [r.as_dict() for r in results],
        "metric_fields": list(_METRIC_FIELDS),
        "acceptance": acceptance,
    }
    _write_json(out / "benchmark_results.json", payload)
    _write_markdown(out / "benchmark_report.md", payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Run MemTrace P1 deterministic benchmark.")
    parser.add_argument("--output-dir", default="reports", help="Directory for benchmark_report.md/results.json")
    args = parser.parse_args()
    asyncio.run(run_benchmark(args.output_dir))


if __name__ == "__main__":
    main()


__all__ = ["run_benchmark", "main"]
