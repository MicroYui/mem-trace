"""Tests for the cold-path run summarizer and completed-run / procedural reuse.

Covers mvp.md section 2.3 (completed run summary + procedural memory) and the
P2 reuse case: a successful run sediments a reusable procedural memory that a
later, similar run recalls into its packed context.
"""
from __future__ import annotations

from app.runtime.models import (
    CompleteRunRequest,
    EventRole,
    EventType,
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


def _ev(run_id, step_id, role, etype, *, content=None, tool_name=None, status=None):
    return WriteEventRequest(
        run_id=run_id, step_id=step_id, role=role, event_type=etype,
        content=content, tool_name=tool_name, status=status,
    )


async def _seed_successful_run(runtime, ws_task="fix failing pytest suite"):
    run = await runtime.start_run(StartRunRequest(session_id="s1", task=ws_task))
    p1 = await runtime.start_step(StartStepRequest(run_id=run.run_id, intent="planning"))
    await runtime.write_event(_ev(run.run_id, p1.step_id, EventRole.user, EventType.message,
                                  content="这个项目使用 Bun"))
    await runtime.finish_step(FinishStepRequest(run_id=run.run_id, step_id=p1.step_id,
                                                status=StepStatus.completed, summary="confirmed project uses Bun"))
    d1 = await runtime.start_step(StartStepRequest(run_id=run.run_id, intent="debugging",
                                                   goal="fix failing pytest suite"))
    await runtime.write_event(_ev(run.run_id, d1.step_id, EventRole.tool, EventType.tool_call,
                                  tool_name="bash", content="bun test"))
    await runtime.write_event(_ev(run.run_id, d1.step_id, EventRole.tool, EventType.tool_result, status="success",
                                  content="Fixed the failing pytest suite by running bun test; all tests passed."))
    await runtime.finish_step(FinishStepRequest(run_id=run.run_id, step_id=d1.step_id,
                                                status=StepStatus.completed, summary="fixed pytest suite with bun test"))
    return run


async def test_complete_run_marks_completed_and_writes_episodic_and_procedural(runtime):
    run = await _seed_successful_run(runtime)
    result = await runtime.complete_run(CompleteRunRequest(run_id=run.run_id))

    assert result.run.status == RunStatus.completed
    assert result.run.finished_at is not None
    assert result.summary_memory_id is not None
    assert result.procedural_memory_id is not None
    assert len(result.created_memory_ids) == 2

    mems = {m.memory_id: m for m in await runtime.list_memories(workspace_id=run.workspace_id)}
    episodic = mems[result.summary_memory_id]
    procedural = mems[result.procedural_memory_id]
    assert episodic.memory_type == MemoryType.episodic
    assert procedural.memory_type == MemoryType.procedural
    assert procedural.source_run_id == run.run_id
    assert "bun" in procedural.content.lower()
    # procedural memory is a high-trust, reusable success path
    assert procedural.trust_score >= 0.8
    assert procedural.status == MemoryStatus.active


async def test_failed_run_does_not_produce_procedural_memory(runtime):
    run = await runtime.start_run(StartRunRequest(session_id="s1", task="broken task"))
    s1 = await runtime.start_step(StartStepRequest(run_id=run.run_id, intent="debugging"))
    await runtime.write_event(_ev(run.run_id, s1.step_id, EventRole.tool, EventType.tool_result, status="failed",
                                  content="it failed"))
    await runtime.finish_step(FinishStepRequest(run_id=run.run_id, step_id=s1.step_id,
                                                status=StepStatus.failed, error_message="boom"))

    result = await runtime.complete_run(CompleteRunRequest(run_id=run.run_id, status=RunStatus.failed))
    assert result.summary_memory_id is not None  # episodic summary always written
    assert result.procedural_memory_id is None   # no reusable procedure for a failed run


async def test_complete_run_is_idempotent(runtime):
    run = await _seed_successful_run(runtime)
    await runtime.complete_run(CompleteRunRequest(run_id=run.run_id))
    await runtime.complete_run(CompleteRunRequest(run_id=run.run_id))

    mems = await runtime.list_memories(workspace_id=run.workspace_id)
    procedural = [m for m in mems if m.memory_type == MemoryType.procedural]
    active_procedural = [m for m in procedural if m.status == MemoryStatus.active]
    # both runs wrote a procedural memory, but only the latest stays active
    assert len(active_procedural) == 1
    assert len(procedural) == 2


async def test_procedural_memory_is_recalled_into_later_run_context(runtime):
    first = await _seed_successful_run(runtime)
    await runtime.complete_run(CompleteRunRequest(run_id=first.run_id))

    # a second, similar run in the same workspace
    second = await runtime.start_run(StartRunRequest(session_id="s2", task="fix failing pytest suite again"))
    s2 = await runtime.start_step(StartStepRequest(run_id=second.run_id, intent="debugging",
                                                   goal="fix failing pytest suite"))
    ctx = await runtime.retrieve_context(
        RetrievalRequest(run_id=second.run_id, step_id=s2.step_id,
                         query="How did we fix the failing pytest suite last time?",
                         strategy=RetrievalStrategy.variant_2)
    )
    procedural_blocks = [b for b in ctx.context_blocks if b.type == "procedural"]
    assert procedural_blocks, "expected a procedural hint block recalled from the prior run"
    assert "bun" in procedural_blocks[0].content.lower()
