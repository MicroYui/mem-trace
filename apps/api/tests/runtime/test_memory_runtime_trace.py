"""Service-layer tests for the run/step/event/state-tree lifecycle.

These are the foundation invariants from .ai/REQUIREMENTS.md (Tests to Write
First) plus rollback/recovery behavior.
"""
from __future__ import annotations

import asyncio

import pytest

from app.providers import ProviderCapabilities, ProviderKind, ProviderRegistry
from app.retrieval.similarity import stable_embedding
from app.runtime.memory_runtime import MemoryRuntime, StateTreeError, StepNotFoundError
from app.runtime.models import (
    AgentStep,
    BranchStatus,
    CompleteRunRequest,
    EmbeddingStatus,
    EventRole,
    EventType,
    FinishStepRequest,
    MemoryItem,
    MemoryScope,
    MemoryStatus,
    MemoryType,
    RetrievalRequest,
    RollbackRequest,
    RunStatus,
    StartRunRequest,
    StartStepRequest,
    StateNodeStatus,
    StateNodeType,
    StepStatus,
    WriteEventRequest,
)
from app.runtime.repository import InMemoryRepository


class _RecordingEmbeddingProvider:
    def __init__(self, vector: list[float] | None = None, *, fail: bool = False) -> None:
        self.vector = vector or [1.0, 0.0]
        self.fail = fail
        self.calls: list[str | None] = []
        self.capabilities = ProviderCapabilities(
            provider_id="embedding.test_runtime.v1",
            kind=ProviderKind.embedding,
            deterministic=False,
            requires_network=False,
            metadata={"dim": len(self.vector)},
        )

    async def embed_text(self, text: str | None) -> list[float]:
        self.calls.append(text)
        if self.fail:
            raise RuntimeError("embedding provider unavailable")
        return list(self.vector)


def _runtime_with_embedding_provider(provider: _RecordingEmbeddingProvider) -> tuple[MemoryRuntime, InMemoryRepository]:
    registry = ProviderRegistry()
    registry.register(ProviderKind.embedding, provider, provider.capabilities)
    repo = InMemoryRepository()
    return MemoryRuntime(repo, default_workspace_id="ws_embed_runtime", provider_registry=registry), repo


async def _start(runtime):
    return await runtime.start_run(StartRunRequest(session_id="s1", task="t"))


async def test_runtime_write_paths_prepare_embeddings_with_provider_before_repository_backfill():
    provider_vector = [0.25] + [0.0] * 255
    provider = _RecordingEmbeddingProvider(provider_vector)
    runtime, repo = _runtime_with_embedding_provider(provider)
    run = await runtime.start_run(StartRunRequest(session_id="s_embed_runtime", task="provider embedding"))
    step = await runtime.start_step(StartStepRequest(run_id=run.run_id, intent="capture memory"))

    user_write = await runtime.write_event(
        WriteEventRequest(
            run_id=run.run_id,
            step_id=step.step_id,
            role=EventRole.user,
            event_type=EventType.message,
            content="这个项目使用 Bun",
        )
    )
    tool_write = await runtime.write_event(
        WriteEventRequest(
            run_id=run.run_id,
            step_id=step.step_id,
            role=EventRole.tool,
            event_type=EventType.tool_result,
            status="success",
            content="bun test passed",
        )
    )
    finish = await runtime.finish_step(
        FinishStepRequest(run_id=run.run_id, step_id=step.step_id, status=StepStatus.completed, summary="done with bun")
    )
    complete = await runtime.complete_run(CompleteRunRequest(run_id=run.run_id))

    created_ids = [*user_write.created_memory_ids, *tool_write.created_memory_ids, *finish.created_memory_ids, *complete.created_memory_ids]
    assert len(created_ids) >= 5
    memories = [await repo.get_memory(memory_id) for memory_id in created_ids]
    assert all(memory is not None for memory in memories)
    assert all(memory.embedding_vector == provider_vector for memory in memories if memory is not None)
    assert all(memory.embedding_status == EmbeddingStatus.embedded for memory in memories if memory is not None)
    assert "这个项目使用 Bun" in provider.calls
    assert "bun test passed" in provider.calls
    assert "done with bun" in provider.calls


