"""Deterministic observability metric helpers for Phase 3-A."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from app.retrieval.gate import GateOutcome
from app.retrieval.negative_evidence import build_negative_evidence
from app.runtime.models import (
    BranchStatus,
    CompactionKind,
    ContextCompactionLog,
    GateDecisionType,
    MemoryAccessLog,
    MemoryGateLog,
    MemoryItem,
    MemoryStatus,
    NegativeEvidence,
    ObservabilitySummary,
)
from app.runtime.repository import Repository


_ACCEPTED_DECISIONS = {GateDecisionType.accept, GateDecisionType.warn}
_FAILED_BRANCH_REASONS = {
    "failed_branch",
    "rolled_back",
    "failed_branch_degraded",
    "rolled_back_degraded",
    "failed_branch_sanitized",
    "rolled_back_sanitized",
}


async def build_observability_summary(
    repo: Repository,
    *,
    workspace_id: str | None = None,
    run_id: str | None = None,
) -> ObservabilitySummary:
    """Aggregate deterministic quality/safety counters from persisted access/gate logs."""
    accesses = await repo.list_access_logs(workspace_id=workspace_id)
    if run_id is not None:
        accesses = [access for access in accesses if access.run_id == run_id]

    totals = _empty_totals()
    by_strategy_totals: dict[str, dict[str, float]] = defaultdict(_empty_totals)

    for access in accesses:
        gate_logs = await repo.list_gate_logs(access.access_id)
        compaction_logs = [
            log
            for log in await repo.list_compaction_logs(access_id=access.access_id, workspace_id=access.workspace_id)
            if log.run_id == access.run_id
        ]
        candidate_memories = await _candidate_memories(repo, gate_logs)
        accepted_memories = await _accepted_memories(repo, gate_logs)
        metrics = build_access_observability_metrics(
            access, gate_logs, candidate_memories, accepted_memories, compaction_logs
        )
        _add_totals(totals, metrics)
        _add_totals(by_strategy_totals[access.retrieval_strategy.value], metrics)

    return ObservabilitySummary(
        workspace_id=workspace_id,
        run_id=run_id,
        access_count=int(totals["access_count"]),
        candidate_count=int(totals["candidate_count"]),
        accepted_count=int(totals["accepted_count"]),
        rejected_count=int(totals["rejected_count"]),
        failed_branch_rejected=int(totals["failed_branch_rejected"]),
        failed_branch_injected=int(totals["failed_branch_injected"]),
        degraded_negative_evidence_count=int(totals["degraded_negative_evidence_count"]),
        sanitized_failure_notice_count=int(totals["sanitized_failure_notice_count"]),
        negative_evidence_block_count=int(totals["negative_evidence_block_count"]),
        retained_negative_evidence_count=int(totals["retained_negative_evidence_count"]),
        sanitized_retained_negative_evidence_count=int(totals["sanitized_retained_negative_evidence_count"]),
        stale_rejected=int(totals["stale_rejected"]),
        stale_injected=int(totals["stale_injected"]),
        tool_sensitive_blocked=int(totals["tool_sensitive_blocked"]),
        destructive_command_blocked=int(totals["destructive_command_blocked"]),
        risk_blocked=int(totals["risk_blocked"]),
        workspace_mismatch_rejected=int(totals["workspace_mismatch_rejected"]),
        workspace_leakage=int(totals["workspace_leakage"]),
        superseded_injected=int(totals["superseded_injected"]),
        avg_latency_ms=_avg(totals, "latency_ms"),
        avg_actual_tokens=_avg(totals, "actual_tokens"),
        compaction_trigger_rate=_rate(totals, "compaction_triggered"),
        avg_compression_ratio=_avg_present(totals, "compression_ratio_sum", "compression_ratio_present"),
        total_dropped_blocks=int(totals["dropped_block_count"]),
        history_summary_count=int(totals["history_summary_count"]),
        by_strategy={strategy: _strategy_summary(values) for strategy, values in sorted(by_strategy_totals.items())},
    )


async def _candidate_memories(repo: Repository, gate_logs: list[MemoryGateLog]) -> list[MemoryItem]:
    memories: list[MemoryItem] = []
    for gate_log in gate_logs:
        memory = await repo.get_memory(gate_log.memory_id)
        if memory is not None:
            memories.append(memory)
    return memories


async def _accepted_memories(repo: Repository, gate_logs: list[MemoryGateLog]) -> list[MemoryItem]:
    memories: list[MemoryItem] = []
    for gate_log in gate_logs:
        if gate_log.decision not in _ACCEPTED_DECISIONS:
            continue
        memory = await repo.get_memory(gate_log.memory_id)
        if memory is not None:
            memories.append(memory)
    return memories


def build_access_observability_metrics(
    access: MemoryAccessLog,
    gate_logs: list[MemoryGateLog],
    candidate_memories: list[MemoryItem],
    accepted_memories: list[MemoryItem],
    compaction_logs: list[ContextCompactionLog] | None = None,
) -> dict[str, float]:
    """Compute deterministic quality/safety metrics for one retrieval access.

    The helper is intentionally pure: callers supply the persisted access log,
    its gate decisions, the candidate memories represented by those gates, and
    the subset of accepted memories. It never reads or writes repository state.
    """
    now = datetime.now(timezone.utc)
    compaction_logs = compaction_logs or []
    negative_evidence = _rebuilt_negative_evidence(gate_logs, candidate_memories)
    retained_negative_evidence_count = sum(len(log.retained_negative_evidence) for log in compaction_logs)
    actual_negative_evidence_block_count = max(0, len(negative_evidence) - retained_negative_evidence_count)
    return {
        "access_count": 1.0,
        "candidate_count": float(access.candidate_count),
        "accepted_count": float(access.accepted_count),
        "rejected_count": float(access.rejected_count),
        "latency_ms": float(access.latency_ms),
        "actual_tokens": float(access.actual_tokens),
        "failed_branch_rejected": float(
            sum(g.reject_reason in _FAILED_BRANCH_REASONS for g in gate_logs)
        ),
        "failed_branch_injected": float(
            sum(m.branch_status in {BranchStatus.failed, BranchStatus.rolled_back} for m in accepted_memories)
        ),
        "degraded_negative_evidence_count": float(sum(g.decision == GateDecisionType.degrade for g in gate_logs)),
        "sanitized_failure_notice_count": float(
            sum(g.reject_reason in {"failed_branch_sanitized", "rolled_back_sanitized"} for g in gate_logs)
        ),
        "negative_evidence_block_count": float(actual_negative_evidence_block_count),
        "retained_negative_evidence_count": float(retained_negative_evidence_count),
        "sanitized_retained_negative_evidence_count": float(
            sum(
                1
                for log in compaction_logs
                for item in log.retained_negative_evidence
                if item.mode == "sanitized_risk_notice"
            )
        ),
        "stale_rejected": float(sum(g.reject_reason == "stale" for g in gate_logs)),
        "stale_injected": float(sum(m.expires_at is not None and m.expires_at < now for m in accepted_memories)),
        "tool_sensitive_blocked": float(sum(g.reject_reason == "tool_sensitive" for g in gate_logs)),
        "destructive_command_blocked": float(sum(g.reject_reason == "destructive_command" for g in gate_logs)),
        "risk_blocked": float(sum(g.reject_reason in {"tool_sensitive", "destructive_command"} for g in gate_logs)),
        "workspace_mismatch_rejected": float(sum(g.reject_reason == "workspace_mismatch" for g in gate_logs)),
        "workspace_leakage": float(sum(m.workspace_id != access.workspace_id for m in accepted_memories)),
        "superseded_injected": float(sum(m.status == MemoryStatus.superseded for m in accepted_memories)),
        "compaction_triggered": float(bool(compaction_logs)),
        "dropped_block_count": float(sum(log.dropped_block_count for log in compaction_logs)),
        "pre_compaction_tokens": float(sum(log.pre_tokens for log in compaction_logs)),
        "post_compaction_tokens": float(sum(log.post_tokens for log in compaction_logs)),
        "compression_ratio_sum": float(sum(log.compression_ratio for log in compaction_logs)),
        "compression_ratio_present": float(len(compaction_logs)),
        "history_summary_count": float(sum(log.kind == CompactionKind.history_summary for log in compaction_logs)),
    }


def _rebuilt_negative_evidence(gate_logs: list[MemoryGateLog], memories: list[MemoryItem]) -> list[NegativeEvidence]:
    memories_by_id = {memory.memory_id: memory for memory in memories}
    outcomes = [
        GateOutcome(
            memory=memory,
            layer=gate_log.layer,
            decision=gate_log.decision,
            reject_reason=gate_log.reject_reason,
            relevance_score=gate_log.relevance_score,
            state_match_score=gate_log.state_match_score,
            freshness_score=gate_log.freshness_score,
            trust_score=gate_log.trust_score,
            risk_score=gate_log.risk_score,
            final_score=gate_log.final_score,
        )
        for gate_log in gate_logs
        if (memory := memories_by_id.get(gate_log.memory_id)) is not None
    ]
    return build_negative_evidence(outcomes, memories_by_id, max_blocks=3)


def _empty_totals() -> dict[str, float]:
    return {
        "access_count": 0.0,
        "candidate_count": 0.0,
        "accepted_count": 0.0,
        "rejected_count": 0.0,
        "latency_ms": 0.0,
        "actual_tokens": 0.0,
        "failed_branch_rejected": 0.0,
        "failed_branch_injected": 0.0,
        "degraded_negative_evidence_count": 0.0,
        "sanitized_failure_notice_count": 0.0,
        "negative_evidence_block_count": 0.0,
        "retained_negative_evidence_count": 0.0,
        "sanitized_retained_negative_evidence_count": 0.0,
        "stale_rejected": 0.0,
        "stale_injected": 0.0,
        "tool_sensitive_blocked": 0.0,
        "destructive_command_blocked": 0.0,
        "risk_blocked": 0.0,
        "workspace_mismatch_rejected": 0.0,
        "workspace_leakage": 0.0,
        "superseded_injected": 0.0,
        "compaction_triggered": 0.0,
        "dropped_block_count": 0.0,
        "pre_compaction_tokens": 0.0,
        "post_compaction_tokens": 0.0,
        "compression_ratio_sum": 0.0,
        "compression_ratio_present": 0.0,
        "history_summary_count": 0.0,
    }


def _add_totals(target: dict[str, float], metrics: dict[str, float]) -> None:
    for key, value in metrics.items():
        target[key] = target.get(key, 0.0) + value


def _avg(totals: dict[str, float], key: str) -> float:
    access_count = totals.get("access_count", 0.0)
    if access_count == 0:
        return 0.0
    return round(totals.get(key, 0.0) / access_count, 6)


def _rate(totals: dict[str, float], numerator: str) -> float:
    access_count = totals.get("access_count", 0.0)
    if access_count == 0:
        return 0.0
    return round(totals.get(numerator, 0.0) / access_count, 6)


def _avg_present(totals: dict[str, float], numerator: str, present: str) -> float:
    count = totals.get(present, 0.0)
    if count == 0:
        return 0.0
    return round(totals.get(numerator, 0.0) / count, 6)


def _strategy_summary(totals: dict[str, float]) -> dict[str, float]:
    access_count = totals.get("access_count", 0.0)
    return {
        "access_count": int(access_count),
        "avg_candidate_count": _avg(totals, "candidate_count"),
        "avg_accepted_count": _avg(totals, "accepted_count"),
        "avg_rejected_count": _avg(totals, "rejected_count"),
        "failed_branch_injection_rate": _rate(totals, "failed_branch_injected"),
        "negative_evidence_block_rate": _rate(totals, "negative_evidence_block_count"),
        "retained_negative_evidence_rate": _rate(totals, "retained_negative_evidence_count"),
        "sanitized_retained_negative_evidence_rate": _rate(totals, "sanitized_retained_negative_evidence_count"),
        "degraded_negative_evidence_rate": _rate(totals, "degraded_negative_evidence_count"),
        "sanitized_failure_notice_rate": _rate(totals, "sanitized_failure_notice_count"),
        "stale_injection_rate": _rate(totals, "stale_injected"),
        "tool_sensitive_block_rate": _rate(totals, "tool_sensitive_blocked"),
        "destructive_command_block_rate": _rate(totals, "destructive_command_blocked"),
        "risk_block_rate": _rate(totals, "risk_blocked"),
        "workspace_leakage_rate": _rate(totals, "workspace_leakage"),
        "superseded_injection_rate": _rate(totals, "superseded_injected"),
        "compaction_trigger_rate": _rate(totals, "compaction_triggered"),
        "avg_compression_ratio": _avg_present(totals, "compression_ratio_sum", "compression_ratio_present"),
        "avg_dropped_block_count": _avg(totals, "dropped_block_count"),
        "history_summary_rate": _rate(totals, "history_summary_count"),
        "avg_latency_ms": _avg(totals, "latency_ms"),
        "avg_actual_tokens": _avg(totals, "actual_tokens"),
    }


__all__ = ["build_access_observability_metrics", "build_observability_summary"]
