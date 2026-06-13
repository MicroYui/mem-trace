"""Replay conformance tests for side-effect-free guarantees."""
from __future__ import annotations

import pytest

from app.runtime.memory_runtime import MemoryRuntime
from app.runtime.models import BranchStatus, MemoryItem, MemoryType, RetrievalRequest, RetrievalStrategy, StartRunRequest, StartStepRequest
from app.runtime.repository import InMemoryRepository


@pytest.mark.asyncio
async def test_replay_access_has_no_access_or_memory_side_effects():
    repo = InMemoryRepository()
    runtime = MemoryRuntime(repo, default_workspace_id="ws_conf_replay")
    run = await runtime.start_run(StartRunRequest(workspace_id="ws_conf_replay", session_id="s", task="replay"))
    step = await runtime.start_step(StartStepRequest(run_id=run.run_id, intent="recall"))
    memory = await repo.add_memory(
        MemoryItem(
            workspace_id="ws_conf_replay",
            run_id=run.run_id,
            memory_type=MemoryType.project,
            content="Replay conformance uses Bun",
            branch_status=BranchStatus.completed,
        )
    )
    ctx = await runtime.retrieve_context(
        RetrievalRequest(
            run_id=run.run_id,
            step_id=step.step_id,
            query="Bun",
            strategy=RetrievalStrategy.variant_2,
        )
    )
    before_accesses = await repo.list_access_logs(workspace_id="ws_conf_replay")
    before_memories = await repo.list_memories(workspace_id="ws_conf_replay")
    before_gate_logs = await repo.list_gate_logs(ctx.access_id)
    before_profile_events = await repo.list_profile_events(run_id=run.run_id)
    before_compaction_logs = await repo.list_compaction_logs(run_id=run.run_id, workspace_id="ws_conf_replay")

    replay = await runtime.replay_access(ctx.access_id)

    after_accesses = await repo.list_access_logs(workspace_id="ws_conf_replay")
    after_memories = await repo.list_memories(workspace_id="ws_conf_replay")
    after_gate_logs = await repo.list_gate_logs(ctx.access_id)
    after_profile_events = await repo.list_profile_events(run_id=run.run_id)
    after_compaction_logs = await repo.list_compaction_logs(run_id=run.run_id, workspace_id="ws_conf_replay")
    assert replay is not None
    assert [access.access_id for access in after_accesses] == [access.access_id for access in before_accesses]
    assert [(mem.memory_id, mem.access_count) for mem in after_memories] == [
        (mem.memory_id, mem.access_count) for mem in before_memories
    ]
    assert [gate.gate_id for gate in after_gate_logs] == [gate.gate_id for gate in before_gate_logs]
    assert [event.profile_id for event in after_profile_events] == [
        event.profile_id for event in before_profile_events
    ]
    assert [log.compaction_id for log in after_compaction_logs] == [
        log.compaction_id for log in before_compaction_logs
    ]
    assert (await repo.get_memory(memory.memory_id)).access_count == 1  # type: ignore[union-attr]
