"""Workspace memory conflict detection for P4-C."""
from __future__ import annotations

from collections import defaultdict
import hashlib

from app.memory.key_ontology import canonical_memory_key, is_single_valued_key, same_memory_key_identity
from app.memory.secrets import redact
from app.runtime.models import MemoryConflictRecord, MemoryItem, MemoryStatus, MemoryType, Sensitivity


def _norm(value: str | None) -> str:
    return (value or "").strip().lower()


def _group_key(memory: MemoryItem) -> tuple[str, str] | None:
    if memory.key is None or not is_single_valued_key(memory.key):
        return None
    canonical = canonical_memory_key(memory.key)
    if canonical is None:
        return None
    return (canonical, memory.scope.value)


def _explanation(memories: list[MemoryItem]) -> str:
    values = ", ".join(f"{m.memory_id}:{_safe_value(m)}" for m in memories)
    if any(m.memory_type == MemoryType.tool_evidence for m in memories):
        return (
            f"Single-valued memory key has conflicting values ({values}); "
            "tool evidence can explain the conflict but requires manual review "
            "before overwriting higher-trust project constraints."
        )
    return f"Single-valued memory key has conflicting active values ({values}); manual review required."


def _safe_value(memory: MemoryItem) -> str:
    if memory.sensitivity == Sensitivity.secret or memory.risk_flags.contains_secret:
        return "[REDACTED]"
    return redact(memory.value)


def detect_memory_conflicts(
    workspace_id: str,
    memories: list[MemoryItem],
    *,
    detected_by: str = "conflict_scan_v1",
) -> list[MemoryConflictRecord]:
    """Detect active same-key/scope single-valued memories with different values."""

    grouped: dict[tuple[str, str], list[MemoryItem]] = defaultdict(list)
    for memory in memories:
        if memory.workspace_id != workspace_id or memory.status not in {MemoryStatus.active, MemoryStatus.conflicted}:
            continue
        key = _group_key(memory)
        if key is None:
            continue
        grouped[key].append(memory)

    conflicts: list[MemoryConflictRecord] = []
    for (canonical_key, _scope), group in grouped.items():
        if len({_norm(memory.value) for memory in group}) <= 1:
            continue
        # Guard alias semantics through ontology helper in addition to the
        # canonical grouping above, so future alias changes remain single-sourced.
        anchor = group[0]
        members = [m for m in group if same_memory_key_identity(anchor.key, m.key)]
        if len({_norm(memory.value) for memory in members}) <= 1:
            continue
        memory_ids = sorted(memory.memory_id for memory in members)
        digest = hashlib.blake2b(
            "|".join([workspace_id, canonical_key, *memory_ids]).encode("utf-8"),
            digest_size=8,
        ).hexdigest()
        conflicts.append(
            MemoryConflictRecord(
                conflict_id=f"mconf_{digest}",
                workspace_id=workspace_id,
                subject_key=canonical_key,
                memory_ids=memory_ids,
                status="open",
                detected_by=detected_by,
                explanation=_explanation(sorted(members, key=lambda m: m.memory_id)),
            )
        )
    conflicts.sort(key=lambda c: (c.subject_key, c.conflict_id))
    return conflicts


__all__ = ["detect_memory_conflicts"]
