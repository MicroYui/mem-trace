"""Eval record and access fidelity repository tests."""
from __future__ import annotations

from app.runtime.memory_runtime import MemoryRuntime
from app.runtime.models import (
    DashboardTables,
    EvalCaseRecord,
    EvalResultRecord,
    EvalRunRecord,
    MemoryAccessLog,
    RetrievalStrategy,
)
from app.runtime.repository import InMemoryRepository, Repository


async def test_access_log_preserves_top_k_through_in_memory_add_get_and_list():
    repo = InMemoryRepository()
    access = MemoryAccessLog(workspace_id="ws_eval", query="remember X", top_k=7)

    await repo.add_access_log(access)

    stored = await repo.get_access_log(access.access_id)
    listed = await repo.list_access_logs(workspace_id="ws_eval")

    assert stored is not None
    assert stored.top_k == 7
    assert [row.top_k for row in listed] == [7]


async def test_in_memory_repo_adds_lists_and_updates_eval_records():
    repo: Repository = InMemoryRepository()
    case = EvalCaseRecord(
        eval_case_id="case_failed_branch",
        name="failed branch rejection",
        description="Variant 2 rejects failed branch memory.",
        tags=["safety", "gate"],
        config={"query": "run tests"},
    )
    run = EvalRunRecord(
        eval_run_id="evalrun_1",
        name="phase3 smoke",
        workspace_id="ws_eval",
        status="running",
        config={"strategy": "variant_2"},
    )
    result = EvalResultRecord(
        eval_result_id="evalres_1",
        eval_run_id=run.eval_run_id,
        eval_case_id=case.eval_case_id,
        run_id="run_1",
        access_id="acc_1",
        strategy=RetrievalStrategy.variant_2,
        metrics={"task_success": 1.0},
        passed=True,
    )

    await repo.add_eval_case(case)
    await repo.add_eval_run(run)
    await repo.add_eval_result(result)
    run.status = "completed"
    result.passed = False
    result.metrics = {"task_success": 0.0}
    await repo.update_eval_run(run)
    await repo.update_eval_result(result)

    assert await repo.list_eval_cases() == [case]
    assert await repo.list_eval_runs(workspace_id="ws_eval") == [run]
    assert await repo.list_eval_results(eval_run_id="evalrun_1") == [result]


async def test_dashboard_tables_exposes_eval_records_with_observability_summary():
    repo = InMemoryRepository()
    runtime = MemoryRuntime(repo, default_workspace_id="ws_eval")
    await repo.add_eval_case(EvalCaseRecord(eval_case_id="case_1", name="case"))
    await repo.add_eval_run(EvalRunRecord(eval_run_id="evalrun_1", workspace_id="ws_eval"))
    await repo.add_eval_result(EvalResultRecord(eval_result_id="evalres_1", eval_run_id="evalrun_1", eval_case_id="case_1"))

    tables = await runtime.dashboard_tables(workspace_id="ws_eval")

    assert isinstance(tables, DashboardTables)
    assert [case.eval_case_id for case in tables.eval_cases] == ["case_1"]
    assert [run.eval_run_id for run in tables.eval_runs] == ["evalrun_1"]
    assert [result.eval_result_id for result in tables.eval_results] == ["evalres_1"]
    assert tables.observability_summary is not None
    assert tables.observability_summary.workspace_id == "ws_eval"
    assert tables.observability_summary.access_count == 0


async def test_dashboard_tables_filters_eval_results_by_workspace():
    repo = InMemoryRepository()
    runtime = MemoryRuntime(repo, default_workspace_id="ws_a")
    await repo.add_eval_case(EvalCaseRecord(eval_case_id="case_1", name="case"))
    await repo.add_eval_run(EvalRunRecord(eval_run_id="evalrun_a", workspace_id="ws_a"))
    await repo.add_eval_run(EvalRunRecord(eval_run_id="evalrun_b", workspace_id="ws_b"))
    await repo.add_eval_result(
        EvalResultRecord(eval_result_id="evalres_a", eval_run_id="evalrun_a", eval_case_id="case_1")
    )
    await repo.add_eval_result(
        EvalResultRecord(eval_result_id="evalres_b", eval_run_id="evalrun_b", eval_case_id="case_1")
    )

    tables = await runtime.dashboard_tables(workspace_id="ws_a")

    assert [run.eval_run_id for run in tables.eval_runs] == ["evalrun_a"]
    assert [result.eval_result_id for result in tables.eval_results] == ["evalres_a"]
