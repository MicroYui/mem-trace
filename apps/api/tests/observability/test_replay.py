"""Replay service tests for Phase 3-A Issue 3."""
from __future__ import annotations

import pytest

from app.runtime.memory_runtime import MemoryRuntime
from app.runtime.models import (
    BranchStatus,
    FinishStepRequest,
    MemoryItem,
    MemoryStatus,
    MemoryType,
    RetrievalRequest,
    RetrievalStrategy,
    StartRunRequest,
    StartStepRequest,
    StepStatus,
)
from app.runtime.repository import InMemoryRepository


async def _seed_runtime() -> tuple[MemoryRuntime, InMemoryRepository, str, str, str]:
    repo = InMemoryRepository()
    runtime = MemoryRuntime(repo, default_workspace_id="ws_replay")
    run = await runtime.start_run(
        StartRunRequest(session_id="s_replay", task="fix tests", workspace_id="ws_replay")
    )
    step = await runtime.start_step(StartStepRequest(run_id=run.run_id, intent="debug tests"))
    memory = await repo.add_memory(
        MemoryItem(
            workspace_id="ws_replay",
            run_id=run.run_id,
            memory_type=MemoryType.project,
            key="project.runtime",
            value="bun",
            content="This project uses Bun to run tests",
            branch_status=BranchStatus.completed,
        )
    )
    return runtime, repo, run.run_id, step.step_id, memory.memory_id


async def _retrieve_once(runtime: MemoryRuntime, run_id: str, step_id: str, *, top_k: int = 5) -> str:
    ctx = await runtime.retrieve_context(
        RetrievalRequest(
            run_id=run_id,
            step_id=step_id,
            query="run tests with bun",
            strategy=RetrievalStrategy.variant_2,
            token_budget=128,
            top_k=top_k,
        )
    )
    return ctx.access_id


@pytest.mark.asyncio
async def test_replay_access_has_no_drift_when_repository_unchanged():
    runtime, _, run_id, step_id, memory_id = await _seed_runtime()
    access_id = await _retrieve_once(runtime, run_id, step_id, top_k=3)

    replay = await runtime.replay_access(access_id)

    assert replay is not None
    assert replay.access_id == access_id
    assert replay.run_id == run_id
    assert replay.step_id == step_id
    assert replay.workspace_id == "ws_replay"
    assert replay.query == "run tests with bun"
    assert replay.strategy == RetrievalStrategy.variant_2
    assert replay.token_budget == 128
    assert replay.top_k == 3
    assert [c.memory_id for c in replay.original_candidates] == [memory_id]
    assert [c.memory_id for c in replay.replayed_candidates] == [memory_id]
    assert [g.memory_id for g in replay.original_gate_decisions] == [memory_id]
    assert [g.memory_id for g in replay.replayed_gate_decisions] == [memory_id]
    assert replay.original_context_blocks_reconstructed
    assert replay.replayed_context_blocks
    assert replay.diffs == []
    assert replay.metrics["candidate_count"] == 1
    assert replay.metrics["accepted_count"] == 1
    assert replay.metrics["drift_count"] == 0
    assert replay.warnings == []


@pytest.mark.asyncio
async def test_replay_detects_decision_drift_after_memory_branch_status_change():
    runtime, repo, run_id, step_id, memory_id = await _seed_runtime()
    access_id = await _retrieve_once(runtime, run_id, step_id)
    memory = await repo.get_memory(memory_id)
    assert memory is not None
    memory.branch_status = BranchStatus.rolled_back
    await repo.update_memory(memory)

    replay = await runtime.replay_access(access_id)

    assert replay is not None
    decision_diffs = [d for d in replay.diffs if d.kind == "decision_changed"]
    assert decision_diffs
    assert decision_diffs[0].memory_id == memory_id
    assert decision_diffs[0].original == "accept"
    assert decision_diffs[0].replayed == "reject"
    assert decision_diffs[0].severity == "warning"
    assert any(d.kind == "reject_reason_changed" and d.replayed == "rolled_back" for d in replay.diffs)


