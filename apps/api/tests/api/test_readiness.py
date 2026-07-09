"""Liveness/readiness probe tests (production LB / k8s readinessProbe surface)."""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import app_state
from app.main import app
from app.runtime.repository import InMemoryRepository


@pytest.fixture(autouse=True)
def _reset_app_state():
    saved_engine, saved_repo = app_state.engine, app_state.repository
    yield
    app_state.engine, app_state.repository = saved_engine, saved_repo


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_liveness_is_always_ok_without_touching_the_datastore():
    app_state.engine = None
    app_state.repository = None  # even with nothing configured, liveness stays ok
    async with await _client() as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_readiness_ok_when_repository_configured_without_sql_engine():
    app_state.engine = None
    app_state.repository = InMemoryRepository()
    async with await _client() as client:
        resp = await client.get("/health/ready")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ready", "checks": {"database": "in_memory"}}


async def test_readiness_503_when_nothing_configured():
    app_state.engine = None
    app_state.repository = None
    async with await _client() as client:
        resp = await client.get("/health/ready")
    assert resp.status_code == 503
    assert resp.json()["status"] == "not_ready"


async def test_readiness_503_when_sql_engine_unreachable():
    # An engine that cannot connect -> not-ready (503), not a 500 crash.
    from sqlalchemy.ext.asyncio import create_async_engine

    app_state.repository = InMemoryRepository()
    app_state.engine = create_async_engine(
        "postgresql+asyncpg://memtrace:memtrace@127.0.0.1:1/does_not_exist"
    )
    try:
        async with await _client() as client:
            resp = await client.get("/health/ready")
        assert resp.status_code == 503
        assert resp.json() == {"status": "not_ready", "checks": {"database": "unavailable"}}
    finally:
        await app_state.engine.dispose()
