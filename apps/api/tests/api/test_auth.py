from __future__ import annotations

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_runtime, require_api_key
from app.config import get_settings
from app.main import app
from app.runtime.memory_runtime import MemoryRuntime
from app.runtime.repository import InMemoryRepository


@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
    app.dependency_overrides.clear()


def _override_runtime() -> None:
    app.dependency_overrides[get_runtime] = lambda: MemoryRuntime(InMemoryRepository(), default_workspace_id="ws_auth")


@pytest.mark.asyncio
async def test_auth_disabled_keeps_health_and_v1_routes_open(monkeypatch):
    monkeypatch.setenv("MEMTRACE_AUTH_ENABLED", "false")
    _override_runtime()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        health = await client.get("/health")
        resp = await client.post("/v1/runs", json={"workspace_id": "ws", "session_id": "s", "task": "t"})

    assert health.status_code == 200
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_auth_enabled_requires_bearer_token(monkeypatch):
    monkeypatch.setenv("MEMTRACE_AUTH_ENABLED", "true")
    monkeypatch.setenv("MEMTRACE_API_KEY", "dev-secret")
    _override_runtime()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        health = await client.get("/health")
        missing = await client.post("/v1/runs", json={"workspace_id": "ws", "session_id": "s"})
        wrong = await client.post(
            "/v1/runs",
            json={"workspace_id": "ws", "session_id": "s"},
            headers={"Authorization": "Bearer wrong"},
        )
        ok = await client.post(
            "/v1/runs",
            json={"workspace_id": "ws", "session_id": "s"},
            headers={"Authorization": "Bearer dev-secret"},
        )
        x_api_key_ok = await client.post(
            "/v1/runs",
            json={"workspace_id": "ws", "session_id": "s"},
            headers={"X-API-Key": "dev-secret"},
        )

    assert health.status_code == 200
    assert missing.status_code == 401
    assert wrong.status_code == 403
    assert ok.status_code == 200
    assert x_api_key_ok.status_code == 200


@pytest.mark.asyncio
async def test_auth_enabled_rejects_non_ascii_api_key_without_server_error(monkeypatch):
    monkeypatch.setenv("MEMTRACE_AUTH_ENABLED", "true")
    monkeypatch.setenv("MEMTRACE_API_KEY", "dev-secret")

    with pytest.raises(HTTPException) as exc:
        await require_api_key(authorization="Bearer inválid")

    assert exc.value.status_code == 403
