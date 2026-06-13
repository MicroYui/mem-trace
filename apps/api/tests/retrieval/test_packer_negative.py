"""Failure-aware negative evidence builder and packer tests."""
from __future__ import annotations

from app.retrieval.gate import GateConfig, GateOutcome, evaluate
from app.retrieval.negative_evidence import (
    SANITIZED_TEMPLATES,
    build_negative_evidence,
    safe_observability_content,
    to_retained_negative_evidence,
)
from app.retrieval.packer import _truncate_text, estimate_tokens, pack_context
from app.runtime.models import (
    BranchStatus,
    ContextBlock,
    MemoryItem,
    MemoryType,
    GateDecisionType,
    GateLayer,
    NegativeEvidence,
    Provenance,
    RetainedFact,
    RiskFlags,
    Sensitivity,
    StateNode,
    StateNodeStatus,
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


def test_estimate_tokens_counts_stopwords_and_cjk_characters():
    assert estimate_tokens("the and of to in") >= 5
    assert estimate_tokens("这是一个没有空格的中文句子") >= 8


def test_truncate_text_handles_cjk_without_exceeding_budget():
    text = "这是一个没有空格的中文句子用于测试截断行为"

    truncated = _truncate_text(text, 6)

    assert estimate_tokens(truncated) <= 6
    assert truncated
    assert len(truncated) < len(text)


def test_truncate_text_handles_mixed_ascii_and_cjk_without_exceeding_budget():
    text = "Investigate 用户认证流程 failure fallback 包含中文 without dropping budget safety"

    truncated = _truncate_text(text, 10)

    assert estimate_tokens(truncated) <= 10
    assert truncated
    assert len(truncated) < len(text)


def test_truncate_text_handles_small_ascii_budget_without_exceeding_budget():
    text = "alpha beta gamma delta epsilon zeta eta theta"

    truncated = _truncate_text(text, 3)

    assert estimate_tokens(truncated) <= 3
    assert truncated
    assert len(truncated) < len(text)


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


def test_negative_evidence_retained_when_avoided_attempt_block_dropped_by_compaction():
    active = StateNode(
        workspace_id="ws",
        run_id="run_1",
        node_type=StateNodeType.step,
        goal="fix the test command",
    )
    failed = _mem(content="npm test failed with lockfile mismatch; prefer bun test next time")
    evidence = build_negative_evidence([_outcome(failed)], {failed.memory_id: failed})
    positive_fact = MemoryItem(
        memory_id="mem_database",
        workspace_id="ws",
        memory_type=MemoryType.project,
        key="project.database",
        value="postgres",
        content="project.database=postgres " * 10,
        branch_status=BranchStatus.completed,
    )

    result = pack_context(
        active_node=active,
        accepted=[positive_fact],
        negative_evidence=evidence,
        token_budget=14,
    )

    assert any(block.type == "avoided_attempts" for block in result.dropped_blocks)
    assert not any(block.type == "avoided_attempts" for block in result.blocks)
    assert result.pending_compaction_logs
    retained = result.pending_compaction_logs[0].retained_negative_evidence
    assert len(retained) == 1
    assert retained[0].source_memory_id == failed.memory_id
    assert retained[0].source_state_node_id == failed.source_state_node_id
    assert retained[0].safe_text == evidence[0].safe_text
    assert retained[0].reason == "failed_branch_degraded"
    assert all(isinstance(fact, RetainedFact) for fact in result.retained_constraints)
    assert result.retained_constraints
    assert result.retained_constraints[0].key == "project.database"


def test_retained_negative_evidence_does_not_force_prompt_injection():
    active = StateNode(
        workspace_id="ws",
        run_id="run_1",
        node_type=StateNodeType.step,
        goal="fix tests",
    )
    evidence = [
        NegativeEvidence(
            source_memory_id=None,
            source_state_node_id="node_failed_without_memory",
            memory_type=MemoryType.tool_evidence,
            branch_status=BranchStatus.failed,
            mode="raw_failed_attempt",
            reason="failed_branch_degraded",
            safe_text="npm test failed repeatedly because npm is unavailable in this workspace",
            provenance=None,
        )
    ]

    result = pack_context(active_node=active, accepted=[], negative_evidence=evidence, token_budget=8)

    assert not [block for block in result.blocks if block.type == "avoided_attempts"]
    assert [block for block in result.dropped_blocks if block.type == "avoided_attempts"]
    assert result.pending_compaction_logs
    retained = result.pending_compaction_logs[0].retained_negative_evidence
    assert len(retained) == 1
    assert retained[0].source_memory_id is None
    assert retained[0].source_state_node_id == "node_failed_without_memory"
    assert retained[0].provenance is not None
    assert retained[0].provenance.state_node_id == "node_failed_without_memory"


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


def test_negative_retained_conversion_preserves_safe_failed_attempt_only():
    evidence = NegativeEvidence(
        source_memory_id="mem_failed",
        source_state_node_id="node_failed",
        memory_type=MemoryType.tool_evidence,
        branch_status=BranchStatus.failed,
        mode="raw_failed_attempt",
        risk_kind=None,
        reason="failed_branch_degraded",
        safe_text="npm install failed with lockfile mismatch",
        provenance=Provenance(run_id="run_1", step_id="step_1", event_id="evt_1", state_node_id="node_failed"),
    )

    retained = to_retained_negative_evidence(evidence)
    dumped = retained.model_dump(mode="json")

    assert retained.safe_text == "npm install failed with lockfile mismatch"
    assert retained.source_memory_id == "mem_failed"
    assert retained.source_state_node_id == "node_failed"
    assert retained.mode == "raw_failed_attempt"
    assert retained.reason == "failed_branch_degraded"
    assert retained.provenance == evidence.provenance
    assert retained.created_from_block_type == "avoided_attempts"
    assert "content" not in dumped
    assert "raw_content" not in dumped
    assert "memory_content" not in dumped


def test_negative_retained_conversion_uses_sanitized_text_for_risky_attempt():
    evidence = NegativeEvidence(
        source_memory_id="mem_risky",
        source_state_node_id="node_risky",
        memory_type=MemoryType.tool_evidence,
        branch_status=BranchStatus.failed,
        mode="sanitized_risk_notice",
        risk_kind="destructive",
        reason="failed_branch_sanitized",
        safe_text=SANITIZED_TEMPLATES["destructive"],
        provenance=Provenance(run_id="run_1", event_id="evt_unsafe", state_node_id="node_risky"),
    )

    retained = to_retained_negative_evidence(evidence)
    payload = str(retained.model_dump(mode="json"))

    assert retained.risk_kind == "destructive"
    assert retained.safe_text == SANITIZED_TEMPLATES["destructive"]
    for marker in ("rm -rf", "/prod", "sk-", "password", "Authorization"):
        assert marker not in payload


def test_positive_redaction_covers_state_path_prelude_and_project_constraints_without_reordering():
    active = StateNode(
        workspace_id="ws",
        run_id="run_1",
        node_type=StateNodeType.step,
        goal="Call API with sk-1234567890abcdef",
    )
    completed = StateNode(
        workspace_id="ws",
        run_id="run_1",
        node_type=StateNodeType.step,
        status=StateNodeStatus.completed,
        summary="Recovered database password is hunter2",
    )
    prelude = ContextBlock(
        type="procedural",
        content="Set api_key=abc123 before running the helper",
        source="test_prelude",
        tokens=estimate_tokens("Set api_key=abc123 before running the helper"),
    )
    project_runtime = MemoryItem(
        workspace_id="ws",
        memory_type=MemoryType.project,
        key="project.runtime",
        value="bun",
        content="This project uses Bun",
        branch_status=BranchStatus.completed,
    )
    project_excluded_secret = MemoryItem(
        workspace_id="ws",
        memory_type=MemoryType.project,
        key="project.runtime.excluded",
        value="password=hunter2",
        content="Do not use the leaked password=hunter2",
        branch_status=BranchStatus.completed,
    )

    result = pack_context(
        active_node=active,
        active_path=[completed, active],
        prelude_blocks=[prelude],
        accepted=[project_runtime, project_excluded_secret],
        token_budget=256,
    )

    assert [block.type for block in result.blocks] == ["active_state", "active_path", "project_memory", "procedural"]
    rendered = "\n".join(block.content for block in result.blocks)
    assert "sk-1234567890abcdef" not in rendered
    assert "hunter2" not in rendered
    assert "api_key=abc123" not in rendered
    assert rendered.count("[REDACTED]") >= 4
    assert all(block.tokens == estimate_tokens(block.content) for block in result.blocks)
    assert result.used == sum(block.tokens for block in result.blocks)


def test_compacted_retained_facts_are_redacted_and_stay_within_budget():
    fact = RetainedFact(key="profile.database_password", value="password=hunter2", source_memory_id="mem_secret")
    memory = MemoryItem(
        memory_id="mem_secret",
        workspace_id="ws",
        memory_type=MemoryType.profile,
        key=fact.key,
        value=fact.value,
        content="profile database credential details " * 20,
        branch_status=BranchStatus.completed,
    )
    active = StateNode(workspace_id="ws", run_id="run_1", node_type=StateNodeType.step, goal="fix tests")

    result = pack_context(active_node=active, accepted=[memory], token_budget=12)

    rendered = "\n".join(block.content for block in result.blocks)
    assert "hunter2" not in rendered
    assert "password=hunter2" not in rendered
    assert any(block.type == "compacted_constraints" and "[REDACTED]" in block.content for block in result.blocks)
    retained_payload = repr([fact.model_dump() for fact in result.retained_constraints])
    pending_payload = repr([
        [fact.model_dump() for fact in log.retained_facts]
        for log in result.pending_compaction_logs
    ])
    assert "hunter2" not in retained_payload
    assert "password=hunter2" not in retained_payload
    assert "hunter2" not in pending_payload
    assert "password=hunter2" not in pending_payload
    assert "[REDACTED]" in retained_payload
    assert "[REDACTED]" in pending_payload
    assert any(block.memory_id == memory.memory_id for block in result.dropped_blocks)
    assert result.used <= 12
    assert all(block.tokens == estimate_tokens(block.content) for block in result.blocks)


def test_compacted_retained_facts_redact_secret_like_keys():
    memory = MemoryItem(
        memory_id="mem_secret_key",
        workspace_id="ws",
        memory_type=MemoryType.project,
        key="project.api_key=sk-1234567890abcdef",
        value="bun",
        content="secret-like key should not leak " * 20,
        branch_status=BranchStatus.completed,
    )
    active = StateNode(workspace_id="ws", run_id="run_1", node_type=StateNodeType.step, goal="fix tests")

    result = pack_context(active_node=active, accepted=[memory], token_budget=20)

    rendered = repr([block.model_dump() for block in result.blocks])
    retained_payload = repr([fact.model_dump() for fact in result.retained_constraints])
    pending_payload = repr([
        [fact.model_dump() for fact in log.retained_facts]
        for log in result.pending_compaction_logs
    ])
    assert "sk-1234567890abcdef" not in rendered
    assert "sk-1234567890abcdef" not in retained_payload
    assert "sk-1234567890abcdef" not in pending_payload
    assert "[REDACTED]" in rendered
    assert "[REDACTED]" in retained_payload
    assert "[REDACTED]" in pending_payload