async def test_runtime_same_identity_actives_match_historical_alias_keys():
    repo = InMemoryRepository()
    runtime = MemoryRuntime(repo)
    run = await runtime.start_run(StartRunRequest(workspace_id="ws", session_id="s", task="setup"))
    await runtime.start_step(StartStepRequest(run_id=run.run_id, intent="setup"))
    await repo.add_memory(
        MemoryItem(
            workspace_id="ws",
            session_id="s",
            run_id=run.run_id,
            memory_type=MemoryType.project,
            key="project.pkg_manager",
            value="npm",
            scope=MemoryScope.workspace,
            content="project.package_manager=npm",
            branch_status=BranchStatus.completed,
            trust_score=0.6,
        )
    )

    await runtime._resolve_and_persist(  # noqa: SLF001 - locks runtime identity behavior
        "ws",
        MemoryItem(
            workspace_id="ws",
            session_id="s",
            run_id=run.run_id,
            memory_type=MemoryType.project,
            key="project.package_manager",
            value="pnpm",
            scope=MemoryScope.workspace,
            content="project.package_manager=pnpm",
            branch_status=BranchStatus.completed,
            trust_score=0.9,
        ),
    )

    memories = await runtime.list_memories(workspace_id="ws")
    old = next(mem for mem in memories if mem.value == "npm")
    assert old.key == "project.package_manager"
    assert old.status == MemoryStatus.superseded


async def test_runtime_keeps_runtime_and_package_manager_as_distinct_active_keys():
    repo = InMemoryRepository()
    runtime = MemoryRuntime(repo)
    run = await runtime.start_run(StartRunRequest(workspace_id="ws_pkg", session_id="s", task="setup"))
    step = await runtime.start_step(StartStepRequest(run_id=run.run_id, intent="setup"))

    await runtime.write_event(
        WriteEventRequest(
            run_id=run.run_id,
            step_id=step.step_id,
            role=EventRole.user,
            event_type=EventType.message,
            content="这个项目使用 Node.js",
        )
    )
    await runtime.write_event(
        WriteEventRequest(
            run_id=run.run_id,
            step_id=step.step_id,
            role=EventRole.user,
            event_type=EventType.message,
            content="这个项目使用 pnpm",
        )
    )

    active = {(mem.key, mem.value) for mem in await runtime.list_memories(workspace_id="ws_pkg") if mem.status == MemoryStatus.active}
    assert ("project.runtime", "nodejs") in active
    assert ("project.package_manager", "pnpm") in active


async def test_runtime_prepare_embedding_falls_back_without_blocking_memory_write():
    provider = _RecordingEmbeddingProvider(fail=True)
    runtime, repo = _runtime_with_embedding_provider(provider)
    run = await runtime.start_run(StartRunRequest(session_id="s_embed_fallback", task="provider fallback"))
    step = await runtime.start_step(StartStepRequest(run_id=run.run_id, intent="capture fallback"))

    write = await runtime.write_event(
        WriteEventRequest(
            run_id=run.run_id,
            step_id=step.step_id,
            role=EventRole.user,
            event_type=EventType.message,
            content="这个项目使用 Bun",
        )
    )

    assert write.created_memory_ids
    memory = await repo.get_memory(write.created_memory_ids[0])
    assert memory is not None
    assert provider.calls == ["这个项目使用 Bun"]
    assert memory.embedding_vector == stable_embedding("这个项目使用 Bun", 256)
    assert memory.embedding_status == EmbeddingStatus.embedded


async def test_prepare_embedding_skips_existing_vectors_and_empty_content():
    provider = _RecordingEmbeddingProvider([0.25] + [0.0] * 255)
    runtime, _ = _runtime_with_embedding_provider(provider)
    existing = MemoryItem(workspace_id="ws_embed_runtime", memory_type=MemoryType.episodic, content="already embedded", embedding_vector=[0.1, 0.9])
    empty = MemoryItem(workspace_id="ws_embed_runtime", memory_type=MemoryType.episodic, content="")

    assert await runtime._prepare_embedding(existing) is existing  # noqa: SLF001
    assert await runtime._prepare_embedding(empty) is empty  # noqa: SLF001

    assert existing.embedding_vector == [0.1, 0.9]
    assert empty.embedding_vector is None
    assert provider.calls == []


