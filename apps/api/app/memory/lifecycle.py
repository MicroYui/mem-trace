"""Memory lifecycle transition policy and audit helpers."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.runtime.models import MemoryItem, MemoryLifecycleAuditRecord, MemoryStatus


_MAINLINE = {
    MemoryStatus.active: {MemoryStatus.dormant},
    MemoryStatus.dormant: {MemoryStatus.archived},
    MemoryStatus.archived: {MemoryStatus.deleted},
    # Conflict adjudication (choose_winner) retires conflicted losers to
    # superseded; this is the legitimate exit for a conflicted memory.
    MemoryStatus.conflicted: {MemoryStatus.superseded},
}
_SAFE_UNPIN_STATUSES = {MemoryStatus.active, MemoryStatus.dormant, MemoryStatus.archived}
_PINNABLE_STATUSES = {MemoryStatus.active, MemoryStatus.dormant, MemoryStatus.archived}
_ACTIVE_SIDE_TRANSITIONS = {MemoryStatus.conflicted, MemoryStatus.quarantined, MemoryStatus.superseded}


def transition_memory_status(
    memory: MemoryItem,
    to_status: MemoryStatus,
    *,
    reason: str,
    actor: str,
    scheduler_run_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> tuple[MemoryItem, MemoryLifecycleAuditRecord]:
    """Validate a lifecycle transition and return updated memory plus audit.

    The input memory is never mutated. Manual unpin requests use
    ``to_status=MemoryStatus.active`` and restore the safe previous status from
    pinned metadata when available.
    """
    from_status = memory.status
    requested_status = MemoryStatus(to_status)
    audit_metadata = dict(metadata or {})

    if actor == "scheduler" and from_status == MemoryStatus.pinned and requested_status == MemoryStatus.archived:
        raise ValueError("pinned memory cannot be archived by scheduler")

    if requested_status == MemoryStatus.pinned:
        if from_status not in _PINNABLE_STATUSES:
            raise ValueError(f"invalid lifecycle transition: {from_status.value} -> pinned")
        audit_metadata.setdefault("previous_status", from_status.value)
        updated = memory.model_copy(
            update={
                "status": MemoryStatus.pinned,
                "lifecycle_metadata": _merged_memory_metadata(memory, {"previous_status": from_status.value}),
                "updated_at": _now(),
            },
            deep=True,
        )
        return updated, _audit(memory, from_status, MemoryStatus.pinned, reason, actor, scheduler_run_id, audit_metadata)

    if from_status == MemoryStatus.pinned and requested_status == MemoryStatus.active:
        previous_raw = _memory_metadata(memory).get("previous_status")
        previous = _safe_status(previous_raw)
        restored = previous if previous in _SAFE_UNPIN_STATUSES else MemoryStatus.active
        audit_metadata["restored_previous_status"] = restored.value
        updated = memory.model_copy(update={"status": restored, "updated_at": _now()}, deep=True)
        return updated, _audit(memory, from_status, restored, reason, actor, scheduler_run_id, audit_metadata)

    allowed = set(_MAINLINE.get(from_status, set()))
    if from_status == MemoryStatus.active:
        allowed |= _ACTIVE_SIDE_TRANSITIONS
    if requested_status not in allowed:
        raise ValueError(f"invalid lifecycle transition: {from_status.value} -> {requested_status.value}")

    updated = memory.model_copy(update={"status": requested_status, "updated_at": _now()}, deep=True)
    return updated, _audit(memory, from_status, requested_status, reason, actor, scheduler_run_id, audit_metadata)


def _audit(
    memory: MemoryItem,
    from_status: MemoryStatus,
    to_status: MemoryStatus,
    reason: str,
    actor: str,
    scheduler_run_id: str | None,
    metadata: dict[str, Any],
) -> MemoryLifecycleAuditRecord:
    return MemoryLifecycleAuditRecord(
        workspace_id=memory.workspace_id,
        memory_id=memory.memory_id,
        from_status=from_status,
        to_status=to_status,
        reason=reason,
        actor=actor,
        scheduler_run_id=scheduler_run_id,
        metadata=metadata,
    )


def _safe_status(value: Any) -> MemoryStatus | None:
    try:
        return MemoryStatus(value) if value is not None else None
    except ValueError:
        return None


def _memory_metadata(memory: MemoryItem) -> dict[str, Any]:
    return dict(memory.lifecycle_metadata or {})


def _merged_memory_metadata(memory: MemoryItem, update: dict[str, Any]) -> dict[str, Any]:
    meta = _memory_metadata(memory)
    meta.update(update)
    return meta


def _now() -> datetime:
    return datetime.now(timezone.utc)


__all__ = ["transition_memory_status"]
