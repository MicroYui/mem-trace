from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.config import Settings
from app.governance.quota import InMemoryQuotaCounter, QuotaService, QuotaUnit
from app.runtime.models import Principal, WorkspacePermission


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