async def test_runtime_prepare_embedding_falls_back_when_provider_returns_wrong_dimension():
    provider = _RecordingEmbeddingProvider([0.25, 0.75])
    runtime, repo = _runtime_with_embedding_provider(provider)
    run = await runtime.start_run(StartRunRequest(session_id="s_embed_bad_dim", task="provider bad dimension"))
    step = await runtime.start_step(StartStepRequest(run_id=run.run_id, intent="capture bad dimension"))

    write = await runtime.write_event(
        WriteEventRequest(
            run_id=run.run_id,
            step_id=step.step_id,
            role=EventRole.user,
            event_type=EventType.message,
            content="这个项目使用 Bun",
        )
    )

    memory = await repo.get_memory(write.created_memory_ids[0])
    assert memory is not None
    assert provider.calls == ["这个项目使用 Bun"]
    assert memory.embedding_vector == stable_embedding("这个项目使用 Bun", 256)
    assert memory.embedding_status == EmbeddingStatus.embedded


async def test_runtime_prepare_embedding_falls_back_when_provider_returns_non_finite_vector():
    provider = _RecordingEmbeddingProvider([float("nan")] + [0.0] * 255)
    runtime, repo = _runtime_with_embedding_provider(provider)
    run = await runtime.start_run(StartRunRequest(session_id="s_embed_nan", task="provider non-finite vector"))
    step = await runtime.start_step(StartStepRequest(run_id=run.run_id, intent="capture non-finite"))

    write = await runtime.write_event(
        WriteEventRequest(
            run_id=run.run_id,
            step_id=step.step_id,
            role=EventRole.user,
            event_type=EventType.message,
            content="这个项目使用 Bun",
        )
    )

    memory = await repo.get_memory(write.created_memory_ids[0])
    assert memory is not None
    assert provider.calls == ["这个项目使用 Bun"]
    assert memory.embedding_vector == stable_embedding("这个项目使用 Bun", 256)
    assert memory.embedding_status == EmbeddingStatus.embedded


async def test_start_run_creates_running_run_and_active_root_node(runtime):
    run = await _start(runtime)
    assert run.status == RunStatus.running
    nodes = await runtime.get_state_tree(run.run_id)
    assert len(nodes) == 1
    assert nodes[0].node_type == StateNodeType.root
    assert nodes[0].status == StateNodeStatus.active


async def test_start_step_creates_active_step_node_under_root(runtime):
    run = await _start(runtime)
    step = await runtime.start_step(StartStepRequest(run_id=run.run_id, intent="planning"))
    assert step.status == StepStatus.active
    nodes = {n.node_id: n for n in await runtime.get_state_tree(run.run_id)}
    node = nodes[step.state_node_id]
    assert node.node_type == StateNodeType.step
    assert node.status == StateNodeStatus.active
    root = next(n for n in nodes.values() if n.node_type == StateNodeType.root)
    assert node.parent_id == root.node_id
    assert node.depth == 1


async def test_write_event_assigns_monotonic_sequence_numbers_per_run(runtime):
    run = await _start(runtime)
    step = await runtime.start_step(StartStepRequest(run_id=run.run_id, intent="x"))
    seqs = []
    for i in range(3):
        r = await runtime.write_event(
            WriteEventRequest(run_id=run.run_id, step_id=step.step_id, content=f"m{i}")
        )
        seqs.append(r.event.sequence_no)
    assert seqs == [1, 2, 3]
    timeline = await runtime.get_timeline(run.run_id)
    assert [e.sequence_no for e in timeline] == [1, 2, 3]


async def test_concurrent_write_events_get_gap_free_run_local_sequence_numbers(runtime):
    run = await _start(runtime)
    step = await runtime.start_step(StartStepRequest(run_id=run.run_id, intent="concurrent"))

    async def write(i: int):
        return await runtime.write_event(
            WriteEventRequest(
                run_id=run.run_id,
                step_id=step.step_id,
                role=EventRole.user,
                event_type=EventType.message,
                content=f"event {i}",
            )
        )

    await asyncio.gather(*(write(i) for i in range(50)))

    events = await runtime.get_timeline(run.run_id)
    assert [event.sequence_no for event in events] == list(range(1, 51))


async def test_sequence_numbers_are_independent_per_run(runtime):
    r1 = await _start(runtime)
    r2 = await _start(runtime)
    s1 = await runtime.start_step(StartStepRequest(run_id=r1.run_id))
    s2 = await runtime.start_step(StartStepRequest(run_id=r2.run_id))
    e1 = await runtime.write_event(WriteEventRequest(run_id=r1.run_id, step_id=s1.step_id, content="a"))
    e2 = await runtime.write_event(WriteEventRequest(run_id=r2.run_id, step_id=s2.step_id, content="b"))
    assert e1.event.sequence_no == 1
    assert e2.event.sequence_no == 1


