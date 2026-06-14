"""P4-A4 extraction mode matrix tests."""
from __future__ import annotations

from app.async_tasks.contracts import TaskEnvelope
from app.memory.candidate_buffer import CandidateBuffer
from app.runtime.memory_runtime import MemoryRuntime
from app.runtime.models import (
    EventRole,
    EventType,
    ExtractionMode,
    RetrievalRequest,
    RetrievalStrategy,
    StartRunRequest,
    StartStepRequest,
    WriteEventRequest,
    WriteEventResult,
)
from app.runtime.repository import InMemoryRepository


def _request(run_id: str, step_id: str, *, mode: ExtractionMode | None = None) -> WriteEventRequest:
    return WriteEventRequest(
        run_id=run_id,
        step_id=step_id,
        role=EventRole.user,
        event_type=EventType.message,
        content="这个项目使用 Bun",
        extraction_mode=mode,
    )


async def _started(rt: MemoryRuntime):
    run = await rt.start_run(StartRunRequest(session_id="s", task="t"))
    step = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="planning"))
    return run, step


async def _project_runtime_values(rt: MemoryRuntime) -> list[str]:
    return [
        str(memory.value)
        for memory in await rt.list_memories(workspace_id="ws_test")
        if memory.key == "project.runtime"
    ]


async def test_extraction_mode_enum_and_write_result_fields_are_backward_compatible():
    assert ExtractionMode("async") is ExtractionMode.async_
    assert ExtractionMode("sync_flush") is ExtractionMode.sync_flush
    assert ExtractionMode("lazy") is ExtractionMode.lazy
    assert ExtractionMode("no_extract") is ExtractionMode.no_extract

    rt = MemoryRuntime(InMemoryRepository(), default_workspace_id="ws_test")
    run, step = await _started(rt)
    event = (await rt.write_event(_request(run.run_id, step.step_id))).event
    result = WriteEventResult(event=event)

    assert result.created_memory_ids == []
    assert result.buffered is False
    assert result.queued is False
    assert result.task_id is None
    assert result.warnings == []


async def test_sync_mode_extracts_inline():
    rt = MemoryRuntime(InMemoryRepository(), default_workspace_id="ws_test", extraction_mode=ExtractionMode.sync)
    run, step = await _started(rt)

    result = await rt.write_event(_request(run.run_id, step.step_id))

    assert result.buffered is False
    assert result.queued is False
    assert len(result.created_memory_ids) == 1
    assert await _project_runtime_values(rt) == ["bun"]


async def test_sync_flush_mode_defers_until_explicit_flush_only():
    rt = MemoryRuntime(InMemoryRepository(), default_workspace_id="ws_test", extraction_mode=ExtractionMode.sync_flush)
    run, step = await _started(rt)

    result = await rt.write_event(_request(run.run_id, step.step_id))
    await rt.retrieve_context(
        RetrievalRequest(
            run_id=run.run_id,
            step_id=step.step_id,
            query="How should I run tests?",
            strategy=RetrievalStrategy.variant_2,
        )
    )

    assert result.buffered is True
    assert result.created_memory_ids == []
    assert await _project_runtime_values(rt) == []

    flushed = await rt.flush_session("s")
    assert flushed.processed_event_count == 1
    assert len(flushed.created_memory_ids) == 1
    assert await _project_runtime_values(rt) == ["bun"]


async def test_lazy_mode_flushes_at_retrieve_boundary():
    rt = MemoryRuntime(InMemoryRepository(), default_workspace_id="ws_test", extraction_mode=ExtractionMode.lazy)
    run, step = await _started(rt)

    result = await rt.write_event(_request(run.run_id, step.step_id))
    await rt.retrieve_context(
        RetrievalRequest(
            run_id=run.run_id,
            step_id=step.step_id,
            query="How should I run tests?",
            strategy=RetrievalStrategy.variant_2,
        )
    )

    assert result.buffered is True
    assert result.queued is False
    assert await _project_runtime_values(rt) == ["bun"]


