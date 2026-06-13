"""Strategy-level conformance tests for non-bypassable retrieval invariants."""
from __future__ import annotations

import json

import pytest

from app.runtime.memory_runtime import MemoryRuntime
from app.runtime.models import (
    BranchStatus,
    MemoryItem,
    MemoryStatus,
    MemoryType,
    RetrievalRequest,
    RetrievalStrategy,
    RiskFlags,
    Sensitivity,
    StartRunRequest,
    StartStepRequest,
)
from app.runtime.repository import InMemoryRepository


async def _seed_strategy_fixture(strategy: RetrievalStrategy):
    repo = InMemoryRepository()
    runtime = MemoryRuntime(repo, default_workspace_id="ws_conf_strategy")
    run = await runtime.start_run(
        StartRunRequest(workspace_id="ws_conf_strategy", session_id="s", task="marker recall")
    )
    step = await runtime.start_step(StartStepRequest(run_id=run.run_id, intent="recall marker"))
    memory_ids: dict[str, str] = {}
    active = await repo.add_memory(
        MemoryItem(
            workspace_id="ws_conf_strategy",
            run_id=run.run_id,
            memory_id="mem_active_marker",
            memory_type=MemoryType.episodic,
            content="ACTIVE_ALLOWED_MARKER marker",
            branch_status=BranchStatus.completed,
        )
    )
    memory_ids["active"] = active.memory_id
    for status, marker in (
        (MemoryStatus.superseded, "SUPERSEDED_MARKER"),
        (MemoryStatus.archived, "ARCHIVED_MARKER"),
        (MemoryStatus.dormant, "DORMANT_MARKER"),
        (MemoryStatus.deleted, "DELETED_MARKER"),
    ):
        memory = await repo.add_memory(
            MemoryItem(
                workspace_id="ws_conf_strategy",
                run_id=run.run_id,
                memory_type=MemoryType.episodic,
                content=f"{marker} marker",
                status=status,
                branch_status=BranchStatus.completed,
            )
        )
        memory_ids[status.value] = memory.memory_id
    other = await repo.add_memory(
        MemoryItem(
            workspace_id="other_workspace",
            run_id=run.run_id,
            memory_type=MemoryType.episodic,
            content="OTHER_WORKSPACE_MARKER marker",
            branch_status=BranchStatus.completed,
        )
    )
    memory_ids["other_workspace"] = other.memory_id
    quarantined = await repo.add_memory(
        MemoryItem(
            workspace_id="ws_conf_strategy",
            run_id=run.run_id,
            memory_type=MemoryType.episodic,
            content="QUARANTINED_MARKER marker",
            status=MemoryStatus.quarantined,
            branch_status=BranchStatus.completed,
        )
    )
    memory_ids["quarantined"] = quarantined.memory_id
    secret = await repo.add_memory(
        MemoryItem(
            workspace_id="ws_conf_strategy",
            run_id=run.run_id,
            memory_type=MemoryType.episodic,
            content="SECRET_RAW_MARKER sk-1234567890abcdef marker",
            sensitivity=Sensitivity.secret,
            risk_flags=RiskFlags(contains_secret=True),
            branch_status=BranchStatus.completed,
        )
    )
    memory_ids["secret"] = secret.memory_id
    destructive = await repo.add_memory(
        MemoryItem(
            workspace_id="ws_conf_strategy",
            run_id=run.run_id,
            memory_type=MemoryType.tool_evidence,
            content="DESTRUCTIVE_MARKER rm -rf / marker",
            risk_flags=RiskFlags(destructive_command=True),
            branch_status=BranchStatus.completed,
        )
    )
    memory_ids["destructive"] = destructive.memory_id
    tool_sensitive = await repo.add_memory(
        MemoryItem(
            workspace_id="ws_conf_strategy",
            run_id=run.run_id,
            memory_type=MemoryType.tool_evidence,
            content="TOOL_SENSITIVE_MARKER production deploy marker",
            risk_flags=RiskFlags(tool_sensitive=True),
            branch_status=BranchStatus.completed,
        )
    )
    memory_ids["tool_sensitive"] = tool_sensitive.memory_id
    ctx = await runtime.retrieve_context(
        RetrievalRequest(run_id=run.run_id, step_id=step.step_id, query="marker", strategy=strategy, top_k=20)
    )
    return runtime, ctx, memory_ids


