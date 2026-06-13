"""Side-effect-free retrieval trace tests for Phase 3-A Issue 2."""
from __future__ import annotations

import pytest

from app.runtime.memory_runtime import MemoryRuntime
from app.runtime.models import (
    BranchStatus,
    MemoryItem,
    MemoryType,
    RetrievalRequest,
    RetrievalStrategy,
    StartRunRequest,
    StartStepRequest,
)
from app.runtime.repository import InMemoryRepository


async def _seed_runtime_with_project_memory() -> tuple[MemoryRuntime, InMemoryRepository, str, str, str]:
    repo = InMemoryRepository()
    runtime = MemoryRuntime(repo, default_workspace_id="ws_trace")
    run = await runtime.start_run(StartRunRequest(session_id="s_trace", task="fix tests", workspace_id="ws_trace"))
    step = await runtime.start_step(StartStepRequest(run_id=run.run_id, intent="debug tests"))
    memory = await repo.add_memory(
        MemoryItem(
            workspace_id="ws_trace",
            run_id=run.run_id,
            memory_type=MemoryType.project,
            key="project.runtime",
            value="bun",
            content="This project uses Bun to run tests",
            branch_status=BranchStatus.completed,
        )
    )
    return runtime, repo, run.run_id, step.step_id, memory.memory_id


@pytest.mark.asyncio
async def test_trace_matches_retrieve_context_without_persisting_logs():
    runtime, repo, run_id, step_id, memory_id = await _seed_runtime_with_project_memory()
    request = RetrievalRequest(
        run_id=run_id,
        step_id=step_id,
        query="run tests with bun",
        strategy=RetrievalStrategy.variant_2,
        top_k=5,
    )
    before_memory = await repo.get_memory(memory_id)
    assert before_memory is not None
    before_memory_dump = before_memory.model_dump()

    trace = await runtime._retrieval.trace(request, workspace_id="ws_trace")  # noqa: SLF001

    assert trace.access_record.top_k == 5
    assert [c.memory.memory_id for c in trace.candidates] == [memory_id]
    assert trace.gate_outcomes and trace.gate_outcomes[0].memory.memory_id == memory_id
    assert trace.context_blocks
    assert {"retrieval", "gate", "context_packing"} <= set(trace.phase_profile)

    assert await repo.list_access_logs() == []
    assert await repo.list_gate_logs(trace.access_record.access_id) == []
    assert await repo.list_profile_events() == []
    stored_memory = await repo.get_memory(memory_id)
    assert stored_memory is not None
    assert stored_memory.access_count == 0
    assert stored_memory.model_dump() == before_memory_dump

    ctx = await runtime.retrieve_context(request)
    assert [b.model_dump() for b in ctx.context_blocks] == [b.model_dump() for b in trace.context_blocks]
    assert ctx.warnings == trace.warnings
    assert ctx.profile["candidate_count"] == trace.access_record.candidate_count
    assert ctx.profile["accepted_count"] == trace.access_record.accepted_count
    assert ctx.profile["rejected_count"] == trace.access_record.rejected_count
    assert ctx.profile["token_budget"] == trace.access_record.token_budget
    assert ctx.profile["actual_tokens"] == trace.access_record.actual_tokens
    assert ctx.profile["strategy"] == trace.access_record.retrieval_strategy.value

    persisted_access = await repo.get_access_log(ctx.access_id)
    assert persisted_access is not None
    assert persisted_access.workspace_id == trace.access_record.workspace_id
    assert persisted_access.run_id == trace.access_record.run_id
    assert persisted_access.step_id == trace.access_record.step_id
    assert persisted_access.query == trace.access_record.query
    assert persisted_access.task_intent == trace.access_record.task_intent
    assert persisted_access.retrieval_strategy == trace.access_record.retrieval_strategy
    assert persisted_access.token_budget == trace.access_record.token_budget
    assert persisted_access.top_k == trace.access_record.top_k
    assert persisted_access.candidate_count == trace.access_record.candidate_count
    assert persisted_access.accepted_count == trace.access_record.accepted_count
    assert persisted_access.rejected_count == trace.access_record.rejected_count
    assert persisted_access.actual_tokens == trace.access_record.actual_tokens

    persisted_gate_logs = await repo.list_gate_logs(ctx.access_id)
    assert len(persisted_gate_logs) == len(trace.gate_outcomes)
    for gate_log, outcome in zip(persisted_gate_logs, trace.gate_outcomes):
        assert gate_log.memory_id == outcome.memory.memory_id
        assert gate_log.layer == outcome.layer
        assert gate_log.decision == outcome.decision
        assert gate_log.reject_reason == outcome.reject_reason
        assert gate_log.relevance_score == outcome.relevance_score
        assert gate_log.state_match_score == outcome.state_match_score
        assert gate_log.freshness_score == outcome.freshness_score
        assert gate_log.trust_score == outcome.trust_score
        assert gate_log.risk_score == outcome.risk_score
        assert gate_log.final_score == outcome.final_score

    persisted_profile = await repo.list_profile_events(access_id=ctx.access_id)
    by_phase = {event.phase.value: event for event in persisted_profile}
    for phase, profile in trace.phase_profile.items():
        assert phase in by_phase
        assert by_phase[phase].operation == profile["operation"]
        assert by_phase[phase].candidate_count == profile["candidate_count"]
        assert by_phase[phase].accepted_count == profile["accepted_count"]
        assert by_phase[phase].rejected_count == profile["rejected_count"]


