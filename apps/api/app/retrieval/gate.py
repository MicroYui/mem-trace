"""Rule-based admission gate (P0).

Three policy layers run in order (mvp.md section 7):
  1. hard_policy  : workspace mismatch, deleted/quarantined, secret,
                    failed/rolled_back branch -> reject immediately
  2. risk_policy  : stale (expires_at < now), tool_sensitive, destructive,
                    production_env, conflicted -> reject/warn/degrade
  3. soft_ranking : weighted relevance/state/freshness/trust/risk -> final_score

Strategy modes tune which layers apply, so the demo/benchmark can prove the
differentiation comes from state-awareness + gating, not from different data:
  - baseline_1 : no hard/risk policy, no state match (pure relevance top-k)
  - variant_1  : state-aware rerank; failed branch downweighted, not rejected
  - variant_2  : full hard + risk policy + state-aware ranking
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
    # failed-branch downweight factor for variant_1 (no hard reject)
    failed_branch_penalty: float = 0.5

    @classmethod
    def for_strategy(cls, strategy: RetrievalStrategy) -> "GateConfig":
        if strategy == RetrievalStrategy.baseline_1:
            return cls(
                enable_hard_policy=False,
                enable_risk_policy=False,
                enable_state_match=False,
                allow_failed_branch=True,
                allow_rolled_back=True,
            )
        if strategy == RetrievalStrategy.variant_1:
            return cls(
                enable_hard_policy=False,
                enable_risk_policy=False,
                enable_state_match=True,
                allow_failed_branch=True,
                allow_rolled_back=True,
            )
        # variant_2 (default) and baseline_0 (no candidates anyway)
        return cls()


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
        return self.decision in (GateDecisionType.accept, GateDecisionType.degrade, GateDecisionType.warn)


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

    # ---- Layer 1: hard policy ------------------------------------------- #
    if config.enable_hard_policy:
        if memory.workspace_id != workspace_id:
            return _reject(memory, GateLayer.hard_policy, "workspace_mismatch", relevance, state_match, freshness, trust, risk)
        if memory.status in (MemoryStatus.deleted, MemoryStatus.quarantined):
            return _reject(memory, GateLayer.hard_policy, "invalid_status", relevance, state_match, freshness, trust, risk)
        if memory.sensitivity == Sensitivity.secret:
            return _reject(memory, GateLayer.hard_policy, "secret", relevance, state_match, freshness, trust, risk)
        if memory.branch_status == BranchStatus.failed and not config.allow_failed_branch:
            return _reject(memory, GateLayer.hard_policy, "failed_branch", relevance, state_match, freshness, trust, risk)
        if memory.branch_status == BranchStatus.rolled_back and not config.allow_rolled_back:
            return _reject(memory, GateLayer.hard_policy, "rolled_back", relevance, state_match, freshness, trust, risk)

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


__all__ = ["GateConfig", "GateOutcome", "evaluate"]
