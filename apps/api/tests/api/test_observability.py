"""Phase 3-A Issue 4 observability/replay API tests."""
from __future__ import annotations

import httpx
from fastapi import FastAPI

from app.api.deps import get_runtime
from app.api.routes import router
from app.runtime.memory_runtime import MemoryRuntime
from app.runtime.models import (
    BranchStatus,
    GateDecisionType,
    GateLayer,
    MemoryAccessLog,
    MemoryGateLog,
    MemoryItem,
    MemoryType,
    RetrievalRequest,
    RetrievalStrategy,
    StartRunRequest,
    StartStepRequest,
)
from app.runtime.repository import InMemoryRepository


def _app_for(runtime: MemoryRuntime) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_runtime] = lambda: runtime
    return app


async def _seed_retrieval(runtime: MemoryRuntime, repo: InMemoryRepository) -> tuple[str, str, str]:
    run = await runtime.start_run(
        StartRunRequest(session_id="s_obs", task="debug test command", workspace_id="ws_obs")
    )
    step = await runtime.start_step(StartStepRequest(run_id=run.run_id, intent="choose test command"))
    await repo.add_memory(
        MemoryItem(
            workspace_id="ws_obs",
            run_id=run.run_id,
            memory_type=MemoryType.project,
            key="project.runtime",
            value="bun",
            content="This project uses Bun; run bun test for tests",
            branch_status=BranchStatus.completed,
        )
    )
    await repo.add_memory(
        MemoryItem(
            workspace_id="ws_obs",
            run_id=run.run_id,
            memory_type=MemoryType.tool_evidence,
            key="tool.command.failed",
            value="npm test",
            content="npm test failed on a rolled back branch",
            branch_status=BranchStatus.rolled_back,
        )
    )
    ctx = await runtime.retrieve_context(
        RetrievalRequest(
            run_id=run.run_id,
            step_id=step.step_id,
            query="which test command should I run, bun test or npm test?",
            strategy=RetrievalStrategy.variant_2,
            token_budget=128,
            top_k=5,
        )
    )
    return run.run_id, step.step_id, ctx.access_id


async def test_replay_access_endpoint_returns_replay_payload():
    repo = InMemoryRepository()
    runtime = MemoryRuntime(repo, default_workspace_id="ws_obs")
    run_id, step_id, access_id = await _seed_retrieval(runtime, repo)
    app = _app_for(runtime)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/v1/replay/access/{access_id}")

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["access_id"] == access_id
    assert payload["run_id"] == run_id
    assert payload["step_id"] == step_id
    assert payload["workspace_id"] == "ws_obs"
    assert payload["strategy"] == "variant_2"
    assert payload["top_k"] == 5
    assert payload["original_candidates"]
    assert payload["replayed_candidates"]
    assert payload["metrics"]["candidate_count"] == 2
    assert payload["metrics"]["failed_branch_rejected"] == 1


async def test_replay_access_endpoint_404_for_missing_access():
    runtime = MemoryRuntime(InMemoryRepository(), default_workspace_id="ws_obs")
    app = _app_for(runtime)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/replay/access/acc_missing")

    assert resp.status_code == 404
    assert resp.json()["detail"] == "access not found"


async def test_replay_access_endpoint_404_when_original_run_is_missing():
    repo = InMemoryRepository()
    runtime = MemoryRuntime(repo, default_workspace_id="ws_obs")
    access = await repo.add_access_log(
        MemoryAccessLog(
            workspace_id="ws_obs",
            run_id="run_missing",
            query="stale access",
            retrieval_strategy=RetrievalStrategy.variant_2,
            token_budget=128,
            top_k=10,
        )
    )
    app = _app_for(runtime)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/v1/replay/access/{access.access_id}")

    assert resp.status_code == 404
    assert resp.json()["detail"] == "run not found"


async def test_replay_run_endpoint_replays_all_run_accesses():
    repo = InMemoryRepository()
    runtime = MemoryRuntime(repo, default_workspace_id="ws_obs")
    run_id, _, first_access_id = await _seed_retrieval(runtime, repo)
    await _seed_retrieval(runtime, repo)
    app = _app_for(runtime)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/v1/replay/runs/{run_id}")

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["run_id"] == run_id
    assert payload["access_count"] == 1
    assert [item["access_id"] for item in payload["replayed"]] == [first_access_id]
    assert "drift_count" in payload["summary"]


async def test_replay_run_endpoint_404_for_missing_run():
    runtime = MemoryRuntime(InMemoryRepository(), default_workspace_id="ws_obs")
    app = _app_for(runtime)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/replay/runs/run_missing")

    assert resp.status_code == 404
    assert resp.json()["detail"] == "run not found"


async def test_observability_summary_endpoint_returns_quality_safety_counts():
    repo = InMemoryRepository()
    runtime = MemoryRuntime(repo, default_workspace_id="ws_obs")
    run_id, _, _ = await _seed_retrieval(runtime, repo)
    app = _app_for(runtime)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/v1/observability/summary?workspace_id=ws_obs&run_id={run_id}")

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["workspace_id"] == "ws_obs"
    assert payload["run_id"] == run_id
    assert payload["access_count"] == 1
    assert payload["candidate_count"] == 2
    assert payload["accepted_count"] == 1
    assert payload["rejected_count"] == 1
    assert payload["failed_branch_rejected"] == 1
    assert payload["failed_branch_injected"] == 0
    assert payload["risk_blocked"] == 0
    assert payload["by_strategy"]["variant_2"]["access_count"] == 1


async def test_observability_summary_counts_workspace_leakage_from_all_candidates():
    repo = InMemoryRepository()
    runtime = MemoryRuntime(repo, default_workspace_id="ws_obs")
    other_memory = await repo.add_memory(
        MemoryItem(
            workspace_id="ws_other",
            memory_type=MemoryType.project,
            key="project.runtime",
            value="deno",
            content="Other workspace uses Deno",
        )
    )
    access = await repo.add_access_log(
        MemoryAccessLog(
            workspace_id="ws_obs",
            query="runtime",
            retrieval_strategy=RetrievalStrategy.variant_2,
            candidate_count=1,
            accepted_count=0,
            rejected_count=1,
        )
    )
    await repo.add_gate_log(
        MemoryGateLog(
            access_id=access.access_id,
            memory_id=other_memory.memory_id,
            layer=GateLayer.hard_policy,
            decision=GateDecisionType.reject,
            reject_reason="workspace_mismatch",
        )
    )
    app = _app_for(runtime)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/observability/summary?workspace_id=ws_obs")

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["workspace_mismatch_rejected"] == 1
    assert payload["workspace_leakage"] == 1
    assert payload["accepted_count"] == 0
