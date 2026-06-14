"""Deterministic lifecycle/reflection scheduler functions."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import hashlib
from typing import Any

from app.memory import summarizer
from app.memory.conflicts import detect_memory_conflicts
from app.memory.key_ontology import canonical_memory_key
from app.memory.lifecycle import transition_memory_status
from app.memory.retention import compute_retention_signals
from app.memory.secrets import is_secret_like_key
from app.retrieval.similarity import stable_embedding
from app.runtime.models import (
    EmbeddingStatus,
    MemoryItem,
    MemoryScope,
    MemoryStatus,
    MemoryType,
    RunStatus,
    Sensitivity,
)
from app.runtime.repository import Repository


_STALE_LIFECYCLE_PREFIX = "stale lifecycle transition"


async def score_memory(
    repo: Repository,
    *,
    workspace_id: str,
    now: datetime | None = None,
    scheduler_run_id: str | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    memories = await repo.list_memories(workspace_id=workspace_id)
    count = 0
    for memory in memories:
        signal = compute_retention_signals(memory, now=now)
        signal.reason["scheduler_run_id"] = scheduler_run_id
        await repo.upsert_retention_signal(signal)
        count += 1
    return {"workspace_id": workspace_id, "scored_count": count, "scheduler_run_id": scheduler_run_id}


async def decay_memory(
    repo: Repository,
    *,
    workspace_id: str,
    now: datetime | None = None,
    scheduler_run_id: str | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    memories = await repo.list_memories(workspace_id=workspace_id)
    decayed = 0
    for memory in memories:
        signal = compute_retention_signals(memory, now=now)
        if signal.retention_score < 0.25 and memory.status == MemoryStatus.active:
            updated, audit = transition_memory_status(
                memory,
                MemoryStatus.dormant,
                reason="retention_decay",
                actor="scheduler",
                scheduler_run_id=scheduler_run_id,
            )
            if await _try_transition(repo, updated, audit):
                decayed += 1
    return {"workspace_id": workspace_id, "decayed_count": decayed, "scheduler_run_id": scheduler_run_id}


async def archive_memory(
    repo: Repository,
    *,
    workspace_id: str,
    now: datetime | None = None,
    scheduler_run_id: str | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    memories = await repo.list_memories(workspace_id=workspace_id)
    archived = 0
    for memory in memories:
        if memory.status == MemoryStatus.pinned:
            continue
        signal = compute_retention_signals(memory, now=now)
        if signal.retention_score >= 0.25:
            continue
        target = MemoryStatus.archived if memory.status == MemoryStatus.dormant else None
        if memory.status == MemoryStatus.active:
            dormant, audit1 = transition_memory_status(
                memory,
                MemoryStatus.dormant,
                reason="retention_decay",
                actor="scheduler",
                scheduler_run_id=scheduler_run_id,
            )
            if not await _try_transition(repo, dormant, audit1):
                continue
            target = MemoryStatus.archived
            memory = dormant
        if target is None:
            continue
        updated, audit = transition_memory_status(
            memory,
            target,
            reason="retention_archive",
            actor="scheduler",
            scheduler_run_id=scheduler_run_id,
        )
        if await _try_transition(repo, updated, audit):
            archived += 1
    return {"workspace_id": workspace_id, "archived_count": archived, "scheduler_run_id": scheduler_run_id}


async def quarantine_memory(
    repo: Repository,
    *,
    workspace_id: str,
    now: datetime | None = None,
    scheduler_run_id: str | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    memories = await repo.list_memories(workspace_id=workspace_id)
    quarantined = 0
    for memory in memories:
        signal = compute_retention_signals(memory, now=now)
        if not signal.reason.get("high_risk") or memory.status != MemoryStatus.active:
            continue
        updated, audit = transition_memory_status(
            memory,
            MemoryStatus.quarantined,
            reason="retention_high_risk",
            actor="scheduler",
            scheduler_run_id=scheduler_run_id,
        )
        if await _try_transition(repo, updated, audit):
            quarantined += 1
    return {"workspace_id": workspace_id, "quarantined_count": quarantined, "scheduler_run_id": scheduler_run_id}


async def profile_refresh(
    repo: Repository,
    *,
    workspace_id: str,
    now: datetime | None = None,
    scheduler_run_id: str | None = None,
) -> dict[str, Any]:
    _ = now or datetime.now(timezone.utc)
    memories = await repo.list_memories(workspace_id=workspace_id)
    status_counts: dict[str, int] = {}
    for memory in memories:
        status_counts[memory.status.value] = status_counts.get(memory.status.value, 0) + 1
    return {
        "workspace_id": workspace_id,
        "memory_count": len(memories),
        "status_counts": status_counts,
        "scheduler_run_id": scheduler_run_id,
    }


async def conflict_scan(
    repo: Repository,
    *,
    workspace_id: str,
    now: datetime | None = None,
    scheduler_run_id: str | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    memories = await repo.list_memories(workspace_id=workspace_id)
    fresh = detect_memory_conflicts(workspace_id, memories, detected_by="maintenance_conflict_scan_v1")
    fresh_ids = {conflict.conflict_id for conflict in fresh}
    existing_open = [
        conflict
        for conflict in await _list_all_memory_conflicts(repo, workspace_id=workspace_id, status="open")
        if conflict.detected_by == "maintenance_conflict_scan_v1"
    ]
    existing_by_id = {conflict.conflict_id: conflict for conflict in existing_open}

    upserted = 0
    for conflict in fresh:
        existing = existing_by_id.get(conflict.conflict_id)
        if existing is not None:
            conflict = conflict.model_copy(update={"created_at": existing.created_at}, deep=True)
        await repo.upsert_memory_conflict(conflict)
        upserted += 1

    resolved = 0
    for conflict in existing_open:
        if conflict.conflict_id in fresh_ids:
            continue
        await repo.upsert_memory_conflict(
            conflict.model_copy(update={"status": "resolved", "resolved_at": now}, deep=True)
        )
        resolved += 1

    return {
        "workspace_id": workspace_id,
        "open_conflict_count": len(fresh),
        "created_or_updated_count": upserted,
        "stale_resolved_count": resolved,
        "scheduler_run_id": scheduler_run_id,
    }


async def dedup_memory(
    repo: Repository,
    *,
    workspace_id: str,
    now: datetime | None = None,
    scheduler_run_id: str | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    _ = now or datetime.now(timezone.utc)
    memories = await repo.list_memories(workspace_id=workspace_id)
    groups: dict[tuple[str, str, str], list[MemoryItem]] = defaultdict(list)
    skipped_sensitive = 0
    skipped_status = 0
    for memory in memories:
        if memory.status != MemoryStatus.active:
            skipped_status += 1
            continue
        if _is_dedup_sensitive(memory):
            skipped_sensitive += 1
            continue
        key = canonical_memory_key(memory.key) if memory.key is not None else None
        if key is None or memory.value is None:
            continue
        groups[(key, memory.scope.value, _norm_value(memory.value))].append(memory)

    candidate_pairs: list[dict[str, Any]] = []
    deduped = 0
    for (canonical_key, scope, value), group in sorted(groups.items()):
        if len(group) <= 1:
            continue
        ordered = sorted(group, key=_dedup_sort_key)
        survivor = ordered[0]
        for duplicate in ordered[1:]:
            pair = {
                "survivor_memory_id": survivor.memory_id,
                "duplicate_memory_id": duplicate.memory_id,
                "canonical_key": canonical_key,
                "scope": scope,
                "value_digest": _value_digest(value),
                "reason": "exact_same_canonical_key_scope_value",
            }
            candidate_pairs.append(pair)
            if dry_run:
                continue
            updated, audit = transition_memory_status(
                duplicate,
                MemoryStatus.superseded,
                reason="maintenance_dedup",
                actor="scheduler",
                scheduler_run_id=scheduler_run_id,
                metadata={"survivor_memory_id": survivor.memory_id, "canonical_key": canonical_key},
            )
            updated = updated.model_copy(update={"superseded_by": survivor.memory_id}, deep=True)
            if await _try_transition(repo, updated, audit):
                deduped += 1

    return {
        "workspace_id": workspace_id,
        "deduped_count": deduped,
        "candidate_pair_count": len(candidate_pairs),
        "candidate_pairs": candidate_pairs,
        "skipped_sensitive_count": skipped_sensitive,
        "skipped_status_count": skipped_status,
        "dry_run": dry_run,
        "scheduler_run_id": scheduler_run_id,
    }


async def reindex_memory(
    repo: Repository,
    *,
    workspace_id: str,
    now: datetime | None = None,
    scheduler_run_id: str | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    reindexed = 0
    skipped = 0
    for memory in await repo.list_memories(workspace_id=workspace_id):
        needs_embedding = memory.embedding_vector is None or memory.embedding_status in {
            EmbeddingStatus.pending,
            EmbeddingStatus.failed,
            EmbeddingStatus.stale,
        }
        if not needs_embedding or not memory.content:
            skipped += 1
            continue
        updated = memory.model_copy(
            update={
                "embedding_vector": stable_embedding(memory.content, 256),
                "embedding_status": EmbeddingStatus.embedded,
                "updated_at": now,
            },
            deep=True,
        )
        await repo.update_memory(updated)
        reindexed += 1
    return {
        "workspace_id": workspace_id,
        "reindexed_count": reindexed,
        "skipped_count": skipped,
        "provider": "deterministic_stable_embedding",
        "provider_backed": False,
        "scheduler_run_id": scheduler_run_id,
    }


async def summary_refresh(
    repo: Repository,
    *,
    workspace_id: str,
    now: datetime | None = None,
    scheduler_run_id: str | None = None,
) -> dict[str, Any]:
    created = await _refresh_completed_run_memory(
        repo,
        workspace_id=workspace_id,
        memory_type=MemoryType.episodic,
        key_prefix=summarizer.SUMMARY_KEY_PREFIX,
    )
    return {
        "workspace_id": workspace_id,
        "created_summary_count": created,
        "scheduler_run_id": scheduler_run_id,
    }


async def procedural_refresh(
    repo: Repository,
    *,
    workspace_id: str,
    now: datetime | None = None,
    scheduler_run_id: str | None = None,
) -> dict[str, Any]:
    created = await _refresh_completed_run_memory(
        repo,
        workspace_id=workspace_id,
        memory_type=MemoryType.procedural,
        key_prefix=summarizer.PROCEDURAL_KEY_PREFIX,
    )
    return {
        "workspace_id": workspace_id,
        "created_procedural_count": created,
        "warnings": [],
        "scheduler_run_id": scheduler_run_id,
    }


async def _try_transition(repo: Repository, memory, audit) -> bool:
    try:
        await repo.transition_memory_with_audit(memory, audit)
    except ValueError as exc:
        if str(exc).startswith(_STALE_LIFECYCLE_PREFIX):
            return False
        raise
    return True


def _norm_value(value: str | None) -> str:
    return (value or "").strip().lower()


def _value_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _dedup_sort_key(memory: MemoryItem) -> tuple[float, float, int, datetime, str]:
    return (-memory.trust_score, -memory.confidence, -memory.access_count, memory.created_at, memory.memory_id)


def _is_dedup_sensitive(memory: MemoryItem) -> bool:
    if memory.status in {MemoryStatus.pinned, MemoryStatus.quarantined, MemoryStatus.conflicted}:
        return True
    if memory.key is not None:
        if is_secret_like_key(memory.key):
            return True
        canonical_key = canonical_memory_key(memory.key)
        if canonical_key is not None and is_secret_like_key(canonical_key):
            return True
    if memory.sensitivity == Sensitivity.secret or memory.risk_flags.contains_secret:
        return True
    redaction_state = str(memory.lifecycle_metadata.get("redaction_state") or memory.lifecycle_metadata.get("redaction_status") or "")
    if redaction_state in {"redacted", "digest_only", "blocked"}:
        return True
    return any(is_secret_like_key(str(key)) for key in memory.lifecycle_metadata.keys())


async def _list_all_memory_conflicts(
    repo: Repository,
    *,
    workspace_id: str,
    status: str,
    page_size: int = 500,
) -> list:
    conflicts = []
    offset = 0
    while True:
        page = await repo.list_memory_conflicts(
            workspace_id=workspace_id,
            status=status,
            limit=page_size,
            offset=offset,
        )
        conflicts.extend(page)
        if len(page) < page_size:
            break
        offset += page_size
    return conflicts


async def _refresh_completed_run_memory(
    repo: Repository,
    *,
    workspace_id: str,
    memory_type: MemoryType,
    key_prefix: str,
) -> int:
    created = 0
    runs = await repo.list_runs(workspace_id=workspace_id)
    memories = await repo.list_memories(workspace_id=workspace_id)
    for run in runs:
        if run.status != RunStatus.completed:
            continue
        if await _run_has_no_events(repo, run.run_id):
            continue
        if _has_run_memory(memories, run_id=run.run_id, memory_type=memory_type, key_prefix=key_prefix):
            continue
        nodes = await repo.list_state_nodes(run.run_id)
        latest_memories = await repo.list_memories(workspace_id=workspace_id)
        result = summarizer.build_run_summary(run=run, nodes=nodes, memories=latest_memories)
        candidates = [result.episodic] if memory_type == MemoryType.episodic else []
        if memory_type == MemoryType.procedural and result.procedural is not None:
            candidates = [result.procedural]
        for memory in candidates:
            if not _has_run_memory(
                await repo.list_memories(workspace_id=workspace_id),
                run_id=run.run_id,
                memory_type=memory_type,
                key_prefix=key_prefix,
            ):
                await _supersede_active_memory_key(repo, workspace_id=workspace_id, memory=memory)
                await repo.add_memory(memory)
                created += 1
    return created


async def _run_has_no_events(repo: Repository, run_id: str) -> bool:
    return len(await repo.list_events(run_id)) == 0


def _has_run_memory(
    memories: list[MemoryItem], *, run_id: str, memory_type: MemoryType, key_prefix: str
) -> bool:
    valid_statuses = {MemoryStatus.active, MemoryStatus.pinned, MemoryStatus.conflicted, MemoryStatus.quarantined}
    expected_key = f"{key_prefix}.{run_id}"
    return any(
        memory.memory_type == memory_type
        and memory.source_run_id == run_id
        and memory.status in valid_statuses
        and memory.key == expected_key
        for memory in memories
    )


async def _supersede_active_memory_key(
    repo: Repository,
    *,
    workspace_id: str,
    memory: MemoryItem,
) -> None:
    if not memory.key:
        return
    for existing in await repo.list_memories(workspace_id=workspace_id):
        if existing.status != MemoryStatus.active or existing.key != memory.key:
            continue
        updated, audit = transition_memory_status(
            existing,
            MemoryStatus.superseded,
            reason="maintenance_run_memory_refresh",
            actor="scheduler",
            metadata={"replacement_memory_id": memory.memory_id, "key": memory.key},
        )
        updated = updated.model_copy(update={"superseded_by": memory.memory_id}, deep=True)
        await _try_transition(repo, updated, audit)


__all__ = [
    "archive_memory",
    "conflict_scan",
    "decay_memory",
    "dedup_memory",
    "profile_refresh",
    "procedural_refresh",
    "quarantine_memory",
    "reindex_memory",
    "score_memory",
    "summary_refresh",
]
