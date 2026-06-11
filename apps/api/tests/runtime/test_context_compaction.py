"""Runtime tests for Context Compaction C4 rolling history summaries."""
from __future__ import annotations

import asyncio

import pytest

from app.memory.summarizer_provider import SummarizeRequest, SummarizeResult
from app.runtime.memory_runtime import MemoryRuntime
from app.runtime.models import (
    BranchStatus,
    CompactionKind,
    CompactionProvider,
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
    Sensitivity,
    StartRunRequest,
    StartStepRequest,
    StepStatus,
    WriteEventRequest,
)
from app.runtime.repository import InMemoryRepository


class _RecordingSummarizer:
    def __init__(self) -> None:
        self.seen: list[SummarizeRequest] = []

    async def summarize(self, request: SummarizeRequest) -> SummarizeResult:
        self.seen.append(request)
        facts = list(request.must_retain_facts)
        summary = "History summary: " + "; ".join(f"{fact.key}={fact.value}" for fact in facts)
        return SummarizeResult(
            summary=summary,
            retained_facts=facts,
            omitted_count=len(request.blocks),
            source_memory_ids=list(request.source_memory_ids),
            source_event_ids=list(request.source_event_ids),
            source_state_node_ids=list(request.source_state_node_ids),
            pre_tokens=sum(block.tokens for block in request.blocks),
            post_tokens=8,
            warnings=[],
            provider=CompactionProvider.rule,
        )


class _HangingSummarizer:
    async def summarize(self, request: SummarizeRequest) -> SummarizeResult:
        await asyncio.sleep(60)
        raise AssertionError("unreachable")


class _FailingSummarizer:
    def __init__(self) -> None:
        self.called = False

    async def summarize(self, request: SummarizeRequest) -> SummarizeResult:
        self.called = True
        raise RuntimeError("replay must not call summarizer")


async def _seed_long_active_history(
    runtime: MemoryRuntime,
    repo: InMemoryRepository,
    *,
    workspace_id: str = "ws_c4",
    include_secret: bool = False,
):
    run = await runtime.start_run(StartRunRequest(session_id="s_c4", task="long debugging", workspace_id=workspace_id))
    planning = await runtime.start_step(StartStepRequest(run_id=run.run_id, intent="planning", goal="plan migration"))
    events = []
    for idx in range(5):
        result = await runtime.write_event(
            WriteEventRequest(
                run_id=run.run_id,
                step_id=planning.step_id,
                role=EventRole.user,
                event_type=EventType.message,
                content=f"Long active history {idx}: use Bun runtime and Postgres database for users service. " * 8,
            )
        )
        events.append((await repo.get_event((await runtime.get_timeline(run.run_id))[-1].event_id)))
    if include_secret:
        await runtime.write_event(
            WriteEventRequest(
                run_id=run.run_id,
                step_id=planning.step_id,
                role=EventRole.user,
                event_type=EventType.message,
                content="api_key=sk-abcdefgh12345678ijklmnop should never be summarized",
            )
        )
    await runtime.finish_step(
        FinishStepRequest(run_id=run.run_id, step_id=planning.step_id, status=StepStatus.completed, summary="planned safe migration")
    )
    current = await runtime.start_step(StartStepRequest(run_id=run.run_id, intent="implement", goal="implement users endpoint"))

    await repo.add_memory(
        MemoryItem(
            workspace_id=workspace_id,
            run_id=run.run_id,
            memory_type=MemoryType.project,
            key="project.runtime",
            value="bun",
            content="This project uses Bun",
            summary="project.runtime=bun",
            source_event_id=events[0].event_id,
            source_state_node_id=planning.state_node_id,
            branch_status=BranchStatus.completed,
        )
    )
    await repo.add_memory(
        MemoryItem(
            workspace_id=workspace_id,
            run_id=run.run_id,
            memory_type=MemoryType.project,
            key="project.database",
            value="postgres",
            content="Use Postgres for users storage",
            summary="project.database=postgres",
            source_event_id=events[1].event_id,
            source_state_node_id=planning.state_node_id,
            branch_status=BranchStatus.completed,
        )
    )
    return run, planning, current, [event.event_id for event in events if event is not None]


