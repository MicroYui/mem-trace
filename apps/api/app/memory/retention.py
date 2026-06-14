"""Deterministic retention and reflection signal scoring."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math

from app.runtime.models import MemoryItem, MemoryRetentionSignal


RETENTION_POLICY_VERSION = "retention-policy-v1"


@dataclass(frozen=True, slots=True)
class RetentionPolicy:
    access_cap: int = 10
    recency_half_life_days: float = 30.0
    high_risk_threshold: float = 0.8
    expired_multiplier: float = 0.1
    high_risk_multiplier: float = 0.25


def compute_retention_signals(
    memory: MemoryItem,
    *,
    now: datetime | None = None,
    policy: RetentionPolicy | None = None,
) -> MemoryRetentionSignal:
    now = now or datetime.now(timezone.utc)
    policy = policy or RetentionPolicy()
    value = _clamp01(memory.value_score)
    freshness = _clamp01(memory.freshness_score)
    trust = _clamp01(memory.trust_score)
    risk = _clamp01(memory.risk_score)
    usage = _clamp01(memory.access_count / max(1, policy.access_cap))
    recency = _recency(memory, now, policy)
    expired = memory.expires_at is not None and memory.expires_at <= now
    high_risk = _high_risk(memory, risk, policy)

    retention = 0.30 * value + 0.20 * freshness + 0.25 * trust + 0.15 * usage + 0.10 * recency
    reflection = 0.35 * trust + 0.25 * freshness + 0.25 * usage + 0.15 * value
    if expired:
        retention *= policy.expired_multiplier
        reflection *= policy.expired_multiplier
    if high_risk:
        retention *= policy.high_risk_multiplier
        reflection *= policy.high_risk_multiplier

    reason = {
        "components": {
            "value": round(value, 6),
            "freshness": round(freshness, 6),
            "trust": round(trust, 6),
            "risk": round(risk, 6),
            "usage": round(usage, 6),
            "recency": round(recency, 6),
        },
        "expired": expired,
        "high_risk": high_risk,
    }
    return MemoryRetentionSignal(
        memory_id=memory.memory_id,
        workspace_id=memory.workspace_id,
        retention_score=round(_clamp01(retention), 6),
        reflection_priority=round(_clamp01(reflection), 6),
        reason=reason,
        policy_version=RETENTION_POLICY_VERSION,
        scored_at=now,
        updated_at=now,
    )


def _recency(memory: MemoryItem, now: datetime, policy: RetentionPolicy) -> float:
    if memory.last_accessed_at is None:
        return 0.0
    age_days = max(0.0, (now - memory.last_accessed_at).total_seconds() / 86400.0)
    return _clamp01(1.0 - age_days / max(policy.recency_half_life_days, 1.0))


def _high_risk(memory: MemoryItem, risk: float, policy: RetentionPolicy) -> bool:
    flags = memory.risk_flags
    return bool(
        risk >= policy.high_risk_threshold
        or flags.contains_secret
        or flags.destructive_command
        or flags.tool_sensitive
        or flags.production_env
    )


def _clamp01(value: float) -> float:
    value = float(value)
    if not math.isfinite(value):
        return 0.0
    return max(0.0, min(1.0, value))


__all__ = ["RETENTION_POLICY_VERSION", "RetentionPolicy", "compute_retention_signals"]
