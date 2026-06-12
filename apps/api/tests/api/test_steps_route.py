from __future__ import annotations

import httpx
from fastapi import FastAPI

from app.api.deps import get_runtime
from app.api.routes import router
from app.runtime.memory_runtime import MemoryRuntime
from app.runtime.models import StartRunRequest, StartStepRequest
from app.runtime.repository import InMemoryRepository


def _app_for(runtime: MemoryRuntime) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_runtime] = lambda: runtime
    return app


async def test_get_run_steps_endpoint_returns_steps_for_run() -> None:
    runtime = MemoryRuntime(InMemoryRepository(), default_workspace_id="ws_steps")
    run = await runtime.start_run(StartRunRequest(session_id="steps-s1"))
    step = await runtime.start_step(StartStepRequest(run_id=run.run_id, intent="record step"))
    app = _app_for(runtime)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(f"/v1/runs/{run.run_id}/steps")

    assert resp.status_code == 200
    assert [item["step_id"] for item in resp.json()] == [step.step_id]


async def test_get_run_steps_endpoint_returns_empty_list_for_missing_run() -> None:
    runtime = MemoryRuntime(InMemoryRepository(), default_workspace_id="ws_steps")
    app = _app_for(runtime)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/v1/runs/run_missing/steps")

    assert resp.status_code == 200
    assert resp.json() == []
