"""Retrieval controller: candidate selection -> gate -> pack -> logs.

Orchestrates similarity scoring, the admission gate, context packing, and the
profiler, then persists access/gate logs and returns a structured MemoryContext.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from app.retrieval import gate as gatemod
from app.retrieval.negative_evidence import build_negative_evidence
from app.retrieval.packer import pack_context
from app.retrieval.similarity import cosine_similarity, lexical_similarity, stable_embedding
from app.config import get_settings
from app.runtime.models import (
    BranchStatus,
    ContextBlock,
    MemoryAccessLog,
    MemoryContext,
    MemoryGateLog,
    MemoryItem,
    MemoryStatus,
    PendingCompactionLog,
    ProfileEvent,
    ProfilePhase,
    RetrievalRequest,
    RetrievalStrategy,
    StateNode,
    StateNodeStatus,
)
from app.runtime.repository import Repository
from app.runtime.state_tree import active_path_chain, active_path_node_ids

# Lifecycle states that are eligible to be retrieval candidates. Superseded /
# archived / dormant / deleted memories are lifecycle-invalid and must never be
# injected (e.g. a project constraint the user explicitly corrected). This is a
# write-time lifecycle decision independent of strategy, so it is applied to all
# strategies and does not affect benchmark fairness. conflicted/quarantined stay
# eligible so the gate can degrade/reject them with an auditable decision.
_RETRIEVABLE_STATUSES = frozenset(
    {
        MemoryStatus.active,
        MemoryStatus.pinned,
        MemoryStatus.conflicted,
        MemoryStatus.quarantined,
    }
)


@dataclass(slots=True)
class RetrievalCandidateTrace:
    """Candidate plus retrieval score components for trace/replay."""

    memory: MemoryItem
    lexical_score: float = 0.0
    vector_score: float = 0.0
    relevance_score: float = 0.0
    state_match_score: float = 0.0


@dataclass(slots=True)
class RetrievalPipelineTrace:
    """Side-effect-free retrieval pipeline output.

    ``access_record`` is an in-memory record. The hot path persists it via
    ``_persist_trace``; replay can consume the same trace without any writes.
    """

    access_record: MemoryAccessLog
    active_node: Optional[StateNode] = None
    active_path: list[StateNode] = field(default_factory=list)
    candidates: list[RetrievalCandidateTrace] = field(default_factory=list)
    gate_outcomes: list[gatemod.GateOutcome] = field(default_factory=list)
    accepted_memories: list[MemoryItem] = field(default_factory=list)
    context_blocks: list[ContextBlock] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    phase_profile: dict[str, dict[str, Any]] = field(default_factory=dict)
    actual_tokens: int = 0
    pending_compaction_logs: list[PendingCompactionLog] = field(default_factory=list)


class RetrievalController:
    def __init__(self, repo: Repository, *, default_token_budget: int = 512):
        self._repo = repo
        self._default_budget = default_token_budget
        settings = get_settings()
        self._use_vector = settings.retrieval_use_vector
        self._vector_weight = settings.retrieval_vector_weight
        self._embed_dim = settings.embedding_dim
        self._timeout_ms = settings.retrieval_timeout_ms
        self._compaction_notice_reserve_tokens = settings.compaction_notice_reserve_tokens

    async def retrieve(self, request: RetrievalRequest, *, workspace_id: str) -> MemoryContext:
        # Hot-path timeout (architecture.md §11 / §12.3: retrieve_context should
        # return within ~2s). On timeout we degrade to an empty context rather
        # than blocking the caller; the partial work is abandoned. A non-positive
        # budget disables the guard (mainly for tests).
        if self._timeout_ms and self._timeout_ms > 0:
            try:
                return await asyncio.wait_for(
                    self._retrieve_impl(request, workspace_id=workspace_id),
                    timeout=self._timeout_ms / 1000.0,
                )
            except asyncio.TimeoutError:
                return MemoryContext(
                    access_id=MemoryAccessLog(workspace_id=workspace_id).access_id,
                    query=request.query,
                    warnings=[f"retrieval timed out after {self._timeout_ms}ms; returned empty context"],
                )
        return await self._retrieve_impl(request, workspace_id=workspace_id)

    async def retrieve_with_prelude(
        self,
        request: RetrievalRequest,
        *,
        workspace_id: str,
        prelude_blocks: list[ContextBlock] | None = None,
        pending_compaction_logs: list[PendingCompactionLog] | None = None,
        prelude_warnings: list[str] | None = None,
    ) -> MemoryContext:
        if self._timeout_ms and self._timeout_ms > 0:
            try:
                return await asyncio.wait_for(
                    self._retrieve_impl(
                        request,
                        workspace_id=workspace_id,
                        prelude_blocks=prelude_blocks,
                        pending_compaction_logs=pending_compaction_logs,
                        prelude_warnings=prelude_warnings,
                    ),
                    timeout=self._timeout_ms / 1000.0,
                )
            except asyncio.TimeoutError:
                access = MemoryAccessLog(
                    workspace_id=workspace_id,
                    run_id=request.run_id,
                    step_id=request.step_id,
                    query=request.query,
                    task_intent=request.task_intent,
                    retrieval_strategy=request.strategy,
                    token_budget=request.token_budget or self._default_budget,
                    top_k=request.top_k,
                )
                await self._repo.add_access_log(access)
                return MemoryContext(
                    access_id=access.access_id,
                    query=request.query,
                    warnings=[*(prelude_warnings or []), f"retrieval timed out after {self._timeout_ms}ms; returned empty context"],
                )
        return await self._retrieve_impl(
            request,
            workspace_id=workspace_id,
            prelude_blocks=prelude_blocks,
            pending_compaction_logs=pending_compaction_logs,
            prelude_warnings=prelude_warnings,
        )

    async def _retrieve_impl(
        self,
        request: RetrievalRequest,
        *,
        workspace_id: str,
        prelude_blocks: list[ContextBlock] | None = None,
        pending_compaction_logs: list[PendingCompactionLog] | None = None,
        prelude_warnings: list[str] | None = None,
    ) -> MemoryContext:
        trace = await self.trace(
            request,
            workspace_id=workspace_id,
            prelude_blocks=prelude_blocks,
            pending_compaction_logs=pending_compaction_logs,
            prelude_warnings=prelude_warnings,
        )
        await self._persist_trace(trace)
        await self._bump_access_counts(trace.accepted_memories)
        return self._context_from_trace(trace)

    async def trace(
        self,
        request: RetrievalRequest,
        *,
        workspace_id: str,
        access_id: str | None = None,
        prelude_blocks: list[ContextBlock] | None = None,
        pending_compaction_logs: list[PendingCompactionLog] | None = None,
        prelude_warnings: list[str] | None = None,
    ) -> RetrievalPipelineTrace:
        """Run selection -> gate -> pack without persistence or mutations."""
        budget = request.token_budget or self._default_budget
        access_kwargs: dict[str, Any] = {"access_id": access_id} if access_id is not None else {}
        access = MemoryAccessLog(
            **access_kwargs,
            workspace_id=workspace_id,
            run_id=request.run_id,
            step_id=request.step_id,
            query=request.query,
            task_intent=request.task_intent,
            retrieval_strategy=request.strategy,
            token_budget=budget,
            top_k=request.top_k,
        )
        phase_profile: dict[str, dict[str, Any]] = {}

        # ---- baseline_0: no memory ------------------------------------- #
        if request.strategy == RetrievalStrategy.baseline_0:
            phase_profile[ProfilePhase.retrieval.value] = {
                "latency_ms": 0,
                "operation": "no_memory",
                "candidate_count": 0,
                "accepted_count": 0,
                "rejected_count": 0,
            }
            return RetrievalPipelineTrace(access_record=access, phase_profile=phase_profile)

        config = gatemod.GateConfig.for_strategy(request.strategy)

        # ---- phase: retrieval (candidate selection) -------------------- #
        t0 = time.perf_counter()
        active_node, active_ids, active_path = await self._load_active_state(request.run_id)
        candidates = await self._select_candidates(
            workspace_id=workspace_id,
            run_id=request.run_id,
            query=request.query,
            top_k=request.top_k,
        )
        retrieval_ms = int((time.perf_counter() - t0) * 1000)
        phase_profile[ProfilePhase.retrieval.value] = {
            "latency_ms": retrieval_ms,
            # Preserve the existing profiler operation label for hot-path
            # backward compatibility; component scores in the trace expose the
            # lexical/vector split for replay and observability.
            "operation": "lexical",
            "candidate_count": len(candidates),
            "accepted_count": 0,
            "rejected_count": 0,
        }

        # ---- phase: gate ----------------------------------------------- #
        t1 = time.perf_counter()
        outcomes = []
        for candidate in candidates:
            mem = candidate.memory
            relevance = candidate.relevance_score
            state_match = self._state_match(mem, active_ids)
            candidate.state_match_score = state_match
            outcome = gatemod.evaluate(
                mem,
                workspace_id=workspace_id,
                relevance=relevance,
                state_match=state_match,
                config=config,
            )
            outcomes.append(outcome)
        gate_ms = int((time.perf_counter() - t1) * 1000)
        accepted_outcomes = [o for o in outcomes if o.accepted]
        rejected_outcomes = [o for o in outcomes if not o.accepted]
        degraded_outcomes = [o for o in rejected_outcomes if o.degraded]
        hard_rejected_outcomes = [o for o in rejected_outcomes if not o.degraded]
        phase_profile[ProfilePhase.gate.value] = {
            "latency_ms": gate_ms,
            "operation": request.strategy.value,
            "candidate_count": len(outcomes),
            "accepted_count": len(accepted_outcomes),
            "rejected_count": len(rejected_outcomes),
            "metadata": {
                "degraded_count": len(degraded_outcomes),
                "hard_rejected_count": len(hard_rejected_outcomes),
            },
        }

        # rank accepted by final score desc
        accepted_outcomes.sort(key=lambda o: o.final_score, reverse=True)
        accepted_memories = [o.memory for o in accepted_outcomes]
        memories_by_id = {candidate.memory.memory_id: candidate.memory for candidate in candidates}
        negative_evidence = build_negative_evidence(outcomes, memories_by_id, max_blocks=3)
        sanitized_negative_evidence_count = sum(1 for ev in negative_evidence if ev.mode == "sanitized_risk_notice")

        # ---- phase: context packing ------------------------------------ #
        t2 = time.perf_counter()
        pack_result = pack_context(
            active_node=active_node,
            accepted=accepted_memories,
            token_budget=budget,
            active_path=active_path,
            prelude_blocks=prelude_blocks,
            negative_evidence=negative_evidence,
            compaction_notice_reserve_tokens=self._compaction_notice_reserve_tokens,
        )
        blocks = pack_result.blocks
        actual_tokens = pack_result.used
        retained_negative_evidence_count = sum(
            1 for block in blocks
            if block.type == "avoided_attempts" or block.source == "negative_evidence"
        )
        retained_sanitized_negative_evidence_count = sum(
            1 for block in blocks
            if (block.type == "avoided_attempts" or block.source == "negative_evidence")
            and block.reason in {"failed_branch_sanitized", "rolled_back_sanitized"}
        )
        dropped_negative_evidence_count = sum(
            1 for block in pack_result.dropped_blocks
            if block.type == "avoided_attempts" or block.source == "negative_evidence"
        )
        packing_ms = int((time.perf_counter() - t2) * 1000)
        phase_profile[ProfilePhase.context_packing.value] = {
            "latency_ms": packing_ms,
            "operation": "pack",
            "candidate_count": 0,
            "accepted_count": len(blocks),
            "rejected_count": len(pack_result.dropped_blocks),
            "metadata": {
                "pre_compaction_tokens": pack_result.pre_compaction_tokens,
                "actual_tokens": pack_result.used,
                "dropped_count": len(pack_result.dropped_blocks),
                "compression_ratio": round(pack_result.used / max(1, pack_result.pre_compaction_tokens), 6),
                "notice_kind": "budget_notice" if pack_result.notice is not None else None,
                "degraded_count": len(degraded_outcomes),
                "hard_rejected_count": len(hard_rejected_outcomes),
                "negative_evidence_count": retained_negative_evidence_count,
                "sanitized_negative_evidence_count": retained_sanitized_negative_evidence_count,
                "built_negative_evidence_count": len(negative_evidence),
                "dropped_negative_evidence_count": dropped_negative_evidence_count,
                "retained_constraints": [f.model_dump(mode="json") for f in pack_result.retained_constraints],
                "dropped_blocks": [b.model_dump(mode="json") for b in pack_result.dropped_blocks],
            },
        }

        # warnings: excluded failed/rolled_back + risk warns
        warnings = [*(prelude_warnings or [])]
        warnings.extend(pack_result.warnings)
        warnings.extend(
            self._build_warnings(
                rejected_outcomes,
                accepted_outcomes,
                dropped_count=len(pack_result.dropped_blocks),
                negative_evidence_count=retained_negative_evidence_count,
                sanitized_negative_evidence_count=retained_sanitized_negative_evidence_count,
            )
        )
        if pending_compaction_logs:
            history_log = next((log for log in pending_compaction_logs if log.kind.value == "history_summary"), None)
            if history_log is not None:
                phase_profile[ProfilePhase.context_compaction.value] = {
                    "latency_ms": 0,
                    "operation": "history_summary",
                    "input_tokens": history_log.pre_tokens,
                    "output_tokens": history_log.post_tokens,
                    "metadata": {
                        "provider": history_log.provider.value,
                        "timed_out": False,
                        "kind": history_log.kind.value,
                    },
                }

        # persist logs
        access.candidate_count = len(outcomes)
        access.accepted_count = len(accepted_outcomes)
        access.rejected_count = len(rejected_outcomes)
        access.actual_tokens = actual_tokens
        access.latency_ms = retrieval_ms + gate_ms + packing_ms

        return RetrievalPipelineTrace(
            access_record=access,
            active_node=active_node,
            active_path=active_path,
            candidates=candidates,
            gate_outcomes=outcomes,
            accepted_memories=accepted_memories,
            context_blocks=blocks,
            warnings=warnings,
            phase_profile=phase_profile,
            actual_tokens=actual_tokens,
            pending_compaction_logs=[*(pending_compaction_logs or []), *pack_result.pending_compaction_logs],
        )

    async def _persist_trace(self, trace: RetrievalPipelineTrace) -> None:
        access = trace.access_record
        await self._repo.add_access_log(access)

        for outcome in trace.gate_outcomes:
            await self._repo.add_gate_log(
                MemoryGateLog(
                    access_id=access.access_id,
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
            )

        for phase_name, fields in trace.phase_profile.items():
            try:
                await self._repo.add_profile_event(
                    ProfileEvent(
                        run_id=access.run_id,
                        step_id=access.step_id,
                        access_id=access.access_id,
                        phase=ProfilePhase(phase_name),
                        operation=fields.get("operation"),
                        latency_ms=int(fields.get("latency_ms", 0)),
                        input_tokens=int(fields.get("input_tokens", 0)),
                        output_tokens=int(fields.get("output_tokens", 0)),
                        candidate_count=int(fields.get("candidate_count", 0)),
                        accepted_count=int(fields.get("accepted_count", 0)),
                        rejected_count=int(fields.get("rejected_count", 0)),
                        metadata=dict(fields.get("metadata", {})),
                    )
                )
            except Exception:  # noqa: BLE001 - profiler must not break hot path
                pass

        for pending in trace.pending_compaction_logs:
            await self._repo.add_compaction_log(
                pending.materialize(
                    access_id=access.access_id,
                    run_id=access.run_id,
                    step_id=access.step_id,
                    workspace_id=access.workspace_id,
                )
            )

    async def _bump_access_counts(self, accepted_memories: list[MemoryItem]) -> None:
        for mem in accepted_memories:
            mem.access_count += 1
            await self._repo.update_memory(mem)

    def _context_from_trace(self, trace: RetrievalPipelineTrace) -> MemoryContext:
        access = trace.access_record
        return MemoryContext(
            access_id=access.access_id,
            query=access.query,
            context_blocks=trace.context_blocks,
            warnings=trace.warnings,
            profile=self._profile_summary(access),
        )

    # ------------------------------------------------------------------ #
    async def _load_active_state(
        self, run_id: str
    ) -> tuple[Optional[StateNode], set[str], list[StateNode]]:
        nodes = await self._repo.list_state_nodes(run_id)
        if not nodes:
            return None, set(), []
        active_ids = active_path_node_ids(nodes)
        chain = active_path_chain(nodes)
        # active node = deepest active, non-root node on the active path
        active_candidates = [
            n for n in nodes
            if n.node_id in active_ids and n.status == StateNodeStatus.active and n.parent_id is not None
        ]
        active_candidates.sort(key=lambda n: (n.depth, n.created_at))
        active = active_candidates[-1] if active_candidates else None
        return active, active_ids, chain

    async def _select_candidates(
        self,
        *,
        workspace_id: str,
        run_id: str,
        query: str,
        top_k: int,
    ) -> list[RetrievalCandidateTrace]:
        # Workspace-scoped retrieval is the permission filter: cross-workspace
        # memories never become candidates, so leakage is impossible by
        # construction. The gate's workspace_mismatch rule is defense-in-depth.
        memories = await self._repo.list_memories(workspace_id=workspace_id)

        # Vector signal: deterministic embedding cosine via pgvector KNN (SQL)
        # or in-memory cosine. Map memory_id -> cosine so we can blend it with
        # the lexical signal per candidate. Falls back to lexical-only if vector
        # retrieval is disabled or yields nothing (e.g. no embeddings stored).
        vector_scores: dict[str, float] = {}
        if self._use_vector:
            q_vec = stable_embedding(query, self._embed_dim)
            knn = await self._repo.search_memories_by_vector(
                embedding=q_vec, workspace_id=workspace_id, top_k=max(top_k * 2, top_k)
            )
            vector_scores = {m.memory_id: sim for m, sim in knn}

        w_vec = self._vector_weight if (self._use_vector and vector_scores) else 0.0
        w_lex = 1.0 - w_vec

        scored: list[RetrievalCandidateTrace] = []
        for m in memories:
            if m.status not in _RETRIEVABLE_STATUSES:
                continue  # skip superseded/archived/dormant/deleted lifecycle states
            lex = lexical_similarity(query, m.content)
            vec = vector_scores.get(m.memory_id, 0.0)
            rel = round(w_lex * lex + w_vec * vec, 6)
            # project constraints are always relevant to coding queries
            if m.memory_type.value == "project" and rel == 0.0:
                rel = 0.2
            if rel > 0.0:
                scored.append(
                    RetrievalCandidateTrace(
                        memory=m,
                        lexical_score=lex,
                        vector_score=vec,
                        relevance_score=rel,
                    )
                )
        scored.sort(key=lambda c: c.relevance_score, reverse=True)
        return scored[:top_k]

    @staticmethod
    def _state_match(mem: MemoryItem, active_ids: set[str]) -> float:
        if mem.source_state_node_id and mem.source_state_node_id in active_ids:
            return 1.0
        if mem.branch_status in (BranchStatus.failed, BranchStatus.rolled_back):
            return 0.0
        if mem.branch_status == BranchStatus.completed:
            return 0.6
        return 0.4

    @staticmethod
    def _build_warnings(
        rejected,
        accepted,
        *,
        dropped_count: int = 0,
        negative_evidence_count: int = 0,
        sanitized_negative_evidence_count: int = 0,
    ) -> list[str]:
        warnings: list[str] = []
        if dropped_count:
            warnings.append(f"context budget exceeded: omitted {dropped_count} blocks.")
        raw_negative_evidence_count = max(0, negative_evidence_count - sanitized_negative_evidence_count)
        if raw_negative_evidence_count:
            warnings.append(f"{raw_negative_evidence_count} failed-branch memories injected as negative evidence.")
        if sanitized_negative_evidence_count:
            warnings.append(
                f"{sanitized_negative_evidence_count} unsafe failed-branch memories were redacted into sanitized safety notices."
            )
        failed_excluded = sum(
            1 for o in rejected
            if o.reject_reason in ("failed_branch", "rolled_back")
        )
        if failed_excluded:
            warnings.append(f"{failed_excluded} failed-branch memory was excluded.")
        secret_excluded = sum(1 for o in rejected if o.reject_reason == "secret")
        if secret_excluded:
            warnings.append(f"{secret_excluded} secret memory was blocked.")
        risky_excluded = sum(
            1 for o in rejected
            if o.reject_reason in ("tool_sensitive", "destructive_command")
        )
        if risky_excluded:
            warnings.append(f"{risky_excluded} tool-sensitive memory was blocked.")
        stale_excluded = sum(1 for o in rejected if o.reject_reason == "stale")
        if stale_excluded:
            warnings.append(f"{stale_excluded} stale memory was excluded.")
        for o in accepted:
            warnings.extend(o.warnings)
        return warnings

    @staticmethod
    def _profile_summary(access: MemoryAccessLog) -> dict:
        return {
            "candidate_count": access.candidate_count,
            "accepted_count": access.accepted_count,
            "rejected_count": access.rejected_count,
            "token_budget": access.token_budget,
            "actual_tokens": access.actual_tokens,
            "latency_ms": access.latency_ms,
            "strategy": access.retrieval_strategy.value,
        }


__all__ = ["RetrievalController", "RetrievalCandidateTrace", "RetrievalPipelineTrace"]
