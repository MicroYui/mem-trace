"""Side-effect-free retrieval replay and deterministic diffing."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from app.retrieval import gate as gatemod
from app.retrieval.controller import RetrievalCandidateTrace, RetrievalController, RetrievalPipelineTrace
from app.retrieval.packer import pack_context
from app.runtime.models import (
    BranchStatus,
    ContextBlock,
    GateDecisionType,
    MemoryAccessLog,
    MemoryGateLog,
    MemoryItem,
    MemoryStatus,
    ReplayCandidateView,
    ReplayDiffItem,
    ReplayGateDecisionView,
    ReplayRetrievalResult,
    RetrievalRequest,
    RiskFlags,
    RunReplayResult,
    StateNode,
    StateNodeStatus,
)
from app.runtime.repository import Repository
from app.runtime.state_tree import active_path_chain


_EPSILON = 0.000001
_SEVERITY_RANK = {"critical": 0, "warning": 1, "info": 2}
_ACCEPTED_DECISIONS = {GateDecisionType.accept, GateDecisionType.degrade, GateDecisionType.warn}
_CRITICAL_REASONS = {
    "failed_branch",
    "rolled_back",
    "stale",
    "tool_sensitive",
    "destructive_command",
    "secret",
    "workspace_mismatch",
    "invalid_status",
}


@dataclass(slots=True)
class _OriginalReplayView:
    candidates: list[ReplayCandidateView]
    gate_decisions: list[ReplayGateDecisionView]
    context_blocks: list[ContextBlock]
    missing_memory_ids: list[str]
    accepted_memories: list[MemoryItem]


class RetrievalReplayService:
    """Replay persisted retrieval accesses without writing logs or mutating memory."""

    def __init__(self, repo: Repository, retrieval: RetrievalController):
        self._repo = repo
        self._retrieval = retrieval

    async def replay_access(self, access_id: str) -> ReplayRetrievalResult | None:
        access = await self._repo.get_access_log(access_id)
        if access is None:
            return None

        gate_logs = await self._repo.list_gate_logs(access.access_id)
        original = await self._build_original_view(access, gate_logs)
        warnings: list[str] = []
        diffs = self._integrity_diffs(original.missing_memory_ids)

        if access.run_id is None:
            warnings.append("access has no run_id; active-state replay unavailable")
            replay_trace = RetrievalPipelineTrace(
                access_record=access.model_copy(deep=True),
                warnings=warnings.copy(),
            )
            diffs.append(
                ReplayDiffItem(kind="run_missing", field="run_id", original=None, replayed=None, severity="warning")
            )
        else:
            run = await self._repo.get_run(access.run_id)
            if run is None:
                warnings.append(f"run {access.run_id} is missing; replay used stored workspace only")
                diffs.append(
                    ReplayDiffItem(
                        kind="run_missing",
                        field="run_id",
                        original=access.run_id,
                        replayed=None,
                        severity="warning",
                    )
                )
            if access.step_id is not None and await self._repo.get_step(access.step_id) is None:
                warnings.append(f"step {access.step_id} is missing")
                diffs.append(
                    ReplayDiffItem(
                        kind="step_missing",
                        field="step_id",
                        original=access.step_id,
                        replayed=None,
                        severity="warning",
                    )
                )
            replay_trace = await self._retrieval.trace(
                self._request_from_access(access),
                workspace_id=access.workspace_id,
                access_id=access.access_id,
            )

        replay_candidates = [_candidate_from_trace(c) for c in replay_trace.candidates]
        replay_gate_decisions = [_gate_from_outcome(o) for o in replay_trace.gate_outcomes]
        diffs.extend(
            _diff_candidates(original.candidates, replay_candidates)
            + _diff_scores_and_gate(original.gate_decisions, replay_gate_decisions)
            + _diff_context_blocks(original.context_blocks, replay_trace.context_blocks)
            + _diff_token_usage(access.actual_tokens, replay_trace.actual_tokens)
        )
        diffs = _sort_diffs(diffs)

        metrics = _access_metrics(access, gate_logs, original.accepted_memories, diffs)
        warnings.extend(replay_trace.warnings)
        return ReplayRetrievalResult(
            access_id=access.access_id,
            run_id=access.run_id,
            step_id=access.step_id,
            workspace_id=access.workspace_id,
            query=access.query,
            strategy=access.retrieval_strategy,
            token_budget=access.token_budget,
            top_k=access.top_k or 10,
            original_candidates=original.candidates,
            original_gate_decisions=original.gate_decisions,
            original_context_blocks_reconstructed=original.context_blocks,
            replayed_candidates=replay_candidates,
            replayed_gate_decisions=replay_gate_decisions,
            replayed_context_blocks=replay_trace.context_blocks,
            diffs=diffs,
            metrics=metrics,
            warnings=_dedupe_preserve_order(warnings),
        )

    async def replay_run(self, run_id: str) -> RunReplayResult:
        accesses = [a for a in await self._repo.list_access_logs() if a.run_id == run_id]
        replayed: list[ReplayRetrievalResult] = []
        for access in accesses:
            result = await self.replay_access(access.access_id)
            if result is not None:
                replayed.append(result)
        drift_count = sum(len(r.diffs) for r in replayed)
        critical_drift_count = sum(1 for r in replayed for d in r.diffs if d.severity == "critical")
        return RunReplayResult(
            run_id=run_id,
            access_count=len(replayed),
            replayed=replayed,
            summary={
                "drift_count": drift_count,
                "critical_drift_count": critical_drift_count,
                "warning_drift_count": sum(1 for r in replayed for d in r.diffs if d.severity == "warning"),
            },
        )

    async def _build_original_view(
        self, access: MemoryAccessLog, gate_logs: list[MemoryGateLog]
    ) -> _OriginalReplayView:
        candidates: list[ReplayCandidateView] = []
        decisions: list[ReplayGateDecisionView] = []
        accepted: list[tuple[MemoryGateLog, MemoryItem]] = []
        missing: list[str] = []

        for gate_log in gate_logs:
            mem = await self._repo.get_memory(gate_log.memory_id)
            if mem is None:
                missing.append(gate_log.memory_id)
            candidates.append(_candidate_from_gate_log(gate_log, mem))
            decisions.append(_gate_from_log(gate_log))
            if mem is not None and gate_log.decision in _ACCEPTED_DECISIONS:
                accepted.append((gate_log, mem))

        accepted.sort(key=lambda pair: pair[0].final_score, reverse=True)
        accepted_memories = [mem for _, mem in accepted]
        active_node, active_path = await self._load_original_access_state(access)
        blocks, _ = pack_context(
            active_node=active_node,
            accepted=accepted_memories,
            token_budget=access.token_budget or 512,
            active_path=active_path,
        )
        return _OriginalReplayView(
            candidates=candidates,
            gate_decisions=decisions,
            context_blocks=blocks,
            missing_memory_ids=missing,
            accepted_memories=accepted_memories,
        )

    async def _load_original_access_state(self, access: MemoryAccessLog) -> tuple[StateNode | None, list[StateNode]]:
        """Best-effort reconstruction of the state view used by the original access.

        The hot path persisted ``step_id`` but not an immutable state snapshot.
        For the original reconstructed context, anchor the active-state block to
        the access step's state node instead of the run's current active node;
        otherwise advancing the run would make original and replayed context both
        point at the latest step and hide state drift.
        """
        if not access.run_id:
            return None, []
        nodes = await self._repo.list_state_nodes(access.run_id)
        if not nodes:
            return None, []
        active_node: StateNode | None = None
        if access.step_id:
            active_node = next((node for node in nodes if node.step_id == access.step_id), None)
        if active_node is None:
            return None, active_path_chain(nodes)
        # The access step was active when retrieval happened. If the run has
        # since advanced, its node may now be completed; use an in-memory copy
        # with active status so the reconstructed active_path does not invent a
        # post-access progress block for the same step.
        historical_active = active_node.model_copy(update={"status": StateNodeStatus.active})
        historical_nodes = [
            historical_active if node.node_id == active_node.node_id else node
            for node in nodes
            if node.created_at <= active_node.created_at
        ]
        return historical_active, active_path_chain(historical_nodes or nodes)

    @staticmethod
    def _request_from_access(access: MemoryAccessLog) -> RetrievalRequest:
        return RetrievalRequest(
            run_id=access.run_id or "",
            step_id=access.step_id,
            query=access.query or "",
            task_intent=access.task_intent,
            workspace_id=access.workspace_id,
            strategy=access.retrieval_strategy,
            token_budget=access.token_budget or None,
            top_k=access.top_k or 10,
        )

    @staticmethod
    def _integrity_diffs(missing_memory_ids: list[str]) -> list[ReplayDiffItem]:
        return [
            ReplayDiffItem(
                kind="memory_missing",
                memory_id=memory_id,
                original=memory_id,
                replayed=None,
                severity="warning",
            )
            for memory_id in missing_memory_ids
        ]


def _candidate_from_gate_log(gate_log: MemoryGateLog, mem: MemoryItem | None) -> ReplayCandidateView:
    return ReplayCandidateView(
        memory_id=gate_log.memory_id,
        content=mem.content if mem else "",
        memory_type=mem.memory_type if mem else None,
        key=mem.key if mem else None,
        value=mem.value if mem else None,
        status=mem.status if mem else None,
        branch_status=mem.branch_status if mem else None,
        sensitivity=mem.sensitivity if mem else None,
        risk_flags=mem.risk_flags if mem else RiskFlags(),
        relevance_score=gate_log.relevance_score,
        state_match_score=gate_log.state_match_score,
    )


def _candidate_from_trace(candidate: RetrievalCandidateTrace) -> ReplayCandidateView:
    mem = candidate.memory
    return ReplayCandidateView(
        memory_id=mem.memory_id,
        content=mem.content,
        memory_type=mem.memory_type,
        key=mem.key,
        value=mem.value,
        status=mem.status,
        branch_status=mem.branch_status,
        sensitivity=mem.sensitivity,
        risk_flags=mem.risk_flags,
        lexical_score=candidate.lexical_score,
        vector_score=candidate.vector_score,
        relevance_score=candidate.relevance_score,
        state_match_score=candidate.state_match_score,
    )


def _gate_from_log(gate_log: MemoryGateLog) -> ReplayGateDecisionView:
    return ReplayGateDecisionView(
        memory_id=gate_log.memory_id,
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


def _gate_from_outcome(outcome: gatemod.GateOutcome) -> ReplayGateDecisionView:
    return ReplayGateDecisionView(
        memory_id=outcome.memory.memory_id,
        layer=outcome.layer,
        decision=outcome.decision,
        reject_reason=outcome.reject_reason,
        relevance_score=outcome.relevance_score,
        state_match_score=outcome.state_match_score,
        freshness_score=outcome.freshness_score,
        trust_score=outcome.trust_score,
        risk_score=outcome.risk_score,
        final_score=outcome.final_score,
    )


def _diff_candidates(
    original: list[ReplayCandidateView], replayed: list[ReplayCandidateView]
) -> list[ReplayDiffItem]:
    diffs: list[ReplayDiffItem] = []
    original_ids = [c.memory_id for c in original]
    replayed_ids = [c.memory_id for c in replayed]
    original_set = set(original_ids)
    replayed_set = set(replayed_ids)
    for memory_id in replayed_set - original_set:
        diffs.append(ReplayDiffItem(kind="candidate_added", memory_id=memory_id, severity="warning"))
    for memory_id in original_set - replayed_set:
        diffs.append(ReplayDiffItem(kind="candidate_removed", memory_id=memory_id, severity="warning"))
    for memory_id in original_set & replayed_set:
        if original_ids.index(memory_id) != replayed_ids.index(memory_id):
            diffs.append(
                ReplayDiffItem(
                    kind="candidate_order_changed",
                    memory_id=memory_id,
                    original=original_ids.index(memory_id),
                    replayed=replayed_ids.index(memory_id),
                    severity="warning",
                )
            )
    return diffs


def _diff_scores_and_gate(
    original: list[ReplayGateDecisionView], replayed: list[ReplayGateDecisionView]
) -> list[ReplayDiffItem]:
    diffs: list[ReplayDiffItem] = []
    replayed_by_id = {g.memory_id: g for g in replayed}
    for orig in original:
        rep = replayed_by_id.get(orig.memory_id)
        if rep is None:
            continue
        if abs(orig.relevance_score - rep.relevance_score) > _EPSILON:
            diffs.append(
                ReplayDiffItem(
                    kind="score_changed",
                    memory_id=orig.memory_id,
                    field="relevance_score",
                    original=orig.relevance_score,
                    replayed=rep.relevance_score,
                    severity="warning",
                )
            )
        if abs(orig.final_score - rep.final_score) > _EPSILON:
            diffs.append(
                ReplayDiffItem(
                    kind="score_changed",
                    memory_id=orig.memory_id,
                    field="final_score",
                    original=orig.final_score,
                    replayed=rep.final_score,
                    severity="warning",
                )
            )
        if abs(orig.state_match_score - rep.state_match_score) > _EPSILON:
            diffs.append(
                ReplayDiffItem(
                    kind="state_match_changed",
                    memory_id=orig.memory_id,
                    field="state_match_score",
                    original=orig.state_match_score,
                    replayed=rep.state_match_score,
                    severity="warning",
                )
            )
        if orig.decision != rep.decision:
            diffs.append(
                ReplayDiffItem(
                    kind="decision_changed",
                    memory_id=orig.memory_id,
                    field="decision",
                    original=orig.decision.value,
                    replayed=rep.decision.value,
                    severity=_decision_severity(orig, rep),
                )
            )
        if orig.reject_reason != rep.reject_reason:
            diffs.append(
                ReplayDiffItem(
                    kind="reject_reason_changed",
                    memory_id=orig.memory_id,
                    field="reject_reason",
                    original=orig.reject_reason,
                    replayed=rep.reject_reason,
                    severity=_decision_severity(orig, rep),
                )
            )
    return diffs


def _decision_severity(original: ReplayGateDecisionView, replayed: ReplayGateDecisionView) -> str:
    original_rejected = original.decision == GateDecisionType.reject
    replayed_accepted = replayed.decision in _ACCEPTED_DECISIONS
    if original_rejected and replayed_accepted and original.reject_reason in _CRITICAL_REASONS:
        return "critical"
    if original.decision in _ACCEPTED_DECISIONS and replayed.decision == GateDecisionType.reject:
        return "warning"
    return "warning"


def _diff_context_blocks(original: list[ContextBlock], replayed: list[ContextBlock]) -> list[ReplayDiffItem]:
    diffs: list[ReplayDiffItem] = []
    original_sigs = [_block_signature(b) for b in original]
    replayed_sigs = [_block_signature(b) for b in replayed]
    original_set = set(original_sigs)
    replayed_set = set(replayed_sigs)
    for sig in replayed_set - original_set:
        diffs.append(ReplayDiffItem(kind="context_block_added", original=None, replayed=sig, severity="warning"))
    for sig in original_set - replayed_set:
        diffs.append(ReplayDiffItem(kind="context_block_removed", original=sig, replayed=None, severity="warning"))
    for sig in original_set & replayed_set:
        if original_sigs.index(sig) != replayed_sigs.index(sig):
            diffs.append(
                ReplayDiffItem(
                    kind="context_block_order_changed",
                    original=original_sigs.index(sig),
                    replayed=replayed_sigs.index(sig),
                    severity="warning",
                )
            )
    return diffs


def _block_signature(block: ContextBlock) -> str:
    return "|".join([block.type, block.memory_id or "", block.source or "", block.content])


def _diff_token_usage(original_tokens: int, replayed_tokens: int) -> list[ReplayDiffItem]:
    if original_tokens == replayed_tokens:
        return []
    return [
        ReplayDiffItem(
            kind="token_usage_changed",
            field="actual_tokens",
            original=original_tokens,
            replayed=replayed_tokens,
            severity="warning",
        )
    ]


def _sort_diffs(diffs: Iterable[ReplayDiffItem]) -> list[ReplayDiffItem]:
    return sorted(
        diffs,
        key=lambda d: (_SEVERITY_RANK.get(d.severity, 99), d.kind, d.memory_id or "", d.field or ""),
    )


def _access_metrics(
    access: MemoryAccessLog,
    gate_logs: list[MemoryGateLog],
    accepted_memories: list[MemoryItem],
    diffs: list[ReplayDiffItem],
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    return {
        "candidate_count": access.candidate_count,
        "accepted_count": access.accepted_count,
        "rejected_count": access.rejected_count,
        "actual_tokens": access.actual_tokens,
        "latency_ms": access.latency_ms,
        "failed_branch_rejected": sum(g.reject_reason in {"failed_branch", "rolled_back"} for g in gate_logs),
        "failed_branch_injected": sum(
            m.branch_status in {BranchStatus.failed, BranchStatus.rolled_back} for m in accepted_memories
        ),
        "stale_rejected": sum(g.reject_reason == "stale" for g in gate_logs),
        "stale_injected": sum(m.expires_at is not None and m.expires_at < now for m in accepted_memories),
        "tool_sensitive_blocked": sum(g.reject_reason == "tool_sensitive" for g in gate_logs),
        "destructive_command_blocked": sum(g.reject_reason == "destructive_command" for g in gate_logs),
        "risk_blocked": sum(g.reject_reason in {"tool_sensitive", "destructive_command"} for g in gate_logs),
        "workspace_mismatch_rejected": sum(g.reject_reason == "workspace_mismatch" for g in gate_logs),
        "workspace_leakage": sum(m.workspace_id != access.workspace_id for m in accepted_memories),
        "superseded_injected": sum(m.status == MemoryStatus.superseded for m in accepted_memories),
        "drift_count": len(diffs),
        "critical_drift_count": sum(d.severity == "critical" for d in diffs),
    }


def _dedupe_preserve_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out


__all__ = ["RetrievalReplayService"]