def _enable_c4(runtime: MemoryRuntime, *, threshold: int = 8, timeout_ms: int = 100) -> None:
    runtime._compaction_enabled = True  # noqa: SLF001
    runtime._compaction_history_token_threshold = threshold  # noqa: SLF001
    runtime._compaction_summary_budget_tokens = 64  # noqa: SLF001
    runtime._compaction_timeout_ms = timeout_ms  # noqa: SLF001


@pytest.mark.asyncio
async def test_history_compaction_disabled_by_default():
    repo = InMemoryRepository()
    provider = _RecordingSummarizer()
    runtime = MemoryRuntime(repo, default_workspace_id="ws_c4", summarizer_provider=provider)
    run, _, current, _ = await _seed_long_active_history(runtime, repo)

    ctx = await runtime.retrieve_context(
        RetrievalRequest(run_id=run.run_id, step_id=current.step_id, query="bun postgres", strategy=RetrievalStrategy.variant_2)
    )

    assert provider.seen == []
    assert not any(block.type == "history_summary" for block in ctx.context_blocks)
    assert await repo.list_compaction_logs(access_id=ctx.access_id) == []


@pytest.mark.asyncio
async def test_history_compaction_emits_history_summary_block_when_over_threshold():
    repo = InMemoryRepository()
    provider = _RecordingSummarizer()
    runtime = MemoryRuntime(repo, default_workspace_id="ws_c4", summarizer_provider=provider)
    _enable_c4(runtime)
    run, _, current, _ = await _seed_long_active_history(runtime, repo)

    ctx = await runtime.retrieve_context(
        RetrievalRequest(run_id=run.run_id, step_id=current.step_id, query="bun postgres", strategy=RetrievalStrategy.variant_2)
    )

    history_blocks = [block for block in ctx.context_blocks if block.type == "history_summary"]
    assert len(history_blocks) == 1
    assert "project.runtime=bun" in history_blocks[0].content
    assert "project.database=postgres" in history_blocks[0].content
    assert provider.seen and provider.seen[0].kind == CompactionKind.history_summary


@pytest.mark.asyncio
async def test_history_compaction_persists_compaction_log_with_source_ids():
    repo = InMemoryRepository()
    provider = _RecordingSummarizer()
    runtime = MemoryRuntime(repo, default_workspace_id="ws_c4", summarizer_provider=provider)
    _enable_c4(runtime)
    run, planning, current, event_ids = await _seed_long_active_history(runtime, repo)

    ctx = await runtime.retrieve_context(
        RetrievalRequest(run_id=run.run_id, step_id=current.step_id, query="bun postgres", strategy=RetrievalStrategy.variant_2)
    )
    logs = await repo.list_compaction_logs(access_id=ctx.access_id)

    history_logs = [log for log in logs if log.kind == CompactionKind.history_summary]
    assert len(history_logs) == 1
    log = history_logs[0]
    assert log.access_id == ctx.access_id
    assert log.run_id == run.run_id
    assert log.step_id == current.step_id
    assert set(event_ids).issubset(set(log.source_event_ids))
    assert planning.state_node_id in set(log.source_state_node_ids)
    assert {fact.key for fact in log.retained_facts} >= {"project.runtime", "project.database"}
    assert log.pre_tokens > log.post_tokens > 0