async def test_buffered_mode_remains_lazy_compatible():
    rt = MemoryRuntime(InMemoryRepository(), default_workspace_id="ws_test", extraction_mode=ExtractionMode.buffered)
    run, step = await _started(rt)

    result = await rt.write_event(_request(run.run_id, step.step_id))

    assert result.buffered is True
    assert result.queued is False
    assert await _project_runtime_values(rt) == []
    await rt.retrieve_context(
        RetrievalRequest(
            run_id=run.run_id,
            step_id=step.step_id,
            query="How should I run tests?",
            strategy=RetrievalStrategy.variant_2,
        )
    )
    assert await _project_runtime_values(rt) == ["bun"]


async def test_per_request_buffered_flushes_at_retrieve_boundary_with_sync_default():
    rt = MemoryRuntime(InMemoryRepository(), default_workspace_id="ws_test", extraction_mode=ExtractionMode.sync)
    run, step = await _started(rt)

    result = await rt.write_event(_request(run.run_id, step.step_id, mode=ExtractionMode.buffered))

    assert result.buffered is True
    assert result.created_memory_ids == []
    await rt.retrieve_context(
        RetrievalRequest(
            run_id=run.run_id,
            step_id=step.step_id,
            query="How should I run tests?",
            strategy=RetrievalStrategy.variant_2,
        )
    )
    assert await _project_runtime_values(rt) == ["bun"]


async def test_per_request_sync_flush_remains_explicit_only_with_lazy_default():
    rt = MemoryRuntime(InMemoryRepository(), default_workspace_id="ws_test", extraction_mode=ExtractionMode.lazy)
    run, step = await _started(rt)

    result = await rt.write_event(_request(run.run_id, step.step_id, mode=ExtractionMode.sync_flush))
    await rt.retrieve_context(
        RetrievalRequest(
            run_id=run.run_id,
            step_id=step.step_id,
            query="How should I run tests?",
            strategy=RetrievalStrategy.variant_2,
        )
    )

    assert result.buffered is True
    assert result.created_memory_ids == []
    assert await _project_runtime_values(rt) == []

    flushed = await rt.flush_session("s")
    assert flushed.processed_event_count == 1
    assert len(flushed.created_memory_ids) == 1
    assert await _project_runtime_values(rt) == ["bun"]


async def test_no_extract_mode_persists_event_without_memory_or_buffer():
    buffer = CandidateBuffer()
    rt = MemoryRuntime(
        InMemoryRepository(),
        default_workspace_id="ws_test",
        extraction_mode=ExtractionMode.no_extract,
        candidate_buffer=buffer,
    )
    run, step = await _started(rt)

    result = await rt.write_event(_request(run.run_id, step.step_id))

    assert result.buffered is False
    assert result.queued is False
    assert result.created_memory_ids == []
    assert len(await rt.get_timeline(run.run_id)) == 1
    assert await buffer.size("s") == 0
    assert await _project_runtime_values(rt) == []


async def test_async_mode_enqueues_event_id_only_payload_without_inline_extraction():
    envelopes: list[TaskEnvelope] = []

    async def enqueue(envelope: TaskEnvelope) -> str:
        envelopes.append(envelope)
        return envelope.task_id

    rt = MemoryRuntime(
        InMemoryRepository(),
        default_workspace_id="ws_test",
        extraction_mode=ExtractionMode.async_,
        task_enqueue=enqueue,
    )
    run, step = await _started(rt)

    result = await rt.write_event(_request(run.run_id, step.step_id))

    assert result.queued is True
    assert result.buffered is False
    assert result.task_id == envelopes[0].task_id
    assert result.created_memory_ids == []
    assert await _project_runtime_values(rt) == []
    assert envelopes[0].task_type == "memory.extract_event"
    assert envelopes[0].workspace_id == "ws_test"
    assert envelopes[0].dedupe_key == f"memory.extract_event:{result.event.event_id}"
    assert envelopes[0].payload == {
        "event_id": result.event.event_id,
        "run_id": run.run_id,
        "workspace_id": "ws_test",
        "session_id": "s",
    }


