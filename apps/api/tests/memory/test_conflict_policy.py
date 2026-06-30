"""Pure-function tests for the deterministic 7-rule conflict policy (architecture §6.7).

``decide_conflict`` ranks same-key/scope active candidates by a fixed priority of
the seven conflict rules and emits an auditable provenance explanation chain:

    R4 user explicit correction
    R5 source authority (tool result / asserted fact > assistant inference)
    R6 completed branch > active > rolled_back > failed
    R2 explicit valid-time override
    -- legacy trust/recency tie-break (established behavior) --
    R3 genuine tie -> uncertain (conflicted), no winner

R1 (detection) and R7 (cross-workspace) are enforced upstream; this engine only
ever sees same-workspace same-canonical-key candidates.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.memory.conflict_policy import decide_conflict
from app.runtime.models import BranchStatus, MemoryItem, MemoryScope, MemoryStatus, MemoryType


def _mem(
    value,
    *,
    mid,
    key="project.runtime",
    trust=0.5,
    updated=None,
    memory_type=MemoryType.project,
    branch_status=BranchStatus.active,
    user_correction=False,
    valid_from=None,
):
    m = MemoryItem(
        memory_id=mid,
        workspace_id="ws",
        memory_type=memory_type,
        key=key,
        value=value,
        scope=MemoryScope.workspace,
        content=f"{key}={value}",
        trust_score=trust,
        branch_status=branch_status,
    )
    if updated is not None:
        m.updated_at = updated
    if user_correction:
        m.lifecycle_metadata["user_correction"] = True
    if valid_from is not None:
        m.lifecycle_metadata["valid_from"] = valid_from
    return m


# --------------------------------------------------------------------------- #
# R4: user explicit correction is the highest priority signal
# --------------------------------------------------------------------------- #
def test_rule4_user_correction_beats_higher_trust():
    correction = _mem("bun", mid="mem_corr", trust=0.3, user_correction=True)
    old = _mem("nodejs", mid="mem_old", trust=0.95)

    decision = decide_conflict([old, correction])

    assert decision.winner_id == "mem_corr"
    assert decision.superseded_ids == ("mem_old",)
    assert decision.conflicted_ids == ()
    assert decision.rule == "R4_user_correction"
    assert "R4" in decision.explanation


# --------------------------------------------------------------------------- #
# R5: tool result / asserted fact outranks assistant verbal inference
# --------------------------------------------------------------------------- #
def test_rule5_tool_evidence_beats_assistant_inference_even_with_higher_trust():
    tool = _mem("node", mid="mem_tool", trust=0.4, memory_type=MemoryType.tool_evidence)
    inferred = _mem("bun", mid="mem_infer", trust=0.95, memory_type=MemoryType.episodic)

    decision = decide_conflict([inferred, tool])

    assert decision.winner_id == "mem_tool"
    assert decision.rule == "R5_source_authority"


def test_rule5_tool_evidence_does_not_auto_beat_higher_trust_project_constraint():
    # Both are asserted sources (same authority tier); the higher-trust project
    # constraint must win on the legacy tie-break, never auto-overwritten by tool
    # evidence. Preserves the manual-review intent from conflicts.py.
    project = _mem("bun", mid="mem_proj", trust=0.9, memory_type=MemoryType.project)
    tool = _mem("node", mid="mem_tool", trust=0.4, memory_type=MemoryType.tool_evidence)

    decision = decide_conflict([project, tool])

    assert decision.winner_id == "mem_proj"
    assert decision.rule == "legacy_trust_recency"


# --------------------------------------------------------------------------- #
# R6: completed branch outranks failed branch
# --------------------------------------------------------------------------- #
def test_rule6_completed_branch_beats_failed_branch_even_with_higher_trust():
    completed = _mem("bun", mid="mem_done", trust=0.4, branch_status=BranchStatus.completed)
    failed = _mem("nodejs", mid="mem_fail", trust=0.95, branch_status=BranchStatus.failed)

    decision = decide_conflict([failed, completed])

    assert decision.winner_id == "mem_done"
    assert decision.rule == "R6_branch_status"


# --------------------------------------------------------------------------- #
# R2: an explicit valid-time fact overrides one without; newer valid_from wins
# --------------------------------------------------------------------------- #
def test_rule2_explicit_valid_time_overrides_fact_without_valid_time():
    dated = _mem("bun", mid="mem_dated", trust=0.4, valid_from="2026-06-01T00:00:00+00:00")
    undated = _mem("nodejs", mid="mem_undated", trust=0.95)

    decision = decide_conflict([undated, dated])

    assert decision.winner_id == "mem_dated"
    assert decision.rule == "R2_valid_time"


def test_rule2_newer_valid_from_wins_between_two_dated_facts():
    older = _mem("nodejs", mid="mem_older", trust=0.9, valid_from="2026-01-01T00:00:00+00:00")
    newer = _mem("bun", mid="mem_newer", trust=0.2, valid_from="2026-06-01T00:00:00+00:00")

    decision = decide_conflict([older, newer])

    assert decision.winner_id == "mem_newer"
    assert decision.rule == "R2_valid_time"


# --------------------------------------------------------------------------- #
# Legacy tie-break: when all higher rules tie, trust then recency still decide
# --------------------------------------------------------------------------- #
def test_legacy_trust_then_recency_when_higher_rules_tie():
    old_ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    new_ts = old_ts + timedelta(days=1)
    a = _mem("nodejs", mid="mem_a", trust=0.8, updated=old_ts)
    b = _mem("bun", mid="mem_b", trust=0.8, updated=new_ts)

    decision = decide_conflict([a, b])

    assert decision.winner_id == "mem_b"
    assert decision.rule == "legacy_trust_recency"
    assert decision.superseded_ids == ("mem_a",)


# --------------------------------------------------------------------------- #
# R3: genuine tie -> uncertain, no winner, both marked conflicted
# --------------------------------------------------------------------------- #
def test_rule3_genuine_tie_is_uncertain_no_winner():
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    a = _mem("nodejs", mid="mem_z", trust=0.8, updated=ts)
    b = _mem("bun", mid="mem_a", trust=0.8, updated=ts)

    decision = decide_conflict([a, b])

    assert decision.winner_id is None
    assert decision.rule == "R3_uncertain"
    assert set(decision.conflicted_ids) == {"mem_a", "mem_z"}
    # successor for any future supersede points at the smallest id deterministically
    assert decision.successor_id == "mem_a"


def test_rule3_tie_at_top_supersedes_strictly_weaker_loser_to_successor():
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    tie_a = _mem("nodejs", mid="mem_b", trust=0.8, updated=ts)
    tie_b = _mem("bun", mid="mem_a", trust=0.8, updated=ts)
    weak = _mem("deno", mid="mem_weak", trust=0.2, updated=ts)

    decision = decide_conflict([tie_a, tie_b, weak])

    assert decision.winner_id is None
    assert set(decision.conflicted_ids) == {"mem_a", "mem_b"}
    assert decision.superseded_ids == ("mem_weak",)
    assert decision.successor_id == "mem_a"


def test_deciding_rule_reflects_margin_over_runner_up_not_whole_field():
    """With several losers won at different rules, the reported deciding rule is
    the one where the winner beats its closest competitor (runner-up), not a
    misleading fallback. Winner beats runner-up C via R6 (completed > active)."""
    winner = _mem(
        "bun", mid="mem_w", trust=0.5,
        user_correction=True, branch_status=BranchStatus.completed,
    )
    runner_up = _mem("deno", mid="mem_c", trust=0.4, user_correction=True)  # ties R4, active
    other = _mem(  # higher trust + completed but beaten earlier at R4
        "nodejs", mid="mem_d", trust=0.95, branch_status=BranchStatus.completed,
    )

    decision = decide_conflict([runner_up, other, winner])

    assert decision.winner_id == "mem_w"
    assert decision.rule == "R6_branch_status"


# --------------------------------------------------------------------------- #
# Provenance explanation chain is redacted and deterministic
# --------------------------------------------------------------------------- #
def test_explanation_redacts_secret_like_values_and_is_deterministic():
    winner = _mem("token=sk-1234567890abcdef1234", mid="mem_secret", trust=0.9)
    loser = _mem("nodejs", mid="mem_plain", trust=0.4)

    d1 = decide_conflict([winner, loser])
    d2 = decide_conflict([loser, winner])

    assert "sk-1234567890abcdef1234" not in d1.explanation
    # deterministic regardless of input order
    assert d1.explanation == d2.explanation
    assert d1.winner_id == "mem_secret"
