"""Admission gate hard/risk policy tests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.retrieval import gate as gatemod
from app.retrieval.gate import GateConfig
from app.runtime.models import (
    BranchStatus,
    GateDecisionType,
    MemoryItem,
    MemoryStatus,
    MemoryType,
    RetrievalStrategy,
    RiskFlags,
    Sensitivity,
)


def _mem(**kw) -> MemoryItem:
    base = dict(workspace_id="ws", memory_type=MemoryType.tool_evidence, content="x")
    base.update(kw)
    return MemoryItem(**base)


def _eval(mem, *, workspace_id="ws", config=None):
    return gatemod.evaluate(
        mem, workspace_id=workspace_id, relevance=0.5, state_match=0.5,
        config=config or GateConfig(),
    )


def test_hard_reject_workspace_mismatch():
    out = _eval(_mem(workspace_id="other"))
    assert out.decision == GateDecisionType.reject
    assert out.reject_reason == "workspace_mismatch"


def test_hard_reject_deleted_or_quarantined():
    assert _eval(_mem(status=MemoryStatus.quarantined)).reject_reason == "invalid_status"
    assert _eval(_mem(status=MemoryStatus.deleted)).reject_reason == "invalid_status"


def test_hard_reject_secret():
    out = _eval(_mem(sensitivity=Sensitivity.secret))
    assert out.reject_reason == "secret"


def test_hard_reject_contains_secret_flag_even_when_completed():
    out = _eval(
        _mem(
            branch_status=BranchStatus.completed,
            sensitivity=Sensitivity.internal,
            risk_flags=RiskFlags(contains_secret=True),
        )
    )
    assert out.decision == GateDecisionType.reject
    assert out.reject_reason == "secret"
    assert out.accepted is False


def test_hard_reject_failed_and_rolled_back_branch():
    assert _eval(_mem(branch_status=BranchStatus.failed)).reject_reason == "failed_branch"
    assert _eval(_mem(branch_status=BranchStatus.rolled_back)).reject_reason == "rolled_back"


def test_failure_learning_degrades_safe_failed_branch_without_positive_acceptance():
    out = _eval(
        _mem(branch_status=BranchStatus.failed),
        config=GateConfig(enable_failure_learning=True),
    )
    assert out.decision == GateDecisionType.degrade
    assert out.reject_reason == "failed_branch_degraded"
    assert out.accepted is False
    assert out.degraded is True
    assert out.final_score == 0.5


def test_failure_learning_degrades_safe_rolled_back_branch():
    out = _eval(
        _mem(branch_status=BranchStatus.rolled_back),
        config=GateConfig(enable_failure_learning=True),
    )
    assert out.decision == GateDecisionType.degrade
    assert out.reject_reason == "rolled_back_degraded"
    assert out.accepted is False
    assert out.degraded is True


def test_failure_learning_sanitizes_unsafe_failed_branch_before_risk_policy():
    out = _eval(
        _mem(
            branch_status=BranchStatus.failed,
            risk_flags=RiskFlags(destructive_command=True, tool_sensitive=True),
        ),
        config=GateConfig(enable_failure_learning=True),
    )
    assert out.decision == GateDecisionType.reject
    assert out.reject_reason == "failed_branch_sanitized"
    assert out.degraded is False


def test_failure_learning_sanitizes_secret_and_production_failed_branch():
    secret = _eval(
        _mem(branch_status=BranchStatus.failed, sensitivity=Sensitivity.secret),
        config=GateConfig(enable_failure_learning=True),
    )
    production = _eval(
        _mem(branch_status=BranchStatus.failed, risk_flags=RiskFlags(production_env=True)),
        config=GateConfig(enable_failure_learning=True),
    )
    assert secret.reject_reason == "failed_branch_sanitized"
    assert production.reject_reason == "failed_branch_sanitized"


@pytest.mark.parametrize(
    ("branch_status", "expected_reason"),
    [
        (BranchStatus.failed, "failed_branch_sanitized"),
        (BranchStatus.rolled_back, "rolled_back_sanitized"),
    ],
)
@pytest.mark.parametrize(
    "memory_kwargs",
    [
        {"sensitivity": Sensitivity.secret},
        {"risk_flags": RiskFlags(contains_secret=True)},
        {"risk_flags": RiskFlags(destructive_command=True)},
        {"risk_flags": RiskFlags(tool_sensitive=True)},
        {"risk_flags": RiskFlags(production_env=True)},
    ],
)
def test_failure_learning_sanitizes_all_unsafe_failedish_branches(branch_status, expected_reason, memory_kwargs):
    out = _eval(
        _mem(branch_status=branch_status, **memory_kwargs),
        config=GateConfig(enable_failure_learning=True),
    )
    assert out.decision == GateDecisionType.reject
    assert out.reject_reason == expected_reason
    assert out.degraded is False


def test_risk_reject_stale():
    past = datetime.now(timezone.utc) - timedelta(days=1)
    out = _eval(_mem(expires_at=past))
    assert out.reject_reason == "stale"


def test_risk_reject_tool_sensitive_and_destructive():
    assert _eval(_mem(risk_flags=RiskFlags(tool_sensitive=True))).reject_reason == "tool_sensitive"
    assert _eval(_mem(risk_flags=RiskFlags(destructive_command=True))).reject_reason == "destructive_command"


def test_production_env_warns_but_accepts():
    out = _eval(_mem(risk_flags=RiskFlags(production_env=True)))
    assert out.decision == GateDecisionType.warn
    assert out.accepted is True


def test_baseline_1_config_disables_hard_policy():
    cfg = GateConfig.for_strategy(RetrievalStrategy.baseline_1)
    out = _eval(_mem(branch_status=BranchStatus.failed), config=cfg)
    assert out.accepted is True  # failed branch admitted by baseline


def test_long_context_config_matches_baseline_1_all_policies_off():
    cfg = GateConfig.for_strategy(RetrievalStrategy.long_context)
    assert cfg.enable_hard_policy is False
    assert cfg.enable_risk_policy is False
    assert cfg.enable_state_match is False
    assert cfg.allow_failed_branch is True
    assert cfg.allow_rolled_back is True
    assert cfg.enable_failure_learning is False
    assert cfg.enable_reflection_rerank is False


def test_variant_1_downweights_failed_branch_without_reject():
    cfg = GateConfig.for_strategy(RetrievalStrategy.variant_1)
    completed = _eval(_mem(branch_status=BranchStatus.completed), config=cfg)
    failed = _eval(_mem(branch_status=BranchStatus.failed), config=cfg)
    assert failed.accepted is True
    assert failed.final_score < completed.final_score


@pytest.mark.parametrize(
    ("strategy", "expected"),
    [
        (RetrievalStrategy.baseline_0, False),
        (RetrievalStrategy.long_context, False),
        (RetrievalStrategy.baseline_1, False),
        (RetrievalStrategy.variant_1, False),
        (RetrievalStrategy.variant_2, True),
        (RetrievalStrategy.variant_3, True),
    ],
)
def test_failure_learning_enabled_for_full_gate_strategies_only(strategy, expected):
    assert GateConfig.for_strategy(strategy).enable_failure_learning is expected


def test_variant_3_config_is_variant_2_plus_reflection_rerank():
    cfg = GateConfig.for_strategy(RetrievalStrategy.variant_3)
    assert cfg.enable_hard_policy is True
    assert cfg.enable_risk_policy is True
    assert cfg.enable_state_match is True
    assert cfg.enable_failure_learning is True
    assert cfg.enable_reflection_rerank is True


def test_reflection_rerank_enabled_only_for_variant_3():
    for strategy in (
        RetrievalStrategy.baseline_0,
        RetrievalStrategy.long_context,
        RetrievalStrategy.baseline_1,
        RetrievalStrategy.variant_1,
        RetrievalStrategy.variant_2,
    ):
        assert GateConfig.for_strategy(strategy).enable_reflection_rerank is False
    assert GateConfig.for_strategy(RetrievalStrategy.variant_3).enable_reflection_rerank is True


def test_variant_2_enables_failure_learning_for_safe_failed_branch():
    cfg = GateConfig.for_strategy(RetrievalStrategy.variant_2)
    out = _eval(_mem(branch_status=BranchStatus.failed), config=cfg)
    assert cfg.enable_failure_learning is True
    assert out.decision == GateDecisionType.degrade
    assert out.reject_reason == "failed_branch_degraded"
    assert out.accepted is False