async def test_write_event_binds_event_to_step_and_state_node(runtime):
    run = await _start(runtime)
    step = await runtime.start_step(StartStepRequest(run_id=run.run_id))
    r = await runtime.write_event(WriteEventRequest(run_id=run.run_id, step_id=step.step_id, content="hi"))
    assert r.event.step_id == step.step_id
    assert r.event.state_node_id == step.state_node_id


async def test_write_event_rejects_step_from_another_run_without_side_effects(runtime):
    run_a = await runtime.start_run(StartRunRequest(session_id="s-cross-a", task="run a"))
    run_b = await runtime.start_run(StartRunRequest(session_id="s-cross-b", task="run b"))
    step_b = await runtime.start_step(StartStepRequest(run_id=run_b.run_id, intent="foreign"))

    with pytest.raises(StepNotFoundError):
        await runtime.write_event(
            WriteEventRequest(run_id=run_a.run_id, step_id=step_b.step_id, content="cross-run event")
        )

    assert await runtime.get_timeline(run_a.run_id) == []
    assert await runtime.get_timeline(run_b.run_id) == []
    node_b = await runtime._repo.get_state_node(step_b.state_node_id)  # noqa: SLF001
    assert node_b is not None
    assert node_b.raw_event_ids == []


async def test_start_step_rejects_cross_run_parent_or_recovery_step(runtime):
    run_a = await runtime.start_run(StartRunRequest(session_id="s-parent-a", task="run a"))
    run_b = await runtime.start_run(StartRunRequest(session_id="s-parent-b", task="run b"))
    foreign_step = await runtime.start_step(StartStepRequest(run_id=run_b.run_id, intent="foreign"))

    with pytest.raises(StepNotFoundError):
        await runtime.start_step(StartStepRequest(run_id=run_a.run_id, parent_step_id=foreign_step.step_id))
    with pytest.raises(StepNotFoundError):
        await runtime.start_step(StartStepRequest(run_id=run_a.run_id, recovery_from_step_id=foreign_step.step_id))

    assert await runtime.get_steps(run_a.run_id) == []


async def test_finish_step_rejects_step_from_another_run_without_side_effects(runtime):
    run_a = await runtime.start_run(StartRunRequest(session_id="s-finish-a", task="run a"))
    run_b = await runtime.start_run(StartRunRequest(session_id="s-finish-b", task="run b"))
    step_b = await runtime.start_step(StartStepRequest(run_id=run_b.run_id, intent="foreign"))

    with pytest.raises(StepNotFoundError):
        await runtime.finish_step(
            FinishStepRequest(run_id=run_a.run_id, step_id=step_b.step_id, summary="foreign summary")
        )

    stored_step = await runtime._repo.get_step(step_b.step_id)  # noqa: SLF001
    assert stored_step is not None
    assert stored_step.status == StepStatus.active
    node_b = await runtime._repo.get_state_node(step_b.state_node_id)  # noqa: SLF001
    assert node_b is not None
    assert node_b.status == StateNodeStatus.active
    assert await runtime._repo.list_memories(workspace_id=run_b.workspace_id) == []  # noqa: SLF001


async def test_retrieve_context_rejects_step_from_another_run_without_access_log(runtime):
    run_a = await runtime.start_run(StartRunRequest(session_id="s-retrieve-a", task="run a"))
    run_b = await runtime.start_run(StartRunRequest(session_id="s-retrieve-b", task="run b"))
    step_b = await runtime.start_step(StartStepRequest(run_id=run_b.run_id, intent="foreign"))

    with pytest.raises(StepNotFoundError):
        await runtime.retrieve_context(
            RetrievalRequest(run_id=run_a.run_id, step_id=step_b.step_id, query="foreign", top_k=1)
        )

    access_logs = await runtime._repo.list_access_logs(workspace_id=run_a.workspace_id)  # noqa: SLF001
    assert [log for log in access_logs if log.run_id == run_a.run_id] == []


