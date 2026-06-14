"""Idempotency stores for async task wrappers."""
from __future__ import annotations

import time
from typing import Protocol


class IdempotencyStore(Protocol):
    async def acquire(self, key: str, ttl_seconds: int) -> bool: ...
    async def release(self, key: str) -> None: ...


class InMemoryIdempotencyStore:
    """Deterministic process-local idempotency store for eager tests."""

    def __init__(self) -> None:
        self._entries: dict[str, float] = {}

    async def acquire(self, key: str, ttl_seconds: int) -> bool:
        now = time.monotonic()
        expires_at = self._entries.get(key)
        if expires_at is not None and expires_at > now:
            return False
        self._entries[key] = now + max(1, ttl_seconds)
        return True

    async def release(self, key: str) -> None:
        self._entries.pop(key, None)


class RedisIdempotencyStore:
    """Redis-backed idempotency using SET NX EX semantics."""

    def __init__(self, redis_client) -> None:
        self._redis = redis_client

    async def acquire(self, key: str, ttl_seconds: int) -> bool:
        result = await self._redis.set(f"memtrace:idempotency:{key}", "1", nx=True, ex=max(1, ttl_seconds))
        return bool(result)

    async def release(self, key: str) -> None:
        await self._redis.delete(f"memtrace:idempotency:{key}")


__all__ = ["IdempotencyStore", "InMemoryIdempotencyStore", "RedisIdempotencyStore"]
