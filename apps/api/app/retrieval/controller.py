"""Retrieval controller: candidate selection -> gate -> pack -> logs.

Orchestrates similarity scoring, the admission gate, context packing, and the
profiler, then persists access/gate logs and returns a structured MemoryContext.
"""
from __future__ import annotations

import asyncio
import copy
import math
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from app.providers.base import ProviderKind
from app.retrieval import gate as gatemod
from app.retrieval.hybrid import HybridBackend, build_hybrid_backend
from app.retrieval.graph import GraphBackend, build_graph_backend, provenance_edges
from app.retrieval.ranking_profiles import select_profile
from app.retrieval.negative_evidence import build_negative_evidence
from app.retrieval.packer import estimate_tokens, pack_context
from app.retrieval.policy import POLICY_VERSION, build_policy_snapshot, policy_hash
from app.retrieval.query_planner import (
    decide_need_retrieval,
    derive_hop_cues,
    hint_boost,
    plan_query,
    rewrite_query,
)
from app.retrieval.similarity import lexical_similarity, stable_embedding
from app.config import get_settings
from app.providers.registry import ProviderRegistry
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
from app.runtime.repository import EMBED_DIM, Repository
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


def retention_score(mem: MemoryItem) -> float:
    """Deterministic reflection-lite retention priority.

    Rewards trustworthy, fresh, and frequently-used memories. ``access_count``
    is a usage-frequency signal the variant_2 soft-ranking does not use; it is
    capped at 10 accesses to keep the score in [0, 1]. This is a placeholder for
    the real ROADMAP §3.2 Reflection/Forgetting scheduler.
    """
    usage = _clamp01(mem.access_count / 10.0)
    trust = _clamp01(mem.trust_score)
    freshness = _clamp01(mem.freshness_score)
    return round(0.4 * trust + 0.3 * freshness + 0.3 * usage, 6)


def _clamp01(value: float) -> float:
    value = float(value)
    if not math.isfinite(value):
        return 0.0
    return max(0.0, min(1.0, value))


