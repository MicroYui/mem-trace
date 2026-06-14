"""Runtime integration tests for the candidate buffer / idle flush (P2).

Exercises the ``buffered`` extraction mode (architecture.md §12.1): write_event
defers extraction; an explicit flush or a lazy flush at a window boundary
(retrieve_context / finish_step / complete_run) runs the deferred write rules.
The default ``sync`` runtime is unchanged (covered by other suites).
"""
from __future__ import annotations

from app.runtime.memory_runtime import MemoryRuntime
from app.memory.candidate_buffer import CandidateBuffer
from app.runtime.models import (
    AgentStep,
    BranchStatus,
    CompleteRunRequest,
    EventRole,
    EventType,
    ExtractionMode,
    FinishStepRequest,
    MemoryStatus,
    MemoryType,
    RetrievalRequest,
    RetrievalStrategy,
    RollbackRequest,
    RunStatus,
    StartRunRequest,
    StartStepRequest,
    StepStatus,
    WriteEventRequest,
)
from app.runtime.repository import InMemoryRepository


def _buffered_runtime() -> MemoryRuntime:
    return MemoryRuntime(
        InMemoryRepository(),
        default_workspace_id="ws_test",
        extraction_mode=ExtractionMode.buffered,
    )


def _ev(run_id, step_id, content, *, mode=None):
    return WriteEventRequest(
        run_id=run_id, step_id=step_id, role=EventRole.user,
        event_type=EventType.message, content=content, extraction_mode=mode,
    )


async def _project_memories(rt, ws="ws_test"):
    return [
        m for m in await rt.list_memories(workspace_id=ws)
        if m.memory_type == MemoryType.project and m.key == "project.runtime"
    ]


async def test_buffered_write_defers_extraction():
    rt = _buffered_runtime()
    run = await rt.start_run(StartRunRequest(session_id="s", task="t"))
    s1 = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="planning"))
    res = await rt.write_event(_ev(run.run_id, s1.step_id, "这个项目使用 Bun"))
    # event persisted, but extraction deferred
    assert res.buffered is True
    assert res.created_memory_ids == []
    assert await _project_memories(rt) == []
    # raw event is still persisted (not lost)
    assert len(await rt.get_timeline(run.run_id)) == 1


async def test_explicit_flush_runs_deferred_extraction():
    rt = _buffered_runtime()
    run = await rt.start_run(StartRunRequest(session_id="s", task="t"))
    s1 = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="planning"))
    await rt.write_event(_ev(run.run_id, s1.step_id, "这个项目使用 Bun"))

    result = await rt.flush_session("s")
    assert result.processed_event_count == 1
    assert len(result.created_memory_ids) == 1
    active = [m for m in await _project_memories(rt) if m.status == MemoryStatus.active]
    assert len(active) == 1 and active[0].value == "bun"


async def test_flush_is_idempotent():
    rt = _buffered_runtime()
    run = await rt.start_run(StartRunRequest(session_id="s", task="t"))
    s1 = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="planning"))
    await rt.write_event(_ev(run.run_id, s1.step_id, "这个项目使用 Bun"))
    await rt.flush_session("s")
    second = await rt.flush_session("s")
    assert second.processed_event_count == 0
    assert second.created_memory_ids == []
    active = [m for m in await _project_memories(rt) if m.status == MemoryStatus.active]
    assert len(active) == 1


async def test_lazy_flush_on_retrieve_context():
    rt = _buffered_runtime()
    run = await rt.start_run(StartRunRequest(session_id="s", task="run tests"))
    s1 = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="planning"))
    await rt.write_event(_ev(run.run_id, s1.step_id, "这个项目使用 Bun"))
    # no explicit flush; retrieve_context should lazily flush first
    ctx = await rt.retrieve_context(RetrievalRequest(
        run_id=run.run_id, step_id=s1.step_id,
        query="How should I run the suite?",
        strategy=RetrievalStrategy.variant_2,
    ))
    proj_text = " ".join(b.content.lower() for b in ctx.context_blocks if b.type == "project_memory")
    assert "bun" in proj_text


async def test_lazy_flush_on_finish_step():
    rt = _buffered_runtime()
    run = await rt.start_run(StartRunRequest(session_id="s", task="t"))
    s1 = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="planning"))
    await rt.write_event(_ev(run.run_id, s1.step_id, "这个项目使用 Bun"))
    await rt.finish_step(FinishStepRequest(run_id=run.run_id, step_id=s1.step_id,
                                           status=StepStatus.completed))
    active = [m for m in await _project_memories(rt) if m.status == MemoryStatus.active]
    assert len(active) == 1 and active[0].value == "bun"


