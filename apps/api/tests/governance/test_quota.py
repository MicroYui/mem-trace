from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.config import Settings
from app.governance.quota import InMemoryQuotaCounter, QuotaService, QuotaUnit
from app.runtime.models import Principal, QuotaLimitRecord, WorkspacePermission
from app.runtime.repository import InMemoryRepository


def _principal() -> Principal:
    return Principal(
        principal_id="user_1",
        kind="api_key",
        workspace_ids=["ws_quota"],
        roles=[WorkspacePermission.writer.value],
        api_key_id="key_1",
    )


@pytest.mark.asyncio
async def test_fixed_window_quota_blocks_over_limit_requests() -> None:
    service = QuotaService(
        InMemoryQuotaCounter(),
        Settings(governance_enabled=True, quota_enabled=True, quota_write_event_per_window=1),
    )

    await service.check(_principal(), "ws_quota", QuotaUnit.write_event)
    with pytest.raises(HTTPException) as exc:
        await service.check(_principal(), "ws_quota", QuotaUnit.write_event)

    assert exc.value.status_code == 429


class _FailingCounter:
    async def increment(self, key: str, *, ttl_seconds: int) -> int:  # pragma: no cover - exercised through service
        raise RuntimeError("redis unavailable")


@pytest.mark.asyncio
async def test_quota_counter_failure_fails_closed_only_when_governance_enabled() -> None:
    enabled = QuotaService(_FailingCounter(), Settings(governance_enabled=True, quota_enabled=True))
    with pytest.raises(HTTPException) as exc:
        await enabled.check(_principal(), "ws_quota", QuotaUnit.retrieve_context)
    assert exc.value.status_code == 503

    disabled = QuotaService(_FailingCounter(), Settings(governance_enabled=False, quota_enabled=True))
    await disabled.check(_principal(), "ws_quota", QuotaUnit.retrieve_context)


@pytest.mark.asyncio
async def test_quota_service_uses_workspace_principal_override() -> None:
    repo = InMemoryRepository()
    await repo.upsert_quota_limit(
        QuotaLimitRecord(
            workspace_id="ws_quota",
            principal_id="user_1",
            unit="write_event",
            limit=1,
            window_seconds=60,
            created_by="admin",
        )
    )
    settings = Settings(governance_enabled=True, quota_enabled=True, quota_write_event_per_window=100)
    service = QuotaService(InMemoryQuotaCounter(), settings, repo=repo)

    await service.check(_principal(), "ws_quota", QuotaUnit.write_event)
    with pytest.raises(HTTPException) as exc:
        await service.check(_principal(), "ws_quota", QuotaUnit.write_event)
    assert exc.value.status_code == 429


@pytest.mark.asyncio
async def test_quota_service_falls_back_to_settings_when_no_override() -> None:
    repo = InMemoryRepository()
    settings = Settings(governance_enabled=True, quota_enabled=True, quota_write_event_per_window=1)
    service = QuotaService(InMemoryQuotaCounter(), settings, repo=repo)

    await service.check(_principal(), "ws_quota", QuotaUnit.write_event)
    with pytest.raises(HTTPException) as exc:
        await service.check(_principal(), "ws_quota", QuotaUnit.write_event)
    assert exc.value.status_code == 429


@pytest.mark.asyncio
async def test_workspace_wide_override_applies_when_no_principal_override() -> None:
    repo = InMemoryRepository()
    await repo.upsert_quota_limit(
        QuotaLimitRecord(
            workspace_id="ws_quota",
            principal_id=None,
            unit="write_event",
            limit=1,
            window_seconds=60,
            created_by="admin",
        )
    )
    settings = Settings(governance_enabled=True, quota_enabled=True, quota_write_event_per_window=100)
    service = QuotaService(InMemoryQuotaCounter(), settings, repo=repo)

    await service.check(_principal(), "ws_quota", QuotaUnit.write_event)
    with pytest.raises(HTTPException) as exc:
        await service.check(_principal(), "ws_quota", QuotaUnit.write_event)
    assert exc.value.status_code == 429


@pytest.mark.asyncio
async def test_override_only_applies_to_its_own_unit() -> None:
    """A write_event override must NOT bleed into retrieve_context checks.

    The override lookup must filter by unit; otherwise an unrelated unit picks up
    the earliest-created override for the (workspace, principal) pair.
    """
    repo = InMemoryRepository()
    await repo.upsert_quota_limit(
        QuotaLimitRecord(
            workspace_id="ws_quota",
            principal_id="user_1",
            unit="write_event",
            limit=1,
            window_seconds=60,
            created_by="admin",
        )
    )
    settings = Settings(
        governance_enabled=True,
        quota_enabled=True,
        quota_write_event_per_window=100,
        quota_retrieve_context_per_window=5,
    )
    service = QuotaService(InMemoryQuotaCounter(), settings, repo=repo)

    # retrieve_context must use its settings default (5), not the write_event override (1).
    for _ in range(5):
        await service.check(_principal(), "ws_quota", QuotaUnit.retrieve_context)
    with pytest.raises(HTTPException) as exc:
        await service.check(_principal(), "ws_quota", QuotaUnit.retrieve_context)
    assert exc.value.status_code == 429

    # write_event still honors its own override of 1.
    await service.check(_principal(), "ws_quota", QuotaUnit.write_event)
    with pytest.raises(HTTPException) as exc2:
        await service.check(_principal(), "ws_quota", QuotaUnit.write_event)
    assert exc2.value.status_code == 429
