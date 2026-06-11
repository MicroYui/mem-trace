"""End-to-end retrieval, gate, and context packing tests via the runtime facade.

Proves the headline P0 claim: baseline_1 (vector/lexical only) admits the
failed-branch npm memory, while variant_2 (state-aware + gate) rejects it and
keeps the Bun project constraint. Also covers workspace isolation, secret
protection, stale rejection, packing order, and merged project constraints.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.runtime.memory_runtime import MemoryRuntime
from app.runtime.models import (
    BranchStatus,
    EventRole,
    EventType,
    FinishStepRequest,
    GateDecisionType,
    MemoryItem,
    MemoryType,
    RetrievalRequest,
    RetrievalStrategy,
    RiskFlags,
    RollbackRequest,
    Sensitivity,
    StateNode,
    StartRunRequest,
    StartStepRequest,
    StateNodeType,
    StepStatus,
    WriteEventRequest,
)
from app.runtime.repository import InMemoryRepository


async def _seed_bun_vs_node(runtime, ws="ws_test"):
    run = await runtime.start_run(StartRunRequest(session_id="s", task="fix tests", workspace_id=ws))
    s1 = await runtime.start_step(StartStepRequest(run_id=run.run_id, intent="planning"))
    await runtime.write_event(
        WriteEventRequest(run_id=run.run_id, step_id=s1.step_id, role=EventRole.user,
                          event_type=EventType.message, content="这个项目使用 Bun，不用 Node.js")
    )
    await runtime.finish_step(FinishStepRequest(run_id=run.run_id, step_id=s1.step_id, status=StepStatus.completed))
    s2 = await runtime.start_step(StartStepRequest(run_id=run.run_id, intent="debugging"))
    await runtime.write_event(
        WriteEventRequest(run_id=run.run_id, step_id=s2.step_id, role=EventRole.tool,
                          event_type=EventType.tool_result, status="failed",
                          content="Tried running tests with npm test, but it failed because npm was unavailable.")
    )
    await runtime.finish_step(
        FinishStepRequest(run_id=run.run_id, step_id=s2.step_id, status=StepStatus.failed, error_message="npm unavailable")
    )
    await runtime.rollback_branch(RollbackRequest(run_id=run.run_id, step_id=s2.step_id, reason="npm unavailable"))
    s3 = await runtime.start_step(
        StartStepRequest(run_id=run.run_id, intent="debugging", recovery_from_step_id=s2.step_id)
    )
    return run, s3


def _contaminated(ctx) -> bool:
    return any("npm" in b.content.lower() and "failed" in b.content.lower() for b in ctx.context_blocks)


def _positive_contaminated(ctx) -> bool:
    return any(
        "npm" in b.content.lower() and "failed" in b.content.lower()
        for b in ctx.context_blocks
        if b.type != "avoided_attempts" and b.source != "negative_evidence"
    )


async def test_baseline_1_is_contaminated_by_failed_branch(runtime):
    run, s3 = await _seed_bun_vs_node(runtime)
    ctx = await runtime.retrieve_context(
        RetrievalRequest(run_id=run.run_id, step_id=s3.step_id,
                         query="How do I run the test suite with npm test?",
                         strategy=RetrievalStrategy.baseline_1)
    )
    assert _contaminated(ctx) is True


async def test_variant_2_eliminates_contamination_and_keeps_bun(runtime):
    run, s3 = await _seed_bun_vs_node(runtime)
    ctx = await runtime.retrieve_context(
        RetrievalRequest(run_id=run.run_id, step_id=s3.step_id,
                         query="How do I run the test suite with npm test?",
                         strategy=RetrievalStrategy.variant_2)
    )
    assert _positive_contaminated(ctx) is False
    joined = " ".join(b.content for b in ctx.context_blocks)
    assert "Bun" in joined and "Nodejs" in joined  # merged positive+negative
    assert any("negative evidence" in w for w in ctx.warnings)


async def test_variant_2_injects_safe_failed_branch_as_negative_evidence(runtime):
    run, s3 = await _seed_bun_vs_node(runtime)

    ctx = await runtime.retrieve_context(
        RetrievalRequest(run_id=run.run_id, step_id=s3.step_id,
                         query="How do I run tests after npm test failed?",
                         strategy=RetrievalStrategy.variant_2)
    )

    avoided = [b for b in ctx.context_blocks if b.type == "avoided_attempts"]
    assert len(avoided) == 1
    assert "npm test" in avoided[0].content.lower()
    assert "do NOT re-execute" in avoided[0].content
    assert _positive_contaminated(ctx) is False
    assert any("failed-branch memories injected as negative evidence" in w for w in ctx.warnings)

    access = await runtime._repo.get_access_log(ctx.access_id)  # noqa: SLF001
    assert access is not None
    assert access.candidate_count == access.accepted_count + access.rejected_count

    gate_logs = await runtime._repo.list_gate_logs(ctx.access_id)  # noqa: SLF001
    assert any(g.decision == GateDecisionType.degrade and g.reject_reason == "rolled_back_degraded" for g in gate_logs)

    profile_events = await runtime._repo.list_profile_events(access_id=ctx.access_id)  # noqa: SLF001
    packing = [p for p in profile_events if p.phase.value == "context_packing"][-1]
    degraded_logs = [g for g in gate_logs if g.decision == GateDecisionType.degrade]
    assert packing.metadata["degraded_count"] == len(degraded_logs)
    assert packing.metadata["hard_rejected_count"] == access.rejected_count - len(degraded_logs)
    assert packing.metadata["negative_evidence_count"] == 1
    assert packing.metadata["sanitized_negative_evidence_count"] == 0


async def test_variant_2_sanitizes_unsafe_failed_branch_negative_evidence(runtime):
    run = await runtime.start_run(StartRunRequest(session_id="s", task="t", workspace_id="ws_test"))
    s = await runtime.start_step(StartStepRequest(run_id=run.run_id, intent="recover from unsafe deploy"))
    await runtime._repo.add_memory(  # noqa: SLF001
        MemoryItem(workspace_id="ws_test", memory_type=MemoryType.project,
                   key="project.runtime", value="bun",
                   content="This project uses Bun", branch_status=BranchStatus.completed)
    )
    await runtime._repo.add_memory(  # noqa: SLF001
        MemoryItem(workspace_id="ws_test", memory_type=MemoryType.tool_evidence,
                   content="Tried git push --force to production and it failed badly.",
                   branch_status=BranchStatus.failed,
                   risk_flags=RiskFlags(tool_sensitive=True, destructive_command=True))
    )

    ctx = await runtime.retrieve_context(
        RetrievalRequest(run_id=run.run_id, step_id=s.step_id,
                         query="force push production failed avoid",
                         strategy=RetrievalStrategy.variant_2)
    )

    avoided = [b for b in ctx.context_blocks if b.type == "avoided_attempts"]
    assert len(avoided) == 1
    assert "destructive operation" in avoided[0].content
    assert "git push" not in avoided[0].content
    assert "--force" not in avoided[0].content
    assert all("git push --force" not in b.content for b in ctx.context_blocks if b.type != "avoided_attempts")
    assert any("redacted into sanitized safety notices" in w for w in ctx.warnings)

    profile_events = await runtime._repo.list_profile_events(access_id=ctx.access_id)  # noqa: SLF001
    packing = [p for p in profile_events if p.phase.value == "context_packing"][-1]
    assert packing.metadata["degraded_count"] == 0
    assert packing.metadata["negative_evidence_count"] == 1
    assert packing.metadata["sanitized_negative_evidence_count"] == 1

    access = await runtime.inspect_access(ctx.access_id)
    assert access is not None
    serialized_inspection = repr(access.model_dump())
    assert "git push" not in serialized_inspection
    assert "--force" not in serialized_inspection
    assert [b.type for b in access.context_blocks] == [b.type for b in ctx.context_blocks]
    assert [b.content for b in access.context_blocks] == [b.content for b in ctx.context_blocks]


async def test_inspect_access_warns_without_raw_negative_evidence_when_source_memory_missing(runtime):
    run, s3 = await _seed_bun_vs_node(runtime)
    ctx = await runtime.retrieve_context(
        RetrievalRequest(run_id=run.run_id, step_id=s3.step_id, query="npm test failed now use bun",
                         strategy=RetrievalStrategy.variant_2)
    )
    degraded_ids = [
        g.memory_id
        for g in await runtime._repo.list_gate_logs(ctx.access_id)  # noqa: SLF001
        if g.decision == GateDecisionType.degrade
    ]
    assert degraded_ids
    for memory_id in degraded_ids:
        del runtime._repo._memories[memory_id]  # noqa: SLF001 - simulate historical source deletion

    access = await runtime.inspect_access(ctx.access_id)

    assert access is not None
    assert all(
        any(memory_id in warning and "negative evidence source memory" in warning for warning in access.warnings)
        for memory_id in degraded_ids
    )
    assert not [b for b in access.context_blocks if b.type == "avoided_attempts"]


async def test_access_inspection_records_all_gate_decisions(runtime):
    run, s3 = await _seed_bun_vs_node(runtime)
    ctx = await runtime.retrieve_context(
        RetrievalRequest(run_id=run.run_id, step_id=s3.step_id, query="run tests npm test",
                         strategy=RetrievalStrategy.variant_2)
    )
    access = await runtime.inspect_access(ctx.access_id)
    assert access is not None
    assert len(access.gate_decisions) >= 1
    # failed/rolled-back branch decisions are still logged, now as the I3
    # negative-evidence ``degrade`` channel instead of positive acceptance.
    assert any(g.decision.value == "degrade" for g in access.gate_decisions)


async def test_workspace_isolation_no_cross_workspace_candidates():
    repo = InMemoryRepository()
    rt = MemoryRuntime(repo, default_workspace_id="ws_a")
    # seed a memory in ws_b
    await repo.add_memory(MemoryItem(workspace_id="ws_b", memory_type=MemoryType.project,
                                     key="project.runtime", value="deno",
                                     content="This project uses Deno", branch_status=BranchStatus.completed))
    run = await rt.start_run(StartRunRequest(session_id="s", task="t", workspace_id="ws_a"))
    s = await rt.start_step(StartStepRequest(run_id=run.run_id))
    ctx = await rt.retrieve_context(
        RetrievalRequest(run_id=run.run_id, step_id=s.step_id, query="which runtime deno",
                         strategy=RetrievalStrategy.variant_2)
    )
    assert all("Deno" not in b.content for b in ctx.context_blocks)


async def test_secret_memory_is_never_created(runtime):
    run = await runtime.start_run(StartRunRequest(session_id="s", task="t"))
    s = await runtime.start_step(StartStepRequest(run_id=run.run_id))
    r = await runtime.write_event(
        WriteEventRequest(run_id=run.run_id, step_id=s.step_id, role=EventRole.user,
                          event_type=EventType.message,
                          content="api_key=sk-abcdefgh12345678ijklmnop use Bun")
    )
    assert r.created_memory_ids == []  # no retrievable memory from secret content
    timeline = await runtime.get_timeline(run.run_id)
    assert timeline[0].redaction_status == "redacted"
    assert "sk-abcdefgh12345678ijklmnop" not in (timeline[0].content or "")


async def test_stale_memory_rejected(runtime):
    run = await runtime.start_run(StartRunRequest(session_id="s", task="t"))
    s = await runtime.start_step(StartStepRequest(run_id=run.run_id))
    past = datetime.now(timezone.utc) - timedelta(days=2)
    await runtime._repo.add_memory(  # noqa: SLF001
        MemoryItem(workspace_id="ws_test", memory_type=MemoryType.project,
                   content="old endpoint http://old.api/run tests", branch_status=BranchStatus.completed,
                   expires_at=past)
    )
    ctx = await runtime.retrieve_context(
        RetrievalRequest(run_id=run.run_id, step_id=s.step_id, query="run tests endpoint",
                         strategy=RetrievalStrategy.variant_2)
    )
    assert all("old endpoint" not in b.content for b in ctx.context_blocks)
    assert any("stale" in w for w in ctx.warnings)


async def test_tool_sensitive_memory_blocked(runtime):
    run = await runtime.start_run(StartRunRequest(session_id="s", task="t"))
    s = await runtime.start_step(StartStepRequest(run_id=run.run_id))
    await runtime._repo.add_memory(  # noqa: SLF001
        MemoryItem(workspace_id="ws_test", memory_type=MemoryType.tool_evidence,
                   content="run git push --force to deploy tests", branch_status=BranchStatus.completed,
                   risk_flags=RiskFlags(tool_sensitive=True, destructive_command=True))
    )
    ctx = await runtime.retrieve_context(
        RetrievalRequest(run_id=run.run_id, step_id=s.step_id, query="deploy tests push",
                         strategy=RetrievalStrategy.variant_2)
    )
    assert all("--force" not in b.content for b in ctx.context_blocks)
    assert any("tool-sensitive" in w for w in ctx.warnings)


async def test_context_packing_order_active_state_first(runtime):
    run, s3 = await _seed_bun_vs_node(runtime)
    ctx = await runtime.retrieve_context(
        RetrievalRequest(run_id=run.run_id, step_id=s3.step_id, query="run tests bun",
                         strategy=RetrievalStrategy.variant_2)
    )
    assert ctx.context_blocks[0].type == "active_state"


async def test_profile_records_three_phases(runtime):
    run, s3 = await _seed_bun_vs_node(runtime)
    ctx = await runtime.retrieve_context(
        RetrievalRequest(run_id=run.run_id, step_id=s3.step_id, query="run tests",
                         strategy=RetrievalStrategy.variant_2)
    )
    profile_events = await runtime.get_profile(run.run_id)
    phases = {p.phase.value for p in profile_events if p.access_id == ctx.access_id}
    assert {"retrieval", "gate", "context_packing"} <= phases


async def test_superseded_memory_is_not_injected(runtime):
    """Explicit correction supersedes the old project constraint, which must
    never be injected regardless of merge order (lifecycle invariant)."""
    run = await runtime.start_run(StartRunRequest(session_id="s", task="t", workspace_id="ws_test"))
    s1 = await runtime.start_step(StartStepRequest(run_id=run.run_id, intent="planning"))
    await runtime.write_event(
        WriteEventRequest(run_id=run.run_id, step_id=s1.step_id, role=EventRole.user,
                          event_type=EventType.message, content="这个项目使用 Node.js")
    )
    await runtime.write_event(
        WriteEventRequest(run_id=run.run_id, step_id=s1.step_id, role=EventRole.user,
                          event_type=EventType.message, content="不是 Node.js，是 Bun")
    )
    await runtime.finish_step(FinishStepRequest(run_id=run.run_id, step_id=s1.step_id, status=StepStatus.completed))
    s2 = await runtime.start_step(StartStepRequest(run_id=run.run_id, intent="debug"))
    ctx = await runtime.retrieve_context(
        RetrievalRequest(run_id=run.run_id, step_id=s2.step_id, query="which runtime nodejs",
                         strategy=RetrievalStrategy.variant_2)
    )
    joined = " ".join(b.content for b in ctx.context_blocks)
    assert "uses Node" not in joined  # superseded constraint never injected
    assert "Bun" in joined


async def test_access_candidates_ranked_by_relevance(runtime):
    run, s3 = await _seed_bun_vs_node(runtime)
    ctx = await runtime.retrieve_context(
        RetrievalRequest(run_id=run.run_id, step_id=s3.step_id, query="run tests npm test",
                         strategy=RetrievalStrategy.variant_2)
    )
    access = await runtime.inspect_access(ctx.access_id)
    assert access is not None
    # candidates = retrieval-input view ranked by relevance (gate-agnostic);
    # gate_decisions = gate-output view. Both cover the same memories.
    rels = [c.relevance_score for c in access.candidates]
    assert rels == sorted(rels, reverse=True)
    assert {c.memory_id for c in access.candidates} == {g.memory_id for g in access.gate_decisions}


async def test_retrieve_times_out_to_empty_context():
    import asyncio

    repo = InMemoryRepository()
    rt = MemoryRuntime(repo, default_workspace_id="ws_t")
    run = await rt.start_run(StartRunRequest(session_id="s", task="t", workspace_id="ws_t"))
    s = await rt.start_step(StartStepRequest(run_id=run.run_id))
    await repo.add_memory(MemoryItem(workspace_id="ws_t", memory_type=MemoryType.project,
                                     key="project.runtime", value="bun",
                                     content="This project uses Bun", branch_status=BranchStatus.completed))

    # Force a tiny timeout and make candidate selection slow.
    rt._retrieval._timeout_ms = 1  # noqa: SLF001
    orig = rt._retrieval._select_candidates  # noqa: SLF001

    async def _slow(*args, **kwargs):
        await asyncio.sleep(0.2)
        return await orig(*args, **kwargs)

    rt._retrieval._select_candidates = _slow  # noqa: SLF001
    ctx = await rt.retrieve_context(
        RetrievalRequest(run_id=run.run_id, step_id=s.step_id, query="which runtime bun",
                         strategy=RetrievalStrategy.variant_2)
    )
    assert ctx.context_blocks == []
    assert any("timed out" in w for w in ctx.warnings)


def test_pack_context_emits_dynamic_key_project_memory():
    """Project memories with non-runtime keys (e.g. from LLM extraction) must
    still be packed, not silently dropped by the runtime-only merge block."""
    from app.retrieval.packer import pack_context

    db = MemoryItem(workspace_id="ws", memory_type=MemoryType.project,
                    key="project.database", value="PostgreSQL",
                    content="数据库选 PostgreSQL，不要用 MySQL",
                    summary="project.database=PostgreSQL")
    runtime = MemoryItem(workspace_id="ws", memory_type=MemoryType.project,
                         key="project.runtime", value="bun",
                         content="This project uses Bun", summary="project.runtime=bun")
    result = pack_context(active_node=None, accepted=[db, runtime], token_budget=256)
    joined = " ".join(b.content for b in result.blocks)
    # dynamic-key project memory is packed (as its own project_memory block)...
    assert "PostgreSQL" in joined
    # ...and the runtime constraint is still merged into the canonical sentence.
    assert "Bun" in joined
    assert result.used > 0


def test_pack_result_preserves_existing_behavior_when_no_truncation():
    """C0: pack_context should return a structured PackResult without changing
    the packed blocks or token count when the budget is ample."""
    from app.retrieval.packer import PackResult, pack_context

    db = MemoryItem(workspace_id="ws", memory_type=MemoryType.project,
                    key="project.database", value="PostgreSQL",
                    content="数据库选 PostgreSQL", summary="project.database=PostgreSQL")
    runtime = MemoryItem(workspace_id="ws", memory_type=MemoryType.project,
                         key="project.runtime", value="bun",
                         content="This project uses Bun", summary="project.runtime=bun")

    result = pack_context(active_node=None, accepted=[db, runtime], token_budget=256)

    assert isinstance(result, PackResult)
    assert [b.content for b in result.blocks] == ["project.database=PostgreSQL", "This project uses Bun."]
    assert result.used == sum(b.tokens for b in result.blocks)
    assert result.pre_compaction_tokens == result.used
    assert result.dropped_blocks == []
    assert result.notice is None
    assert result.retained_constraints == []


def test_pack_result_reports_pre_compaction_tokens_when_truncated():
    """pre_compaction_tokens describes all candidate blocks, not only the final
    packed subset; C1 also records the blocks omitted under budget pressure."""
    from app.retrieval.packer import pack_context

    first = MemoryItem(workspace_id="ws", memory_type=MemoryType.episodic,
                       content="first retained memory about bun tests")
    second = MemoryItem(workspace_id="ws", memory_type=MemoryType.episodic,
                        content="second lower priority memory about postgres migrations")

    result = pack_context(active_node=None, accepted=[first, second], token_budget=3)
    ample_budget_result = pack_context(active_node=None, accepted=[first, second], token_budget=256)
    expected_candidate_tokens = sum(b.tokens for b in ample_budget_result.blocks)

    assert result.blocks
    assert result.pre_compaction_tokens >= result.used
    assert result.pre_compaction_tokens == expected_candidate_tokens
    assert result.pre_compaction_tokens > result.used
    assert result.dropped_blocks
    assert result.notice is not None


def test_compacted_constraints_preserve_key_values_when_over_budget():
    from app.retrieval.packer import pack_context

    runtime = MemoryItem(workspace_id="ws", memory_type=MemoryType.project,
                         key="project.runtime", value="bun",
                         content="This project uses Bun", summary="project.runtime=bun")
    database = MemoryItem(workspace_id="ws", memory_type=MemoryType.project,
                          key="project.database", value="postgres",
                          content="Use Postgres for durable storage",
                          summary="project.database=postgres")
    endpoint = MemoryItem(workspace_id="ws", memory_type=MemoryType.project,
                          key="endpoint.current", value="/v2/users",
                          content="Current users endpoint is /v2/users",
                          summary="endpoint.current=/v2/users")
    filler = MemoryItem(workspace_id="ws", memory_type=MemoryType.episodic,
                        content="Long lower priority detail " * 20)

    result = pack_context(active_node=None, accepted=[runtime, database, endpoint, filler], token_budget=14)

    compacted = [b for b in result.blocks if b.type == "compacted_constraints"]
    assert compacted
    assert "project.database=postgres" in compacted[0].content
    assert "endpoint.current=/v2/users" in compacted[0].content
    assert [(f.key, f.value) for f in result.retained_constraints] == [
        ("endpoint.current", "/v2/users"),
        ("project.database", "postgres"),
    ]
    assert result.dropped_blocks
    assert result.used <= 14


def test_compaction_notice_emitted_when_over_budget():
    from app.retrieval.packer import pack_context

    memories = [
        MemoryItem(workspace_id="ws", memory_type=MemoryType.episodic,
                   content="first ordinary memory with many words"),
        MemoryItem(workspace_id="ws", memory_type=MemoryType.episodic,
                   content="second ordinary memory with many words"),
    ]

    result = pack_context(active_node=None, accepted=memories, token_budget=8)

    assert result.notice is not None
    assert result.notice.type == "compaction_notice"
    assert result.notice.reason == "kind=budget_notice"
    assert f"dropped {len(result.dropped_blocks)} blocks" in result.notice.content
    assert any(b.type == "compaction_notice" for b in result.blocks)
    assert result.used <= 8


def test_compaction_notice_absent_when_within_budget():
    from app.retrieval.packer import pack_context

    memories = [
        MemoryItem(workspace_id="ws", memory_type=MemoryType.project,
                   key="project.database", value="postgres",
                   content="Use Postgres", summary="project.database=postgres"),
        MemoryItem(workspace_id="ws", memory_type=MemoryType.episodic,
                   content="short detail"),
    ]

    result = pack_context(active_node=None, accepted=memories, token_budget=128)

    assert result.notice is None
    assert result.retained_constraints == []
    assert result.dropped_blocks == []
    assert result.pre_compaction_tokens == result.used
    assert all(b.type not in {"compacted_constraints", "compaction_notice"} for b in result.blocks)


def test_active_state_is_protected_under_tiny_budget():
    from app.retrieval.packer import pack_context

    active = StateNode(workspace_id="ws", run_id="run", node_type=StateNodeType.step,
                       goal="Implement the currently selected migration safely")
    filler = MemoryItem(workspace_id="ws", memory_type=MemoryType.episodic,
                        content="Long lower priority detail " * 30)

    result = pack_context(active_node=active, accepted=[filler], token_budget=20)

    assert result.blocks[0].type == "active_state"
    assert "migration" in result.blocks[0].content
    assert result.used <= 20


def test_protected_block_truncated_not_dropped_when_oversized():
    from app.retrieval.packer import pack_context

    active = StateNode(workspace_id="ws", run_id="run", node_type=StateNodeType.step,
                       goal=" ".join(f"important{i}" for i in range(80)))

    result = pack_context(active_node=active, accepted=[], token_budget=20)

    assert [b.type for b in result.blocks] == ["active_state"]
    assert result.blocks[0].tokens <= 20
    assert "truncated" in (result.blocks[0].reason or "")
    assert result.used <= 20


def test_notice_and_summary_never_exceed_budget():
    from app.retrieval.packer import pack_context

    memories = [
        MemoryItem(workspace_id="ws", memory_type=MemoryType.project,
                   key="project.database", value="postgres-with-a-very-long-value-that-must-be-trimmed",
                   content="database detail", summary="project.database=postgres"),
        MemoryItem(workspace_id="ws", memory_type=MemoryType.project,
                   key="endpoint.current", value="/v2/users/with/a/very/long/path/that/must/be-trimmed",
                   content="endpoint detail", summary="endpoint.current=/v2/users"),
        MemoryItem(workspace_id="ws", memory_type=MemoryType.episodic,
                   content="ordinary detail " * 20),
    ]

    result = pack_context(active_node=None, accepted=memories, token_budget=6)

    assert result.used <= 6
    assert all(b.tokens >= 0 for b in result.blocks)


def test_compaction_notice_is_in_blocks_when_protected_block_fills_budget():
    from app.retrieval.packer import pack_context

    active = StateNode(workspace_id="ws", run_id="run", node_type=StateNodeType.step,
                       goal=" ".join(f"critical{i}" for i in range(40)))
    filler = MemoryItem(workspace_id="ws", memory_type=MemoryType.episodic,
                        content="ordinary detail that must be omitted")

    result = pack_context(active_node=active, accepted=[filler], token_budget=8)

    assert result.notice is not None
    assert any(b.type == "compaction_notice" for b in result.blocks)
    assert result.used <= 8


def test_pack_context_respects_custom_compaction_notice_reserve_tokens():
    from app.retrieval.packer import pack_context

    runtime = MemoryItem(workspace_id="ws", memory_type=MemoryType.project,
                         key="project.runtime", value="bun",
                         content="This project uses Bun", summary="project.runtime=bun")
    database = MemoryItem(workspace_id="ws", memory_type=MemoryType.project,
                          key="project.database", value="postgres",
                          content="Use Postgres for durable storage",
                          summary="project.database=postgres")
    endpoint = MemoryItem(workspace_id="ws", memory_type=MemoryType.project,
                          key="endpoint.current", value="/v2/users",
                          content="Current users endpoint is /v2/users",
                          summary="endpoint.current=/v2/users")
    filler = MemoryItem(workspace_id="ws", memory_type=MemoryType.episodic,
                        content="Long lower priority detail " * 20)

    high_reserve = pack_context(
        active_node=None,
        accepted=[runtime, database, endpoint, filler],
        token_budget=14,
        compaction_notice_reserve_tokens=12,
    )
    low_reserve = pack_context(
        active_node=None,
        accepted=[runtime, database, endpoint, filler],
        token_budget=14,
        compaction_notice_reserve_tokens=4,
    )

    assert [f.key for f in high_reserve.retained_constraints] == ["endpoint.current", "project.database"]
    assert low_reserve.retained_constraints == []


async def test_compaction_never_includes_failed_branch_block(runtime):
    run, s3 = await _seed_bun_vs_node(runtime)

    trace = await runtime._retrieval.trace(  # noqa: SLF001
        RetrievalRequest(run_id=run.run_id, step_id=s3.step_id, query="run tests npm bun",
                         strategy=RetrievalStrategy.variant_2, token_budget=6),
        workspace_id="ws_test",
    )
    dropped_blocks = trace.phase_profile["context_packing"]["metadata"]["dropped_blocks"]
    dropped_positive_text = " ".join(
        b["content"] for b in dropped_blocks
        if b["type"] != "avoided_attempts" and b.get("source") != "negative_evidence"
    )
    retained_text = " ".join(
        f"{f['key']}={f['value']}" for f in trace.phase_profile["context_packing"]["metadata"]["retained_constraints"]
    )

    assert "npm test" not in dropped_positive_text.lower()
    assert "npm test" not in retained_text.lower()


def test_pack_result_pre_compaction_tokens_equals_sum_of_candidates():
    from app.retrieval.packer import pack_context

    memories = [
        MemoryItem(workspace_id="ws", memory_type=MemoryType.project,
                   key="project.runtime", value="bun", content="This project uses Bun"),
        MemoryItem(workspace_id="ws", memory_type=MemoryType.project,
                   key="project.database", value="postgres", content="Use Postgres", summary="project.database=postgres"),
        MemoryItem(workspace_id="ws", memory_type=MemoryType.episodic,
                   content="ordinary detail " * 8),
    ]
    compacted = pack_context(active_node=None, accepted=memories, token_budget=8)
    ample = pack_context(active_node=None, accepted=memories, token_budget=256)

    assert compacted.pre_compaction_tokens == sum(b.tokens for b in ample.blocks)


async def test_context_budget_warning_and_profile_metadata(runtime):
    run = await runtime.start_run(StartRunRequest(session_id="s", task="t", workspace_id="ws_test"))
    s = await runtime.start_step(StartStepRequest(run_id=run.run_id))
    await runtime.write_event(
        WriteEventRequest(run_id=run.run_id, step_id=s.step_id, role=EventRole.user,
                          event_type=EventType.message, content="This project uses Bun and Postgres")
    )
    await runtime._repo.add_memory(  # noqa: SLF001
        MemoryItem(workspace_id="ws_test", memory_type=MemoryType.project,
                   key="project.database", value="postgres",
                   content="Use postgres for storage", summary="project.database=postgres",
                   branch_status=BranchStatus.completed)
    )
    await runtime._repo.add_memory(  # noqa: SLF001
        MemoryItem(workspace_id="ws_test", memory_type=MemoryType.episodic,
                   content="postgres bun migration detail " * 20,
                   branch_status=BranchStatus.completed)
    )
    await runtime.finish_step(FinishStepRequest(run_id=run.run_id, step_id=s.step_id, status=StepStatus.completed))

    ctx = await runtime.retrieve_context(
        RetrievalRequest(run_id=run.run_id, step_id=s.step_id, query="bun postgres",
                         strategy=RetrievalStrategy.variant_2, token_budget=5)
    )

    assert any("context budget exceeded" in w for w in ctx.warnings)
    profile_events = await runtime._repo.list_profile_events(run_id=run.run_id)  # noqa: SLF001
    packing = [p for p in profile_events if p.phase.value == "context_packing"][-1]
    assert packing.metadata["dropped_count"] > 0
    assert packing.metadata["pre_compaction_tokens"] >= packing.metadata["actual_tokens"]
    assert 0 <= packing.metadata["compression_ratio"] <= 1


async def test_inspect_access_unchanged_after_pack_result_refactor(runtime):
    """C0 callsite guard: inspect_access should still reconstruct the same
    context blocks after pack_context returns PackResult."""
    run, s3 = await _seed_bun_vs_node(runtime)
    ctx = await runtime.retrieve_context(
        RetrievalRequest(run_id=run.run_id, step_id=s3.step_id, query="run tests bun",
                         strategy=RetrievalStrategy.variant_2)
    )

    access = await runtime.inspect_access(ctx.access_id)

    assert access is not None
    assert [b.type for b in access.context_blocks] == [b.type for b in ctx.context_blocks]
    assert [b.content for b in access.context_blocks] == [b.content for b in ctx.context_blocks]