@dataclass(slots=True)
class RetrievalCandidateTrace:
    """Candidate plus retrieval score components for trace/replay."""

    memory: MemoryItem
    lexical_score: float = 0.0
    vector_score: float = 0.0
    bm25_score: float = 0.0
    graph_score: float = 0.0
    relevance_score: float = 0.0
    state_match_score: float = 0.0
    # 0 == retrieved directly for the query; >0 == surfaced by a multi-hop cue
    # expansion (ROADMAP §4). Default-off retrieval leaves this 0 everywhere.
    hop: int = 0


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
    def __init__(
        self,
        repo: Repository,
        *,
        default_token_budget: int = 512,
        provider_registry: ProviderRegistry | None = None,
        provider_snapshot: dict[str, Any] | None = None,
    ):
        self._repo = repo
        self._default_budget = default_token_budget
        self._provider_registry = provider_registry
        self._embedding_provider = (
            provider_registry.get(ProviderKind.embedding) if provider_registry is not None else None
        )
        if provider_snapshot is not None:
            self._provider_snapshot = copy.deepcopy(provider_snapshot)
        else:
            self._provider_snapshot = provider_registry.snapshot() if provider_registry is not None else None
        settings = get_settings()
        self._use_vector = settings.retrieval_use_vector
        self._vector_weight = settings.retrieval_vector_weight
        self._fusion = (settings.retrieval_fusion or "linear").lower()
        self._rrf_k = max(1, settings.retrieval_rrf_k)
        self._embed_dim = EMBED_DIM
        self._timeout_ms = settings.retrieval_timeout_ms
        self._compaction_notice_reserve_tokens = settings.compaction_notice_reserve_tokens
        # ROADMAP §5: default-off active-path summary compression. 0 == disabled,
        # so build_active_path_block lists every completed step (unchanged).
        if settings.summary_node_compression_enabled:
            self._active_path_summarize_after = max(0, settings.active_path_summary_threshold)
            self._active_path_keep_recent = max(0, settings.active_path_summary_keep_recent)
        else:
            self._active_path_summarize_after = 0
            self._active_path_keep_recent = settings.active_path_summary_keep_recent
        # ROADMAP §9.1: stale -> outdated-warning degrade, default-off and only on
        # failure-learning strategies (see _gate_config).
        self._stale_warning = settings.stale_warning_enabled
        # ROADMAP §1.1: protect sanitized safety negative evidence from budget drops.
        self._protect_safety_notices = settings.protect_safety_negative_evidence
        # ROADMAP §4: default-off deterministic query planner (entity/keyword
        # hints). "off" leaves candidate scoring byte-identical; "hints" boosts
        # candidates that mention entity-like query terms.
        self._query_planner = (settings.retrieval_query_planner or "off").lower()
        self._query_planner_weight = settings.retrieval_query_planner_weight
        # ROADMAP §4: default-off deterministic multi-hop iterative retrieval.
        # 0 == single pass (unchanged); >0 runs that many cue-driven expansion
        # hops bounded by the request token budget.
        self._multi_hop_hops = max(0, settings.retrieval_multi_hop_hops)
        self._multi_hop_max_cues = max(1, settings.retrieval_multi_hop_max_cues)
        # ROADMAP §4: optional hybrid BM25 backend (default-off). None unless a
        # backend is configured; when present and available, BM25 joins the
        # lexical/vector blend as a third signal.
        self._hybrid_backend: HybridBackend | None = build_hybrid_backend(settings)
        self._hybrid_weight = settings.retrieval_hybrid_weight
        self._hybrid_backend_name = (settings.retrieval_hybrid_backend or "off").lower()
        # ROADMAP §4: optional provenance-graph neighbor expansion (default-off).
        self._graph_backend: GraphBackend | None = build_graph_backend(settings)
        self._graph_weight = settings.retrieval_graph_weight
        self._graph_max_hops = max(1, settings.retrieval_graph_max_hops)
        self._graph_backend_name = (settings.retrieval_graph_backend or "off").lower()
        # ROADMAP §4: deterministic task-intent ranking profiles (default-off).
        self._ranking_profiles_enabled = settings.retrieval_ranking_profiles_enabled

    def _gate_config(self, strategy: RetrievalStrategy) -> "gatemod.GateConfig":
        config = gatemod.GateConfig.for_strategy(strategy)
        if self._stale_warning and config.enable_failure_learning:
            config.enable_stale_warning = True
        return config

    async def retrieve(self, request: RetrievalRequest, *, workspace_id: str) -> MemoryContext:
        # Hot-path timeout (architecture.md §11 / §12.3: retrieve_context should
        # return within ~2s). On timeout we degrade to an empty context rather
        # than blocking the caller; the partial work is abandoned. A non-positive
        # budget disables the guard (mainly for tests).
        if self._timeout_ms and self._timeout_ms > 0:
            try:
                trace = await asyncio.wait_for(
                    self.trace(request, workspace_id=workspace_id),
                    timeout=self._timeout_ms / 1000.0,
                )
            except asyncio.TimeoutError:
                access = self._timeout_access(request, workspace_id=workspace_id)
                await self._repo.add_access_log(access)
                return self._timeout_context(access)
            await self._persist_trace_and_mutations(trace)
            return self._context_from_trace(trace)
        trace = await self.trace(request, workspace_id=workspace_id)
        await self._persist_trace_and_mutations(trace)
        return self._context_from_trace(trace)

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
                trace = await asyncio.wait_for(
                    self.trace(
                        request,
                        workspace_id=workspace_id,
                        prelude_blocks=prelude_blocks,
                        pending_compaction_logs=pending_compaction_logs,
                        prelude_warnings=prelude_warnings,
                    ),
                    timeout=self._timeout_ms / 1000.0,
                )
            except asyncio.TimeoutError:
                access = self._timeout_access(request, workspace_id=workspace_id)
                await self._repo.add_access_log(access)
                return self._timeout_context(access, prelude_warnings=prelude_warnings)
            await self._persist_trace_and_mutations(trace)
            return self._context_from_trace(trace)
        trace = await self.trace(
            request,
            workspace_id=workspace_id,
            prelude_blocks=prelude_blocks,
            pending_compaction_logs=pending_compaction_logs,
            prelude_warnings=prelude_warnings,
        )
        await self._persist_trace_and_mutations(trace)
        return self._context_from_trace(trace)

    async def _persist_trace_and_mutations(self, trace: RetrievalPipelineTrace) -> None:
        await self._persist_trace(trace)
        await self._bump_access_counts(trace.accepted_memories)

    def _timeout_access(self, request: RetrievalRequest, *, workspace_id: str) -> MemoryAccessLog:
        budget = request.token_budget or self._default_budget
        access = MemoryAccessLog(
            workspace_id=workspace_id,
            run_id=request.run_id,
            step_id=request.step_id,
            query=request.query,
            task_intent=request.task_intent,
            retrieval_strategy=request.strategy,
            token_budget=budget,
            top_k=request.top_k,
            latency_ms=self._timeout_ms or 0,
        )
        self._attach_policy_snapshot(access, request, effective_token_budget=budget)
        return access

    def _attach_policy_snapshot(
        self,
        access: MemoryAccessLog,
        request: RetrievalRequest,
        *,
        effective_token_budget: int,
        reflection_signal_source: str = "fallback_lite",
        retention_policy_version: str | None = None,
        scheduler_signal_memory_ids: list[str] | None = None,
        fallback_lite_memory_ids: list[str] | None = None,
        retention_policy_versions: list[str] | None = None,
    ) -> None:
        fusion = self._effective_policy_fusion()
        snapshot = build_policy_snapshot(
            request,
            gate_config=self._gate_config(request.strategy),
            effective_token_budget=effective_token_budget,
            vector_enabled=self._use_vector,
            vector_weight=self._vector_weight,
            compaction_notice_reserve_tokens=self._compaction_notice_reserve_tokens,
            provider_snapshot=self.provider_snapshot,
            reflection_signal_source=reflection_signal_source,
            retention_policy_version=retention_policy_version,
            scheduler_signal_memory_ids=scheduler_signal_memory_ids,
            fallback_lite_memory_ids=fallback_lite_memory_ids,
            retention_policy_versions=retention_policy_versions,
            fusion=fusion,
            rrf_k=self._rrf_k if fusion == "rrf" else None,
            query_planner=self._query_planner,
            query_planner_weight=(
                self._query_planner_weight if self._query_planner != "off" else None
            ),
            multi_hop_hops=self._multi_hop_hops,
            hybrid_backend=(
                self._hybrid_backend_name if self._hybrid_backend is not None else None
            ),
            hybrid_weight=(
                self._hybrid_weight if self._hybrid_backend is not None else None
            ),
            graph_backend=(
                self._graph_backend_name if self._graph_backend is not None else None
            ),
            graph_weight=(
                self._graph_weight if self._graph_backend is not None else None
            ),
            graph_max_hops=(
                self._graph_max_hops if self._graph_backend is not None else None
            ),
            ranking_profile=(
                select_profile(request.task_intent).name
                if self._ranking_profiles_enabled
                else None
            ),
        )
        access.policy_version = POLICY_VERSION
        access.policy_snapshot = snapshot
        access.policy_hash = policy_hash(snapshot)

    def _effective_policy_fusion(self) -> str:
        if self._fusion == "rrf" and not self._use_vector:
            return "linear"
        return self._fusion

    @property
    def provider_snapshot(self) -> dict[str, Any] | None:
        return copy.deepcopy(self._provider_snapshot)

    async def _embed_query(self, query: str | None) -> list[float]:
        if self._embedding_provider is not None:
            try:
                vector = list(await self._embedding_provider.embed_text(query))
                if len(vector) != self._embed_dim:
                    raise ValueError(f"embedding dimension mismatch: expected {self._embed_dim}, got {len(vector)}")
                if not all(isinstance(v, int | float) and math.isfinite(v) for v in vector):
                    raise ValueError("embedding provider returned non-finite vector")
                return vector
            except Exception:  # noqa: BLE001 - retrieval must degrade to deterministic vector search
                pass
        return stable_embedding(query, self._embed_dim)

    def _timeout_context(
        self,
        access: MemoryAccessLog,
        *,
        prelude_warnings: list[str] | None = None,
    ) -> MemoryContext:
        return MemoryContext(
            access_id=access.access_id,
            query=access.query,
            warnings=[*(prelude_warnings or []), f"retrieval timed out after {self._timeout_ms}ms; returned empty context"],
        )

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
        long_context = request.strategy == RetrievalStrategy.long_context
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
        config = self._gate_config(request.strategy)
        self._attach_policy_snapshot(access, request, effective_token_budget=budget)
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

        # ---- phase: retrieval (candidate selection) -------------------- #
        t0 = time.perf_counter()
        active_node, active_ids, active_path = await self._load_active_state(request.run_id)
        candidates = await self._select_candidates_multi_hop(
            workspace_id=workspace_id,
            run_id=request.run_id,
            query=request.query,
            top_k=request.top_k,
            include_all=long_context,
            task_intent=request.task_intent,
            token_budget=budget,
        )
        retrieval_ms = int((time.perf_counter() - t0) * 1000)
        retrieval_phase: dict[str, Any] = {
            "latency_ms": retrieval_ms,
            # Preserve the existing profiler operation label for hot-path
            # backward compatibility; component scores in the trace expose the
            # lexical/vector split for replay and observability.
            "operation": "lexical",
            "candidate_count": len(candidates),
            "accepted_count": 0,
            "rejected_count": 0,
        }
        if self._multi_hop_hops > 0:
            retrieval_phase["metadata"] = {
                "multi_hop_hops": self._multi_hop_hops,
                "multi_hop_candidate_count": sum(1 for c in candidates if c.hop > 0),
            }
        phase_profile[ProfilePhase.retrieval.value] = retrieval_phase

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

        # rank accepted by final score desc; variant_3 blends a retention
        # priority so high-retention memories survive tight budgets. Prefer
        # scheduler-persisted signals when present, fall back per-memory to the
        # deterministic lite score for default benchmark/reproduce behavior.
        if config.enable_reflection_rerank:
            accepted_memory_ids = [o.memory.memory_id for o in accepted_outcomes]
            signals = await self._repo.list_retention_signals(
                workspace_id,
                memory_ids=accepted_memory_ids,
            )
            signals_by_id = {signal.memory_id: signal for signal in signals}
            scheduler_signal_memory_ids = sorted(set(signals_by_id) & set(accepted_memory_ids))
            fallback_lite_memory_ids = sorted(set(accepted_memory_ids) - set(scheduler_signal_memory_ids))
            if scheduler_signal_memory_ids and fallback_lite_memory_ids:
                signal_source = "mixed_scheduler_v1_fallback_lite"
            elif scheduler_signal_memory_ids:
                signal_source = "scheduler_v1"
            else:
                signal_source = "fallback_lite"
            retention_policy_versions = sorted({signal.policy_version for signal in signals if signal.policy_version})
            retention_policy_version = retention_policy_versions[0] if len(retention_policy_versions) == 1 else None
            self._attach_policy_snapshot(
                access,
                request,
                effective_token_budget=budget,
                reflection_signal_source=signal_source,
                retention_policy_version=retention_policy_version,
                scheduler_signal_memory_ids=scheduler_signal_memory_ids,
                fallback_lite_memory_ids=fallback_lite_memory_ids,
                retention_policy_versions=retention_policy_versions,
            )
            for outcome in accepted_outcomes:
                signal = signals_by_id.get(outcome.memory.memory_id)
                priority = signal.reflection_priority if signal is not None else retention_score(outcome.memory)
                outcome.final_score = round(0.5 * outcome.final_score + 0.5 * priority, 6)
            accepted_outcomes.sort(key=lambda o: (-o.final_score, o.memory.memory_id))
        else:
            accepted_outcomes.sort(key=lambda o: (-o.final_score, o.memory.memory_id))
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
            active_path_summarize_after=self._active_path_summarize_after,
            active_path_keep_recent=self._active_path_keep_recent,
            protect_safety_notices=self._protect_safety_notices,
        )
        if long_context and pack_result.pre_compaction_tokens > budget:
            # Long-context is the intentional all-context baseline: keep the
            # normal gate/logging path, but expand the effective budget to the
            # exact pre-compaction size instead of relying on a fixed sentinel.
            budget = max(budget, pack_result.pre_compaction_tokens)
            access.token_budget = budget
            self._attach_policy_snapshot(access, request, effective_token_budget=budget)
            pack_result = pack_context(
                active_node=active_node,
                accepted=accepted_memories,
                token_budget=budget,
                active_path=active_path,
                prelude_blocks=prelude_blocks,
                negative_evidence=negative_evidence,
                compaction_notice_reserve_tokens=self._compaction_notice_reserve_tokens,
                active_path_summarize_after=self._active_path_summarize_after,
                active_path_keep_recent=self._active_path_keep_recent,
            protect_safety_notices=self._protect_safety_notices,
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
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        for mem in accepted_memories:
            await self._repo.bump_memory_access(mem.memory_id, accessed_at=now)

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

    async def _select_candidates_multi_hop(
        self,
        *,
        workspace_id: str,
        run_id: str,
        query: str,
        top_k: int,
        token_budget: int,
        include_all: bool = False,
        task_intent: str | None = None,
    ) -> list[RetrievalCandidateTrace]:
        """Single-pass selection, optionally followed by cue-driven hops.

        ROADMAP §4 iterative reconstruction (default-off, deterministic): after
        the first pass, derive entity cues from the current candidates' content
        and run extra retrieval hops to pull in complementary memories the query
        never names (e.g. a fact linked only by a shared ``service.gateway``
        token). Each hop appends only new, budget-fitting candidates; the request
        token budget caps cumulative content so expansion stays bounded. With
        ``hops == 0`` (default) or ``include_all`` this is exactly the single pass.
        """
        base = await self._select_candidates(
            workspace_id=workspace_id,
            run_id=run_id,
            query=query,
            top_k=top_k,
            include_all=include_all,
            task_intent=task_intent,
        )
        if self._multi_hop_hops <= 0 or include_all:
            return base

        result = list(base)
        seen_ids = {c.memory.memory_id for c in result}
        # Entities the query/rewrite already targets must not seed a hop again.
        covered: set[str] = set(plan_query(query, task_intent).hints)
        used_tokens = sum(estimate_tokens(c.memory.content) for c in result)
        for hop_index in range(1, self._multi_hop_hops + 1):
            if used_tokens >= token_budget:
                break
            cues = derive_hop_cues(
                [c.memory.content for c in result],
                exclude=covered,
                max_cues=self._multi_hop_max_cues,
            )
            if not cues:
                break
            covered.update(cues)
            hop_candidates = await self._select_candidates(
                workspace_id=workspace_id,
                run_id=run_id,
                query=" ".join(cues),
                top_k=top_k,
                include_all=False,
                task_intent=None,
            )
            added_any = False
            for cand in hop_candidates:
                if cand.memory.memory_id in seen_ids:
                    continue
                cand_tokens = estimate_tokens(cand.memory.content)
                if used_tokens + cand_tokens > token_budget:
                    continue
                cand.hop = hop_index
                result.append(cand)
                seen_ids.add(cand.memory.memory_id)
                used_tokens += cand_tokens
                added_any = True
            if not added_any:
                break
        return result

    async def _select_candidates(
        self,
        *,
        workspace_id: str,
        run_id: str,
        query: str,
        top_k: int,
        include_all: bool = False,
        task_intent: str | None = None,
    ) -> list[RetrievalCandidateTrace]:
        # Workspace-scoped retrieval is the permission filter: cross-workspace
        # memories never become candidates, so leakage is impossible by
        # construction. The gate's workspace_mismatch rule is defense-in-depth.

        # ROADMAP §4 need-retrieval decision (only under the "full" planner): a
        # trivial query with no entity/content signal skips retrieval entirely.
        # Never applied to long_context (the deliberate dump-everything baseline).
        if (
            self._query_planner == "full"
            and not include_all
            and not decide_need_retrieval(query, task_intent).should_retrieve
        ):
            return []

        memories = await self._repo.list_memories(workspace_id=workspace_id)

        # ROADMAP §4 query rewrite (only under "full"): expand structural entity
        # terms (dotted keys, paths) into their component words so prose memories
        # that spell the words out still match. The original query is preserved;
        # the rewritten text is only the lexical/vector scoring input. Off/hints
        # leave `lexical_query == query`, so the default path is unchanged.
        lexical_query = query
        if self._query_planner == "full":
            lexical_query = rewrite_query(query, task_intent).text

        # Vector signal: deterministic embedding cosine via pgvector KNN (SQL)
        # or in-memory cosine. Map memory_id -> cosine so we can blend it with
        # the lexical signal per candidate. Falls back to lexical-only if vector
        # retrieval is disabled or yields nothing (e.g. no embeddings stored).
        vector_scores: dict[str, float] = {}
        if self._use_vector:
            q_vec = await self._embed_query(lexical_query)
            knn = await self._repo.search_memories_by_vector(
                embedding=q_vec, workspace_id=workspace_id, top_k=max(top_k * 2, top_k)
            )
            vector_scores = {m.memory_id: sim for m, sim in knn}

        w_vec = self._vector_weight if (self._use_vector and vector_scores) else 0.0
        w_lex = 1.0 - w_vec

        # ROADMAP §4 query planner (default-off): entity-like query terms boost
        # candidates that mention them, so structural names (dotted keys, paths,
        # identifiers) outrank generic token overlap. `hints` is empty unless the
        # planner is enabled, so the boost is a no-op on the default path.
        hints: tuple[str, ...] = ()
        if self._query_planner in ("hints", "full"):
            hints = plan_query(query, task_intent).hints

        retrievable = [m for m in memories if m.status in _RETRIEVABLE_STATUSES]

        # ROADMAP §4 hybrid BM25 (default-off): an optional third lexical signal
        # from an external/deterministic backend. When it returns scores, scale
        # the lexical/vector weights by (1 - hybrid_weight) so the blend sums to 1.
        bm25_scores: dict[str, float] = {}
        w_bm25 = 0.0
        if self._hybrid_backend is not None and self._hybrid_backend.available:
            bm25_scores = await self._hybrid_backend.bm25_scores(
                query=lexical_query,
                memories=retrievable,
                workspace_id=workspace_id,
                top_k=max(top_k * 2, top_k),
            )
            if bm25_scores:
                w_bm25 = self._hybrid_weight
                w_lex *= 1.0 - w_bm25
                w_vec *= 1.0 - w_bm25

        # First pass: compute raw lexical/vector signals for retrievable memories.
        raw: list[tuple[MemoryItem, float, float]] = []
        for m in retrievable:
            lex = lexical_similarity(lexical_query, m.content)
            if hints:
                lex = min(
                    1.0,
                    round(lex + hint_boost(m.content, hints, weight=self._query_planner_weight), 6),
                )
            vec = vector_scores.get(m.memory_id, 0.0)
            raw.append((m, lex, vec))

        # Fusion: blend the signals into a single relevance score. "linear"
        # is the default weighted blend; "rrf" uses Reciprocal Rank Fusion over
        # each signal's ranking, which is robust when lexical/vector/BM25 scores
        # live on different scales (ROADMAP §4 multi-path fusion).
        rrf_active = self._fusion == "rrf" and (w_vec > 0.0 or bool(bm25_scores))
        rrf_scores: dict[str, float] = {}
        if rrf_active:
            rrf_scores = self._rrf_scores(raw, bm25_scores)

        scored: list[RetrievalCandidateTrace] = []
        for m, lex, vec in raw:
            bm25 = bm25_scores.get(m.memory_id, 0.0)
            if rrf_active:
                rel = round(rrf_scores.get(m.memory_id, 0.0), 6)
                positive = rel > 0.0
            else:
                rel = round(w_lex * lex + w_vec * vec + w_bm25 * bm25, 6)
                positive = rel > 0.0
            # project constraints are always relevant to coding queries
            if m.memory_type.value == "project" and not positive:
                rel = 0.2 if not rrf_active else round(0.2 / (self._rrf_k + 1), 6)
                positive = True
            if positive or include_all:
                scored.append(
                    RetrievalCandidateTrace(
                        memory=m,
                        lexical_score=lex,
                        vector_score=vec,
                        bm25_score=bm25,
                        relevance_score=rel,
                    )
                )

        # ROADMAP §4 provenance-graph neighbor expansion (default-off): surface
        # memories linked to the current candidates through SUPERSEDES /
        # CONFLICTS_WITH edges, even when they don't match the query. Graph
        # neighbors stay subject to the lifecycle filter (only `retrievable`
        # memories can be surfaced), so retired branches never leak.
        if (
            self._graph_backend is not None
            and self._graph_backend.available
            and not include_all
            and scored
        ):
            scored = await self._expand_graph_neighbors(
                scored, retrievable=retrievable, memories=memories, workspace_id=workspace_id
            )

        # ROADMAP §4 task-intent ranking profiles (default-off): re-weight
        # candidate relevance by per-memory-type multipliers derived from the
        # task intent (e.g. debug -> boost tool_evidence). A "default" profile
        # (no intent match) is a no-op, so the standard blend is preserved.
        if self._ranking_profiles_enabled:
            profile = select_profile(task_intent)
            if profile.type_weights:
                for cand in scored:
                    mult = profile.weight_for(cand.memory.memory_type.value)
                    if mult != 1.0:
                        cand.relevance_score = round(cand.relevance_score * mult, 6)

        scored.sort(key=lambda c: (-c.relevance_score, c.memory.memory_id))
        if include_all:
            return scored
        return scored[:top_k]

    async def _expand_graph_neighbors(
        self,
        scored: list["RetrievalCandidateTrace"],
        *,
        retrievable: list[MemoryItem],
        memories: list[MemoryItem],
        workspace_id: str,
    ) -> list["RetrievalCandidateTrace"]:
        """Add provenance-graph neighbors of the current candidates.

        Builds SUPERSEDES/CONFLICTS_WITH edges from repository provenance (the
        loaded memories' ``superseded_by`` lineage plus open conflict groups),
        asks the backend for memories within ``max_hops`` of the candidate seed
        set, then either boosts an existing candidate's relevance or appends a new
        candidate for a retrievable neighbor. Relatedness is scaled by
        ``graph_weight``; neighbors that are not retrievable are skipped, so the
        lifecycle filter is preserved.
        """
        if self._graph_backend is None:
            return scored
        conflicts = await self._repo.list_memory_conflicts(
            workspace_id=workspace_id, status="open"
        )
        edges = provenance_edges(memories, conflicts)
        if not edges:
            return scored
        seeds = [c.memory.memory_id for c in scored]
        related = await self._graph_backend.related(
            seeds, edges, max_hops=self._graph_max_hops
        )
        if not related:
            return scored
        by_id = {c.memory.memory_id: c for c in scored}
        retr_by_id = {m.memory_id: m for m in retrievable}
        for memory_id, relatedness in related.items():
            boost = round(self._graph_weight * relatedness, 6)
            existing = by_id.get(memory_id)
            if existing is not None:
                existing.graph_score = relatedness
                existing.relevance_score = round(existing.relevance_score + boost, 6)
            elif memory_id in retr_by_id:
                candidate = RetrievalCandidateTrace(
                    memory=retr_by_id[memory_id],
                    graph_score=relatedness,
                    relevance_score=boost,
                )
                scored.append(candidate)
                by_id[memory_id] = candidate
        return scored

    def _rrf_scores(
        self,
        raw: list[tuple[MemoryItem, float, float]],
        bm25_scores: dict[str, float] | None = None,
    ) -> dict[str, float]:
        """Reciprocal Rank Fusion of the lexical, vector, and (optional) BM25 signals.

        Each signal contributes ``1 / (k + rank)`` for memories with a positive
        score in that signal. Ranks are deterministic: sort by descending score,
        tie-break by ``memory_id``. Memories absent from a signal contribute
        nothing for it. When ``bm25_scores`` is provided (hybrid backend active),
        BM25 joins as a third ranked list — the "vector + BM25 + lexical" multi-path
        fusion (ROADMAP §4). Graph relatedness is fused additively after expansion.
        """
        k = self._rrf_k
        bm25_scores = bm25_scores or {}

        def ranked_pairs(pairs: list[tuple[str, float]]) -> list[str]:
            present = [(mid, s) for mid, s in pairs if s > 0.0]
            present.sort(key=lambda pair: (-pair[1], pair[0]))
            return [mid for mid, _ in present]

        ranked_lists = [
            ranked_pairs([(m.memory_id, lex) for (m, lex, vec) in raw]),  # lexical
            ranked_pairs([(m.memory_id, vec) for (m, lex, vec) in raw]),  # vector
        ]
        if bm25_scores:
            ranked_lists.append(ranked_pairs(list(bm25_scores.items())))  # BM25

        scores: dict[str, float] = {}
        for ranked in ranked_lists:
            for rank, memory_id in enumerate(ranked):
                scores[memory_id] = scores.get(memory_id, 0.0) + 1.0 / (k + rank + 1)
        return scores

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
