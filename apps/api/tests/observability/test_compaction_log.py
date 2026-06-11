"""Context compaction log persistence and observability tests."""
from __future__ import annotations

import pytest

from app.runtime.memory_runtime import MemoryRuntime
from app.runtime.models import (
    BranchStatus,
    CompactionKind,
    CompactionProvider,
    MemoryItem,
    MemoryType,
    RetrievalRequest,
    RetrievalStrategy,
    StartRunRequest,
    StartStepRequest,
)
from app.runtime.repository import InMemoryRepository


async def _seed_over_budget_retrieval(
    runtime: MemoryRuntime,
    repo: InMemoryRepository,
    *,
    workspace_id: str = "ws_compaction",
):
    run = await runtime.start_run(
        StartRunRequest(session_id="s_compaction_log", task="observe compaction", workspace_id=workspace_id)
    )
    step = await runtime.start_step(StartStepRequest(run_id=run.run_id, intent="debug compaction"))

    memories = [
        MemoryItem(
            workspace_id=workspace_id,
            run_id=run.run_id,
            memory_type=MemoryType.project,
            key="project.runtime",
            value="bun",
            content="This project uses Bun",
            summary="project.runtime=bun",
            source_event_id="evt_runtime",
            source_state_node_id=step.state_node_id,
            branch_status=BranchStatus.completed,
        ),
        MemoryItem(
            workspace_id=workspace_id,
            run_id=run.run_id,
            memory_type=MemoryType.project,
            key="project.database",
            value="postgres",
            content="Use postgres for storage",
            summary="project.database=postgres",
            source_event_id="evt_database",
            source_state_node_id=step.state_node_id,
            branch_status=BranchStatus.completed,
        ),
        MemoryItem(
            workspace_id=workspace_id,
            run_id=run.run_id,
            memory_type=MemoryType.project,
            key="endpoint.current",
            value="/v2/users",
            content="Current users endpoint is /v2/users",
            summary="endpoint.current=/v2/users",
            source_event_id="evt_endpoint",
            source_state_node_id=step.state_node_id,
            branch_status=BranchStatus.completed,
        ),
        MemoryItem(
            workspace_id=workspace_id,
            run_id=run.run_id,
            memory_type=MemoryType.episodic,
            content="postgres bun migration detail " * 20,
            source_event_id="evt_story",
            source_state_node_id=step.state_node_id,
            branch_status=BranchStatus.completed,
        ),
    ]
    for memory in memories:
        await repo.add_memory(memory)

    ctx = await runtime.retrieve_context(
        RetrievalRequest(
            run_id=run.run_id,
            step_id=step.step_id,
            query="bun postgres users migration detail",
            strategy=RetrievalStrategy.variant_2,
            token_budget=14,
            top_k=10,
        )
    )
    return run, step, ctx


@pytest.mark.asyncio
async def test_retrieve_with_over_budget_persists_compaction_log(runtime, repo):
    run, step, ctx = await _seed_over_budget_retrieval(runtime, repo)

    logs = await repo.list_compaction_logs(access_id=ctx.access_id)

    assert len(logs) == 1
    log = logs[0]
    assert log.access_id == ctx.access_id
    assert log.run_id == run.run_id
    assert log.step_id == step.step_id
    assert log.workspace_id == "ws_compaction"
    assert log.kind == CompactionKind.budget_notice
    assert log.provider == CompactionProvider.rule
    assert log.dropped_block_count > 0
    assert log.pre_tokens > log.post_tokens > 0
    assert 0 < log.compression_ratio <= 1
    assert {fact.key for fact in log.retained_facts} >= {"project.database", "endpoint.current"}
    assert {fact.value for fact in log.retained_facts} >= {"postgres", "/v2/users"}
    assert {"evt_database", "evt_endpoint", "evt_story"}.issubset(set(log.source_event_ids))
    assert step.state_node_id in set(log.source_state_node_ids)
    assert any(log.source_memory_ids)


@pytest.mark.asyncio
async def test_observability_summary_counts_compaction_metrics(runtime, repo):
    run, _, ctx = await _seed_over_budget_retrieval(runtime, repo)

    summary = await runtime.observability_summary(workspace_id="ws_compaction", run_id=run.run_id)

    logs = await repo.list_compaction_logs(access_id=ctx.access_id)
    assert len(logs) == 1
    log = logs[0]
    assert summary.access_count == 1
    assert summary.compaction_trigger_rate == 1.0
    assert summary.total_dropped_blocks == log.dropped_block_count
    assert summary.avg_compression_ratio == log.compression_ratio
    assert summary.history_summary_count == 0
    assert summary.by_strategy["variant_2"]["compaction_trigger_rate"] == 1.0
    assert summary.by_strategy["variant_2"]["avg_compression_ratio"] == log.compression_ratio


@pytest.mark.asyncio
async def test_replay_includes_persisted_compaction_log_without_rerunning_summary(runtime, repo):
    _, _, ctx = await _seed_over_budget_retrieval(runtime, repo)

    replay = await runtime.replay_access(ctx.access_id)

    assert replay is not None
    assert len(replay.compaction_logs) == 1
    assert replay.compaction_logs[0].kind == CompactionKind.budget_notice
    assert replay.compaction_logs[0].provider == CompactionProvider.rule
    assert not [diff for diff in replay.diffs if diff.kind == "compaction_drift"]
