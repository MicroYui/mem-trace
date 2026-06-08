"""Retrieval controller: candidate selection -> gate -> pack -> logs.

Orchestrates similarity scoring, the admission gate, context packing, and the
profiler, then persists access/gate logs and returns a structured MemoryContext.
"""
from __future__ import annotations

import time
from typing import Optional

from app.retrieval import gate as gatemod
from app.retrieval.packer import pack_context
from app.retrieval.profiler import Profiler
from app.retrieval.similarity import lexical_similarity
from app.runtime.models import (
    BranchStatus,
    MemoryAccessLog,
    MemoryContext,
    MemoryGateLog,
    MemoryItem,
    MemoryStatus,
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


class RetrievalController:
    def __init__(self, repo: Repository, *, default_token_budget: int = 512):
        self._repo = repo
        self._default_budget = default_token_budget

    async def retrieve(self, request: RetrievalRequest, *, workspace_id: str) -> MemoryContext:
        budget = request.token_budget or self._default_budget
        access = MemoryAccessLog(
            workspace_id=workspace_id,
            run_id=request.run_id,
            step_id=request.step_id,
            query=request.query,
            task_intent=request.task_intent,
            retrieval_strategy=request.strategy,
            token_budget=budget,
        )
        profiler = Profiler(self._repo, run_id=request.run_id, step_id=request.step_id, access_id=access.access_id)

        # ---- baseline_0: no memory ------------------------------------- #
        if request.strategy == RetrievalStrategy.baseline_0:
            await self._repo.add_access_log(access)
            await profiler.record(ProfilePhase.retrieval, latency_ms=0, operation="no_memory")
            return MemoryContext(access_id=access.access_id, query=request.query, profile=self._profile_summary(access))

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
        await profiler.record(
            ProfilePhase.retrieval,
            latency_ms=retrieval_ms,
            operation="lexical",
            candidate_count=len(candidates),
        )

        # ---- phase: gate ----------------------------------------------- #
        t1 = time.perf_counter()
        outcomes = []
        gate_logs: list[MemoryGateLog] = []
        for mem, relevance in candidates:
            state_match = self._state_match(mem, active_ids)
            outcome = gatemod.evaluate(
                mem,
                workspace_id=workspace_id,
                relevance=relevance,
                state_match=state_match,
                config=config,
            )
            outcomes.append(outcome)
            gate_logs.append(
                MemoryGateLog(
                    access_id=access.access_id,
                    memory_id=mem.memory_id,
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
        gate_ms = int((time.perf_counter() - t1) * 1000)
        accepted_outcomes = [o for o in outcomes if o.accepted]
        rejected_outcomes = [o for o in outcomes if not o.accepted]
        await profiler.record(
            ProfilePhase.gate,
            latency_ms=gate_ms,
            operation=request.strategy.value,
            candidate_count=len(outcomes),
            accepted_count=len(accepted_outcomes),
            rejected_count=len(rejected_outcomes),
        )

        # rank accepted by final score desc
        accepted_outcomes.sort(key=lambda o: o.final_score, reverse=True)
        accepted_memories = [o.memory for o in accepted_outcomes]

        # ---- phase: context packing ------------------------------------ #
        t2 = time.perf_counter()
        blocks, actual_tokens = pack_context(
            active_node=active_node,
            accepted=accepted_memories,
            token_budget=budget,
            active_path=active_path,
        )
        packing_ms = int((time.perf_counter() - t2) * 1000)
        await profiler.record(
            ProfilePhase.context_packing,
            latency_ms=packing_ms,
            operation="pack",
            accepted_count=len(blocks),
        )

        # warnings: excluded failed/rolled_back + risk warns
        warnings = self._build_warnings(rejected_outcomes, accepted_outcomes)

        # persist logs
        access.candidate_count = len(outcomes)
        access.accepted_count = len(accepted_outcomes)
        access.rejected_count = len(rejected_outcomes)
        access.actual_tokens = actual_tokens
        access.latency_ms = retrieval_ms + gate_ms + packing_ms
        await self._repo.add_access_log(access)
        for gl in gate_logs:
            await self._repo.add_gate_log(gl)

        # bump access bookkeeping on accepted memories (best-effort)
        for mem in accepted_memories:
            mem.access_count += 1
            await self._repo.update_memory(mem)

        return MemoryContext(
            access_id=access.access_id,
            query=request.query,
            context_blocks=blocks,
            warnings=warnings,
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
    ) -> list[tuple[MemoryItem, float]]:
        # Workspace-scoped retrieval is the permission filter: cross-workspace
        # memories never become candidates, so leakage is impossible by
        # construction. The gate's workspace_mismatch rule is defense-in-depth.
        memories = await self._repo.list_memories(workspace_id=workspace_id)
        scored: list[tuple[MemoryItem, float]] = []
        for m in memories:
            if m.status not in _RETRIEVABLE_STATUSES:
                continue  # skip superseded/archived/dormant/deleted lifecycle states
            rel = lexical_similarity(query, m.content)
            # project constraints are always relevant to coding queries
            if m.memory_type.value == "project" and rel == 0.0:
                rel = 0.2
            if rel > 0.0:
                scored.append((m, rel))
        scored.sort(key=lambda x: x[1], reverse=True)
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
    def _build_warnings(rejected, accepted) -> list[str]:
        warnings: list[str] = []
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


__all__ = ["RetrievalController"]
