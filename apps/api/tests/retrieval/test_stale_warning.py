"""ROADMAP §9.1 derivative: stale -> outdated-warning downgrade (default-off).

Mirrors failure-learning ``degrade``: a stale but otherwise safe memory is not
hard-rejected and silently dropped; instead it degrades into the warning-only
negative-evidence channel as an "outdated warning", never positive context. This
keeps ``case_9 variant_2_excludes_stale_memory`` intact because the stale memory
still does not enter the accepted/positive context, and it stays default-off so
benchmark behavior is unchanged.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.retrieval import gate
from app.retrieval.gate import GateConfig, GateLayer, GateOutcome
from app.retrieval.negative_evidence import build_negative_evidence
from app.retrieval.packer import pack_context
from app.runtime.models import (
    BranchStatus,
    GateDecisionType,
    MemoryItem,
    MemoryScope,
    MemoryType,
    RiskFlags,
)


def _stale_mem(*, value="/v1/old", content="The API endpoint is /v1/old") -> MemoryItem:
    return MemoryItem(
        workspace_id="ws",
        memory_type=MemoryType.project,
        key="endpoint.current",
        value=value,
        content=content,
        scope=MemoryScope.workspace,
        expires_at=datetime.now(timezone.utc) - timedelta(days=1),
    )


def _stale_outcome(mem: MemoryItem) -> GateOutcome:
    return GateOutcome(
        memory=mem,
        layer=GateLayer.risk_policy,
        decision=GateDecisionType.degrade,
        reject_reason="stale_outdated",
    )


def test_stale_warning_disabled_by_default_rejects_stale():
    out = gate.evaluate(_stale_mem(), workspace_id="ws", relevance=0.9, state_match=0.5, config=GateConfig())
    assert out.decision == GateDecisionType.reject
    assert out.reject_reason == "stale"


def test_stale_warning_enabled_degrades_safe_stale_to_outdated():
    out = gate.evaluate(
        _stale_mem(), workspace_id="ws", relevance=0.9, state_match=0.5,
        config=GateConfig(enable_stale_warning=True),
    )
    assert out.decision == GateDecisionType.degrade
    assert out.reject_reason == "stale_outdated"
    # degrade is NOT accepted positive context
    assert out.accepted is False


def test_builder_renders_stale_outdated_warning_block():
    mem = _stale_mem()
    evs = build_negative_evidence([_stale_outcome(mem)], {mem.memory_id: mem})
    assert len(evs) == 1
    ev = evs[0]
    assert ev.mode == "outdated_warning"
    assert ev.reason == "stale_outdated"
    assert "OUTDATED" in ev.safe_text
    assert "/v1/old" in ev.safe_text


def test_builder_sanitizes_secret_bearing_stale_without_leak():
    mem = _stale_mem(content="token=sk-abcdef1234567890abcd is the key")
    mem.risk_flags = RiskFlags(contains_secret=True)
    ev = build_negative_evidence([_stale_outcome(mem)], {mem.memory_id: mem})[0]
    assert ev.mode == "outdated_warning"
    assert "sk-abcdef1234567890abcd" not in ev.safe_text


def test_stale_outdated_warning_packs_as_avoided_block_not_positive():
    mem = _stale_mem()
    evs = build_negative_evidence([_stale_outcome(mem)], {mem.memory_id: mem})
    result = pack_context(active_node=None, accepted=[], negative_evidence=evs, token_budget=256)
    block = next(b for b in result.blocks if b.type == "avoided_attempts")
    assert block.source == "negative_evidence"
    assert "OUTDATED" in block.content
    # there is no positive memory block for the stale memory
    assert all(b.type == "avoided_attempts" for b in result.blocks)


def test_controller_enables_stale_warning_only_for_failure_learning_strategies(monkeypatch):
    from app.config import Settings
    from app.retrieval import controller as controller_mod
    from app.runtime.models import RetrievalStrategy
    from app.runtime.repository import InMemoryRepository

    on = Settings(stale_warning_enabled=True)
    monkeypatch.setattr(controller_mod, "get_settings", lambda: on)
    c = controller_mod.RetrievalController(InMemoryRepository())
    assert c._gate_config(RetrievalStrategy.variant_2).enable_stale_warning is True
    assert c._gate_config(RetrievalStrategy.variant_3).enable_stale_warning is True
    # ablation/state-only strategies never enable it
    assert c._gate_config(RetrievalStrategy.baseline_1).enable_stale_warning is False
    assert c._gate_config(RetrievalStrategy.variant_1).enable_stale_warning is False

    off = Settings(stale_warning_enabled=False)
    monkeypatch.setattr(controller_mod, "get_settings", lambda: off)
    c2 = controller_mod.RetrievalController(InMemoryRepository())
    assert c2._gate_config(RetrievalStrategy.variant_2).enable_stale_warning is False


def test_stale_warning_disabled_on_baseline_strategies(monkeypatch):
    # Contract: even with the flag globally ON, stale -> stale_outdated degrade is
    # reserved for the failure-learning strategies (variant_2/variant_3). Baseline
    # and state-only-rerank strategies never enable it, so a stale-but-safe memory
    # is never routed into the warning-only channel for them.
    from app.config import Settings
    from app.retrieval import controller as controller_mod
    from app.runtime.models import RetrievalStrategy
    from app.runtime.repository import InMemoryRepository

    on = Settings(stale_warning_enabled=True)
    monkeypatch.setattr(controller_mod, "get_settings", lambda: on)
    c = controller_mod.RetrievalController(InMemoryRepository())

    # baseline_1 (ablation) disables the risk policy entirely, so a stale-but-safe
    # memory is never gated as stale: it is neither hard-rejected nor degraded to
    # the stale_outdated warning channel.
    b1_cfg = c._gate_config(RetrievalStrategy.baseline_1)
    assert b1_cfg.enable_stale_warning is False
    b1_out = gate.evaluate(_stale_mem(), workspace_id="ws", relevance=0.9, state_match=0.5, config=b1_cfg)
    assert b1_out.decision is not GateDecisionType.degrade
    assert b1_out.reject_reason != "stale_outdated"
    assert b1_out.decision == GateDecisionType.accept

    # variant_1 keeps the risk policy but not the stale-warning degrade, so a
    # stale memory is a HARD 'stale' reject -- never a degraded stale_outdated.
    v1_cfg = c._gate_config(RetrievalStrategy.variant_1)
    assert v1_cfg.enable_stale_warning is False
    v1_out = gate.evaluate(_stale_mem(), workspace_id="ws", relevance=0.9, state_match=0.5, config=v1_cfg)
    assert v1_out.decision == GateDecisionType.reject
    assert v1_out.reject_reason == "stale"


def test_secret_precedence_over_stale_when_warning_enabled():
    # Contract: secret is a non-bypassable HARD reject that runs BEFORE the stale
    # branch. A memory that is BOTH expired/stale AND secret-bearing must reject on
    # 'secret' at the hard_policy layer, never degrade to the stale_outdated warning
    # -- even on variant_2 with the stale-warning flag enabled.
    from app.runtime.models import RetrievalStrategy, Sensitivity

    cfg = GateConfig.for_strategy(RetrievalStrategy.variant_2)
    cfg.enable_stale_warning = True
    assert cfg.enable_failure_learning is True

    # secret carried via risk_flags.contains_secret
    mem = _stale_mem(content="token=sk-abcdef1234567890abcd is the key")
    mem.risk_flags = RiskFlags(contains_secret=True)
    out = gate.evaluate(mem, workspace_id="ws", relevance=0.9, state_match=0.5, config=cfg)
    assert out.decision == GateDecisionType.reject
    assert out.reject_reason == "secret"
    assert out.layer == GateLayer.hard_policy
    assert out.reject_reason != "stale_outdated"

    # secret carried via sensitivity=secret takes the same precedence over stale
    mem2 = _stale_mem()
    mem2.sensitivity = Sensitivity.secret
    out2 = gate.evaluate(mem2, workspace_id="ws", relevance=0.9, state_match=0.5, config=cfg)
    assert out2.decision == GateDecisionType.reject
    assert out2.reject_reason == "secret"
    assert out2.reject_reason != "stale_outdated"


def test_destructive_precedence_over_stale_when_warning_enabled():
    # Contract: a destructive_command is a non-bypassable HARD reject that runs
    # BEFORE the stale branch. A memory that is BOTH expired/stale AND destructive
    # must reject on 'destructive_command' at the risk_policy safety floor, never
    # degrade to the stale_outdated warning -- even with the flag enabled.
    from app.runtime.models import RetrievalStrategy

    cfg = GateConfig.for_strategy(RetrievalStrategy.variant_2)
    cfg.enable_stale_warning = True

    mem = _stale_mem(content="run rm -rf / on the prod box")
    mem.risk_flags = RiskFlags(destructive_command=True)
    out = gate.evaluate(mem, workspace_id="ws", relevance=0.9, state_match=0.5, config=cfg)
    assert out.decision == GateDecisionType.reject
    assert out.reject_reason == "destructive_command"
    assert out.layer == GateLayer.risk_policy
    assert out.reject_reason != "stale_outdated"
