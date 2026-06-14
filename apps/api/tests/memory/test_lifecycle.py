from __future__ import annotations

import pytest

from app.memory.lifecycle import transition_memory_status
from app.runtime.models import MemoryItem, MemoryStatus, MemoryType
from app.runtime.repository import InMemoryRepository


def _memory(status: MemoryStatus = MemoryStatus.active) -> MemoryItem:
    return MemoryItem(
        memory_id="mem_lifecycle",
        workspace_id="ws_lifecycle",
        memory_type=MemoryType.episodic,
        content="remember lifecycle marker",
        status=status,
    )


def test_lifecycle_allows_mainline_and_records_audit_metadata():
    memory = _memory(MemoryStatus.active)

    dormant, audit = transition_memory_status(
        memory,
        MemoryStatus.dormant,
        reason="low_retention",
        actor="scheduler",
        scheduler_run_id="sched_1",
    )

    assert dormant.status == MemoryStatus.dormant
    assert memory.status == MemoryStatus.active
    assert audit.workspace_id == memory.workspace_id
    assert audit.memory_id == memory.memory_id
    assert audit.from_status == MemoryStatus.active
    assert audit.to_status == MemoryStatus.dormant
    assert audit.reason == "low_retention"
    assert audit.actor == "scheduler"
    assert audit.scheduler_run_id == "sched_1"


def test_lifecycle_pin_and_unpin_restores_safe_previous_status():
    dormant = _memory(MemoryStatus.dormant)

    pinned, pin_audit = transition_memory_status(dormant, MemoryStatus.pinned, reason="manual_pin", actor="user")
    unpinned, unpin_audit = transition_memory_status(pinned, MemoryStatus.active, reason="manual_unpin", actor="user")

    assert pinned.status == MemoryStatus.pinned
    assert pin_audit.metadata["previous_status"] == "dormant"
    assert unpinned.status == MemoryStatus.dormant
    assert unpin_audit.from_status == MemoryStatus.pinned
    assert unpin_audit.to_status == MemoryStatus.dormant
    assert unpin_audit.metadata["restored_previous_status"] == "dormant"


def test_lifecycle_rejects_invalid_transition_without_mutation():
    archived = _memory(MemoryStatus.archived)

    with pytest.raises(ValueError, match="invalid lifecycle transition"):
        transition_memory_status(archived, MemoryStatus.active, reason="resurrect", actor="scheduler")

    assert archived.status == MemoryStatus.archived


def test_scheduler_cannot_archive_pinned_memory():
    pinned = _memory(MemoryStatus.pinned)

    with pytest.raises(ValueError, match="pinned memory cannot be archived by scheduler"):
        transition_memory_status(pinned, MemoryStatus.archived, reason="retention_decay", actor="scheduler")

    assert pinned.status == MemoryStatus.pinned


@pytest.mark.asyncio
async def test_lifecycle_audit_repository_round_trip():
    repo = InMemoryRepository()
    memory = await repo.add_memory(_memory())
    updated, audit = transition_memory_status(memory, MemoryStatus.dormant, reason="low_retention", actor="scheduler")

    await repo.update_memory(updated)
    await repo.add_lifecycle_audit(audit)

    rows = await repo.list_lifecycle_audits(workspace_id="ws_lifecycle", memory_id=memory.memory_id)
    assert [row.audit_id for row in rows] == [audit.audit_id]
    assert rows[0].from_status == MemoryStatus.active
    assert rows[0].to_status == MemoryStatus.dormant


@pytest.mark.asyncio
async def test_lifecycle_transition_rejects_stale_status_and_preserves_current_memory():
    repo = InMemoryRepository()
    memory = await repo.add_memory(_memory(MemoryStatus.active))
    stale_update, stale_audit = transition_memory_status(
        memory,
        MemoryStatus.dormant,
        reason="retention_decay",
        actor="scheduler",
    )
    pinned, _pin_audit = transition_memory_status(memory, MemoryStatus.pinned, reason="manual_pin", actor="user")
    await repo.update_memory(pinned)

    with pytest.raises(ValueError, match="stale lifecycle transition"):
        await repo.transition_memory_with_audit(stale_update, stale_audit)

    current = await repo.get_memory(memory.memory_id)
    assert current.status == MemoryStatus.pinned
    assert await repo.list_lifecycle_audits(workspace_id="ws_lifecycle", memory_id=memory.memory_id) == []
