from __future__ import annotations

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from app.api.deps import app_state, get_quota_service, get_repository, get_runtime, require_api_key
from app.config import Settings, get_settings
from app.governance.auth import create_api_key_record
from app.governance.quota import InMemoryQuotaCounter, QuotaService
from app.main import app
from app.runtime.models import EventRole, EventType, ExtractionMode, WorkspacePermission, WriteEventRequest
from app.runtime.memory_runtime import MemoryRuntime
from app.runtime.repository import InMemoryRepository


@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
    app.dependency_overrides.clear()


def _override_runtime(repo: InMemoryRepository | None = None) -> InMemoryRepository:
    repo = repo or InMemoryRepository()
    app_state.repository = repo
    app.dependency_overrides[get_runtime] = lambda: MemoryRuntime(repo, default_workspace_id="ws_auth")
    app.dependency_overrides[get_repository] = lambda: repo
    return repo


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


@pytest.mark.asyncio
async def test_db_api_key_authorizes_only_own_workspace_resource_routes(monkeypatch):
    monkeypatch.setenv("MEMTRACE_AUTH_ENABLED", "true")
    monkeypatch.setenv("MEMTRACE_GOVERNANCE_ENABLED", "true")
    repo = _override_runtime()
    raw = "mt_live_ws_auth_reader"
    await repo.add_api_key(
        create_api_key_record(
            raw,
            workspace_id="ws_allowed",
            principal_id="user_1",
            roles=[WorkspacePermission.reader.value],
        )
    )
    runtime = MemoryRuntime(repo, default_workspace_id="ws_auth")
    allowed_run = await runtime.start_run(type("Req", (), {"workspace_id": "ws_allowed", "session_id": "s1", "task": None, "metadata": {}})())
    denied_run = await runtime.start_run(type("Req", (), {"workspace_id": "ws_denied", "session_id": "s2", "task": None, "metadata": {}})())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        allowed = await client.get(
            f"/v1/runs/{allowed_run.run_id}/timeline",
            headers={"Authorization": f"Bearer {raw}"},
        )
        denied = await client.get(
            f"/v1/runs/{denied_run.run_id}/timeline",
            headers={"Authorization": f"Bearer {raw}"},
        )
        missing = await client.get(
            "/v1/runs/run_missing/timeline",
            headers={"Authorization": f"Bearer {raw}"},
        )

    assert allowed.status_code == 200
    assert denied.status_code == 403
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_writer_role_can_create_only_bound_workspace(monkeypatch):
    monkeypatch.setenv("MEMTRACE_AUTH_ENABLED", "true")
    monkeypatch.setenv("MEMTRACE_GOVERNANCE_ENABLED", "true")
    repo = _override_runtime()
    raw = "mt_live_ws_writer"
    await repo.add_api_key(
        create_api_key_record(
            raw,
            workspace_id="ws_allowed",
            principal_id="user_1",
            roles=[WorkspacePermission.writer.value],
        )
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        ok = await client.post(
            "/v1/runs",
            json={"workspace_id": "ws_allowed", "session_id": "s"},
            headers={"X-API-Key": raw},
        )
        denied = await client.post(
            "/v1/runs",
            json={"workspace_id": "ws_denied", "session_id": "s"},
            headers={"X-API-Key": raw},
        )

    assert ok.status_code == 200
    assert denied.status_code == 403


@pytest.mark.asyncio
async def test_authorized_session_flush_is_workspace_scoped(monkeypatch):
    monkeypatch.setenv("MEMTRACE_AUTH_ENABLED", "true")
    monkeypatch.setenv("MEMTRACE_GOVERNANCE_ENABLED", "true")
    repo = InMemoryRepository()
    runtime = MemoryRuntime(repo, default_workspace_id="ws_auth")
    app_state.repository = repo
    app.dependency_overrides[get_runtime] = lambda: runtime
    app.dependency_overrides[get_repository] = lambda: repo
    raw = "mt_live_ws_writer"
    await repo.add_api_key(
        create_api_key_record(
            raw,
            workspace_id="ws_allowed",
            principal_id="user_1",
            roles=[WorkspacePermission.writer.value],
        )
    )
    denied_run = await runtime.start_run(type("Req", (), {"workspace_id": "ws_denied", "session_id": "shared-session", "task": None, "metadata": {}})())
    denied_step = await runtime.start_step(type("Req", (), {"run_id": denied_run.run_id, "intent": "capture", "parent_step_id": None, "recovery_from_step_id": None, "goal": None, "metadata": {}})())
    await runtime.write_event(
        WriteEventRequest(
            run_id=denied_run.run_id,
            step_id=denied_step.step_id,
            role=EventRole.user,
            event_type=EventType.message,
            content="这个项目使用 Bun",
            extraction_mode=ExtractionMode.sync_flush,
        )
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        denied = await client.post(
            "/v1/sessions/flush?workspace_id=ws_allowed",
            json={"session_id": "shared-session"},
            headers={"X-API-Key": raw},
        )

    assert denied.status_code == 200
    assert denied.json()["processed_event_count"] == 0
    assert await repo.list_memories(workspace_id="ws_denied") == []


@pytest.mark.asyncio
async def test_run_scoped_workspace_mismatch_returns_400_for_report_routes(monkeypatch):
    monkeypatch.setenv("MEMTRACE_AUTH_ENABLED", "true")
    monkeypatch.setenv("MEMTRACE_GOVERNANCE_ENABLED", "true")
    repo = _override_runtime()
    raw = "mt_live_ws_reporter"
    await repo.add_api_key(
        create_api_key_record(
            raw,
            workspace_id="ws_allowed",
            principal_id="user_1",
            roles=[WorkspacePermission.report_reader.value],
        )
    )
    runtime = MemoryRuntime(repo, default_workspace_id="ws_auth")
    run = await runtime.start_run(type("Req", (), {"workspace_id": "ws_allowed", "session_id": "s1", "task": None, "metadata": {}})())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        summary = await client.get(
            f"/v1/observability/summary?run_id={run.run_id}&workspace_id=ws_other",
            headers={"X-API-Key": raw},
        )
        report = await client.post(
            "/v1/observability/reports",
            json={"run_id": run.run_id, "workspace_id": "ws_other", "output_dir": "reports/auth-mismatch"},
            headers={"X-API-Key": raw},
        )

    assert summary.status_code == 400
    assert report.status_code == 400


@pytest.mark.asyncio
async def test_write_quota_applies_to_step_lifecycle_routes(monkeypatch):
    monkeypatch.setenv("MEMTRACE_AUTH_ENABLED", "true")
    monkeypatch.setenv("MEMTRACE_GOVERNANCE_ENABLED", "true")
    repo = InMemoryRepository()
    runtime = MemoryRuntime(repo, default_workspace_id="ws_auth")
    app_state.repository = repo
    app.dependency_overrides[get_runtime] = lambda: runtime
    app.dependency_overrides[get_repository] = lambda: repo
    counter = InMemoryQuotaCounter()
    app.dependency_overrides[get_quota_service] = lambda: QuotaService(
        counter,
        Settings(governance_enabled=True, quota_enabled=True, quota_write_event_per_window=1),
    )
    raw = "mt_live_ws_writer_quota"
    await repo.add_api_key(
        create_api_key_record(
            raw,
            workspace_id="ws_allowed",
            principal_id="user_1",
            roles=[WorkspacePermission.writer.value],
        )
    )
    run = await runtime.start_run(type("Req", (), {"workspace_id": "ws_allowed", "session_id": "s1", "task": None, "metadata": {}})())

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post(
            "/v1/steps/start",
            json={"run_id": run.run_id, "intent": "first"},
            headers={"X-API-Key": raw},
        )
        second = await client.post(
            "/v1/steps/start",
            json={"run_id": run.run_id, "intent": "second"},
            headers={"X-API-Key": raw},
        )

    assert first.status_code == 200
    assert second.status_code == 429


@pytest.mark.asyncio
async def test_async_enqueue_quota_applies_to_async_write_events(monkeypatch):
    monkeypatch.setenv("MEMTRACE_AUTH_ENABLED", "true")
    monkeypatch.setenv("MEMTRACE_GOVERNANCE_ENABLED", "true")
    repo = InMemoryRepository()

    async def enqueue(_envelope):
        return "task-id"

    runtime = MemoryRuntime(repo, default_workspace_id="ws_auth", task_enqueue=enqueue)
    app_state.repository = repo
    app.dependency_overrides[get_runtime] = lambda: runtime
    app.dependency_overrides[get_repository] = lambda: repo
    counter = InMemoryQuotaCounter()
    app.dependency_overrides[get_quota_service] = lambda: QuotaService(
        counter,
        Settings(
            governance_enabled=True,
            quota_enabled=True,
            quota_write_event_per_window=10,
            quota_async_task_enqueue_per_window=1,
        ),
    )
    raw = "mt_live_ws_writer_async_quota"
    await repo.add_api_key(
        create_api_key_record(
            raw,
            workspace_id="ws_allowed",
            principal_id="user_1",
            roles=[WorkspacePermission.writer.value],
        )
    )
    run = await runtime.start_run(type("Req", (), {"workspace_id": "ws_allowed", "session_id": "s1", "task": None, "metadata": {}})())
    step = await runtime.start_step(type("Req", (), {"run_id": run.run_id, "intent": "capture", "parent_step_id": None, "recovery_from_step_id": None, "goal": None, "metadata": {}})())

    payload = {
        "run_id": run.run_id,
        "step_id": step.step_id,
        "role": "user",
        "event_type": "message",
        "content": "safe async content",
        "extraction_mode": "async",
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post("/v1/events", json=payload, headers={"X-API-Key": raw})
        second = await client.post("/v1/events", json=payload, headers={"X-API-Key": raw})

    assert first.status_code == 200
    assert first.json()["queued"] is True
    assert second.status_code == 429