@pytest.mark.asyncio
async def test_replay_detects_candidate_added_and_removed():
    runtime, repo, run_id, step_id, memory_id = await _seed_runtime()
    access_id = await _retrieve_once(runtime, run_id, step_id, top_k=5)
    original_memory = await repo.get_memory(memory_id)
    assert original_memory is not None
    original_memory.status = MemoryStatus.superseded
    await repo.update_memory(original_memory)
    added = await repo.add_memory(
        MemoryItem(
            workspace_id="ws_replay",
            run_id=run_id,
            memory_type=MemoryType.project,
            key="project.test_command",
            value="bun test",
            content="Run the test suite with bun test",
            branch_status=BranchStatus.completed,
        )
    )

    replay = await runtime.replay_access(access_id)

    assert replay is not None
    assert any(d.kind == "candidate_removed" and d.memory_id == memory_id for d in replay.diffs)
    assert any(d.kind == "candidate_added" and d.memory_id == added.memory_id for d in replay.diffs)
    assert {d.severity for d in replay.diffs if d.kind in {"candidate_added", "candidate_removed"}} == {"warning"}


@pytest.mark.asyncio
async def test_replay_does_not_increment_access_count_or_write_logs():
    runtime, repo, run_id, step_id, memory_id = await _seed_runtime()
    access_id = await _retrieve_once(runtime, run_id, step_id)
    before_access_logs = len(await repo.list_access_logs())
    before_gate_logs = len(await repo.list_gate_logs(access_id))
    before_profile_events = len(await repo.list_profile_events())
    before_memory = await repo.get_memory(memory_id)
    assert before_memory is not None
    before_access_count = before_memory.access_count

    replay = await runtime.replay_access(access_id)

    assert replay is not None
    after_memory = await repo.get_memory(memory_id)
    assert after_memory is not None
    assert len(await repo.list_access_logs()) == before_access_logs
    assert len(await repo.list_gate_logs(access_id)) == before_gate_logs
    assert len(await repo.list_profile_events()) == before_profile_events
    assert after_memory.access_count == before_access_count


@pytest.mark.asyncio
async def test_replay_run_replays_all_accesses_for_run():
    runtime, _, run_id, step_id, _ = await _seed_runtime()
    first_access = await _retrieve_once(runtime, run_id, step_id, top_k=2)
    second_access = await _retrieve_once(runtime, run_id, step_id, top_k=4)

    result = await runtime.replay_run(run_id)

    assert result.run_id == run_id
    assert result.access_count == 2
    assert [item.access_id for item in result.replayed] == [first_access, second_access]
    assert result.summary["drift_count"] == 0
    assert result.summary["critical_drift_count"] == 0


@pytest.mark.asyncio
async def test_replay_access_returns_none_for_missing_access():
    runtime, _, _, _, _ = await _seed_runtime()

    assert await runtime.replay_access("acc_missing") is None


@pytest.mark.asyncio
async def test_original_context_reconstruction_uses_access_step_not_current_active_step():
    runtime, repo, run_id, step_id, _ = await _seed_runtime()
    access_id = await _retrieve_once(runtime, run_id, step_id)
    await runtime.finish_step(FinishStepRequest(run_id=run_id, step_id=step_id, status=StepStatus.completed))
    await runtime.start_step(StartStepRequest(run_id=run_id, intent="second active step"))

    replay = await runtime.replay_access(access_id)

    assert replay is not None
    original_active = [b for b in replay.original_context_blocks_reconstructed if b.type == "active_state"]
    replayed_active = [b for b in replay.replayed_context_blocks if b.type == "active_state"]
    assert original_active and original_active[0].provenance is not None
    assert original_active[0].provenance.step_id == step_id
    assert not [b for b in replay.original_context_blocks_reconstructed if b.type == "active_path"]
    assert replayed_active and replayed_active[0].content == "second active step"
    assert any(d.kind in {"context_block_added", "context_block_removed"} for d in replay.diffs)