async def test_failed_finish_does_not_extract_buffered_user_memory_as_completed():
    rt = _buffered_runtime()
    run = await rt.start_run(StartRunRequest(session_id="s", task="t"))
    s1 = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="bad plan"))
    await rt.write_event(_ev(run.run_id, s1.step_id, "这个项目使用 Bun"))

    await rt.finish_step(FinishStepRequest(run_id=run.run_id, step_id=s1.step_id, status=StepStatus.failed))

    assert await _project_memories(rt) == []
    flushed = await rt.flush_session("s")
    assert flushed.processed_event_count == 0


async def test_per_request_sync_override_extracts_inline():
    rt = _buffered_runtime()
    run = await rt.start_run(StartRunRequest(session_id="s", task="t"))
    s1 = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="planning"))
    # force sync even though runtime default is buffered (e.g. explicit correction)
    res = await rt.write_event(_ev(run.run_id, s1.step_id, "这个项目使用 Bun",
                                   mode=ExtractionMode.sync))
    assert res.buffered is False
    assert len(res.created_memory_ids) == 1
    active = [m for m in await _project_memories(rt) if m.status == MemoryStatus.active]
    assert len(active) == 1 and active[0].value == "bun"


async def test_secret_event_is_not_buffered():
    rt = _buffered_runtime()
    run = await rt.start_run(StartRunRequest(session_id="s", task="t"))
    s1 = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="planning"))
    res = await rt.write_event(_ev(run.run_id, s1.step_id,
                                   "my api key is sk-ABCDEF1234567890ABCDEF"))
    assert res.buffered is False
    # flushing produces nothing from a secret event
    flushed = await rt.flush_session("s")
    assert flushed.processed_event_count == 0


async def test_buffered_event_metadata_is_redacted_before_buffering():
    buffer = CandidateBuffer()
    rt = MemoryRuntime(
        InMemoryRepository(),
        default_workspace_id="ws_test",
        extraction_mode=ExtractionMode.buffered,
        candidate_buffer=buffer,
    )
    run = await rt.start_run(StartRunRequest(session_id="s", task="t"))
    step = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="planning"))

    await rt.write_event(
        WriteEventRequest(
            run_id=run.run_id,
            step_id=step.step_id,
            role=EventRole.user,
            event_type=EventType.message,
            content="safe content",
            metadata={"password": "hunter2", "nested": {"body": "api_key=sk-ABCDEF1234567890ABCDEF"}},
        )
    )

    pending = await buffer.pending("s")
    assert pending[0].metadata == {"password": "[REDACTED]", "nested": {"body": "[REDACTED]"}}


async def test_buffered_flush_resolves_conflict_in_write_order():
    rt = _buffered_runtime()
    run = await rt.start_run(StartRunRequest(session_id="s", task="t"))
    s1 = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="planning"))
    await rt.write_event(_ev(run.run_id, s1.step_id, "这个项目使用 Node.js"))
    await rt.write_event(_ev(run.run_id, s1.step_id, "这个项目使用 Bun"))
    await rt.flush_session("s")

    mems = await _project_memories(rt)
    active = [m for m in mems if m.status == MemoryStatus.active]
    superseded = [m for m in mems if m.status == MemoryStatus.superseded]
    assert len(active) == 1 and active[0].value == "bun"
    assert len(superseded) == 1 and superseded[0].value == "nodejs"
    assert superseded[0].superseded_by == active[0].memory_id


async def test_rollback_flushes_then_isolates_buffered_branch_memory():
    """A branch's buffered memory must still be isolated when rolled back.

    Without a flush-before-rollback, the tool-evidence memory would stay pending
    and a later flush would resurrect it as a completed-branch memory. Rollback
    flushes first so the memory is materialized and flipped to rolled_back,
    matching sync-mode failed-branch isolation.
    """
    rt = _buffered_runtime()
    run = await rt.start_run(StartRunRequest(session_id="s", task="t"))
    s1 = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="plan A"))
    await rt.write_event(WriteEventRequest(
        run_id=run.run_id, step_id=s1.step_id, role=EventRole.tool,
        event_type=EventType.tool_result, content="ran plan A tool", status="success",
    ))
    # rollback before any explicit flush
    await rt.rollback_branch(RollbackRequest(run_id=run.run_id, step_id=s1.step_id,
                                             reason="plan A abandoned"))

    tool_mems = [
        m for m in await rt.list_memories(workspace_id="ws_test")
        if m.memory_type == MemoryType.tool_evidence
    ]
    assert len(tool_mems) == 1
    assert tool_mems[0].branch_status == BranchStatus.rolled_back
    # a subsequent flush does not resurrect a new completed-branch copy
    again = await rt.flush_session("s")
    assert again.processed_event_count == 0


