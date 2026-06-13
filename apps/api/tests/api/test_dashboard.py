"""P1 dashboard table API tests."""
from __future__ import annotations

import httpx
from fastapi import FastAPI

from app.api.deps import get_runtime
from app.api.routes import router
from app.benchmark.runner import run_benchmark
from app.runtime.memory_runtime import MemoryRuntime
from app.runtime.memory_runtime import _benchmark_summary_from_records
from app.runtime.models import (
    BenchmarkResultRecord,
    EvalCaseRecord,
    EvalResultRecord,
    EvalRunRecord,
    GateDecisionType,
    GateLayer,
    MemoryAccessLog,
    MemoryGateLog,
    MemoryItem,
    MemoryType,
    RetrievalStrategy,
)
from app.runtime.repository import InMemoryRepository


async def test_dashboard_tables_endpoint_exposes_benchmark_and_runtime_rows(tmp_path):
    repo = InMemoryRepository()
    runtime = MemoryRuntime(repo, default_workspace_id="dash_ws")
    report = await run_benchmark(output_dir=tmp_path, repo=repo)

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_runtime] = lambda: runtime

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/dashboard/tables")

    assert resp.status_code == 200
    payload = resp.json()
    # Thirteen benchmark cases: case 3 seeds a competing workspace run, case 6
    # seeds a prior completed run plus a follow-up run, and each remaining case
    # (including case 12/13) seeds one benchmark run, for 15 runs total.
    assert len(payload["runs"]) == 15
    assert len(payload["accesses"]) == 78
    assert len(payload["benchmark_cases"]) == 13
    assert len(payload["benchmark_results"]) == 78
    assert payload["benchmark_summary"]["variant_2"]["failed_branch_contamination_rate"] == 0
    assert payload["benchmark_summary"]["variant_2"]["constraint_retention_hit_rate"] == 1
    for field in [
        "stale_memory_injection_rate",
        "superseded_injection_rate",
        "compaction_trigger_rate",
        "constraint_retention_hit_rate",
        "unsafe_compaction_leakage_rate",
        "cross_workspace_leakage_rate",
        "positive_contamination_rate",
        "negative_lesson_retained_rate",
        "correct_action_rate",
        "unsafe_negative_leakage_rate",
        "sanitized_notice_rate",
        "reflection_retention_hit_rate",
        "avg_retained_negative_evidence_count",
        "compaction_negative_lesson_retained_rate",
        "compaction_retained_negative_unsafe_leakage_rate",
        "avg_compression_ratio",
        "avg_memory_token_overhead",
    ]:
        assert payload["benchmark_summary"]["variant_2"][field] == report["summary"]["variant_2"][field]
    assert (
        payload["benchmark_summary"]["variant_3"]["reflection_retention_hit_rate"]
        == report["summary"]["variant_3"]["reflection_retention_hit_rate"]
        == 1
    )


def test_dashboard_benchmark_summary_filters_cross_workspace_rate_by_present_flag():
    summary = _benchmark_summary_from_records(
        [
            BenchmarkResultRecord(
                case_id="case_3_workspace_isolation",
                strategy="variant_2",
                metrics={"cross_workspace_leakage": 1, "cross_workspace_leakage_present": 1},
            ),
            BenchmarkResultRecord(
                case_id="case_1_project_preference",
                strategy="variant_2",
                metrics={"cross_workspace_leakage": 0, "cross_workspace_leakage_present": 0},
            ),
        ]
    )

    assert summary["variant_2"]["cross_workspace_leakage_rate"] == 1


async def test_dashboard_tables_include_eval_rows_and_workspace_observability_summary():
    repo = InMemoryRepository()
    runtime = MemoryRuntime(repo, default_workspace_id="dash_ws")

    case = await repo.add_eval_case(EvalCaseRecord(eval_case_id="eval_case_1", name="quality gate"))
    eval_run = await repo.add_eval_run(EvalRunRecord(eval_run_id="eval_run_1", workspace_id="dash_ws"))
    await repo.add_eval_run(EvalRunRecord(eval_run_id="eval_run_other", workspace_id="other_ws"))
    await repo.add_eval_result(
        EvalResultRecord(
            eval_result_id="eval_result_1",
            eval_run_id=eval_run.eval_run_id,
            eval_case_id=case.eval_case_id,
            strategy=RetrievalStrategy.variant_2,
            metrics={"failed_branch_contamination_rate": 0.0},
        )
    )
    await repo.add_eval_result(
        EvalResultRecord(
            eval_result_id="eval_result_other",
            eval_run_id="eval_run_other",
            eval_case_id=case.eval_case_id,
        )
    )

    memory = await repo.add_memory(
        MemoryItem(workspace_id="dash_ws", memory_type=MemoryType.project, content="Use bun test")
    )
    access = await repo.add_access_log(
        MemoryAccessLog(
            workspace_id="dash_ws",
            query="test command",
            retrieval_strategy=RetrievalStrategy.variant_2,
            candidate_count=1,
            accepted_count=1,
            rejected_count=0,
            latency_ms=12,
            actual_tokens=7,
        )
    )
    await repo.add_gate_log(
        MemoryGateLog(
            access_id=access.access_id,
            memory_id=memory.memory_id,
            layer=GateLayer.soft_ranking,
            decision=GateDecisionType.accept,
        )
    )
    await repo.add_access_log(
        MemoryAccessLog(
            workspace_id="other_ws",
            query="other workspace should not affect dashboard summary",
            retrieval_strategy=RetrievalStrategy.variant_2,
            candidate_count=100,
            accepted_count=100,
            rejected_count=0,
        )
    )

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_runtime] = lambda: runtime

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/dashboard/tables?workspace_id=dash_ws")

    assert resp.status_code == 200
    payload = resp.json()
    assert [row["eval_case_id"] for row in payload["eval_cases"]] == ["eval_case_1"]
    assert [row["eval_run_id"] for row in payload["eval_runs"]] == ["eval_run_1"]
    assert [row["eval_result_id"] for row in payload["eval_results"]] == ["eval_result_1"]
    assert payload["observability_summary"]["workspace_id"] == "dash_ws"
    assert payload["observability_summary"]["access_count"] == 1
    assert payload["observability_summary"]["candidate_count"] == 1
    assert payload["observability_summary"]["accepted_count"] == 1
    assert payload["observability_summary"]["by_strategy"]["variant_2"]["access_count"] == 1
