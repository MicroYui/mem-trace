"""P1 dashboard table API tests."""
from __future__ import annotations

import httpx
from fastapi import FastAPI

from app.api.deps import get_runtime
from app.api.routes import router
from app.benchmark.runner import run_benchmark
from app.runtime.memory_runtime import MemoryRuntime
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
    # Six benchmark cases: case 3 seeds a competing workspace run and case 6
    # seeds a prior completed run plus a follow-up run, for 8 runs total.
    assert len(payload["runs"]) == 8
    assert len(payload["accesses"]) == 24
    assert len(payload["benchmark_cases"]) == 6
    assert len(payload["benchmark_results"]) == 24
    assert payload["benchmark_summary"]["variant_2"]["failed_branch_contamination_rate"] == 0