@pytest.mark.asyncio
async def test_history_compaction_excludes_failed_branch_event():
    repo = InMemoryRepository()
    provider = _RecordingSummarizer()
    runtime = MemoryRuntime(repo, default_workspace_id="ws_c4", summarizer_provider=provider)
    _enable_c4(runtime)
    run, _, current, _ = await _seed_long_active_history(runtime, repo)
    bad = await runtime.start_step(StartStepRequest(run_id=run.run_id, intent="bad npm branch", goal="try npm"))
    await runtime.write_event(
        WriteEventRequest(
            run_id=run.run_id,
            step_id=bad.step_id,
            role=EventRole.tool,
            event_type=EventType.tool_result,
            status="failed",
            content="Tried npm test and failed; this failed branch must not be summarized. " * 10,
        )
    )
    await runtime.finish_step(FinishStepRequest(run_id=run.run_id, step_id=bad.step_id, status=StepStatus.failed))
    await runtime.rollback_branch(RollbackRequest(run_id=run.run_id, step_id=bad.step_id, reason="wrong branch"))
    recovery = await runtime.start_step(StartStepRequest(run_id=run.run_id, intent="recover", recovery_from_step_id=bad.step_id))

    ctx = await runtime.retrieve_context(
        RetrievalRequest(run_id=run.run_id, step_id=recovery.step_id, query="bun postgres npm", strategy=RetrievalStrategy.variant_2)
    )
    joined = " ".join(block.content for block in ctx.context_blocks if block.type == "history_summary")

    assert "npm test" not in joined
    assert "failed branch" not in joined


@pytest.mark.asyncio
async def test_history_compaction_excludes_secret_redacted_event():
    repo = InMemoryRepository()
    provider = _RecordingSummarizer()
    runtime = MemoryRuntime(repo, default_workspace_id="ws_c4", summarizer_provider=provider)
    _enable_c4(runtime)
    run, _, current, _ = await _seed_long_active_history(runtime, repo, include_secret=True)

    ctx = await runtime.retrieve_context(
        RetrievalRequest(run_id=run.run_id, step_id=current.step_id, query="bun postgres", strategy=RetrievalStrategy.variant_2)
    )
    joined = " ".join(block.content for block in ctx.context_blocks)

    assert "sk-abcdefgh" not in joined
    assert "api_key" not in joined


@pytest.mark.asyncio
async def test_history_compaction_excludes_failed_tool_result_inside_completed_step():
    repo = InMemoryRepository()
    provider = _RecordingSummarizer()
    runtime = MemoryRuntime(repo, default_workspace_id="ws_c4", summarizer_provider=provider)
    _enable_c4(runtime)
    run, _, current, _ = await _seed_long_active_history(runtime, repo)
    await runtime.write_event(
        WriteEventRequest(
            run_id=run.run_id,
            step_id=current.step_id,
            role=EventRole.tool,
            event_type=EventType.tool_result,
            status="failed",
            content="Failed active-path tool output says use npm test and should not be summarized. " * 8,
        )
    )

    ctx = await runtime.retrieve_context(
        RetrievalRequest(run_id=run.run_id, step_id=current.step_id, query="bun postgres npm", strategy=RetrievalStrategy.variant_2)
    )
    joined = " ".join(block.content for block in ctx.context_blocks if block.type == "history_summary")

    assert "npm test" not in joined
    assert "Failed active-path tool output" not in joined


@pytest.mark.asyncio
async def test_history_compaction_excludes_destructive_tool_call_event():
    repo = InMemoryRepository()
    provider = _RecordingSummarizer()
    runtime = MemoryRuntime(repo, default_workspace_id="ws_c4", summarizer_provider=provider)
    _enable_c4(runtime)
    run, _, current, _ = await _seed_long_active_history(runtime, repo)
    await runtime.write_event(
        WriteEventRequest(
            run_id=run.run_id,
            step_id=current.step_id,
            role=EventRole.tool,
            event_type=EventType.tool_call,
            content="Run rm -rf /tmp/project and git push --force to production. " * 8,
        )
    )

    ctx = await runtime.retrieve_context(
        RetrievalRequest(run_id=run.run_id, step_id=current.step_id, query="bun postgres force", strategy=RetrievalStrategy.variant_2)
    )
    joined = " ".join(block.content for block in ctx.context_blocks if block.type == "history_summary")

    assert "rm -rf" not in joined
    assert "git push --force" not in joined


