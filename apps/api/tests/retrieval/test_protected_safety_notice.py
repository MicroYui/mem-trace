"""ROADMAP §1.1: protect safety-critical sanitized negative evidence from budget drops.

`sanitized_risk_notice` blocks carry "a previous destructive/secret attempt was
redacted — do not repeat it" safety guidance. By default they are ordinary
(droppable) blocks. With `protect_safety_negative_evidence` enabled (default-off),
they join the protected set so a tight budget cannot silently discard the safety
notice. Default-off keeps case_13 compaction-retention and benchmark 13/13.
"""
from __future__ import annotations

from app.retrieval.negative_evidence import SANITIZED_TEMPLATES
from app.retrieval.packer import pack_context
from app.runtime.models import (
    BranchStatus,
    MemoryItem,
    MemoryScope,
    MemoryType,
    NegativeEvidence,
)

_BIG = " ".join(
    "alpha beta gamma delta echo foxtrot golf hotel india juliet kilo lima "
    "mike november oscar papa quebec romeo sierra tango uniform victor".split()
)


def _positive() -> MemoryItem:
    return MemoryItem(
        workspace_id="ws", memory_type=MemoryType.project, key="project.database",
        value="postgres", content=_BIG, scope=MemoryScope.workspace,
    )


def _sanitized_ne(mid="m1") -> NegativeEvidence:
    return NegativeEvidence(
        source_memory_id=mid,
        branch_status=BranchStatus.failed,
        mode="sanitized_risk_notice",
        risk_kind="destructive",
        reason="failed_branch_sanitized",
        safe_text=SANITIZED_TEMPLATES["destructive"],
    )


def _raw_ne(mid="m2") -> NegativeEvidence:
    return NegativeEvidence(
        source_memory_id=mid,
        branch_status=BranchStatus.failed,
        mode="raw_failed_attempt",
        reason="failed_branch_degraded",
        safe_text="ran npm install which failed during setup",
    )


def test_sanitized_safety_notice_droppable_by_default():
    result = pack_context(
        active_node=None, accepted=[_positive()], negative_evidence=[_sanitized_ne()], token_budget=30,
    )
    # default: the safety notice is an ordinary block and gets dropped under budget
    assert all(b.reason != "failed_branch_sanitized" for b in result.blocks)
    assert any(b.reason == "failed_branch_sanitized" for b in result.dropped_blocks)


def test_sanitized_safety_notice_protected_when_enabled():
    result = pack_context(
        active_node=None, accepted=[_positive()], negative_evidence=[_sanitized_ne()], token_budget=30,
        protect_safety_notices=True,
    )
    # enabled: the safety notice survives in the packed prompt
    assert any(b.reason == "failed_branch_sanitized" for b in result.blocks)
    assert all(b.reason != "failed_branch_sanitized" for b in result.dropped_blocks)


def test_only_sanitized_protected_not_raw_failed_attempt():
    result = pack_context(
        active_node=None, accepted=[_positive()], negative_evidence=[_sanitized_ne(), _raw_ne()],
        token_budget=30, protect_safety_notices=True,
    )
    # the sanitized safety notice is protected; the raw failed-attempt block is not
    assert any(b.reason == "failed_branch_sanitized" for b in result.blocks)
    assert all(b.reason != "failed_branch_degraded" for b in result.blocks)


def test_controller_threads_protect_safety_setting(monkeypatch):
    from app.config import Settings
    from app.retrieval import controller as controller_mod
    from app.runtime.repository import InMemoryRepository

    on = Settings(protect_safety_negative_evidence=True)
    monkeypatch.setattr(controller_mod, "get_settings", lambda: on)
    c = controller_mod.RetrievalController(InMemoryRepository())
    assert c._protect_safety_notices is True

    off = Settings(protect_safety_negative_evidence=False)
    monkeypatch.setattr(controller_mod, "get_settings", lambda: off)
    c2 = controller_mod.RetrievalController(InMemoryRepository())
    assert c2._protect_safety_notices is False
