from __future__ import annotations

import httpx
import pytest

from app.api.deps import get_runtime
from app.main import app
from app.runtime.memory_runtime import MemoryRuntime
from app.runtime.repository import InMemoryRepository
from memtrace_sdk.backends import InProcessBackend
from memtrace_sdk import MemTrace, NotFoundError
from memtrace_sdk.types import (
    EventRole,
    EventType,
    FinishStepRequest,
    RetrievalRequest,
    StartRunRequest,
    StartStepRequest,
    StepStatus,
    WriteEventRequest,
)


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


async def _http_client_for(runtime: MemoryRuntime) -> MemTrace:
    app.dependency_overrides[get_runtime] = lambda: runtime
    transport = httpx.ASGITransport(app=app)
    http_client = httpx.AsyncClient(transport=transport, base_url="http://test")
    return MemTrace.http("http://test", client=http_client)


async def test_backends_are_isomorphic_for_golden_path_and_read_shapes() -> None:
    runtime = MemoryRuntime(InMemoryRepository(), default_workspace_id="ws_iso")
    in_process = MemTrace.in_process(runtime)
    http_client = await _http_client_for(runtime)

    try:
        run = await in_process.start_run(StartRunRequest(session_id="iso-shared", task="remember runtime"))
        step = await http_client.start_step(StartStepRequest(run_id=run.run_id, intent="record constraint"))
        await in_process.write_event(
            WriteEventRequest(
                run_id=run.run_id,
                step_id=step.step_id,
                role=EventRole.user,
                event_type=EventType.message,
                content="这个项目使用 Bun",
            )
        )
        await http_client.finish_step(
            FinishStepRequest(
                run_id=run.run_id,
                step_id=step.step_id,
                status=StepStatus.completed,
                summary="recorded Bun runtime constraint",
            )
        )
        http_context = await http_client.retrieve_context(
            RetrievalRequest(run_id=run.run_id, step_id=step.step_id, query="Bun runtime project")
        )
        in_process_context = await in_process.retrieve_context(
            RetrievalRequest(run_id=run.run_id, step_id=step.step_id, query="Bun runtime project")
        )

        assert [block.type for block in http_context.context_blocks] == [
            block.type for block in in_process_context.context_blocks
        ]
        assert [step.step_id for step in await http_client.get_steps(run.run_id)] == [
            step.step_id for step in await in_process.get_steps(run.run_id)
        ]
        assert await http_client.get_step(step.step_id) == await in_process.get_step(step.step_id)
        assert [event.event_id for event in await http_client.get_timeline(run.run_id)] == [
            event.event_id for event in await in_process.get_timeline(run.run_id)
        ]
        assert [node.node_id for node in await http_client.get_state_tree(run.run_id)] == [
            node.node_id for node in await in_process.get_state_tree(run.run_id)
        ]
        assert [event.phase for event in await http_client.get_profile(run.run_id)] == [
            event.phase for event in await in_process.get_profile(run.run_id)
        ]
        assert [memory.memory_id for memory in await http_client.list_memories(run_id=run.run_id)] == [
            memory.memory_id for memory in await InProcessBackend(runtime).list_memories(run_id=run.run_id)
        ]
        assert await in_process.flush_session("tenant/session") == await http_client.flush_session("tenant/session")
        assert await in_process.get_steps("run_missing") == []
        assert await http_client.get_steps("run_missing") == []

        for client in (in_process, http_client):
            with pytest.raises(NotFoundError):
                await client.inspect_access("acc_missing")
            with pytest.raises(NotFoundError):
                await client.get_step("step_missing")
    finally:
        await http_client.aclose()
