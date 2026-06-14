"""Fixed-window governance quota checks."""
from __future__ import annotations

import time
from enum import Enum
from typing import Protocol

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
    def __init__(self, counter: QuotaCounter, settings: Settings) -> None:
        self._counter = counter
        self._settings = settings

    def _limit_for(self, unit: QuotaUnit) -> int:
        return {
            QuotaUnit.write_event: self._settings.quota_write_event_per_window,
            QuotaUnit.retrieve_context: self._settings.quota_retrieve_context_per_window,
            QuotaUnit.report_export: self._settings.quota_report_export_per_window,
            QuotaUnit.replay: self._settings.quota_replay_per_window,
            QuotaUnit.async_task_enqueue: self._settings.quota_async_task_enqueue_per_window,
        }[unit]

    async def check(self, principal: Principal, workspace_id: str, unit: QuotaUnit) -> None:
        if not self._settings.quota_enabled:
            return
        window = int(time.time() // max(1, self._settings.quota_window_seconds))
        key = f"memtrace:quota:{workspace_id}:{principal.principal_id}:{unit.value}:{window}"
        try:
            count = await self._counter.increment(key, ttl_seconds=self._settings.quota_window_seconds)
        except Exception as exc:  # noqa: BLE001 - governance mode intentionally fail-closed
            if self._settings.governance_enabled:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="quota service unavailable",
                ) from exc
            return
        if count > self._limit_for(unit):
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="quota exceeded")