async def test_rollback_missing_state_node_does_not_flush_buffered_memories():
    rt = _buffered_runtime()
    run = await rt.start_run(StartRunRequest(session_id="s", task="t"))
    good = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="plan A"))
    await rt.write_event(_ev(run.run_id, good.step_id, "这个项目使用 Bun"))
    corrupt = AgentStep(workspace_id=run.workspace_id, run_id=run.run_id, state_node_id="missing_node")
    await rt._repo.add_step(corrupt)  # noqa: SLF001 - seed intentionally corrupt state

    from app.runtime.memory_runtime import StateTreeError

    try:
        await rt.rollback_branch(RollbackRequest(run_id=run.run_id, step_id=corrupt.step_id, reason="corrupt"))
    except StateTreeError:
        pass
    else:  # pragma: no cover - assertion clarity if the guard regresses
        raise AssertionError("rollback_branch should reject a corrupt state-node reference")

    assert await _project_memories(rt) == []
    flushed = await rt.flush_session("s")
    assert flushed.processed_event_count == 1


async def test_delayed_process_event_extraction_skips_rolled_back_state_node():
    rt = MemoryRuntime(InMemoryRepository(), default_workspace_id="ws_test")
    run = await rt.start_run(StartRunRequest(session_id="s", task="t"))
    step = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="plan A"))
    res = await rt.write_event(_ev(run.run_id, step.step_id, "这个项目使用 Bun", mode=ExtractionMode.buffered))
    event_id = res.event.event_id

    await rt.rollback_branch(RollbackRequest(run_id=run.run_id, step_id=step.step_id, reason="bad branch"))
    # Simulate a delayed async worker trying to process the event after rollback.
    created = await rt.process_event_extraction(event_id)

    assert created == []
    completed_branch = [m for m in await _project_memories(rt) if m.branch_status == BranchStatus.completed]
    assert completed_branch == []


async def test_delayed_process_event_extraction_skips_failed_run():
    rt = MemoryRuntime(InMemoryRepository(), default_workspace_id="ws_test")
    run = await rt.start_run(StartRunRequest(session_id="s", task="t"))
    step = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="plan A"))
    res = await rt.write_event(_ev(run.run_id, step.step_id, "这个项目使用 Bun", mode=ExtractionMode.buffered))

    await rt.complete_run(CompleteRunRequest(run_id=run.run_id, status=RunStatus.failed))
    created = await rt.process_event_extraction(res.event.event_id)

    assert created == []


async def test_process_event_extraction_is_persistently_idempotent_for_same_event():
    rt = MemoryRuntime(InMemoryRepository(), default_workspace_id="ws_test")
    run = await rt.start_run(StartRunRequest(session_id="s", task="t"))
    step = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="plan A"))
    res = await rt.write_event(WriteEventRequest(
        run_id=run.run_id,
        step_id=step.step_id,
        role=EventRole.tool,
        event_type=EventType.tool_result,
        content="bun test passed",
        status="success",
        extraction_mode=ExtractionMode.buffered,
    ))

    first = await rt.process_event_extraction(res.event.event_id)
    second = await rt.process_event_extraction(res.event.event_id)

    assert len(first) == 1
    assert second == []
    tool_mems = [
        m for m in await rt.list_memories(workspace_id="ws_test")
        if m.memory_type == MemoryType.tool_evidence and m.source_event_id == res.event.event_id
    ]
    assert len(tool_mems) == 1


async def test_retrieve_context_rejects_workspace_mismatch_before_lazy_flush():
    rt = _buffered_runtime()
    run = await rt.start_run(StartRunRequest(session_id="s", task="t"))
    step = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="plan A"))
    await rt.write_event(_ev(run.run_id, step.step_id, "这个项目使用 Bun"))

    from app.runtime.memory_runtime import StateTreeError

    try:
        await rt.retrieve_context(
            RetrievalRequest(
                run_id=run.run_id,
                step_id=step.step_id,
                workspace_id="other_ws",
                query="runtime",
            )
        )
    except StateTreeError:
        pass
    else:  # pragma: no cover - assertion clarity if the guard regresses
        raise AssertionError("retrieve_context should reject mismatched workspace")

    assert await _project_memories(rt) == []
    flushed = await rt.flush_session("s")
    assert flushed.processed_event_count == 1
