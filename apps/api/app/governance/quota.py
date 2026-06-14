"""Fixed-window governance quota checks."""
from __future__ import annotations

import time
from enum import Enum
from typing import Optional, Protocol

from fastapi import HTTPException, status

from app.config import Settings
from app.runtime.models import Principal


class QuotaUnit(str, Enum):
    write_event = "write_event"
    retrieve_context = "retrieve_context"
    report_export = "report_export"
    replay = "replay"
    async_task_enqueue = "async_task_enqueue"


class QuotaCounter(Protocol):
    async def increment(self, key: str, *, ttl_seconds: int) -> int: ...


class InMemoryQuotaCounter:
    def __init__(self) -> None:
        self._values: dict[str, int] = {}

    async def increment(self, key: str, *, ttl_seconds: int) -> int:
        self._values[key] = self._values.get(key, 0) + 1
        return self._values[key]


class QuotaService:
    def __init__(self, counter: QuotaCounter, settings: Settings, *, repo: Optional[object] = None) -> None:
        self._counter = counter
        self._settings = settings
        self._repo = repo

    def _settings_limit_for(self, unit: QuotaUnit) -> int:
        return {
            QuotaUnit.write_event: self._settings.quota_write_event_per_window,
            QuotaUnit.retrieve_context: self._settings.quota_retrieve_context_per_window,
            QuotaUnit.report_export: self._settings.quota_report_export_per_window,
            QuotaUnit.replay: self._settings.quota_replay_per_window,
            QuotaUnit.async_task_enqueue: self._settings.quota_async_task_enqueue_per_window,
        }[unit]

    async def _resolve_limit(
        self, principal: Principal, workspace_id: str, unit: QuotaUnit
    ) -> tuple[int, int]:
        """Resolve (limit, window_seconds), preferring DB overrides.

        Override lookup order: principal-specific -> workspace-wide -> settings
        default. The repository is consulted only when quota is enabled and a
        repo was injected, so hot runtime routes never hit the DB by default.
        """
        default = (self._settings_limit_for(unit), self._settings.quota_window_seconds)
        if self._repo is None:
            return default
        try:
            specific = await self._repo.list_quota_limits(
                workspace_id=workspace_id,
                principal_id=principal.principal_id,
                unit=unit.value,
                limit=1,
                offset=0,
            )
            if specific:
                return specific[0].limit, specific[0].window_seconds
            workspace_wide = await self._repo.list_quota_limits(
                workspace_id=workspace_id, principal_id=None, unit=unit.value, limit=1, offset=0
            )
            if workspace_wide:
                return workspace_wide[0].limit, workspace_wide[0].window_seconds
            return default
        except Exception as exc:  # noqa: BLE001 - governance mode intentionally fail-closed
            if self._settings.governance_enabled:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="quota service unavailable",
                ) from exc
            return default

    async def check(self, principal: Principal, workspace_id: str, unit: QuotaUnit) -> None:
        if not self._settings.quota_enabled:
            return
        limit, window_seconds = await self._resolve_limit(principal, workspace_id, unit)
        window = int(time.time() // max(1, window_seconds))
        key = f"memtrace:quota:{workspace_id}:{principal.principal_id}:{unit.value}:{window}"
        try:
            count = await self._counter.increment(key, ttl_seconds=window_seconds)
        except Exception as exc:  # noqa: BLE001 - governance mode intentionally fail-closed
            if self._settings.governance_enabled:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="quota service unavailable",
                ) from exc
            return
        if count > limit:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="quota exceeded")
