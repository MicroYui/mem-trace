"""Dedup / merge + simple conflict resolver (P2, mvp.md §2.3).

Pure, deterministic, no-LLM. Given an incoming memory and the existing *active*
memories that share its dedup identity ``(workspace_id, key, scope)``, decide how
they reconcile:

- **Same value** (normalized): dedup/merge. One existing memory is kept active as
  the representative; the incoming write is folded into it (provenance via
  ``source_event_ids``; scores raised to the max). Any other same-value duplicates
  are retired to ``superseded`` pointing at the survivor. No new memory is added.

- **Different value, single-valued key** (e.g. ``project.runtime`` can hold only
  one runtime): conflict. The winner is chosen by ``trust_score`` then recency
  (``updated_at``); losers become ``superseded`` with ``superseded_by`` set to the
  winner. A genuine tie (equal trust *and* equal timestamp) marks the tied
  memories ``conflicted`` so the gate degrades them instead of silently dropping.

- **Different value, multi-valued key** (e.g. ``project.runtime.excluded`` is a
  set): not a conflict; distinct values coexist.

The resolver never rewrites ``content``, so embeddings never go stale — only
status / score / provenance fields change. The runtime facade persists the
result; this module stays storage-agnostic and pure.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from app.memory.conflict_policy import decide_conflict
from app.memory.key_ontology import canonical_memory_key, is_single_valued_key
from app.runtime.models import MemoryItem, MemoryStatus


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _norm(value: Optional[str]) -> str:
    return (value or "").strip().lower()


@dataclass
class ResolveResult:
    """Outcome of reconciling an incoming memory against existing actives.

    - ``add``: the incoming memory to persist as a NEW row, or ``None`` when it was
      merged into an existing memory (deduped).
    - ``updates``: existing memories whose fields changed and must be re-persisted.
    """

    add: Optional[MemoryItem]
    updates: list[MemoryItem] = field(default_factory=list)


def _collect_sources(memories: list[MemoryItem]) -> list[str]:
    """Union of provenance event ids across memories, order-preserving."""
    out: list[str] = []
    for m in memories:
        for eid in list(m.source_event_ids or []) + ([m.source_event_id] if m.source_event_id else []):
            if eid and eid not in out:
                out.append(eid)
    return out


def _strongest(memories: list[MemoryItem]) -> MemoryItem:
    """Pick the representative: highest trust/importance/confidence, then the
    earliest created (stable lineage), then smallest id (deterministic)."""
    return max(
        memories,
        key=lambda m: (
            m.trust_score,
            m.importance,
            m.confidence,
            -m.created_at.timestamp(),
            _neg_id(m.memory_id),
        ),
    )


def _promote_to_canonical_key(memory: MemoryItem, key: str | None) -> None:
    canonical_key = canonical_memory_key(key)
    if canonical_key is not None and memory.key != canonical_key:
        memory.key = canonical_key
        memory.summary = f"{canonical_key}={memory.value}" if memory.value is not None else memory.summary


def _neg_id(memory_id: str) -> tuple[int, ...]:
    # Invert codepoints so that `max` prefers the lexicographically smaller id.
    return tuple(-ord(c) for c in memory_id)


def resolve(incoming: MemoryItem, existing_active: list[MemoryItem]) -> ResolveResult:
    """Reconcile ``incoming`` against same-identity active memories.

    ``existing_active`` must already be filtered to memories sharing
    ``incoming``'s ``(workspace_id, key, scope)`` and having ``status == active``,
    excluding ``incoming`` itself.
    """
    updates: dict[str, MemoryItem] = {}
    norm_in = _norm(incoming.value)
    same = [m for m in existing_active if _norm(m.value) == norm_in]
    diff = [m for m in existing_active if _norm(m.value) != norm_in]

    # ---- dedup / merge: incoming duplicates an existing value ---------------- #
    if same:
        primary = _strongest(same)
        group = same + [incoming]
        primary.source_event_ids = _collect_sources(group)
        primary.confidence = max(m.confidence for m in group)
        primary.importance = max(m.importance for m in group)
        primary.trust_score = max(m.trust_score for m in group)
        primary.value_score = max(m.value_score for m in group)
        _promote_to_canonical_key(primary, incoming.key)
        primary.updated_at = _now()
        updates[primary.memory_id] = primary
        for m in same:
            if m.memory_id != primary.memory_id:
                m.status = MemoryStatus.superseded
                m.superseded_by = primary.memory_id
                m.updated_at = _now()
                updates[m.memory_id] = m
        add: Optional[MemoryItem] = None
    else:
        primary = incoming
        add = incoming

    # ---- conflict: different value for a single-valued key ------------------- #
    if is_single_valued_key(incoming.key) and diff:
        candidates = [primary] + diff
        for m in candidates:
            _promote_to_canonical_key(m, incoming.key)
        decision = decide_conflict(candidates)
        if decision.winner_id is not None:
            for m in candidates:
                if m.memory_id != decision.winner_id:
                    m.status = MemoryStatus.superseded
                    m.superseded_by = decision.winner_id
                    m.updated_at = _now()
        else:
            for m in candidates:
                if m.memory_id in decision.conflicted_ids:
                    m.status = MemoryStatus.conflicted
                    m.updated_at = _now()
                elif m.memory_id in decision.superseded_ids:
                    m.status = MemoryStatus.superseded
                    m.superseded_by = decision.successor_id
                    m.updated_at = _now()
        # Record every mutated EXISTING memory (incoming is carried by `add`).
        for m in candidates:
            if m is not incoming:
                updates[m.memory_id] = m

    return ResolveResult(add=add, updates=list(updates.values()))


__all__ = ["ResolveResult", "resolve"]
