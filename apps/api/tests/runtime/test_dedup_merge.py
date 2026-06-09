"""Runtime integration tests for dedup/merge + conflict resolution (mvp.md §2.3).

Exercises the write-path hook in MemoryRuntime: repeated identical project
preferences dedup into one active memory; a newer conflicting preference
supersedes the older one (with superseded_by lineage); superseded memories are
never recalled into context; and resolution is idempotent.
"""
from __future__ import annotations

from app.runtime.models import (
    EventRole,
    EventType,
    FinishStepRequest,
    MemoryStatus,
    MemoryType,
    RetrievalRequest,
    RetrievalStrategy,
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


async def _project_memories(runtime, ws="ws_test"):
    return [
        m for m in await runtime.list_memories(workspace_id=ws)
        if m.memory_type == MemoryType.project and m.key == "project.runtime"
    ]


async def test_repeated_identical_preference_dedups_to_one_active(runtime):
    run = await runtime.start_run(StartRunRequest(session_id="s", task="t"))
    s1 = await runtime.start_step(StartStepRequest(run_id=run.run_id, intent="planning"))
    for _ in range(3):
        await runtime.write_event(_ev(run.run_id, s1.step_id, EventRole.user,
                                       EventType.message, content="这个项目使用 Bun"))

    mems = await _project_memories(runtime)
    active = [m for m in mems if m.status == MemoryStatus.active]
    assert len(active) == 1
    assert active[0].value == "bun"
    # the duplicate writes were folded in, not kept as separate active rows
    assert all(m.status == MemoryStatus.active for m in mems)
    assert len(mems) == 1


async def test_conflicting_preference_supersedes_older_with_lineage(runtime):
    run = await runtime.start_run(StartRunRequest(session_id="s", task="t"))
    s1 = await runtime.start_step(StartStepRequest(run_id=run.run_id, intent="planning"))
    await runtime.write_event(_ev(run.run_id, s1.step_id, EventRole.user,
                                   EventType.message, content="这个项目使用 Node.js"))
    await runtime.write_event(_ev(run.run_id, s1.step_id, EventRole.user,
                                   EventType.message, content="这个项目使用 Bun"))

    mems = await _project_memories(runtime)
    active = [m for m in mems if m.status == MemoryStatus.active]
    superseded = [m for m in mems if m.status == MemoryStatus.superseded]
    assert len(active) == 1 and active[0].value == "bun"
    assert len(superseded) == 1 and superseded[0].value == "nodejs"
    # lineage points at the surviving Bun memory
    assert superseded[0].superseded_by == active[0].memory_id


async def test_superseded_preference_not_recalled_into_context(runtime):
    run = await runtime.start_run(StartRunRequest(session_id="s", task="run tests"))
    s1 = await runtime.start_step(StartStepRequest(run_id=run.run_id, intent="planning"))
    await runtime.write_event(_ev(run.run_id, s1.step_id, EventRole.user,
                                   EventType.message, content="这个项目使用 Node.js"))
    await runtime.write_event(_ev(run.run_id, s1.step_id, EventRole.user,
                                   EventType.message, content="这个项目使用 Bun"))
    await runtime.finish_step(FinishStepRequest(run_id=run.run_id, step_id=s1.step_id,
                                                status=StepStatus.completed, summary="settled on Bun"))
    s2 = await runtime.start_step(StartStepRequest(run_id=run.run_id, intent="debugging",
                                                   goal="choose runner"))
    ctx = await runtime.retrieve_context(RetrievalRequest(
        run_id=run.run_id, step_id=s2.step_id,
        query="How should I run the test suite? Earlier I mentioned Node.",
        strategy=RetrievalStrategy.variant_2,
    ))
    proj_text = " ".join(b.content.lower() for b in ctx.context_blocks if b.type == "project_memory")
    assert "bun" in proj_text
    assert "nodejs" not in proj_text


async def test_resolution_is_idempotent(runtime):
    run = await runtime.start_run(StartRunRequest(session_id="s", task="t"))
    s1 = await runtime.start_step(StartStepRequest(run_id=run.run_id, intent="planning"))
    # node, bun, bun, node-again: end state must have exactly one active value
    for content in ("这个项目使用 Node.js", "这个项目使用 Bun", "这个项目使用 Bun", "这个项目使用 Node.js"):
        await runtime.write_event(_ev(run.run_id, s1.step_id, EventRole.user,
                                       EventType.message, content=content))
    mems = await _project_memories(runtime)
    active = [m for m in mems if m.status == MemoryStatus.active]
    assert len(active) == 1
