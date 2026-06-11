"""Failure-aware negative evidence builder and packer tests."""
from __future__ import annotations

from app.retrieval.gate import GateConfig, GateOutcome, evaluate
from app.retrieval.negative_evidence import (
    SANITIZED_TEMPLATES,
    build_negative_evidence,
    safe_observability_content,
)
from app.retrieval.packer import pack_context
from app.runtime.models import (
    BranchStatus,
    MemoryItem,
    MemoryType,
    GateDecisionType,
    GateLayer,
    RiskFlags,
    Sensitivity,
    StateNode,
    StateNodeType,
)


def _mem(**kw) -> MemoryItem:
    base = dict(
        workspace_id="ws",
        memory_type=MemoryType.tool_evidence,
        content="Tried running tests with npm test, but it failed because npm was unavailable.",
        branch_status=BranchStatus.failed,
        source_state_node_id="node_failed",
        source_run_id="run_1",
        source_event_id="evt_1",
    )
    base.update(kw)
    return MemoryItem(**base)


def _outcome(mem: MemoryItem):
    return evaluate(
        mem,
        workspace_id="ws",
        relevance=0.8,
        state_match=0.5,
        config=GateConfig(enable_failure_learning=True),
    )


def test_raw_failed_attempt_renders_as_avoided_attempts_block():
    mem = _mem()
    evidence = build_negative_evidence([_outcome(mem)], {mem.memory_id: mem})

    result = pack_context(active_node=None, accepted=[], negative_evidence=evidence, token_budget=256)

    block = next(b for b in result.blocks if b.type == "avoided_attempts")
    assert block.source == "negative_evidence"
    assert block.memory_id == mem.memory_id
    assert block.reason == "failed_branch_degraded"
    assert "Tried running tests with npm test" in block.content
    assert "do NOT re-execute" in block.content
    assert "negative evidence only" in block.content


def test_sanitized_risk_notice_uses_template_without_original_command_markers():
    mem = _mem(
        content="FAILED: rm -rf /prod/customer-data --no-preserve-root MARKER_UNSAFE_COMMAND",
        risk_flags=RiskFlags(destructive_command=True, tool_sensitive=True),
    )
    evidence = build_negative_evidence([_outcome(mem)], {mem.memory_id: mem})

    assert len(evidence) == 1
    assert evidence[0].mode == "sanitized_risk_notice"
    assert evidence[0].risk_kind == "destructive"
    assert evidence[0].safe_text == SANITIZED_TEMPLATES["destructive"]
    result = pack_context(active_node=None, accepted=[], negative_evidence=evidence, token_budget=256)

    block = next(b for b in result.blocks if b.type == "avoided_attempts")
    assert block.content == SANITIZED_TEMPLATES["destructive"]
    assert "rm -rf" not in block.content
    assert "/prod/customer-data" not in block.content
    assert "MARKER_UNSAFE_COMMAND" not in block.content


def test_builder_sanitizes_unsafe_memory_even_if_outcome_is_degraded():
    mem = _mem(
        content="FAILED: git push --force origin main MARKER_TOOL_SENSITIVE",
        risk_flags=RiskFlags(tool_sensitive=True, production_env=True),
    )
    drifted_outcome = GateOutcome(
        memory=mem,
        layer=GateLayer.hard_policy,
        decision=GateDecisionType.degrade,
        reject_reason="failed_branch_degraded",
    )

    evidence = build_negative_evidence([drifted_outcome], {mem.memory_id: mem})

    assert len(evidence) == 1
    assert evidence[0].mode == "sanitized_risk_notice"
    assert evidence[0].risk_kind == "tool_sensitive"
    assert evidence[0].safe_text == SANITIZED_TEMPLATES["tool_sensitive"]
    assert "git push --force" not in evidence[0].safe_text
    assert "MARKER_TOOL_SENSITIVE" not in evidence[0].safe_text


def test_safe_observability_content_honors_explicit_secret_metadata_without_regex_match():
    mem = _mem(
        branch_status=BranchStatus.completed,
        sensitivity=Sensitivity.secret,
        content="customer credential is hunter2 MARKER_SECRET_METADATA",
    )

    rendered = safe_observability_content(mem, reject_reason="secret")

    assert rendered == SANITIZED_TEMPLATES["secret"]
    assert "hunter2" not in rendered
    assert "MARKER_SECRET_METADATA" not in rendered


