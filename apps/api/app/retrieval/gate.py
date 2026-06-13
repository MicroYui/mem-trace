"""Rule-based admission gate (P0).

Three policy layers run in order (mvp.md section 7):
  1. hard_policy  : workspace mismatch, deleted/quarantined, secret,
                    failed/rolled_back branches reject by default; when failure
                    learning is enabled, safe failures degrade into the
                    negative-evidence channel and unsafe failures reject with
                    sanitized reasons
  2. risk_policy  : stale (expires_at < now), tool_sensitive, destructive,
                    production_env, conflicted -> reject/warn/degrade
  3. soft_ranking : weighted relevance/state/freshness/trust/risk -> final_score

Strategy modes tune which layers apply, so the demo/benchmark can prove the
differentiation comes from state-awareness + gating, not from different data:
  - long_context : ablation baseline with hard/risk policy disabled and no state
                   match; controller later stuffs all retrievable workspace
                   memory into an unbounded budget. Non-bypassable safety floors
                   (such as quarantine rejection) still apply.
  - baseline_1 : hard/risk policy disabled, no state match (pure relevance top-k),
                 while non-bypassable safety floors still apply.
  - variant_1  : state-aware rerank; failed branch downweighted, not rejected;
                 hard/risk safety policy remains enabled.
  - variant_2  : full hard + risk policy + state-aware ranking
  - variant_3  : variant_2 + deterministic reflection-lite retention rerank
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from app.runtime.models import (
    BranchStatus,
    GateDecisionType,
    GateLayer,
    MemoryItem,
    MemoryStatus,
    RetrievalStrategy,
    Sensitivity,
)


@dataclass
class GateConfig:
    allow_failed_branch: bool = False
    allow_rolled_back: bool = False
    enable_hard_policy: bool = True
    enable_risk_policy: bool = True
    enable_state_match: bool = True
    enable_failure_learning: bool = False
    enable_reflection_rerank: bool = False
    # failed-branch downweight factor for variant_1 (no hard reject)
    failed_branch_penalty: float = 0.5

    @classmethod
    def for_strategy(cls, strategy: RetrievalStrategy) -> "GateConfig":
        if strategy in (RetrievalStrategy.baseline_1, RetrievalStrategy.long_context):
            return cls(
                enable_hard_policy=False,
                enable_risk_policy=False,
                enable_state_match=False,
                allow_failed_branch=True,
                allow_rolled_back=True,
                enable_failure_learning=False,
            )
        if strategy == RetrievalStrategy.variant_1:
            return cls(
                enable_hard_policy=True,
                enable_risk_policy=True,
                enable_state_match=True,
                allow_failed_branch=True,
                allow_rolled_back=True,
                enable_failure_learning=False,
            )
        if strategy == RetrievalStrategy.variant_2:
            return cls(enable_failure_learning=True)
        if strategy == RetrievalStrategy.variant_3:
            return cls(enable_failure_learning=True, enable_reflection_rerank=True)
        # baseline_0 has no candidates, but keep its config contract explicit:
        # neither failure learning nor reflection rerank is enabled.
        return cls(enable_failure_learning=False)


@dataclass
class GateOutcome:
    memory: MemoryItem
    layer: GateLayer
    decision: GateDecisionType
    reject_reason: Optional[str] = None
    relevance_score: float = 0.0
    state_match_score: float = 0.0
    freshness_score: float = 0.0
    trust_score: float = 0.0
    risk_score: float = 0.0
    final_score: float = 0.0
    warnings: list[str] = field(default_factory=list)

    @property
    def accepted(self) -> bool:
        return self.decision in (GateDecisionType.accept, GateDecisionType.warn)

    @property
    def degraded(self) -> bool:
        return self.decision == GateDecisionType.degrade


def _now() -> datetime:
    return datetime.now(timezone.utc)


def evaluate(
    memory: MemoryItem,
    *,
    workspace_id: str,
    relevance: float,
    state_match: float,
    config: GateConfig,
) -> GateOutcome:
    """Run the layered policy for one candidate."""
    freshness = float(memory.freshness_score)
    trust = float(memory.trust_score)
    risk = float(memory.risk_score)

    # Mandatory safety floor: quarantine is never prompt-injectable, even in
    # ablation strategies that disable parts of the hard/risk gate. Candidate
    # retrieval may still surface quarantined memories so gate logs remain
    # auditable, but the prompt context must never include them.
    if memory.status == MemoryStatus.quarantined:
        return _reject(memory, GateLayer.hard_policy, "invalid_status", relevance, state_match, freshness, trust, risk)

    # ---- Layer 1: hard policy ------------------------------------------- #
    if config.enable_hard_policy:
        if memory.workspace_id != workspace_id:
            return _reject(memory, GateLayer.hard_policy, "workspace_mismatch", relevance, state_match, freshness, trust, risk)
        if memory.status in (MemoryStatus.deleted, MemoryStatus.quarantined):
            return _reject(memory, GateLayer.hard_policy, "invalid_status", relevance, state_match, freshness, trust, risk)
        if memory.branch_status == BranchStatus.failed and not config.allow_failed_branch:
            if config.enable_failure_learning:
                if _is_unsafe_failed(memory):
                    return _reject(
                        memory,
                        GateLayer.hard_policy,
                        "failed_branch_sanitized",
                        relevance,
                        state_match,
                        freshness,
                        trust,
                        risk,
                    )
                return _degrade(
                    memory,
                    GateLayer.hard_policy,
                    "failed_branch_degraded",
                    relevance,
                    state_match,
                    freshness,
                    trust,
                    risk,
                )
            return _reject(memory, GateLayer.hard_policy, "failed_branch", relevance, state_match, freshness, trust, risk)
        if memory.branch_status == BranchStatus.rolled_back and not config.allow_rolled_back:
            if config.enable_failure_learning:
                if _is_unsafe_failed(memory):
                    return _reject(
                        memory,
                        GateLayer.hard_policy,
                        "rolled_back_sanitized",
                        relevance,
                        state_match,
                        freshness,
                        trust,
                        risk,
                    )
                return _degrade(
                    memory,
                    GateLayer.hard_policy,
                    "rolled_back_degraded",
                    relevance,
                    state_match,
                    freshness,
                    trust,
                    risk,
                )
            return _reject(memory, GateLayer.hard_policy, "rolled_back", relevance, state_match, freshness, trust, risk)
        if memory.sensitivity == Sensitivity.secret or memory.risk_flags.contains_secret:
            return _reject(memory, GateLayer.hard_policy, "secret", relevance, state_match, freshness, trust, risk)

    # Non-bypassable safety floor for ablation strategies with hard/risk policy
    # disabled. This intentionally runs after failure-learning sanitization so
    # unsafe failed/rolled_back branches keep their sanitized reject reasons.
    if memory.sensitivity == Sensitivity.secret or memory.risk_flags.contains_secret:
        return _reject(memory, GateLayer.hard_policy, "secret", relevance, state_match, freshness, trust, risk)
    if memory.risk_flags.destructive_command:
        return _reject(memory, GateLayer.risk_policy, "destructive_command", relevance, state_match, freshness, trust, risk)
    if memory.risk_flags.tool_sensitive:
        return _reject(memory, GateLayer.risk_policy, "tool_sensitive", relevance, state_match, freshness, trust, risk)

    warnings: list[str] = []
    # ---- Layer 2: risk policy ------------------------------------------- #
    if config.enable_risk_policy:
        if memory.expires_at is not None and memory.expires_at < _now():
            return _reject(memory, GateLayer.risk_policy, "stale", relevance, state_match, freshness, trust, risk)
        flags = memory.risk_flags
        if flags.destructive_command:
            return _reject(memory, GateLayer.risk_policy, "destructive_command", relevance, state_match, freshness, trust, risk)
        if flags.tool_sensitive:
            return _reject(memory, GateLayer.risk_policy, "tool_sensitive", relevance, state_match, freshness, trust, risk)
        if flags.production_env:
            warnings.append("production_env memory flagged")
        if memory.status == MemoryStatus.conflicted:
            warnings.append("conflicted memory degraded")

    # ---- Layer 3: soft ranking ------------------------------------------ #
    state_component = state_match if config.enable_state_match else 0.0
    final = (
        0.40 * relevance
        + 0.25 * state_component
        + 0.15 * freshness
        + 0.15 * trust
        - 0.15 * risk
    )
    # variant_1: downweight failed/rolled_back instead of rejecting
    if memory.branch_status in (BranchStatus.failed, BranchStatus.rolled_back):
        if config.allow_failed_branch or config.allow_rolled_back:
            final *= config.failed_branch_penalty
    final = round(final, 6)

    decision = GateDecisionType.warn if warnings else GateDecisionType.accept
    return GateOutcome(
        memory=memory,
        layer=GateLayer.soft_ranking,
        decision=decision,
        relevance_score=relevance,
        state_match_score=state_component,
        freshness_score=freshness,
        trust_score=trust,
        risk_score=risk,
        final_score=final,
        warnings=warnings,
    )


def _reject(memory, layer, reason, relevance, state_match, freshness, trust, risk) -> GateOutcome:
    return GateOutcome(
        memory=memory,
        layer=layer,
        decision=GateDecisionType.reject,
        reject_reason=reason,
        relevance_score=relevance,
        state_match_score=state_match,
        freshness_score=freshness,
        trust_score=trust,
        risk_score=risk,
        final_score=0.0,
    )


def _degrade(memory, layer, reason, relevance, state_match, freshness, trust, risk) -> GateOutcome:
    return GateOutcome(
        memory=memory,
        layer=layer,
        decision=GateDecisionType.degrade,
        reject_reason=reason,
        relevance_score=relevance,
        state_match_score=state_match,
        freshness_score=freshness,
        trust_score=trust,
        risk_score=risk,
        final_score=relevance,
    )


def _is_unsafe_failed(memory: MemoryItem) -> bool:
    flags = memory.risk_flags
    return (
        memory.sensitivity == Sensitivity.secret
        or flags.contains_secret
        or flags.destructive_command
        or flags.tool_sensitive
        or flags.production_env
    )


__all__ = ["GateConfig", "GateOutcome", "evaluate"]
