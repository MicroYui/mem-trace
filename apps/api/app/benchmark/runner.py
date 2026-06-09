"""P1 benchmark runner and report writer.

Runs the four deterministic MVP benchmark cases from `mvp.md` section 10.4
against the same seeded memory items for each strategy, then emits the required
`benchmark_report.md` and `benchmark_results.json` artifacts.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from app.benchmark.cases import ALL_STRATEGIES, CASES, BenchmarkCase
from app.benchmark.evaluator import CaseMetrics, evaluate_case
from app.runtime.memory_runtime import MemoryRuntime
from app.runtime.models import BenchmarkCaseRecord, BenchmarkResultRecord, RetrievalRequest, RetrievalStrategy
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
            "cross_workspace_leakage_rate": _average([r.cross_workspace_leakage for r in rows]),
            "tool_sensitive_blocked_rate": _average(
                [r.tool_sensitive_blocked for r in rows if r.tool_sensitive_present]
            ),
            "procedural_reuse_hit_rate": _average(
                [r.procedural_reuse_hit for r in rows if r.procedural_reuse_present]
            ),
            "superseded_injection_rate": _average(
                [r.superseded_injection for r in rows if r.superseded_injection_present]
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


async def _run_case(case: BenchmarkCase, workspace_id: str, repo: Repository | None = None) -> list[CaseMetrics]:
    repo = repo or InMemoryRepository()
    runtime = MemoryRuntime(repo, default_workspace_id=workspace_id)
    seed = await case.seed(runtime, workspace_id)

    metrics: list[CaseMetrics] = []
    for strategy in ALL_STRATEGIES:
        ctx = await runtime.retrieve_context(
            RetrievalRequest(
                run_id=seed.run_id,
                step_id=seed.step_id,
                query=seed.query,
                strategy=strategy,
            )
        )
        access = await runtime.inspect_access(ctx.access_id)
        profile_events = await runtime.get_profile(seed.run_id)
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


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_markdown(path: Path, payload: dict[str, Any]) -> None:
    lines = [
        "# MemTrace P1 Benchmark Report",
        "",
        "Deterministic benchmark for `baseline_0`, `baseline_1`, `variant_1`, and `variant_2`.",
        "",
        "## Summary",
        "",
        "| Strategy | task_success_rate | correct_active_path_hit_rate | failed_branch_contamination_rate | cross_workspace_leakage_rate | tool_sensitive_blocked_rate | procedural_reuse_hit_rate | avg_memory_token_overhead |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for strategy, row in payload["summary"].items():
        lines.append(
            "| {strategy} | {task_success_rate} | {correct_active_path_hit_rate} | "
            "{failed_branch_contamination_rate} | {cross_workspace_leakage_rate} | "
            "{tool_sensitive_blocked_rate} | {procedural_reuse_hit_rate} | {avg_memory_token_overhead} |".format(
                strategy=strategy,
                **row,
            )
        )
    lines.extend([
        "",
        "## Case Results",
        "",
        "| Case | Strategy | final_action | task_success | failed_branch_contamination | cross_workspace_leakage | tool_sensitive_blocked | candidate/accepted/rejected |",
        "|---|---|---|---:|---:|---:|---:|---:|",
    ])
    for row in payload["results"]:
        lines.append(
            "| {case_id} | {strategy} | {final_action} | {task_success} | "
            "{failed_branch_contamination} | {cross_workspace_leakage} | {tool_sensitive_blocked} | "
            "{candidate_count}/{accepted_count}/{rejected_count} |".format(**row)
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


def _acceptance(summary: dict[str, dict[str, float]]) -> dict[str, Any]:
    """Encode the computable mvp.md section 10.5 pass criteria.

    Criteria 4-6 (project constraints, profiler fields, access inspection) are
    covered by unit tests; criteria 1-3 are checked here against the summary.
    """
    b1 = summary.get("baseline_1", {})
    b0 = summary.get("baseline_0", {})
    v2 = summary.get("variant_2", {})
    checks = {
        "variant_2_contamination_below_baseline_1": (
            v2.get("failed_branch_contamination_rate", 1.0)
            < b1.get("failed_branch_contamination_rate", 0.0)
        ),
        "variant_2_zero_cross_workspace_leakage": (
            v2.get("cross_workspace_leakage_rate", 1.0) == 0.0
        ),
        "variant_2_blocks_tool_sensitive": (
            v2.get("tool_sensitive_blocked_rate", 0.0) == 1.0
        ),
        "variant_2_reuses_procedural_memory": (
            v2.get("procedural_reuse_hit_rate", 0.0) == 1.0
        ),
        "variant_2_excludes_superseded_memory": (
            v2.get("superseded_injection_rate", 1.0) == 0.0
        ),
        "variant_2_excludes_stale_memory": (
            v2.get("stale_memory_injection_rate", 1.0) == 0.0
            and b1.get("stale_memory_injection_rate", 0.0) > 0.0
        ),
        "variant_2_succeeds_where_no_memory_baseline_fails": (
            v2.get("task_success_rate", 0.0) > b0.get("task_success_rate", 1.0)
        ),
    }
    return {"passed": all(checks.values()), "checks": checks}


async def run_benchmark(output_dir: str | Path = "reports", repo: Repository | None = None) -> dict[str, Any]:
    """Run all P1 benchmark cases and write JSON/Markdown reports."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    results: list[CaseMetrics] = []
    for index, case in enumerate(CASES, start=1):
        results.extend(await _run_case(case, workspace_id=f"bench_ws_{index}", repo=repo))

    if repo is not None:
        await _persist_results(repo, results)

    summary = _summarize(results)
    payload: dict[str, Any] = {
        "cases": [
            {"case_id": c.case_id, "name": c.name, "description": c.description}
            for c in CASES
        ],
        "strategies": [s.value for s in ALL_STRATEGIES],
        "summary": summary,
        "results": [r.as_dict() for r in results],
        "metric_fields": list(_METRIC_FIELDS),
        "acceptance": _acceptance(summary),
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
