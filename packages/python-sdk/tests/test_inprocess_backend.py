from __future__ import annotations

import pytest

from memtrace_sdk import BadRequestError, MemTrace, NotFoundError
from memtrace_sdk.backends import InProcessBackend
from memtrace_sdk.types import (
    CompleteRunRequest,
    EventRole,
    EventType,
    FinishStepRequest,
    ObservabilityReportRequest,
    RetrievalRequest,
    RollbackRequest,
    StartRunRequest,
    StartStepRequest,
    StepStatus,
    WriteEventRequest,
)
from app.runtime.memory_runtime import MemoryRuntime
from app.runtime.repository import InMemoryRepository


async def test_memtrace_in_memory_runs_golden_path_and_stamps_sdk_event_source() -> None:
    client = MemTrace.in_memory(default_workspace_id="ws_sdk")

    run = await client.start_run(StartRunRequest(session_id="sdk-s1", task="remember runtime"))
    step = await client.start_step(StartStepRequest(run_id=run.run_id, intent="record constraint"))

    write = await client.write_event(
        WriteEventRequest(
            run_id=run.run_id,
            step_id=step.step_id,
            role=EventRole.user,
            event_type=EventType.message,
            content="这个项目使用 Bun",
        )
    )
    finish = await client.finish_step(
        FinishStepRequest(
            run_id=run.run_id,
            step_id=step.step_id,
            status=StepStatus.completed,
            summary="recorded Bun runtime constraint",
        )
    )
    context = await client.retrieve_context(
        RetrievalRequest(
            run_id=run.run_id,
            step_id=step.step_id,
            query="Bun runtime project",
        )
    )
    inspection = await client.inspect_access(context.access_id)
    timeline = await client.get_timeline(run.run_id)
    steps = await client.get_steps(run.run_id)

    assert write.event.event_source == "sdk"
    assert timeline[0].event_source == "sdk"
    assert finish.step.status == StepStatus.completed
    assert steps == [finish.step]
    assert any(block.type == "project_memory" and "uses Bun" in block.content for block in context.context_blocks)
    assert inspection.access_id == context.access_id
    assert inspection.context_blocks == context.context_blocks


async def test_memtrace_write_event_preserves_explicit_event_source() -> None:
    client = MemTrace.in_memory(default_workspace_id="ws_sdk")
    run = await client.start_run(StartRunRequest(session_id="sdk-s2"))
    step = await client.start_step(StartStepRequest(run_id=run.run_id))

    write = await client.write_event(
        WriteEventRequest(
            run_id=run.run_id,
            step_id=step.step_id,
            content="manual source",
            event_source="custom_loop",
        )
    )

    assert write.event.event_source == "custom_loop"


async def test_memtrace_in_process_wraps_existing_runtime_and_preserves_empty_list_reads() -> None:
    runtime = MemoryRuntime(InMemoryRepository(), default_workspace_id="ws_existing")
    client = MemTrace.in_process(runtime)

    run = await client.start_run(StartRunRequest(session_id="sdk-s3"))
    step = await client.start_step(StartStepRequest(run_id=run.run_id))

    assert step in await runtime.get_steps(run.run_id)
    assert await client.get_steps("run_missing") == []
    assert await client.get_timeline("run_missing") == []
    assert await client.get_state_tree("run_missing") == []
    assert await client.get_profile("run_missing") == []
    assert await client.list_memories(run_id="run_missing") == []


async def test_inprocess_backend_convenience_constructor_builds_runtime() -> None:
    backend = InProcessBackend.in_memory(default_workspace_id="ws_backend")

    run = await backend.start_run(StartRunRequest(session_id="backend-s1"))

    assert run.workspace_id == "ws_backend"


async def test_inprocess_backend_write_event_does_not_stamp_sdk_event_source() -> None:
    backend = InProcessBackend.in_memory(default_workspace_id="ws_backend")
    run = await backend.start_run(StartRunRequest(session_id="backend-s2"))
    step = await backend.start_step(StartStepRequest(run_id=run.run_id))

    write = await backend.write_event(
        WriteEventRequest(run_id=run.run_id, step_id=step.step_id, content="backend source")
    )

    assert write.event.event_source is None


@pytest.mark.parametrize("method_name", ["inspect_access", "replay_access"])
async def test_inprocess_missing_access_raises_not_found(method_name: str) -> None:
    client = MemTrace.in_memory(default_workspace_id="ws_sdk")

    with pytest.raises(NotFoundError):
        await getattr(client, method_name)("acc_missing")


async def test_inprocess_missing_replay_run_matches_http_not_found_semantics() -> None:
    client = MemTrace.in_memory(default_workspace_id="ws_sdk")

    with pytest.raises(NotFoundError):
        await client.replay_run("run_missing")


async def test_inprocess_runtime_missing_resources_raise_sdk_not_found() -> None:
    client = MemTrace.in_memory(default_workspace_id="ws_sdk")
    run = await client.start_run(StartRunRequest(session_id="sdk-s4"))
    step = await client.start_step(StartStepRequest(run_id=run.run_id))

    call_factories = [
        lambda: client.start_step(StartStepRequest(run_id="run_missing")),
        lambda: client.write_event(WriteEventRequest(run_id="run_missing", step_id=step.step_id, content="x")),
        lambda: client.write_event(WriteEventRequest(run_id=run.run_id, step_id="step_missing", content="x")),
        lambda: client.finish_step(FinishStepRequest(run_id=run.run_id, step_id="step_missing")),
        lambda: client.rollback_branch(RollbackRequest(run_id=run.run_id, step_id="step_missing")),
        lambda: client.complete_run(CompleteRunRequest(run_id="run_missing")),
        lambda: client.retrieve_context(RetrievalRequest(run_id="run_missing", query="x")),
    ]

    for make_call in call_factories:
        with pytest.raises(NotFoundError):
            await make_call()


async def test_inprocess_observability_report_bad_request_maps_to_sdk_error() -> None:
    client = MemTrace.in_memory(default_workspace_id="ws_sdk")

    with pytest.raises(BadRequestError):
        await client.write_observability_report(ObservabilityReportRequest(output_dir="../outside"))
