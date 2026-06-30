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


async def test_write_event_maps_state_tree_error_to_400(monkeypatch) -> None:
    runtime = MemoryRuntime(InMemoryRepository(), default_workspace_id="ws_events")
    run = await runtime.start_run(StartRunRequest(session_id="events-s1"))
    step = await runtime.start_step(StartStepRequest(run_id=run.run_id, intent="record"))

    # Corrupt the state tree: the step keeps its state_node_id but the node is
    # gone, so write_event raises StateTreeError. The route must translate that
    # into HTTP 400 like every sibling mutating route (not surface a 500).
    async def _missing_node(_node_id: str):
        return None

    monkeypatch.setattr(runtime._repo, "get_state_node", _missing_node)

    app = _app_for(runtime)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/v1/events",
            json={
                "run_id": run.run_id,
                "step_id": step.step_id,
                "role": "user",
                "event_type": "message",
                "content": "hello",
            },
        )

    assert resp.status_code == 400