@pytest.mark.asyncio
async def test_hot_path_persists_trace_and_keeps_existing_context_output():
    runtime, repo, run_id, step_id, memory_id = await _seed_runtime_with_project_memory()
    request = RetrievalRequest(
        run_id=run_id,
        step_id=step_id,
        query="run tests with bun",
        strategy=RetrievalStrategy.variant_2,
        token_budget=128,
        top_k=3,
    )

    ctx = await runtime.retrieve_context(request)
    assert ctx.context_blocks
    access = await repo.get_access_log(ctx.access_id)
    assert access is not None
    assert access.top_k == 3
    assert access.candidate_count == 1
    assert access.accepted_count == 1
    assert access.rejected_count == 0
    assert access.actual_tokens == ctx.profile["actual_tokens"]
    gate_logs = await repo.list_gate_logs(ctx.access_id)
    assert [g.memory_id for g in gate_logs] == [memory_id]
    phases = {p.phase.value for p in await repo.list_profile_events(access_id=ctx.access_id)}
    assert {"retrieval", "gate", "context_packing"} <= phases
    stored_memory = await repo.get_memory(memory_id)
    assert stored_memory is not None
    assert stored_memory.access_count == 1


@pytest.mark.asyncio
async def test_candidate_selection_uses_memory_id_tiebreak_for_equal_scores():
    repo = InMemoryRepository()
    runtime = MemoryRuntime(repo, default_workspace_id="ws_trace_tie")
    run = await runtime.start_run(StartRunRequest(session_id="s_trace_tie", task="tie", workspace_id="ws_trace_tie"))
    step = await runtime.start_step(StartStepRequest(run_id=run.run_id, intent="retrieve tie"))
    await repo.add_memory(
        MemoryItem(
            memory_id="mem_z_equal",
            workspace_id="ws_trace_tie",
            run_id=run.run_id,
            memory_type=MemoryType.episodic,
            content="same deterministic retrieval marker",
            branch_status=BranchStatus.completed,
        )
    )
    await repo.add_memory(
        MemoryItem(
            memory_id="mem_a_equal",
            workspace_id="ws_trace_tie",
            run_id=run.run_id,
            memory_type=MemoryType.episodic,
            content="same deterministic retrieval marker",
            branch_status=BranchStatus.completed,
        )
    )

    trace = await runtime._retrieval.trace(  # noqa: SLF001
        RetrievalRequest(
            run_id=run.run_id,
            step_id=step.step_id,
            query="same deterministic retrieval marker",
            strategy=RetrievalStrategy.baseline_1,
            top_k=2,
        ),
        workspace_id="ws_trace_tie",
    )

    assert [candidate.memory.memory_id for candidate in trace.candidates] == ["mem_a_equal", "mem_z_equal"]


@pytest.mark.asyncio
async def test_access_log_persists_retrieval_policy_snapshot():
    runtime, repo, run_id, step_id, _ = await _seed_runtime_with_project_memory()

    ctx = await runtime.retrieve_context(
        RetrievalRequest(
            run_id=run_id,
            step_id=step_id,
            query="run tests with bun",
            strategy=RetrievalStrategy.variant_2,
            token_budget=123,
            top_k=4,
        )
    )

    access = await repo.get_access_log(ctx.access_id)
    assert access is not None
    assert access.policy_version == "retrieval-policy-v1"
    assert access.policy_snapshot["strategy"] == "variant_2"
    assert access.policy_snapshot["top_k"] == 4
    assert access.policy_snapshot["token_budget"] == 123
    assert access.policy_snapshot["gate_config"]["enable_failure_learning"] is True
    assert access.policy_snapshot["retrieval"]["lifecycle_filter_version"] == "retrievable-statuses-v1"
    assert access.policy_snapshot["packer"]["token_estimator_version"] == "regex-stopword-cjk-v1"
    assert access.policy_hash.startswith("sha256:")


@pytest.mark.asyncio
async def test_timeout_access_log_persists_policy_snapshot(monkeypatch):
    repo = InMemoryRepository()
    controller = MemoryRuntime(repo, default_workspace_id="ws_policy_timeout")._retrieval  # noqa: SLF001
    controller._timeout_ms = 1  # noqa: SLF001 - force timeout path

    async def slow_trace(*args, **kwargs):
        import asyncio

        await asyncio.sleep(1)

    monkeypatch.setattr(controller, "trace", slow_trace)
    request = RetrievalRequest(
        run_id="run_policy_timeout",
        query="q",
        strategy=RetrievalStrategy.long_context,
        token_budget=77,
        top_k=6,
    )

    ctx = await controller.retrieve(request, workspace_id="ws_policy_timeout")

    access = await repo.get_access_log(ctx.access_id)
    assert access is not None
    assert access.policy_version == "retrieval-policy-v1"
    assert access.policy_snapshot["strategy"] == "long_context"
    assert access.policy_snapshot["top_k"] == 6
    assert access.policy_snapshot["token_budget"] == 77
    assert access.policy_snapshot["retrieval"]["include_all"] is True
    assert access.policy_hash.startswith("sha256:")


@pytest.mark.asyncio
async def test_trace_exposes_lexical_and_vector_components():
    runtime, _, run_id, step_id, _ = await _seed_runtime_with_project_memory()
    runtime._retrieval._use_vector = True  # noqa: SLF001
    runtime._retrieval._vector_weight = 0.25  # noqa: SLF001
    request = RetrievalRequest(
        run_id=run_id,
        step_id=step_id,
        query="run tests with bun",
        strategy=RetrievalStrategy.variant_2,
    )

    trace = await runtime._retrieval.trace(request, workspace_id="ws_trace")  # noqa: SLF001

    assert len(trace.candidates) == 1
    candidate = trace.candidates[0]
    assert candidate.lexical_score > 0.0
    assert candidate.vector_score > 0.0
    expected = round(0.75 * candidate.lexical_score + 0.25 * candidate.vector_score, 6)
    assert candidate.relevance_score == expected
    assert candidate.state_match_score == trace.gate_outcomes[0].state_match_score
