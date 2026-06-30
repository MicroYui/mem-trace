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
