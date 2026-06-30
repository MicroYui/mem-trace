"""Distributed scheduler lease (ROADMAP §3.4, default-off).

When maintenance runs are scheduled periodically (Celery beat) across multiple
workers, only one worker should execute a given sweep. A lease provides that
mutual exclusion. Two backends:

- ``InMemoryLease`` — single-process mutual exclusion with TTL expiry. Useful for
  a single beat scheduler; deterministic and dependency-free.
- ``RedisLease`` — cross-process lease via ``SET key value NX EX`` over an
  injected redis client. Degrades to "not acquired" on any redis error so a
  broker hiccup never wedges the scheduler.

``NoOpLease`` (the ``off`` default) always acquires, preserving today's
single-runner behavior. ``time.monotonic`` is used for TTL so wall-clock changes
don't affect expiry.
"""
from __future__ import annotations

import time
from typing import Protocol, runtime_checkable


@runtime_checkable
class SchedulerLease(Protocol):
    name: str

    async def acquire(self, key: str, *, ttl_seconds: int) -> bool:
        ...

    async def release(self, key: str) -> None:
        ...


class NoOpLease:
    """Always acquires — preserves single-runner behavior when leasing is off."""

    name = "noop"

    async def acquire(self, key: str, *, ttl_seconds: int) -> bool:
        return True

    async def release(self, key: str) -> None:
        return None


class InMemoryLease:
    """Single-process lease with monotonic TTL expiry."""

    name = "inmemory"

    def __init__(self) -> None:
        self._held: dict[str, float] = {}

    async def acquire(self, key: str, *, ttl_seconds: int) -> bool:
        now = time.monotonic()
        expiry = self._held.get(key)
        if expiry is not None and expiry > now:
            return False
        self._held[key] = now + max(1, ttl_seconds)
        return True

    async def release(self, key: str) -> None:
        self._held.pop(key, None)


class RedisLease:
    """Cross-process lease via SET NX EX. Degrades to not-acquired on error."""

    name = "redis"

    def __init__(self, client: object) -> None:
        self._client = client

    def _key(self, key: str) -> str:
        return f"memtrace:lease:{key}"

    async def acquire(self, key: str, *, ttl_seconds: int) -> bool:
        try:
            result = await self._client.set(  # type: ignore[attr-defined]
                self._key(key), "1", nx=True, ex=max(1, ttl_seconds)
            )
            return bool(result)
        except Exception:  # noqa: BLE001 - a broker hiccup must not wedge scheduling
            return False

    async def release(self, key: str) -> None:
        try:
            await self._client.delete(self._key(key))  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            return None


def build_scheduler_lease(settings, *, redis_client: object | None = None) -> SchedulerLease:
    """Construct the configured lease backend (default ``off`` -> NoOpLease)."""
    backend = (getattr(settings, "scheduler_lease_backend", "off") or "off").lower()
    if backend == "inmemory":
        return InMemoryLease()
    if backend == "redis":
        if redis_client is not None:
            return RedisLease(redis_client)
        try:  # lazy: redis is an optional dependency
            from redis.asyncio import from_url  # type: ignore

            return RedisLease(from_url(settings.redis_url))
        except Exception:  # noqa: BLE001 - degrade to single-process safety
            return InMemoryLease()
    return NoOpLease()


__all__ = [
    "SchedulerLease",
    "NoOpLease",
    "InMemoryLease",
    "RedisLease",
    "build_scheduler_lease",
]
