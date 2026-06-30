"""Distributed scheduler lease + Celery beat config tests (ROADMAP §3.4, default-off)."""
from __future__ import annotations

import pytest

from app.async_tasks.celery_app import make_celery_app
from app.async_tasks.lease import (
    InMemoryLease,
    NoOpLease,
    RedisLease,
    build_scheduler_lease,
)
from app.config import Settings


# ------------------------------ lease ------------------------------- #


@pytest.mark.asyncio
async def test_noop_lease_always_acquires():
    lease = NoOpLease()
    assert await lease.acquire("k", ttl_seconds=10) is True
    assert await lease.acquire("k", ttl_seconds=10) is True  # never blocks


@pytest.mark.asyncio
async def test_inmemory_lease_excludes_until_released():
    lease = InMemoryLease()
    assert await lease.acquire("k", ttl_seconds=300) is True
    assert await lease.acquire("k", ttl_seconds=300) is False  # held
    await lease.release("k")
    assert await lease.acquire("k", ttl_seconds=300) is True


class _FakeRedis:
    def __init__(self, *, fail=False):
        self.fail = fail
        self.store: dict[str, str] = {}

    async def set(self, key, value, *, nx, ex):
        if self.fail:
            raise RuntimeError("down")
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    async def delete(self, key):
        if self.fail:
            raise RuntimeError("down")
        self.store.pop(key, None)


@pytest.mark.asyncio
async def test_redis_lease_set_nx_semantics():
    lease = RedisLease(_FakeRedis())
    assert await lease.acquire("k", ttl_seconds=30) is True
    assert await lease.acquire("k", ttl_seconds=30) is False
    await lease.release("k")
    assert await lease.acquire("k", ttl_seconds=30) is True


@pytest.mark.asyncio
async def test_redis_lease_degrades_to_not_acquired_on_error():
    lease = RedisLease(_FakeRedis(fail=True))
    assert await lease.acquire("k", ttl_seconds=30) is False  # never wedges


def test_build_scheduler_lease_modes():
    assert isinstance(build_scheduler_lease(Settings(scheduler_lease_backend="off")), NoOpLease)
    assert isinstance(build_scheduler_lease(Settings(scheduler_lease_backend="inmemory")), InMemoryLease)
    assert isinstance(
        build_scheduler_lease(Settings(scheduler_lease_backend="redis"), redis_client=_FakeRedis()),
        RedisLease,
    )


# ------------------------------ beat -------------------------------- #


def test_celery_beat_off_by_default():
    app = make_celery_app(Settings())
    assert not app.conf.beat_schedule


def test_celery_beat_schedule_when_enabled():
    settings = Settings(celery_beat_enabled=True, maintenance_beat_workspace="ws_beat", maintenance_beat_interval_seconds=120)
    app = make_celery_app(settings)
    schedule = app.conf.beat_schedule
    assert "maintenance-sweep" in schedule
    assert schedule["maintenance-sweep"]["schedule"] == 120.0
    assert schedule["maintenance-sweep"]["kwargs"]["payload"]["workspace_id"] == "ws_beat"