async def test_rollback_branch_rejects_step_from_another_run_without_side_effects(runtime):
    run_a = await runtime.start_run(StartRunRequest(session_id="s-rollback-a", task="run a"))
    run_b = await runtime.start_run(StartRunRequest(session_id="s-rollback-b", task="run b"))
    step_b = await runtime.start_step(StartStepRequest(run_id=run_b.run_id, intent="foreign"))

    with pytest.raises(StepNotFoundError):
        await runtime.rollback_branch(RollbackRequest(run_id=run_a.run_id, step_id=step_b.step_id, reason="cross"))

    stored_step = await runtime._repo.get_step(step_b.step_id)  # noqa: SLF001
    assert stored_step is not None
    assert stored_step.status == StepStatus.active


async def test_write_event_stamps_event_source(runtime):
    run = await _start(runtime)
    step = await runtime.start_step(StartStepRequest(run_id=run.run_id))

    r = await runtime.write_event(
        WriteEventRequest(
            run_id=run.run_id,
            step_id=step.step_id,
            content="hi from sdk",
            event_source="sdk",
        )
    )

    assert r.event.event_source == "sdk"
    timeline = await runtime.get_timeline(run.run_id)
    assert timeline[0].event_source == "sdk"


async def test_write_event_event_source_defaults_none(runtime):
    run = await _start(runtime)
    step = await runtime.start_step(StartStepRequest(run_id=run.run_id))

    r = await runtime.write_event(
        WriteEventRequest(run_id=run.run_id, step_id=step.step_id, content="hi")
    )

    assert r.event.event_source is None
    timeline = await runtime.get_timeline(run.run_id)
    assert timeline[0].event_source is None


async def test_finish_step_success_marks_step_and_state_node_completed(runtime):
    run = await _start(runtime)
    step = await runtime.start_step(StartStepRequest(run_id=run.run_id))
    res = await runtime.finish_step(
        FinishStepRequest(run_id=run.run_id, step_id=step.step_id, status=StepStatus.completed)
    )
    assert res.step.status == StepStatus.completed
    assert res.state_node.status == StateNodeStatus.completed


async def test_finish_step_failed_marks_step_and_state_node_failed(runtime):
    run = await _start(runtime)
    step = await runtime.start_step(StartStepRequest(run_id=run.run_id))
    res = await runtime.finish_step(
        FinishStepRequest(run_id=run.run_id, step_id=step.step_id, status=StepStatus.failed, error_message="boom")
    )
    assert res.step.status == StepStatus.failed
    assert res.state_node.status == StateNodeStatus.failed
    assert res.state_node.failure_reason == "boom"


async def test_finish_step_missing_state_node_raises_state_tree_error(runtime):
    step = AgentStep(workspace_id="ws_missing_node", run_id="run_missing_node", state_node_id="missing_node")
    await runtime._repo.add_step(step)  # noqa: SLF001 - seed intentionally corrupt state

    with pytest.raises(StateTreeError):
        await runtime.finish_step(
            FinishStepRequest(step_id=step.step_id, run_id=step.run_id, status=StepStatus.completed)
        )

    stored = await runtime.get_step(step.step_id)
    assert stored is not None
    assert stored.status == StepStatus.active
    assert stored.finished_at is None
    assert stored.error_message is None


async def test_finish_step_without_state_node_id_raises_state_tree_error(runtime):
    step = AgentStep(workspace_id="ws_missing_node", run_id="run_missing_node", state_node_id=None)
    await runtime._repo.add_step(step)  # noqa: SLF001 - seed intentionally corrupt state

    with pytest.raises(StateTreeError):
        await runtime.finish_step(
            FinishStepRequest(step_id=step.step_id, run_id=step.run_id, status=StepStatus.completed)
        )

    stored = await runtime.get_step(step.step_id)
    assert stored is not None
    assert stored.status == StepStatus.active
    assert stored.finished_at is None
    assert stored.error_message is None


async def test_rollback_branch_missing_state_node_raises_state_tree_error(runtime):
    step = AgentStep(workspace_id="ws_missing_node", run_id="run_missing_node", state_node_id="missing_node")
    await runtime._repo.add_step(step)  # noqa: SLF001 - seed intentionally corrupt state

    with pytest.raises(StateTreeError):
        await runtime.rollback_branch(RollbackRequest(run_id=step.run_id, step_id=step.step_id, reason="corrupt"))


async def test_rollback_branch_without_state_node_id_raises_state_tree_error(runtime):
    step = AgentStep(workspace_id="ws_missing_node", run_id="run_missing_node", state_node_id=None)
    await runtime._repo.add_step(step)  # noqa: SLF001 - seed intentionally corrupt state

    with pytest.raises(StateTreeError):
        await runtime.rollback_branch(RollbackRequest(run_id=step.run_id, step_id=step.step_id, reason="corrupt"))


