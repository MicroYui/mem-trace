"""Phase-aware profiler.

Records latency / counts for the three P0 phases (retrieval, gate,
context_packing). Profiler writes must never break the hot path, so all writes
are best-effort and swallow exceptions (mvp.md section 11).
"""
from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import Optional

from app.runtime.models import ProfileEvent, ProfilePhase
from app.runtime.repository import Repository


class Profiler:
    def __init__(self, repo: Repository, *, run_id: Optional[str], step_id: Optional[str], access_id: Optional[str]):
        self._repo = repo
        self.run_id = run_id
        self.step_id = step_id
        self.access_id = access_id
        self.events: list[ProfileEvent] = []

    async def record(
        self,
        phase: ProfilePhase,
        *,
        latency_ms: int,
        operation: Optional[str] = None,
        candidate_count: int = 0,
        accepted_count: int = 0,
        rejected_count: int = 0,
        metadata: Optional[dict] = None,
        error_code: Optional[str] = None,
    ) -> None:
        evt = ProfileEvent(
            run_id=self.run_id,
            step_id=self.step_id,
            access_id=self.access_id,
            phase=phase,
            operation=operation,
            latency_ms=latency_ms,
            candidate_count=candidate_count,
            accepted_count=accepted_count,
            rejected_count=rejected_count,
            metadata=metadata or {},
            error_code=error_code,
        )
        self.events.append(evt)
        try:
            await self._repo.add_profile_event(evt)
        except Exception:  # noqa: BLE001 - profiler must not break the hot path
            pass

    @asynccontextmanager
    async def phase(self, phase: ProfilePhase, **fields):
        start = time.perf_counter()
        meta = _PhaseScope()
        try:
            yield meta
        finally:
            latency = int((time.perf_counter() - start) * 1000)
            await self.record(
                phase,
                latency_ms=latency,
                candidate_count=meta.candidate_count,
                accepted_count=meta.accepted_count,
                rejected_count=meta.rejected_count,
                operation=fields.get("operation"),
                metadata=meta.metadata,
            )


class _PhaseScope:
    def __init__(self) -> None:
        self.candidate_count = 0
        self.accepted_count = 0
        self.rejected_count = 0
        self.metadata: dict = {}


__all__ = ["Profiler"]