@pytest.mark.parametrize("strategy", list(RetrievalStrategy))
@pytest.mark.asyncio
async def test_all_strategies_apply_workspace_lifecycle_and_safety_floors(strategy):
    runtime, ctx, memory_ids = await _seed_strategy_fixture(strategy)

    rendered = "\n".join(block.content for block in ctx.context_blocks)
    assert "OTHER_WORKSPACE_MARKER" not in rendered
    assert "SUPERSEDED_MARKER" not in rendered
    assert "ARCHIVED_MARKER" not in rendered
    assert "DORMANT_MARKER" not in rendered
    assert "DELETED_MARKER" not in rendered
    assert "QUARANTINED_MARKER" not in rendered
    assert "SECRET_RAW_MARKER" not in rendered
    assert "sk-1234567890abcdef" not in rendered
    assert "DESTRUCTIVE_MARKER" not in rendered
    assert "TOOL_SENSITIVE_MARKER" not in rendered

    if strategy == RetrievalStrategy.baseline_0:
        assert ctx.context_blocks == []
        return

    assert "ACTIVE_ALLOWED_MARKER" in rendered

    access = await runtime.inspect_access(ctx.access_id)
    candidate_ids = {candidate.memory_id for candidate in access.candidates}
    gate_by_id = {gate.memory_id: gate for gate in access.gate_decisions}

    assert memory_ids["active"] in candidate_ids
    assert memory_ids["other_workspace"] not in candidate_ids
    for status in ("superseded", "archived", "dormant", "deleted"):
        assert memory_ids[status] not in candidate_ids

    assert gate_by_id[memory_ids["quarantined"]].decision.value == "reject"
    assert gate_by_id[memory_ids["quarantined"]].reject_reason == "invalid_status"
    assert gate_by_id[memory_ids["secret"]].decision.value == "reject"
    assert gate_by_id[memory_ids["secret"]].reject_reason == "secret"
    assert gate_by_id[memory_ids["destructive"]].decision.value == "reject"
    assert gate_by_id[memory_ids["destructive"]].reject_reason == "destructive_command"
    assert gate_by_id[memory_ids["tool_sensitive"]].decision.value == "reject"
    assert gate_by_id[memory_ids["tool_sensitive"]].reject_reason == "tool_sensitive"


@pytest.mark.parametrize("strategy", [s for s in RetrievalStrategy if s != RetrievalStrategy.baseline_0])
@pytest.mark.asyncio
async def test_memory_using_strategies_reject_destructive_and_tool_sensitive_candidates(strategy):
    runtime, ctx, memory_ids = await _seed_strategy_fixture(strategy)

    rendered = "\n".join(block.content for block in ctx.context_blocks)
    access = await runtime.inspect_access(ctx.access_id)
    gate_by_id = {gate.memory_id: gate for gate in access.gate_decisions}

    assert "ACTIVE_ALLOWED_MARKER" in rendered
    assert "DESTRUCTIVE_MARKER" not in rendered
    assert "TOOL_SENSITIVE_MARKER" not in rendered
    assert gate_by_id[memory_ids["destructive"]].reject_reason == "destructive_command"
    assert gate_by_id[memory_ids["tool_sensitive"]].reject_reason == "tool_sensitive"


@pytest.mark.asyncio
async def test_access_policy_provider_snapshot_is_non_secret_and_retrieval_relevant():
    runtime, ctx, _ = await _seed_strategy_fixture(RetrievalStrategy.variant_2)

    inspection = await runtime.inspect_access(ctx.access_id)
    providers = inspection.policy_snapshot["providers"]
    snapshot_text = json.dumps(providers, sort_keys=True)

    assert set(providers) == {"embedding", "summarizer"}
    assert providers["embedding"]["provider_id"]
    assert providers["summarizer"]["provider_id"]
    assert "judge" not in providers
    assert "api_key" not in snapshot_text
    assert "authorization" not in snapshot_text
    assert "sk-" not in snapshot_text
    assert "secret" not in snapshot_text


@pytest.mark.asyncio
async def test_variant_1_relaxes_failed_branch_but_keeps_destructive_safety_floor():
    repo = InMemoryRepository()
    runtime = MemoryRuntime(repo, default_workspace_id="ws_conf_variant1")
    run = await runtime.start_run(StartRunRequest(workspace_id="ws_conf_variant1", session_id="s", task="recover"))
    step = await runtime.start_step(StartStepRequest(run_id=run.run_id, intent="recover"))
    await repo.add_memory(
        MemoryItem(
            workspace_id="ws_conf_variant1",
            run_id=run.run_id,
            memory_type=MemoryType.episodic,
            content="SAFE_FAILED_MARKER tried npm and it failed",
            branch_status=BranchStatus.failed,
        )
    )
    await repo.add_memory(
        MemoryItem(
            workspace_id="ws_conf_variant1",
            run_id=run.run_id,
            memory_type=MemoryType.tool_evidence,
            content="DESTRUCTIVE_MARKER run rm -rf /",
            risk_flags=RiskFlags(destructive_command=True),
            branch_status=BranchStatus.completed,
        )
    )

    ctx = await runtime.retrieve_context(
        RetrievalRequest(
            run_id=run.run_id,
            step_id=step.step_id,
            query="failed destructive marker",
            strategy=RetrievalStrategy.variant_1,
            top_k=10,
        )
    )

    rendered = "\n".join(block.content for block in ctx.context_blocks)
    assert "SAFE_FAILED_MARKER" in rendered
    assert "DESTRUCTIVE_MARKER" not in rendered
