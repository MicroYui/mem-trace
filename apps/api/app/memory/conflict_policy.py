"""Deterministic 7-rule memory conflict resolution policy (architecture §6.7).

Pure, no-LLM. Given the active candidates that conflict on a single-valued key,
decide a winner / losers / uncertain set by a fixed priority ordering of the
seven conflict rules, and emit an auditable provenance explanation chain.

Rule priority (architecture §6.7), highest-first:

    R4  user explicit correction        -- ``lifecycle_metadata["user_correction"]``
    R5  source authority: tool result / asserted fact > assistant verbal inference
    R6  completed branch > active > rolled_back > failed
    R2  explicit valid-time: a fact carrying an explicit ``valid_from`` overrides
        one without; among those carrying it, the newer ``valid_from`` wins
    --- legacy tie-break (the established trust/recency behavior) ---
        trust_score, then ``updated_at`` recency
    R3  if nothing above discriminates (a genuine tie) the differing values are
        *uncertain*: there is no winner and all tied memories are marked
        ``conflicted`` pending manual review.

Rules R1 (same subject+predicate, different object -> candidate) and R7
(cross-workspace facts are never compared) are enforced upstream by
``detect_memory_conflicts`` / the dedup identity, which only ever passes
same-workspace, same-canonical-key candidates into this engine.

The engine never mutates the candidates; it returns a :class:`ConflictDecision`
the caller applies. This keeps the policy storage-agnostic and unit-testable.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from app.memory.secrets import redact
from app.runtime.models import BranchStatus, MemoryItem, MemoryType, Sensitivity

# Assistant-inferred memory types rank below asserted facts for rule R5.
_INFERRED_TYPES = {MemoryType.working_state, MemoryType.episodic}

# Completed branches outrank failed/rolled-back ones for rule R6.
_BRANCH_RANK = {
    BranchStatus.completed: 3,
    BranchStatus.active: 2,
    BranchStatus.rolled_back: 1,
    BranchStatus.failed: 0,
}

_MIN_TS = datetime.min.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class ConflictDecision:
    """Outcome of adjudicating a single-valued conflict group.

    - ``winner_id``: the memory that survives active, or ``None`` when the group
      is uncertain (rule R3) and no value may silently win.
    - ``superseded_ids``: losers to retire to ``superseded`` (pointed at
      ``winner_id`` when there is a winner, else at ``successor_id``).
    - ``conflicted_ids``: tied memories to mark ``conflicted`` (only when there
      is no winner).
    - ``successor_id``: deterministic ``superseded_by`` target for losers in the
      uncertain branch (smallest tied memory id).
    - ``rule``: the highest-priority rule that decided the outcome.
    - ``explanation``: a redacted, deterministic provenance chain for audit /
      owner-gated manual review.
    """

    winner_id: Optional[str]
    superseded_ids: tuple[str, ...]
    conflicted_ids: tuple[str, ...]
    successor_id: Optional[str]
    rule: str
    explanation: str


def _is_user_correction(memory: MemoryItem) -> bool:
    return bool((memory.lifecycle_metadata or {}).get("user_correction"))


def _authority_tier(memory: MemoryItem) -> int:
    """R5: asserted facts (incl. tool evidence) outrank assistant inference."""
    return 0 if memory.memory_type in _INFERRED_TYPES else 1


def _branch_rank(memory: MemoryItem) -> int:
    return _BRANCH_RANK.get(memory.branch_status, _BRANCH_RANK[BranchStatus.active])


def _valid_from(memory: MemoryItem) -> Optional[datetime]:
    raw: Any = (memory.lifecycle_metadata or {}).get("valid_from")
    if raw is None:
        return None
    if isinstance(raw, datetime):
        dt = raw
    elif isinstance(raw, str):
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# The rule labels, ordered highest-priority first, paired with the per-memory
# signal extractor whose value (larger == stronger) encodes that rule.
_RULES: tuple[tuple[str, Any], ...] = (
    ("R4_user_correction", lambda m: 1 if _is_user_correction(m) else 0),
    ("R5_source_authority", _authority_tier),
    ("R6_branch_status", _branch_rank),
    ("R2_valid_time", lambda m: (1 if _valid_from(m) is not None else 0, _valid_from(m) or _MIN_TS)),
    ("legacy_trust_recency", lambda m: (m.trust_score, m.updated_at)),
)


def _signal(memory: MemoryItem) -> tuple:
    return tuple(extract(memory) for _label, extract in _RULES)


def _safe_value(memory: MemoryItem) -> str:
    if memory.sensitivity == Sensitivity.secret or memory.risk_flags.contains_secret:
        return "[REDACTED]"
    return redact(memory.value)


def _deciding_rule(winner: MemoryItem, others: list[MemoryItem]) -> str:
    """The highest-priority rule where ``winner`` beats its closest competitor.

    The runner-up (strongest loser by full signal) sets the decisive margin: the
    first rule on which the winner's signal exceeds the runner-up's is what
    actually secured the win, which is the meaningful audit label even when other
    weaker losers were beaten on different rules.
    """
    if not others:
        return "legacy_trust_recency"
    runner_up = max(others, key=_signal)
    for label, extract in _RULES:
        if extract(winner) > extract(runner_up):
            return label
    return "legacy_trust_recency"


def decide_conflict(candidates: list[MemoryItem]) -> ConflictDecision:
    """Adjudicate a single-valued conflict group deterministically.

    ``candidates`` must all share the same canonical key/scope/workspace and have
    differing values (the caller guarantees this). Order-independent.
    """
    if not candidates:
        return ConflictDecision(None, (), (), None, "R3_uncertain", "no candidates")
    if len(candidates) == 1:
        only = candidates[0]
        return ConflictDecision(
            winner_id=only.memory_id,
            superseded_ids=(),
            conflicted_ids=(),
            successor_id=None,
            rule="legacy_trust_recency",
            explanation=f"single candidate {only.memory_id}={_safe_value(only)}",
        )

    top = max(_signal(m) for m in candidates)
    tied = [m for m in candidates if _signal(m) == top]

    if len(tied) == 1:
        winner = tied[0]
        losers = [m for m in candidates if m.memory_id != winner.memory_id]
        rule = _deciding_rule(winner, losers)
        superseded_ids = tuple(sorted(m.memory_id for m in losers))
        explanation = (
            f"Conflict on '{winner.key}' resolved by {rule}: winner {winner.memory_id}="
            f"{_safe_value(winner)} supersedes "
            + ", ".join(f"{m.memory_id}={_safe_value(m)}" for m in sorted(losers, key=lambda x: x.memory_id))
            + ". Provenance preserved (superseded, not deleted)."
        )
        return ConflictDecision(
            winner_id=winner.memory_id,
            superseded_ids=superseded_ids,
            conflicted_ids=(),
            successor_id=None,
            rule=rule,
            explanation=explanation,
        )

    # R3 uncertain: the top is a genuine tie. No value may silently win; the tied
    # memories are marked conflicted, strictly-weaker losers are superseded to the
    # smallest tied id so provenance still has a deterministic anchor.
    tied_ids = {m.memory_id for m in tied}
    successor_id = min(tied_ids)
    losers = [m for m in candidates if m.memory_id not in tied_ids]
    conflicted_ids = tuple(sorted(tied_ids))
    superseded_ids = tuple(sorted(m.memory_id for m in losers))
    explanation = (
        f"Conflict on '{tied[0].key}' is uncertain (R3): no discriminating signal between "
        + ", ".join(f"{m.memory_id}={_safe_value(m)}" for m in sorted(tied, key=lambda x: x.memory_id))
        + "; marked conflicted pending manual review."
    )
    return ConflictDecision(
        winner_id=None,
        superseded_ids=superseded_ids,
        conflicted_ids=conflicted_ids,
        successor_id=successor_id,
        rule="R3_uncertain",
        explanation=explanation,
    )


__all__ = ["ConflictDecision", "decide_conflict"]