async def test_async_enqueue_failure_falls_back_to_lazy_buffer():
    async def enqueue(_envelope: TaskEnvelope) -> str:
        raise RuntimeError("broker unavailable")

    rt = MemoryRuntime(
        InMemoryRepository(),
        default_workspace_id="ws_test",
        extraction_mode=ExtractionMode.async_,
        task_enqueue=enqueue,
    )
    run, step = await _started(rt)

    result = await rt.write_event(_request(run.run_id, step.step_id))

    assert result.queued is False
    assert result.buffered is True
    assert result.task_id is None
    assert result.warnings == ["async enqueue failed; fell back to lazy buffer"]
    assert await _project_runtime_values(rt) == []

    await rt.retrieve_context(
        RetrievalRequest(
            run_id=run.run_id,
            step_id=step.step_id,
            query="How should I run tests?",
            strategy=RetrievalStrategy.variant_2,
        )
    )
    assert await _project_runtime_values(rt) == ["bun"]


async def test_async_enqueue_failure_uses_local_fallback_when_primary_buffer_fails():
    class FailingBuffer:
        async def append(self, _event):
            raise RuntimeError("redis unavailable")

        async def pending(self, session_id: str, workspace_id: str | None = None):
            return []

        async def drain(self, session_id: str, workspace_id: str | None = None):
            raise RuntimeError("redis still unavailable")

        async def size(self, session_id: str, workspace_id: str | None = None):
            return 0

        async def total_size(self, workspace_id: str | None = None):
            return 0

        async def sessions(self, workspace_id: str | None = None):
            return []

    async def enqueue(_envelope: TaskEnvelope) -> str:
        raise RuntimeError("broker unavailable")

    rt = MemoryRuntime(
        InMemoryRepository(),
        default_workspace_id="ws_test",
        extraction_mode=ExtractionMode.async_,
        candidate_buffer=FailingBuffer(),
        task_enqueue=enqueue,
    )
    run, step = await _started(rt)

    result = await rt.write_event(_request(run.run_id, step.step_id))

    assert result.queued is False
    assert result.buffered is True
    assert result.warnings == [
        "async enqueue failed; fell back to lazy buffer",
        "primary lazy buffer failed; used local fallback buffer",
    ]

    flushed = await rt.flush_session("s")
    assert flushed.processed_event_count == 1
    assert len(flushed.created_memory_ids) == 1
    assert await _project_runtime_values(rt) == ["bun"]


async def test_lazy_mode_uses_local_fallback_when_primary_buffer_fails():
    class FailingBuffer:
        async def append(self, _event):
            raise RuntimeError("redis unavailable")

        async def pending(self, session_id: str, workspace_id: str | None = None):
            return []

        async def drain(self, session_id: str, workspace_id: str | None = None):
            raise RuntimeError("redis still unavailable")

        async def size(self, session_id: str, workspace_id: str | None = None):
            return 0

        async def total_size(self, workspace_id: str | None = None):
            return 0

        async def sessions(self, workspace_id: str | None = None):
            return []

    rt = MemoryRuntime(
        InMemoryRepository(),
        default_workspace_id="ws_test",
        extraction_mode=ExtractionMode.lazy,
        candidate_buffer=FailingBuffer(),
    )
    run, step = await _started(rt)

    result = await rt.write_event(_request(run.run_id, step.step_id))

    assert result.buffered is True
    assert result.queued is False
    assert result.warnings == ["primary lazy buffer failed; used local fallback buffer"]

    flushed = await rt.flush_session("s")
    assert flushed.processed_event_count == 1
    assert len(flushed.created_memory_ids) == 1
    assert await _project_runtime_values(rt) == ["bun"]