@pytest.mark.asyncio
async def test_history_compaction_does_not_leak_superseded_memory():
    repo = InMemoryRepository()
    provider = _RecordingSummarizer()
    runtime = MemoryRuntime(repo, default_workspace_id="ws_c4", summarizer_provider=provider)
    _enable_c4(runtime)
    run, planning, current, event_ids = await _seed_long_active_history(runtime, repo)
    await repo.add_memory(
        MemoryItem(
            workspace_id="ws_c4",
            run_id=run.run_id,
            memory_type=MemoryType.project,
            key="project.runtime",
            value="npm",
            content="This project uses npm",
            summary="project.runtime=npm",
            source_event_id=event_ids[0],
            source_state_node_id=planning.state_node_id,
            status=MemoryStatus.superseded,
            branch_status=BranchStatus.completed,
        )
    )

    ctx = await runtime.retrieve_context(
        RetrievalRequest(run_id=run.run_id, step_id=current.step_id, query="bun postgres npm", strategy=RetrievalStrategy.variant_2)
    )
    joined = " ".join(block.content for block in ctx.context_blocks if block.type == "history_summary")

    assert "project.runtime=npm" not in joined
    assert "project.runtime=bun" in joined


@pytest.mark.asyncio
async def test_history_retained_facts_require_active_non_quarantined_source():
    repo = InMemoryRepository()
    provider = _RecordingSummarizer()
    runtime = MemoryRuntime(repo, default_workspace_id="ws_c4", summarizer_provider=provider)
    _enable_c4(runtime)
    run, _, current, _ = await _seed_long_active_history(runtime, repo)
    await repo.add_memory(
        MemoryItem(
            workspace_id="ws_c4",
            run_id=run.run_id,
            memory_type=MemoryType.project,
            key="project.cache",
            value="redis",
            content="Use Redis cache",
            summary="project.cache=redis",
            status=MemoryStatus.quarantined,
            branch_status=BranchStatus.completed,
        )
    )
    await repo.add_memory(
        MemoryItem(
            workspace_id="ws_c4",
            run_id=run.run_id,
            memory_type=MemoryType.project,
            key="project.queue",
            value="celery",
            content="Use Celery queue",
            summary="project.queue=celery",
            status=MemoryStatus.active,
            branch_status=BranchStatus.completed,
        )
    )

    ctx = await runtime.retrieve_context(
        RetrievalRequest(run_id=run.run_id, step_id=current.step_id, query="bun postgres redis celery", strategy=RetrievalStrategy.variant_2)
    )
    joined = " ".join(block.content for block in ctx.context_blocks if block.type == "history_summary")

    assert "project.cache=redis" not in joined
    assert "project.queue=celery" not in joined


@pytest.mark.asyncio
async def test_history_compaction_timeout_degrades_to_no_fold_not_empty_context():
    repo = InMemoryRepository()
    runtime = MemoryRuntime(repo, default_workspace_id="ws_c4", summarizer_provider=_HangingSummarizer())
    _enable_c4(runtime, timeout_ms=1)
    run, _, current, _ = await _seed_long_active_history(runtime, repo)

    ctx = await runtime.retrieve_context(
        RetrievalRequest(run_id=run.run_id, step_id=current.step_id, query="bun postgres", strategy=RetrievalStrategy.variant_2)
    )

    assert ctx.context_blocks
    assert not any(block.type == "history_summary" for block in ctx.context_blocks)
    assert any("history compaction skipped" in warning for warning in ctx.warnings)


