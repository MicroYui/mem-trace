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
    MemoryItem,
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
    assert _contaminated(ctx) is False
    joined = " ".join(b.content for b in ctx.context_blocks)
    assert "Bun" in joined and "Nodejs" in joined  # merged positive+negative
    assert any("failed-branch" in w for w in ctx.warnings)


async def test_access_inspection_records_all_gate_decisions(runtime):
    run, s3 = await _seed_bun_vs_node(runtime)
    ctx = await runtime.retrieve_context(
        RetrievalRequest(run_id=run.run_id, step_id=s3.step_id, query="run tests npm test",
                         strategy=RetrievalStrategy.variant_2)
    )
    access = await runtime.inspect_access(ctx.access_id)
    assert access is not None
    assert len(access.gate_decisions) >= 1
    # at least one rejection recorded for the failed branch
    assert any(g.decision.value == "reject" for g in access.gate_decisions)


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
