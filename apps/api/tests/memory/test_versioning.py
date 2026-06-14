"""P4-C memory versioning tests."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.memory.versioning import redacted_memory_snapshot, should_create_memory_version
from app.memory.lifecycle import transition_memory_status
from app.runtime.models import MemoryItem, MemoryScope, MemoryStatus, MemoryType, MemoryVersionRecord, RiskFlags, Sensitivity
from app.runtime.repository import InMemoryRepository


def _memory(**overrides) -> MemoryItem:
    data = dict(
        memory_id="mem_versioned",
        workspace_id="ws_versions",
        memory_type=MemoryType.project,
        key="project.runtime",
        value="bun",
        scope=MemoryScope.workspace,
        content="Use bun for this project",
        summary="project.runtime=bun",
        lifecycle_metadata={"source": "test"},
        risk_flags=RiskFlags(),
        sensitivity=Sensitivity.internal,
    )
    data.update(overrides)
    return MemoryItem(**data)


def test_redacted_memory_snapshot_redacts_nested_secret_material_but_keeps_safe_values() -> None:
    memory = _memory(
        key="project.api_key",
        value="api_key=sk-1234567890abcdef1234",
        content="token=sk-1234567890abcdef1234 safe runtime is bun",
        summary="password=hunter2 but package manager remains bun",
        lifecycle_metadata={
            "safe_note": "keep me",
            "nested": {"authorization": "Bearer abcdefghijklmnop", "plain": "visible"},
        },
        risk_flags=RiskFlags(contains_secret=True),
    )

    snapshot = redacted_memory_snapshot(memory)

    rendered = str(snapshot)
    assert "sk-1234567890abcdef1234" not in rendered
    assert "hunter2" not in rendered
    assert "Bearer abcdefghijklmnop" not in rendered
    assert snapshot["key"] == "[REDACTED]"
    assert snapshot["value"] == "[REDACTED]"
    assert snapshot["content"] == "[REDACTED] safe runtime is bun"
    assert snapshot["summary"] == "[REDACTED] but package manager remains bun"
    assert snapshot["lifecycle_metadata"]["safe_note"] == "keep me"
    assert snapshot["lifecycle_metadata"]["nested"]["authorization"] == "[REDACTED]"
    assert snapshot["lifecycle_metadata"]["nested"]["plain"] == "visible"
    assert snapshot["risk_flags"]["contains_secret"] is True


def test_redacted_memory_snapshot_redacts_credential_like_metadata_keys() -> None:
    memory = _memory(
        lifecycle_metadata={
            "credential": "prod-db-login",
            "access_key": "internal-access-key-value",
            "private_key": "plain-private-key-value",
            "access-key": "plain-access-key-value",
            "private-key": ["plain-private-key-value"],
            "api-key": {"raw": "plain-api-key-value"},
            "apikey": {"raw": "plain-api-key-value"},
            "passwd": ["hunter2"],
            "safe": "visible",
        }
    )

    snapshot = redacted_memory_snapshot(memory)

    assert snapshot["lifecycle_metadata"]["credential"] == "[REDACTED]"
    assert snapshot["lifecycle_metadata"]["access_key"] == "[REDACTED]"
    assert snapshot["lifecycle_metadata"]["private_key"] == "[REDACTED]"
    assert snapshot["lifecycle_metadata"]["access-key"] == "[REDACTED]"
    assert snapshot["lifecycle_metadata"]["private-key"] == "[REDACTED]"
    assert snapshot["lifecycle_metadata"]["api-key"] == "[REDACTED]"
    assert snapshot["lifecycle_metadata"]["apikey"] == "[REDACTED]"
    assert snapshot["lifecycle_metadata"]["passwd"] == "[REDACTED]"
    assert snapshot["lifecycle_metadata"]["safe"] == "visible"


def test_redacted_memory_snapshot_uses_memory_key_semantics_for_short_secret_values() -> None:
    memory = _memory(
        key="project.password",
        value="hunter2",
        content="Store only redacted password metadata",
        summary="project password configured",
    )

    snapshot = redacted_memory_snapshot(memory)

    rendered = str(snapshot)
    assert "project.password" not in rendered
    assert "hunter2" not in rendered
    assert snapshot["key"] == "[REDACTED]"
    assert snapshot["value"] == "[REDACTED]"


def test_should_create_memory_version_only_for_semantic_changes() -> None:
    before = _memory(access_count=1)
    access_only = before.model_copy(
        update={
            "access_count": 2,
            "last_accessed_at": datetime(2026, 6, 14, tzinfo=timezone.utc),
            "updated_at": datetime(2026, 6, 14, tzinfo=timezone.utc),
        }
    )
    status_changed = before.model_copy(update={"status": MemoryStatus.superseded})
    value_changed = before.model_copy(update={"value": "node", "content": "Use node"})
    risk_changed = before.model_copy(update={"risk_flags": RiskFlags(tool_sensitive=True)})

    assert should_create_memory_version(before, access_only) is False
    assert should_create_memory_version(before, status_changed) is True
    assert should_create_memory_version(before, value_changed) is True
    assert should_create_memory_version(before, risk_changed) is True


@pytest.mark.asyncio
async def test_repository_update_memory_writes_redacted_versions_but_access_bumps_do_not() -> None:
    repo = InMemoryRepository()
    original = await repo.add_memory(_memory())

    changed = original.model_copy(
        update={
            "value": "node",
            "content": "Use Node.js instead; token=sk-1234567890abcdef1234",
            "updated_at": datetime(2026, 6, 14, tzinfo=timezone.utc),
        }
    )
    await repo.update_memory(changed)
    await repo.bump_memory_access(changed.memory_id, accessed_at=datetime(2026, 6, 14, 1, tzinfo=timezone.utc))

    versions = await repo.list_memory_versions(changed.memory_id)

    assert len(versions) == 1
    assert versions[0].memory_id == changed.memory_id
    assert versions[0].workspace_id == changed.workspace_id
    assert versions[0].version_no == 1
    assert versions[0].change_reason == "update_memory"
    assert versions[0].snapshot["value"] == "node"
    assert versions[0].snapshot["content"] == "Use Node.js instead; [REDACTED]"
    assert "sk-1234567890abcdef1234" not in str(versions[0].snapshot)


@pytest.mark.asyncio
async def test_lifecycle_status_transition_writes_memory_version() -> None:
    repo = InMemoryRepository()
    original = await repo.add_memory(_memory())
    transitioned, audit = transition_memory_status(
        original,
        MemoryStatus.dormant,
        reason="retention_decay",
        actor="scheduler",
    )

    await repo.transition_memory_with_audit(transitioned, audit)

    versions = await repo.list_memory_versions(original.memory_id)
    assert len(versions) == 1
    assert versions[0].change_reason == "lifecycle:retention_decay"
    assert versions[0].snapshot["status"] == "dormant"


@pytest.mark.asyncio
async def test_update_memory_preserves_concurrent_access_only_fields_from_current_row() -> None:
    repo = InMemoryRepository()
    stale = await repo.add_memory(_memory(access_count=0, last_accessed_at=None))
    accessed_at = datetime(2026, 6, 14, 2, tzinfo=timezone.utc)
    await repo.bump_memory_access(stale.memory_id, accessed_at=accessed_at)

    semantic_update_from_stale_copy = stale.model_copy(
        update={
            "value": "node",
            "content": "Use Node.js",
            "updated_at": datetime(2026, 6, 14, 3, tzinfo=timezone.utc),
        }
    )
    await repo.update_memory(semantic_update_from_stale_copy)

    current = await repo.get_memory(stale.memory_id)
    versions = await repo.list_memory_versions(stale.memory_id)

    assert current is not None
    assert current.value == "node"
    assert current.access_count == 1
    assert current.last_accessed_at == accessed_at
    assert len(versions) == 1


@pytest.mark.asyncio
async def test_update_memory_preserves_current_lifecycle_status_from_stale_semantic_copy() -> None:
    repo = InMemoryRepository()
    stale = await repo.add_memory(_memory(status=MemoryStatus.active))
    transitioned, audit = transition_memory_status(
        stale,
        MemoryStatus.dormant,
        reason="retention_decay",
        actor="scheduler",
    )
    await repo.transition_memory_with_audit(transitioned, audit)

    stale_semantic_update = stale.model_copy(
        update={
            "value": "node",
            "content": "Use Node.js",
            "updated_at": datetime(2026, 6, 14, 3, tzinfo=timezone.utc),
        }
    )
    await repo.update_memory(stale_semantic_update)

    current = await repo.get_memory(stale.memory_id)
    assert current is not None
    assert current.value == "node"
    assert current.status == MemoryStatus.dormant


@pytest.mark.asyncio
async def test_in_memory_repository_rejects_duplicate_memory_version_number() -> None:
    repo = InMemoryRepository()
    original = await repo.add_memory(_memory())
    await repo.add_memory_version(
        MemoryVersionRecord(
            memory_id=original.memory_id,
            workspace_id=original.workspace_id,
            version_no=1,
            snapshot={"value": "bun"},
            change_reason="first",
        )
    )

    with pytest.raises(ValueError, match="duplicate memory version"):
        await repo.add_memory_version(
            MemoryVersionRecord(
                memory_id=original.memory_id,
                workspace_id=original.workspace_id,
                version_no=1,
                snapshot={"value": "node"},
                change_reason="duplicate",
            )
        )