def test_safe_observability_content_honors_contains_secret_flag_without_regex_match():
    mem = _mem(
        branch_status=BranchStatus.completed,
        risk_flags=RiskFlags(contains_secret=True),
        content="customer credential is hunter2 MARKER_FLAGGED_SECRET",
    )

    rendered = safe_observability_content(mem)

    assert rendered == SANITIZED_TEMPLATES["secret"]
    assert "hunter2" not in rendered
    assert "MARKER_FLAGGED_SECRET" not in rendered


def test_avoided_attempts_sort_after_project_memory_and_before_tool_evidence():
    project = MemoryItem(
        workspace_id="ws",
        memory_type=MemoryType.project,
        key="project.runtime",
        value="bun",
        content="This project uses Bun",
        branch_status=BranchStatus.completed,
    )
    tool = MemoryItem(
        workspace_id="ws",
        memory_type=MemoryType.tool_evidence,
        content="Use bun test for the current test suite.",
        branch_status=BranchStatus.completed,
    )
    failed = _mem()
    evidence = build_negative_evidence([_outcome(failed)], {failed.memory_id: failed})

    result = pack_context(active_node=None, accepted=[tool, project], negative_evidence=evidence, token_budget=256)

    ordered_types = [b.type for b in result.blocks]
    assert ordered_types == ["project_memory", "avoided_attempts", "tool_evidence"]


def test_negative_evidence_dedupes_by_source_state_node_and_applies_max_blocks():
    lower_priority = _mem(
        memory_type=MemoryType.working_state,
        content="Working-state failed note from same node.",
        source_state_node_id="node_shared",
    )
    preferred_tool = _mem(
        memory_type=MemoryType.tool_evidence,
        content="Tool evidence failed note from same node.",
        source_state_node_id="node_shared",
    )
    other = _mem(content="Other failed attempt.", source_state_node_id="node_other")
    overflow = _mem(content="Overflow failed attempt.", source_state_node_id="node_overflow")
    memories = [lower_priority, preferred_tool, other, overflow]

    evidence = build_negative_evidence(
        [_outcome(m) for m in memories],
        {m.memory_id: m for m in memories},
        max_blocks=2,
    )

    assert len(evidence) == 2
    assert {ev.source_state_node_id for ev in evidence} == {"node_shared", "node_other"}
    shared = next(ev for ev in evidence if ev.source_state_node_id == "node_shared")
    assert shared.source_memory_id == preferred_tool.memory_id
    assert shared.memory_type == MemoryType.tool_evidence


def test_negative_evidence_is_ordinary_and_dropped_before_protected_blocks_under_tiny_budget():
    active = StateNode(
        workspace_id="ws",
        run_id="run_1",
        node_type=StateNodeType.step,
        goal="fix tests",
    )
    failed = _mem(content="failed attempt with many details " * 20)
    evidence = build_negative_evidence([_outcome(failed)], {failed.memory_id: failed})

    result = pack_context(active_node=active, accepted=[], negative_evidence=evidence, token_budget=3)

    assert any(b.type == "active_state" for b in result.blocks)
    assert any(b.type == "avoided_attempts" for b in result.dropped_blocks)
    assert not any(b.type == "avoided_attempts" for b in result.blocks)


def test_negative_evidence_none_preserves_existing_packer_blocks():
    project = MemoryItem(
        workspace_id="ws",
        memory_type=MemoryType.project,
        key="project.runtime",
        value="bun",
        content="This project uses Bun",
        branch_status=BranchStatus.completed,
    )
    tool = MemoryItem(
        workspace_id="ws",
        memory_type=MemoryType.tool_evidence,
        content="Use bun test for the current test suite.",
        branch_status=BranchStatus.completed,
    )

    before = pack_context(active_node=None, accepted=[tool, project], token_budget=256)
    after = pack_context(active_node=None, accepted=[tool, project], negative_evidence=None, token_budget=256)

    assert [b.model_dump() for b in after.blocks] == [b.model_dump() for b in before.blocks]
    assert after.used == before.used
    assert after.pre_compaction_tokens == before.pre_compaction_tokens
