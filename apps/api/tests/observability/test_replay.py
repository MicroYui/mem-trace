"""Replay service tests for Phase 3-A Issue 3."""
from __future__ import annotations

import pytest

from app.runtime.memory_runtime import MemoryRuntime
from app.runtime.models import (
    BranchStatus,
    CompactionKind,
    CompactionProvider,
    ContextCompactionLog,
    EventRole,
    EventType,
    FinishStepRequest,
    MemoryItem,
    MemoryStatus,
    MemoryType,
    RetrievalRequest,
    RetrievalStrategy,
    RiskFlags,
    RollbackRequest,
    StartRunRequest,
    StartStepRequest,
    StepStatus,
    WriteEventRequest,
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


async def _seed_failure_learning_runtime() -> tuple[MemoryRuntime, InMemoryRepository, str, str]:
    repo = InMemoryRepository()
    runtime = MemoryRuntime(repo, default_workspace_id="ws_replay_negative")
    run = await runtime.start_run(
        StartRunRequest(session_id="s_negative", task="fix tests", workspace_id="ws_replay_negative")
    )
    planning = await runtime.start_step(StartStepRequest(run_id=run.run_id, intent="planning"))
    await runtime.write_event(
        WriteEventRequest(
            run_id=run.run_id,
            step_id=planning.step_id,
            role=EventRole.user,
            event_type=EventType.message,
            content="This project uses Bun to run tests, not npm.",
        )
    )
    await runtime.finish_step(FinishStepRequest(run_id=run.run_id, step_id=planning.step_id, status=StepStatus.completed))
    failed = await runtime.start_step(StartStepRequest(run_id=run.run_id, intent="debug failed npm"))
    await runtime.write_event(
        WriteEventRequest(
            run_id=run.run_id,
            step_id=failed.step_id,
            role=EventRole.tool,
            event_type=EventType.tool_result,
            status="failed",
            content="Tried npm test and it failed because npm is unavailable.",
        )
    )
    await runtime.finish_step(
        FinishStepRequest(run_id=run.run_id, step_id=failed.step_id, status=StepStatus.failed, error_message="npm")
    )
    await runtime.rollback_branch(RollbackRequest(run_id=run.run_id, step_id=failed.step_id, reason="npm"))
    recovery = await runtime.start_step(
        StartStepRequest(run_id=run.run_id, intent="recover with bun", recovery_from_step_id=failed.step_id)
    )
    return runtime, repo, run.run_id, recovery.step_id


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
    assert decision_diffs[0].replayed == "degrade"
    assert decision_diffs[0].severity == "warning"
    assert any(d.kind == "reject_reason_changed" and d.replayed == "rolled_back_degraded" for d in replay.diffs)


@pytest.mark.asyncio
async def test_replay_reconstructs_negative_evidence_without_false_context_drift():
    runtime, _, run_id, step_id = await _seed_failure_learning_runtime()
    ctx = await runtime.retrieve_context(
        RetrievalRequest(
            run_id=run_id,
            step_id=step_id,
            query="npm test failed how should I run tests now",
            strategy=RetrievalStrategy.variant_2,
            token_budget=160,
            top_k=5,
        )
    )
    assert any(block.type == "avoided_attempts" for block in ctx.context_blocks)

    replay = await runtime.replay_access(ctx.access_id)

    assert replay is not None
    assert any(block.type == "avoided_attempts" for block in replay.original_context_blocks_reconstructed)
    assert any(block.type == "avoided_attempts" for block in replay.replayed_context_blocks)
    assert not [d for d in replay.diffs if d.kind.startswith("context_block_")]
    assert not _positive_failed_blocks(replay.original_context_blocks_reconstructed)
    assert not _positive_failed_blocks(replay.replayed_context_blocks)
    degraded_count = sum(g.decision.value == "degrade" for g in replay.original_gate_decisions)
    original_negative_blocks = sum(block.type == "avoided_attempts" for block in replay.original_context_blocks_reconstructed)
    assert replay.metrics["degraded_negative_evidence_count"] == degraded_count
    assert replay.metrics["negative_evidence_block_count"] == original_negative_blocks


def _positive_failed_blocks(blocks):
    return [
        block
        for block in blocks
        if block.type != "avoided_attempts"
        and block.source != "negative_evidence"
        and "npm" in block.content.lower()
        and "failed" in block.content.lower()
    ]


@pytest.mark.asyncio
async def test_replay_sanitizes_original_and_replayed_candidate_views_for_sanitized_failure():
    repo = InMemoryRepository()
    runtime = MemoryRuntime(repo, default_workspace_id="ws_replay_sanitized_view")
    run = await runtime.start_run(
        StartRunRequest(session_id="s_sanitized_view", task="recover", workspace_id="ws_replay_sanitized_view")
    )
    step = await runtime.start_step(StartStepRequest(run_id=run.run_id, intent="recover"))
    await repo.add_memory(
        MemoryItem(
            workspace_id="ws_replay_sanitized_view",
            run_id=run.run_id,
            memory_type=MemoryType.tool_evidence,
            key="tool.raw.git push --force RAW_KEY_MARKER",
            value="git push --force RAW_VALUE_MARKER",
            content="Tried git push --force to production and it failed. RAW_FORCE_MARKER",
            branch_status=BranchStatus.failed,
            risk_flags=RiskFlags(destructive_command=True, tool_sensitive=True),
        )
    )
    ctx = await runtime.retrieve_context(
        RetrievalRequest(
            run_id=run.run_id,
            step_id=step.step_id,
            query="git push force production failed RAW_FORCE_MARKER",
            strategy=RetrievalStrategy.variant_2,
            top_k=5,
        )
    )

    replay = await runtime.replay_access(ctx.access_id)

    assert replay is not None
    serialized = repr(
        {
            "original_candidates": [candidate.model_dump() for candidate in replay.original_candidates],
            "replayed_candidates": [candidate.model_dump() for candidate in replay.replayed_candidates],
        }
    )
    assert "git push" not in serialized
    assert "--force" not in serialized
    assert "RAW_FORCE_MARKER" not in serialized
    assert "RAW_KEY_MARKER" not in serialized
    assert "RAW_VALUE_MARKER" not in serialized


@pytest.mark.asyncio
async def test_replay_marks_sanitized_reject_to_accept_as_critical():
    repo = InMemoryRepository()
    runtime = MemoryRuntime(repo, default_workspace_id="ws_replay_sanitized")
    run = await runtime.start_run(
        StartRunRequest(session_id="s_sanitized", task="recover", workspace_id="ws_replay_sanitized")
    )
    step = await runtime.start_step(StartStepRequest(run_id=run.run_id, intent="recover"))
    mem = await repo.add_memory(
        MemoryItem(
            workspace_id="ws_replay_sanitized",
            run_id=run.run_id,
            memory_type=MemoryType.tool_evidence,
            content="Tried git push --force to production and it failed.",
            branch_status=BranchStatus.failed,
            risk_flags=RiskFlags(destructive_command=True, tool_sensitive=True),
        )
    )
    ctx = await runtime.retrieve_context(
        RetrievalRequest(
            run_id=run.run_id,
            step_id=step.step_id,
            query="git push force production failed",
            strategy=RetrievalStrategy.variant_2,
            top_k=5,
        )
    )
    gate_logs = await repo.list_gate_logs(ctx.access_id)
    assert any(g.memory_id == mem.memory_id and g.reject_reason == "failed_branch_sanitized" for g in gate_logs)
    mem.branch_status = BranchStatus.completed
    mem.risk_flags = RiskFlags()
    await repo.update_memory(mem)

    replay = await runtime.replay_access(ctx.access_id)

    assert replay is not None
    assert any(
        d.kind == "decision_changed"
        and d.memory_id == mem.memory_id
        and d.original == "reject"
        and d.replayed in {"accept", "warn"}
        and d.severity == "critical"
        for d in replay.diffs
    )


@pytest.mark.asyncio
async def test_replay_marks_sanitized_reject_to_degrade_as_critical():
    repo = InMemoryRepository()
    runtime = MemoryRuntime(repo, default_workspace_id="ws_replay_sanitized_degrade")
    run = await runtime.start_run(
        StartRunRequest(session_id="s_sanitized_degrade", task="recover", workspace_id="ws_replay_sanitized_degrade")
    )
    step = await runtime.start_step(StartStepRequest(run_id=run.run_id, intent="recover"))
    mem = await repo.add_memory(
        MemoryItem(
            workspace_id="ws_replay_sanitized_degrade",
            run_id=run.run_id,
            memory_type=MemoryType.tool_evidence,
            content="Tried git push --force to production and it failed.",
            branch_status=BranchStatus.failed,
            risk_flags=RiskFlags(destructive_command=True, tool_sensitive=True),
        )
    )
    ctx = await runtime.retrieve_context(
        RetrievalRequest(
            run_id=run.run_id,
            step_id=step.step_id,
            query="git push force production failed",
            strategy=RetrievalStrategy.variant_2,
            top_k=5,
        )
    )
    mem.risk_flags = RiskFlags()
    await repo.update_memory(mem)

    replay = await runtime.replay_access(ctx.access_id)

    assert replay is not None
    assert any(
        d.kind == "decision_changed"
        and d.memory_id == mem.memory_id
        and d.original == "reject"
        and d.replayed == "degrade"
        and d.severity == "critical"
        for d in replay.diffs
    )


@pytest.mark.asyncio
async def test_replay_warns_without_raw_negative_evidence_when_source_memory_missing():
    runtime, repo, run_id, step_id = await _seed_failure_learning_runtime()
    ctx = await runtime.retrieve_context(
        RetrievalRequest(
            run_id=run_id,
            step_id=step_id,
            query="npm test failed how should I run tests now",
            strategy=RetrievalStrategy.variant_2,
            top_k=5,
        )
    )
    degraded_ids = [g.memory_id for g in await repo.list_gate_logs(ctx.access_id) if g.decision.value == "degrade"]
    assert degraded_ids
    for degraded_id in degraded_ids:
        del repo._memories[degraded_id]  # noqa: SLF001 - simulate historical source memory deletion

    replay = await runtime.replay_access(ctx.access_id)

    assert replay is not None
    assert all(
        any(degraded_id in warning and "negative evidence source memory" in warning for warning in replay.warnings)
        for degraded_id in degraded_ids
    )
    assert not [b for b in replay.original_context_blocks_reconstructed if b.type == "avoided_attempts"]
    assert "Tried npm test" not in repr(replay.model_dump())


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
    before_compaction_logs = len(await repo.list_compaction_logs(access_id=access_id))
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
    assert len(await repo.list_compaction_logs(access_id=access_id)) == before_compaction_logs
    assert len(await repo.list_profile_events()) == before_profile_events
    assert after_memory.access_count == before_access_count


@pytest.mark.asyncio
async def test_replay_detects_compaction_drift_when_dropped_count_changes():
    runtime, repo, run_id, step_id, _ = await _seed_runtime()
    access_id = await _retrieve_once(runtime, run_id, step_id, top_k=5)
    await repo.add_compaction_log(
        ContextCompactionLog(
            access_id=access_id,
            run_id=run_id,
            step_id=step_id,
            workspace_id="ws_replay",
            kind=CompactionKind.budget_notice,
            provider=CompactionProvider.rule,
            pre_tokens=100,
            post_tokens=10,
            dropped_block_count=99,
            compression_ratio=0.1,
        )
    )

    replay = await runtime.replay_access(access_id)

    assert replay is not None
    assert replay.compaction_logs
    assert any(
        diff.kind == "compaction_drift"
        and diff.field == "dropped_block_count"
        and diff.original == 99
        and diff.replayed == 0
        and diff.severity == "warning"
        for diff in replay.diffs
    )


@pytest.mark.asyncio
async def test_replay_detects_compaction_drift_from_persisted_over_budget_access():
    repo = InMemoryRepository()
    runtime = MemoryRuntime(repo, default_workspace_id="ws_replay_compact")
    run = await runtime.start_run(
        StartRunRequest(session_id="s_replay_compact", task="choose stack", workspace_id="ws_replay_compact")
    )
    step = await runtime.start_step(StartStepRequest(run_id=run.run_id, intent="choose stack"))
    mutable_memory_ids: list[str] = []
    for key, value in [
        ("project.runtime", "bun"),
        ("project.database", "postgres"),
        ("endpoint.current", "/v2/users"),
    ]:
        memory = await repo.add_memory(
            MemoryItem(
                workspace_id="ws_replay_compact",
                run_id=run.run_id,
                memory_type=MemoryType.project,
                key=key,
                value=value,
                content=f"{key}={value}",
                summary=f"{key}={value}",
                branch_status=BranchStatus.completed,
            )
        )
        if key != "project.runtime":
            mutable_memory_ids.append(memory.memory_id)
    for i in range(6):
        memory = await repo.add_memory(
            MemoryItem(
                workspace_id="ws_replay_compact",
                run_id=run.run_id,
                memory_type=MemoryType.episodic,
                content=f"verbose benign users API investigation note {i} that can be compacted away",
                branch_status=BranchStatus.completed,
            )
        )
        mutable_memory_ids.append(memory.memory_id)
    ctx = await runtime.retrieve_context(
        RetrievalRequest(
            run_id=run.run_id,
            step_id=step.step_id,
            query="which DB/runtime/endpoint should I use?",
            strategy=RetrievalStrategy.variant_2,
            token_budget=18,
            top_k=10,
        )
    )
    persisted = await repo.list_compaction_logs(access_id=ctx.access_id)
    assert persisted and persisted[0].dropped_block_count > 0

    for memory_id in mutable_memory_ids:
        memory = await repo.get_memory(memory_id)
        assert memory is not None
        memory.status = MemoryStatus.superseded
        await repo.update_memory(memory)

    replay = await runtime.replay_access(ctx.access_id)

    assert replay is not None
    assert any(
        diff.kind == "compaction_drift"
        and diff.field == "dropped_block_count"
        and diff.original == persisted[0].dropped_block_count
        and diff.replayed == 0
        and diff.severity == "warning"
        for diff in replay.diffs
    )

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
