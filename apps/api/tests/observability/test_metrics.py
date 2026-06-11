"""Phase 3-A Issue 5 quality/safety metric tests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.observability import metrics
from app.runtime.memory_runtime import MemoryRuntime
from app.runtime.models import (
    BranchStatus,
    GateDecisionType,
    GateLayer,
    CompactionKind,
    CompactionProvider,
    ContextCompactionLog,
    MemoryAccessLog,
    MemoryGateLog,
    MemoryItem,
    MemoryStatus,
    MemoryType,
    ProfileEvent,
    ProfilePhase,
    RetrievalStrategy,
    RiskFlags,
)
from app.runtime.repository import InMemoryRepository


def _memory(**overrides) -> MemoryItem:
    defaults = {
        "workspace_id": "ws_metrics",
        "memory_type": MemoryType.project,
        "content": "metric fixture memory",
    }
    defaults.update(overrides)
    return MemoryItem(**defaults)


def _gate(access_id: str, memory_id: str, decision: GateDecisionType, reject_reason: str | None = None) -> MemoryGateLog:
    return MemoryGateLog(
        access_id=access_id,
        memory_id=memory_id,
        layer=GateLayer.risk_policy,
        decision=decision,
        reject_reason=reject_reason,
    )


def _compaction_log(access_id: str, **overrides) -> ContextCompactionLog:
    defaults = {
        "access_id": access_id,
        "workspace_id": "ws_metrics",
        "kind": CompactionKind.budget_notice,
        "provider": CompactionProvider.rule,
        "pre_tokens": 40,
        "post_tokens": 10,
        "dropped_block_count": 2,
        "compression_ratio": 0.25,
    }
    defaults.update(overrides)
    return ContextCompactionLog(**defaults)


async def _add_logged_memory(
    repo: InMemoryRepository,
    access_id: str,
    memory: MemoryItem,
    decision: GateDecisionType,
    reject_reason: str | None = None,
) -> tuple[MemoryItem, MemoryGateLog]:
    stored = await repo.add_memory(memory)
    gate = await repo.add_gate_log(_gate(access_id, stored.memory_id, decision, reject_reason))
    return stored, gate


def test_profile_phase_keeps_existing_values_and_adds_architecture_phases():
    assert ProfilePhase.retrieval.value == "retrieval"
    assert ProfilePhase.gate.value == "gate"
    assert ProfilePhase.context_packing.value == "context_packing"

    for value in {
        "ingestion",
        "construction",
        "rerank",
        "generation",
        "maintenance",
        "quality",
        "safety",
    }:
        assert ProfilePhase(value).value == value


@pytest.mark.asyncio
async def test_access_metrics_cover_all_quality_safety_signals():
    repo = InMemoryRepository()
    access = await repo.add_access_log(
        MemoryAccessLog(
            workspace_id="ws_metrics",
            run_id="run_metrics",
            retrieval_strategy=RetrievalStrategy.variant_2,
            candidate_count=8,
            accepted_count=3,
            rejected_count=5,
            actual_tokens=321,
            latency_ms=42,
        )
    )
    past = datetime.now(timezone.utc) - timedelta(days=1)

    failed_injected, failed_injected_gate = await _add_logged_memory(
        repo,
        access.access_id,
        _memory(branch_status=BranchStatus.failed),
        GateDecisionType.accept,
    )
    failed_rejected, failed_rejected_gate = await _add_logged_memory(
        repo,
        access.access_id,
        _memory(branch_status=BranchStatus.rolled_back),
        GateDecisionType.reject,
        "rolled_back",
    )
    stale_injected, stale_injected_gate = await _add_logged_memory(
        repo,
        access.access_id,
        _memory(expires_at=past),
        GateDecisionType.accept,
    )
    stale_rejected, stale_rejected_gate = await _add_logged_memory(
        repo,
        access.access_id,
        _memory(expires_at=past),
        GateDecisionType.reject,
        "stale",
    )
    tool_blocked, tool_blocked_gate = await _add_logged_memory(
        repo,
        access.access_id,
        _memory(risk_flags=RiskFlags(tool_sensitive=True)),
        GateDecisionType.reject,
        "tool_sensitive",
    )
    destructive_blocked, destructive_blocked_gate = await _add_logged_memory(
        repo,
        access.access_id,
        _memory(risk_flags=RiskFlags(destructive_command=True)),
        GateDecisionType.reject,
        "destructive_command",
    )
    workspace_leak, workspace_leak_gate = await _add_logged_memory(
        repo,
        access.access_id,
        _memory(workspace_id="ws_other"),
        GateDecisionType.reject,
        "workspace_mismatch",
    )
    superseded_injected, superseded_injected_gate = await _add_logged_memory(
        repo,
        access.access_id,
        _memory(status=MemoryStatus.superseded),
        GateDecisionType.accept,
    )

    candidate_memories = [
        failed_injected,
        failed_rejected,
        stale_injected,
        stale_rejected,
        tool_blocked,
        destructive_blocked,
        workspace_leak,
        superseded_injected,
    ]
    accepted_memories = [failed_injected, stale_injected, superseded_injected]
    gate_logs = [
        failed_injected_gate,
        failed_rejected_gate,
        stale_injected_gate,
        stale_rejected_gate,
        tool_blocked_gate,
        destructive_blocked_gate,
        workspace_leak_gate,
        superseded_injected_gate,
    ]

    access_metrics = metrics.build_access_observability_metrics(
        access,
        gate_logs,
        candidate_memories,
        accepted_memories,
        [_compaction_log(access.access_id)],
    )

    assert access_metrics == {
        "access_count": 1.0,
        "candidate_count": 8.0,
        "accepted_count": 3.0,
        "rejected_count": 5.0,
        "latency_ms": 42.0,
        "actual_tokens": 321.0,
        "failed_branch_rejected": 1.0,
        "failed_branch_injected": 1.0,
        "stale_rejected": 1.0,
        "stale_injected": 1.0,
        "tool_sensitive_blocked": 1.0,
        "destructive_command_blocked": 1.0,
        "risk_blocked": 2.0,
        "workspace_mismatch_rejected": 1.0,
        "workspace_leakage": 0.0,
        "superseded_injected": 1.0,
        "compaction_triggered": 1.0,
        "dropped_block_count": 2.0,
        "pre_compaction_tokens": 40.0,
        "post_compaction_tokens": 10.0,
        "compression_ratio_sum": 0.25,
        "compression_ratio_present": 1.0,
        "history_summary_count": 0.0,
    }


@pytest.mark.asyncio
async def test_summary_filters_and_by_strategy_rates():
    repo = InMemoryRepository()
    first = await repo.add_access_log(
        MemoryAccessLog(
            workspace_id="ws_metrics",
            run_id="run_keep",
            retrieval_strategy=RetrievalStrategy.variant_2,
            candidate_count=2,
            accepted_count=1,
            rejected_count=1,
            actual_tokens=100,
            latency_ms=20,
        )
    )
    second = await repo.add_access_log(
        MemoryAccessLog(
            workspace_id="ws_metrics",
            run_id="run_keep",
            retrieval_strategy=RetrievalStrategy.variant_2,
            candidate_count=4,
            accepted_count=2,
            rejected_count=2,
            actual_tokens=200,
            latency_ms=40,
        )
    )
    ignored_run = await repo.add_access_log(
        MemoryAccessLog(
            workspace_id="ws_metrics",
            run_id="run_ignore",
            retrieval_strategy=RetrievalStrategy.baseline_1,
            candidate_count=100,
            accepted_count=100,
            rejected_count=0,
            actual_tokens=999,
            latency_ms=999,
        )
    )
    other_workspace = await repo.add_access_log(
        MemoryAccessLog(
            workspace_id="ws_other",
            run_id="run_keep",
            retrieval_strategy=RetrievalStrategy.baseline_0,
            candidate_count=100,
            accepted_count=0,
            rejected_count=100,
        )
    )
    await _add_logged_memory(repo, first.access_id, _memory(branch_status=BranchStatus.failed), GateDecisionType.reject, "failed_branch")
    await _add_logged_memory(repo, first.access_id, _memory(risk_flags=RiskFlags(tool_sensitive=True)), GateDecisionType.reject, "tool_sensitive")
    await _add_logged_memory(repo, second.access_id, _memory(expires_at=datetime.now(timezone.utc) - timedelta(days=1)), GateDecisionType.accept)
    await _add_logged_memory(repo, second.access_id, _memory(status=MemoryStatus.superseded), GateDecisionType.accept)
    await repo.add_compaction_log(_compaction_log(first.access_id, run_id="run_keep", pre_tokens=40, post_tokens=10, dropped_block_count=2, compression_ratio=0.25))
    await repo.add_compaction_log(_compaction_log(second.access_id, run_id="run_keep", pre_tokens=50, post_tokens=25, dropped_block_count=1, compression_ratio=0.5))
    await _add_logged_memory(repo, ignored_run.access_id, _memory(status=MemoryStatus.superseded), GateDecisionType.accept)
    await _add_logged_memory(repo, other_workspace.access_id, _memory(workspace_id="ws_metrics"), GateDecisionType.reject, "workspace_mismatch")

    summary = await metrics.build_observability_summary(repo, workspace_id="ws_metrics", run_id="run_keep")

    assert summary.workspace_id == "ws_metrics"
    assert summary.run_id == "run_keep"
    assert summary.access_count == 2
    assert summary.candidate_count == 6
    assert summary.accepted_count == 3
    assert summary.rejected_count == 3
    assert summary.failed_branch_rejected == 1
    assert summary.stale_injected == 1
    assert summary.tool_sensitive_blocked == 1
    assert summary.superseded_injected == 1
    assert summary.avg_latency_ms == 30.0
    assert summary.avg_actual_tokens == 150.0
    assert summary.compaction_trigger_rate == 1.0
    assert summary.avg_compression_ratio == 0.375
    assert summary.total_dropped_blocks == 3
    assert summary.history_summary_count == 0
    assert set(summary.by_strategy) == {"variant_2"}
    assert summary.by_strategy["variant_2"] == {
        "access_count": 2,
        "avg_candidate_count": 3.0,
        "avg_accepted_count": 1.5,
        "avg_rejected_count": 1.5,
        "failed_branch_injection_rate": 0.0,
        "stale_injection_rate": 0.5,
        "tool_sensitive_block_rate": 0.5,
        "destructive_command_block_rate": 0.0,
        "risk_block_rate": 0.5,
        "workspace_leakage_rate": 0.0,
        "superseded_injection_rate": 0.5,
        "compaction_trigger_rate": 1.0,
        "avg_compression_ratio": 0.375,
        "avg_dropped_block_count": 1.5,
        "history_summary_rate": 0.0,
        "avg_latency_ms": 30.0,
        "avg_actual_tokens": 150.0,
    }


@pytest.mark.asyncio
async def test_summary_filters_compaction_logs_to_access_workspace_and_run():
    repo = InMemoryRepository()
    access = await repo.add_access_log(
        MemoryAccessLog(
            workspace_id="ws_metrics",
            run_id="run_keep",
            retrieval_strategy=RetrievalStrategy.variant_2,
        )
    )
    await repo.add_compaction_log(
        _compaction_log(access.access_id, workspace_id="ws_metrics", run_id="run_keep", pre_tokens=40, post_tokens=10)
    )
    await repo.add_compaction_log(
        _compaction_log(access.access_id, workspace_id="ws_other", run_id="run_keep", pre_tokens=1000, post_tokens=1000)
    )
    await repo.add_compaction_log(
        _compaction_log(access.access_id, workspace_id="ws_metrics", run_id="run_other", pre_tokens=1000, post_tokens=1000)
    )

    summary = await metrics.build_observability_summary(repo, workspace_id="ws_metrics", run_id="run_keep")

    assert summary.compaction_trigger_rate == 1.0
    assert summary.avg_compression_ratio == 0.25
    assert summary.total_dropped_blocks == 2


@pytest.mark.asyncio
async def test_runtime_observability_summary_does_not_write_fake_quality_safety_profile_events():
    repo = InMemoryRepository()
    runtime = MemoryRuntime(repo, default_workspace_id="ws_metrics")
    access = await repo.add_access_log(
        MemoryAccessLog(workspace_id="ws_metrics", run_id="run_metrics", retrieval_strategy=RetrievalStrategy.variant_2)
    )
    await repo.add_profile_event(
        ProfileEvent(run_id="run_metrics", access_id=access.access_id, phase=ProfilePhase.retrieval, operation="existing")
    )

    summary = await runtime.observability_summary(workspace_id="ws_metrics", run_id="run_metrics")

    profile_events = await repo.list_profile_events(run_id="run_metrics")
    assert summary.access_count == 1
    assert len(profile_events) == 1
    assert [event.phase for event in profile_events] == [ProfilePhase.retrieval]
    assert all(event.phase not in {ProfilePhase.quality, ProfilePhase.safety} for event in profile_events)
