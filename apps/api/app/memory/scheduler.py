"""Deterministic lifecycle/reflection scheduler functions."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.memory.lifecycle import transition_memory_status
from app.memory.retention import compute_retention_signals
from app.runtime.models import MemoryStatus
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


async def _try_transition(repo: Repository, memory, audit) -> bool:
    try:
        await repo.transition_memory_with_audit(memory, audit)
    except ValueError as exc:
        if str(exc).startswith(_STALE_LIFECYCLE_PREFIX):
            return False
        raise
    return True


__all__ = ["archive_memory", "decay_memory", "profile_refresh", "quarantine_memory", "score_memory"]
