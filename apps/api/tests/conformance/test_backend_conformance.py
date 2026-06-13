"""Backend transport conformance tests."""
from __future__ import annotations

import httpx
import pytest

from app.api.deps import get_runtime
from app.main import app
from app.runtime.memory_runtime import MemoryRuntime
from app.runtime.repository import InMemoryRepository
from memtrace_sdk import MemTrace
from memtrace_sdk.types import EventRole, EventType, StartRunRequest, StartStepRequest, WriteEventRequest


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


async def _http_client_for(runtime: MemoryRuntime) -> MemTrace:
    app.dependency_overrides[get_runtime] = lambda: runtime
    transport = httpx.ASGITransport(app=app)
    http_client = httpx.AsyncClient(transport=transport, base_url="http://test")
    return MemTrace.http("http://test", client=http_client)


@pytest.mark.asyncio
async def test_in_process_and_http_cross_read_write_runtime_contract():
    runtime = MemoryRuntime(InMemoryRepository(), default_workspace_id="ws_conf_backend")
    in_process = MemTrace.in_process(runtime)
    http = await _http_client_for(runtime)

    try:
        run = await in_process.start_run(
            StartRunRequest(workspace_id="ws_conf_backend", session_id="s", task="contract")
        )
        step = await http.start_step(StartStepRequest(run_id=run.run_id, intent="step"))
        await in_process.write_event(
            WriteEventRequest(
                run_id=run.run_id,
                step_id=step.step_id,
                role=EventRole.user,
                event_type=EventType.message,
                content="use bun",
            )
        )
        await http.write_event(
            WriteEventRequest(
                run_id=run.run_id,
                step_id=step.step_id,
                role=EventRole.assistant,
                event_type=EventType.message,
                content="ack",
            )
        )

        timeline_via_http = await http.get_timeline(run.run_id)
        timeline_via_in_process = await in_process.get_timeline(run.run_id)
        assert [event.sequence_no for event in timeline_via_http] == [1, 2]
        assert [event.sequence_no for event in timeline_via_in_process] == [1, 2]
        assert [event.event_id for event in timeline_via_http] == [event.event_id for event in timeline_via_in_process]
    finally:
        await http.aclose()