@pytest.mark.asyncio
async def test_retrieval_timeout_after_history_fold_persists_access_without_compaction_log():
    repo = InMemoryRepository()
    provider = _RecordingSummarizer()
    runtime = MemoryRuntime(repo, default_workspace_id="ws_c4", summarizer_provider=provider)
    _enable_c4(runtime)
    runtime._retrieval._timeout_ms = 1  # noqa: SLF001
    run, _, current, _ = await _seed_long_active_history(runtime, repo)
    original_select = runtime._retrieval._select_candidates  # noqa: SLF001

    async def _slow_select(*args, **kwargs):
        await asyncio.sleep(0.2)
        return await original_select(*args, **kwargs)

    runtime._retrieval._select_candidates = _slow_select  # noqa: SLF001

    ctx = await runtime.retrieve_context(
        RetrievalRequest(run_id=run.run_id, step_id=current.step_id, query="bun postgres", strategy=RetrievalStrategy.variant_2)
    )

    assert ctx.context_blocks == []
    assert await repo.get_access_log(ctx.access_id) is not None
    logs = await repo.list_compaction_logs(access_id=ctx.access_id)
    assert not any(log.kind == CompactionKind.history_summary for log in logs)


@pytest.mark.asyncio
async def test_history_compaction_timeout_covers_slow_history_scan():
    class _SlowEventsRepository(InMemoryRepository):
        async def list_events(self, run_id: str):
            await asyncio.sleep(0.2)
            return await super().list_events(run_id)

    repo = _SlowEventsRepository()
    provider = _RecordingSummarizer()
    runtime = MemoryRuntime(repo, default_workspace_id="ws_c4", summarizer_provider=provider)
    _enable_c4(runtime, timeout_ms=1)
    run, _, current, _ = await _seed_long_active_history(runtime, repo)

    ctx = await runtime.retrieve_context(
        RetrievalRequest(run_id=run.run_id, step_id=current.step_id, query="bun postgres", strategy=RetrievalStrategy.variant_2)
    )

    assert ctx.context_blocks
    assert provider.seen == []
    assert any("history compaction skipped" in warning for warning in ctx.warnings)


@pytest.mark.asyncio
async def test_replay_returns_persisted_history_summary_without_calling_summarizer():
    repo = InMemoryRepository()
    provider = _RecordingSummarizer()
    runtime = MemoryRuntime(repo, default_workspace_id="ws_c4", summarizer_provider=provider)
    _enable_c4(runtime)
    run, _, current, _ = await _seed_long_active_history(runtime, repo)
    ctx = await runtime.retrieve_context(
        RetrievalRequest(run_id=run.run_id, step_id=current.step_id, query="bun postgres", strategy=RetrievalStrategy.variant_2)
    )

    failing = _FailingSummarizer()
    replay_runtime = MemoryRuntime(repo, default_workspace_id="ws_c4", summarizer_provider=failing)
    replay = await replay_runtime.replay_access(ctx.access_id)

    assert replay is not None
    assert failing.called is False
    assert any(log.kind == CompactionKind.history_summary for log in replay.compaction_logs)
    assert any(block.type == "history_summary" for block in replay.original_context_blocks_reconstructed)
    assert any(block.type == "history_summary" for block in replay.replayed_context_blocks)


@pytest.mark.asyncio
async def test_history_summary_is_protected_under_tiny_budget():
    repo = InMemoryRepository()
    provider = _RecordingSummarizer()
    runtime = MemoryRuntime(repo, default_workspace_id="ws_c4", summarizer_provider=provider)
    _enable_c4(runtime)
    run, _, current, _ = await _seed_long_active_history(runtime, repo)
    await repo.add_memory(
        MemoryItem(
            workspace_id="ws_c4",
            run_id=run.run_id,
            memory_type=MemoryType.episodic,
            content="ordinary bun postgres detail " * 30,
            branch_status=BranchStatus.completed,
        )
    )

    ctx = await runtime.retrieve_context(
        RetrievalRequest(
            run_id=run.run_id,
            step_id=current.step_id,
            query="bun postgres detail",
            strategy=RetrievalStrategy.variant_2,
            token_budget=18,
            top_k=10,
        )
    )

    assert any(block.type == "history_summary" for block in ctx.context_blocks)
    assert ctx.profile["actual_tokens"] <= 18