async def test_rollback_branch_marks_failed_step_rolled_back(runtime):
    run = await _start(runtime)
    step = await runtime.start_step(StartStepRequest(run_id=run.run_id))
    await runtime.finish_step(
        FinishStepRequest(run_id=run.run_id, step_id=step.step_id, status=StepStatus.failed, error_message="npm")
    )
    rb = await runtime.rollback_branch(RollbackRequest(run_id=run.run_id, step_id=step.step_id, reason="npm"))
    assert step.step_id in rb.rolled_back_step_ids
    nodes = {n.node_id: n for n in await runtime.get_state_tree(run.run_id)}
    node = nodes[step.state_node_id]
    assert node.status == StateNodeStatus.rolled_back
    # failure_reason preserved across rollback
    assert node.failure_reason == "npm"
    assert node.branch_reason.get("rollback_reason") == "npm"


async def test_recovery_step_attaches_to_failed_step_parent_not_failed_node(runtime):
    run = await _start(runtime)
    failed = await runtime.start_step(StartStepRequest(run_id=run.run_id, intent="debug"))
    await runtime.finish_step(
        FinishStepRequest(run_id=run.run_id, step_id=failed.step_id, status=StepStatus.failed, error_message="npm")
    )
    await runtime.rollback_branch(RollbackRequest(run_id=run.run_id, step_id=failed.step_id, reason="npm"))
    recovery = await runtime.start_step(
        StartStepRequest(run_id=run.run_id, intent="debug", recovery_from_step_id=failed.step_id)
    )
    nodes = {n.node_id: n for n in await runtime.get_state_tree(run.run_id)}
    failed_node = nodes[failed.state_node_id]
    recovery_node = nodes[recovery.state_node_id]
    root = next(n for n in nodes.values() if n.node_type == StateNodeType.root)
    # recovery attaches to failed node's PARENT (root), not under the failed node
    assert recovery_node.parent_id == failed_node.parent_id == root.node_id
    assert recovery_node.node_type == StateNodeType.recovery
    assert recovery_node.branch_reason.get("recovery_from_step_id") == failed.step_id


async def test_rollback_flips_related_memory_branch_status(runtime):
    run = await _start(runtime)
    step = await runtime.start_step(StartStepRequest(run_id=run.run_id))
    await runtime.write_event(
        WriteEventRequest(
            run_id=run.run_id, step_id=step.step_id, role=EventRole.tool,
            event_type=EventType.tool_result, status="failed",
            content="Tried running tests with npm test, but it failed because npm was unavailable.",
        )
    )
    await runtime.finish_step(
        FinishStepRequest(run_id=run.run_id, step_id=step.step_id, status=StepStatus.failed, error_message="npm")
    )
    rb = await runtime.rollback_branch(RollbackRequest(run_id=run.run_id, step_id=step.step_id, reason="npm"))
    assert rb.affected_memory_ids
    mems = await runtime.list_memories(run_id=run.run_id)
    tool_ev = [m for m in mems if m.memory_type.value == "tool_evidence"]
    assert tool_ev and all(m.branch_status.value == "rolled_back" for m in tool_ev)


async def test_recovery_raises_when_failed_node_parent_is_dangling(runtime):
    # A structurally inconsistent tree (failed node points at a missing parent)
    # must NOT silently reattach the recovery to root; it raises StateTreeError.
    from app.runtime.memory_runtime import StateTreeError

    run = await _start(runtime)
    failed = await runtime.start_step(StartStepRequest(run_id=run.run_id, intent="debug"))
    await runtime.finish_step(
        FinishStepRequest(run_id=run.run_id, step_id=failed.step_id, status=StepStatus.failed, error_message="boom")
    )
    # Corrupt the tree: point the failed node at a non-existent parent.
    nodes = {n.node_id: n for n in await runtime.get_state_tree(run.run_id)}
    failed_node = nodes[failed.state_node_id]
    failed_node.parent_id = "node_missing"
    await runtime._repo.update_state_node(failed_node)

    with pytest.raises(StateTreeError):
        await runtime.start_step(
            StartStepRequest(run_id=run.run_id, intent="debug", recovery_from_step_id=failed.step_id)
        )
