"""Runtime integration tests for the candidate buffer / idle flush (P2).

Exercises the ``buffered`` extraction mode (architecture.md §12.1): write_event
defers extraction; an explicit flush or a lazy flush at a window boundary
(retrieve_context / finish_step / complete_run) runs the deferred write rules.
The default ``sync`` runtime is unchanged (covered by other suites).
"""
from __future__ import annotations

from app.runtime.memory_runtime import MemoryRuntime
from app.runtime.models import (
    BranchStatus,
    EventRole,
    EventType,
    ExtractionMode,
    FinishStepRequest,
    MemoryStatus,
    MemoryType,
    RetrievalRequest,
    RetrievalStrategy,
    RollbackRequest,
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
