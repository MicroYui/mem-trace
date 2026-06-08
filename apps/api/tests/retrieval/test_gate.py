"""Admission gate hard/risk policy tests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

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


def test_hard_reject_failed_and_rolled_back_branch():
    assert _eval(_mem(branch_status=BranchStatus.failed)).reject_reason == "failed_branch"
    assert _eval(_mem(branch_status=BranchStatus.rolled_back)).reject_reason == "rolled_back"


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


def test_variant_1_downweights_failed_branch_without_reject():
    cfg = GateConfig.for_strategy(RetrievalStrategy.variant_1)
    completed = _eval(_mem(branch_status=BranchStatus.completed), config=cfg)
    failed = _eval(_mem(branch_status=BranchStatus.failed), config=cfg)
    assert failed.accepted is True
    assert failed.final_score < completed.final_score


def test_variant_2_rejects_failed_branch():
    cfg = GateConfig.for_strategy(RetrievalStrategy.variant_2)
    out = _eval(_mem(branch_status=BranchStatus.failed), config=cfg)
    assert out.decision == GateDecisionType.reject
