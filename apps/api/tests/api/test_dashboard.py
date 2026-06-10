"""P1 dashboard table API tests."""
from __future__ import annotations

import httpx
from fastapi import FastAPI

from app.api.deps import get_runtime
from app.api.routes import router
from app.benchmark.runner import run_benchmark
from app.runtime.memory_runtime import MemoryRuntime
from app.runtime.models import (
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
    await run_benchmark(output_dir=tmp_path, repo=repo)

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_runtime] = lambda: runtime

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/dashboard/tables")

    assert resp.status_code == 200
    payload = resp.json()
    # Eight benchmark cases: case 3 seeds a competing workspace run and case 6
    # seeds a prior completed run plus a follow-up run; cases 7 and 8 seed one
    # run each, for 10 runs total.
    assert len(payload["runs"]) == 10
    assert len(payload["accesses"]) == 32
    assert len(payload["benchmark_cases"]) == 8
    assert len(payload["benchmark_results"]) == 32
    assert payload["benchmark_summary"]["variant_2"]["failed_branch_contamination_rate"] == 0


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
