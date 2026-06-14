from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import app_state, get_quota_service, get_repository, get_runtime
from app.config import Settings, get_settings
from app.governance.auth import create_api_key_record
from app.governance.quota import InMemoryQuotaCounter, QuotaService
from app.main import app
from app.memory.lifecycle import transition_memory_status
from app.runtime.memory_runtime import MemoryRuntime
from app.runtime.models import MemoryItem, MemoryStatus, MemoryType, WorkspacePermission
from app.runtime.repository import InMemoryRepository


@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
    app.dependency_overrides.clear()
    app_state.maintenance_enqueue = None


def _override(repo: InMemoryRepository | None = None) -> InMemoryRepository:
    repo = repo or InMemoryRepository()
    app_state.repository = repo
    app.dependency_overrides[get_runtime] = lambda: MemoryRuntime(repo, default_workspace_id="ws_admin")
    app.dependency_overrides[get_repository] = lambda: repo
    return repo


async def _add_owner_key(repo: InMemoryRepository, *, workspace_id: str = "ws_1", raw: str = "mt_owner_ws_1") -> str:
    await repo.add_api_key(
        create_api_key_record(
            raw,
            workspace_id=workspace_id,
            principal_id="owner_1",
            roles=[WorkspacePermission.owner.value],
        )
    )
    return raw


@pytest.mark.asyncio
async def test_admin_maintenance_disabled_by_default(monkeypatch):
    monkeypatch.setenv("MEMTRACE_ADMIN_API_ENABLED", "false")
    _override()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/admin/maintenance/runs",
            json={"workspace_id": "ws_1", "operations": ["score_memory"]},
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "admin api disabled"


@pytest.mark.asyncio
async def test_admin_maintenance_requires_auth_when_enabled(monkeypatch):
    monkeypatch.setenv("MEMTRACE_ADMIN_API_ENABLED", "true")
    monkeypatch.setenv("MEMTRACE_AUTH_ENABLED", "true")
    monkeypatch.setenv("MEMTRACE_GOVERNANCE_ENABLED", "true")
    _override()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/admin/maintenance/runs",
            json={"workspace_id": "ws_1", "operations": ["score_memory"]},
        )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_non_owner_principal_is_forbidden(monkeypatch):
    monkeypatch.setenv("MEMTRACE_ADMIN_API_ENABLED", "true")
    monkeypatch.setenv("MEMTRACE_AUTH_ENABLED", "true")
    monkeypatch.setenv("MEMTRACE_GOVERNANCE_ENABLED", "true")
    repo = _override()
    raw = "mt_reader_ws_1"
    await repo.add_api_key(
        create_api_key_record(
            raw,
            workspace_id="ws_1",
            principal_id="reader_1",
            roles=[WorkspacePermission.reader.value],
        )
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/admin/maintenance/runs",
            json={"workspace_id": "ws_1", "operations": ["score_memory"]},
            headers={"X-API-Key": raw},
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "admin owner permission required"


@pytest.mark.asyncio
async def test_owner_can_start_dry_run_maintenance(monkeypatch):
    monkeypatch.setenv("MEMTRACE_ADMIN_API_ENABLED", "true")
    monkeypatch.setenv("MEMTRACE_AUTH_ENABLED", "true")
    monkeypatch.setenv("MEMTRACE_GOVERNANCE_ENABLED", "true")
    repo = _override()
    raw = await _add_owner_key(repo)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/admin/maintenance/runs",
            json={
                "workspace_id": "ws_1",
                "operations": ["score_memory", "conflict_scan"],
                "dry_run": True,
                "reason": "operator preview",
            },
            headers={"X-API-Key": raw},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["dry_run"] is True
    assert body["status"] == "completed"
    assert body["workspace_id"] == "ws_1"
    # Reason persisted on run record, redacted helper keeps benign text.
    assert body["reason"] == "operator preview"


@pytest.mark.asyncio
async def test_owner_can_start_real_run_default_operations_and_audit(monkeypatch):
    monkeypatch.setenv("MEMTRACE_ADMIN_API_ENABLED", "true")
    monkeypatch.setenv("MEMTRACE_AUTH_ENABLED", "true")
    monkeypatch.setenv("MEMTRACE_GOVERNANCE_ENABLED", "true")
    repo = _override()
    raw = await _add_owner_key(repo)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/admin/maintenance/runs",
            json={"workspace_id": "ws_1"},
            headers={"X-API-Key": raw},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    # operations=None falls back to settings.maintenance_default_operations (10).
    assert len(body["operations"]) == 10

    audits = await repo.list_admin_action_audits(workspace_id="ws_1")
    assert len(audits) == 1
    assert audits[0].action == "start_maintenance_run"
    assert audits[0].target_type == "maintenance_run"
    assert audits[0].principal_id == "owner_1"


@pytest.mark.asyncio
async def test_get_and_list_maintenance_runs(monkeypatch):
    monkeypatch.setenv("MEMTRACE_ADMIN_API_ENABLED", "true")
    monkeypatch.setenv("MEMTRACE_AUTH_ENABLED", "true")
    monkeypatch.setenv("MEMTRACE_GOVERNANCE_ENABLED", "true")
    repo = _override()
    raw = await _add_owner_key(repo)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        start = await client.post(
            "/v1/admin/maintenance/runs",
            json={"workspace_id": "ws_1", "operations": ["score_memory"]},
            headers={"X-API-Key": raw},
        )
        run_id = start.json()["scheduler_run_id"]
        got = await client.get(
            f"/v1/admin/maintenance/runs/{run_id}",
            headers={"X-API-Key": raw},
        )
        listed = await client.get(
            "/v1/admin/maintenance/runs?workspace_id=ws_1",
            headers={"X-API-Key": raw},
        )
        attempts = await client.get(
            f"/v1/admin/maintenance/runs/{run_id}/attempts",
            headers={"X-API-Key": raw},
        )

    assert got.status_code == 200
    assert got.json()["scheduler_run_id"] == run_id
    assert listed.status_code == 200
    assert any(r["scheduler_run_id"] == run_id for r in listed.json())
    assert attempts.status_code == 200
    assert [a["operation"] for a in attempts.json()] == ["score_memory"]


@pytest.mark.asyncio
async def test_get_maintenance_run_missing_returns_404(monkeypatch):
    monkeypatch.setenv("MEMTRACE_ADMIN_API_ENABLED", "true")
    monkeypatch.setenv("MEMTRACE_AUTH_ENABLED", "true")
    monkeypatch.setenv("MEMTRACE_GOVERNANCE_ENABLED", "true")
    repo = _override()
    raw = await _add_owner_key(repo)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        missing = await client.get(
            "/v1/admin/maintenance/runs/msrun_missing",
            headers={"X-API-Key": raw},
        )

    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_get_run_workspace_isolation(monkeypatch):
    monkeypatch.setenv("MEMTRACE_ADMIN_API_ENABLED", "true")
    monkeypatch.setenv("MEMTRACE_AUTH_ENABLED", "true")
    monkeypatch.setenv("MEMTRACE_GOVERNANCE_ENABLED", "true")
    repo = _override()
    owner_ws1 = await _add_owner_key(repo, workspace_id="ws_1", raw="mt_ws1_owner_key")
    owner_ws2 = await _add_owner_key(repo, workspace_id="ws_2", raw="mt_ws2_owner_key")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        start = await client.post(
            "/v1/admin/maintenance/runs",
            json={"workspace_id": "ws_1", "operations": ["score_memory"]},
            headers={"X-API-Key": owner_ws1},
        )
        run_id = start.json()["scheduler_run_id"]
        cross = await client.get(
            f"/v1/admin/maintenance/runs/{run_id}",
            headers={"X-API-Key": owner_ws2},
        )

    assert cross.status_code == 403


@pytest.mark.asyncio
async def test_list_pagination_validation(monkeypatch):
    monkeypatch.setenv("MEMTRACE_ADMIN_API_ENABLED", "true")
    monkeypatch.setenv("MEMTRACE_AUTH_ENABLED", "true")
    monkeypatch.setenv("MEMTRACE_GOVERNANCE_ENABLED", "true")
    repo = _override()
    raw = await _add_owner_key(repo)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        too_big = await client.get(
            "/v1/admin/maintenance/runs?workspace_id=ws_1&limit=501",
            headers={"X-API-Key": raw},
        )
        negative = await client.get(
            "/v1/admin/maintenance/runs?workspace_id=ws_1&offset=-1",
            headers={"X-API-Key": raw},
        )

    assert too_big.status_code == 422
    assert negative.status_code == 422


@pytest.mark.asyncio
async def test_list_lifecycle_audits(monkeypatch):
    monkeypatch.setenv("MEMTRACE_ADMIN_API_ENABLED", "true")
    monkeypatch.setenv("MEMTRACE_AUTH_ENABLED", "true")
    monkeypatch.setenv("MEMTRACE_GOVERNANCE_ENABLED", "true")
    repo = _override()
    raw = await _add_owner_key(repo)
    memory = await repo.add_memory(
        MemoryItem(
            workspace_id="ws_1",
            memory_type=MemoryType.project,
            key="project.runtime",
            value="bun",
            content="bun",
            status=MemoryStatus.active,
        )
    )
    updated, audit = transition_memory_status(
        memory, MemoryStatus.dormant, reason="cleanup", actor="admin:owner_1"
    )
    await repo.transition_memory_with_audit(updated, audit)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        audits = await client.get(
            "/v1/admin/lifecycle-audits?workspace_id=ws_1",
            headers={"X-API-Key": raw},
        )

    assert audits.status_code == 200
    body = audits.json()
    assert len(body) == 1
    assert body[0]["memory_id"] == memory.memory_id
    assert body[0]["to_status"] == "dormant"


@pytest.mark.asyncio
async def test_enqueue_without_async_tasks_returns_400(monkeypatch):
    monkeypatch.setenv("MEMTRACE_ADMIN_API_ENABLED", "true")
    monkeypatch.setenv("MEMTRACE_AUTH_ENABLED", "true")
    monkeypatch.setenv("MEMTRACE_GOVERNANCE_ENABLED", "true")
    monkeypatch.setenv("MEMTRACE_ASYNC_TASKS_ENABLED", "false")
    repo = _override()
    raw = await _add_owner_key(repo)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/admin/maintenance/runs",
            json={"workspace_id": "ws_1", "operations": ["score_memory"], "enqueue": True},
            headers={"X-API-Key": raw},
        )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_duplicate_operations_rejected_for_both_paths(monkeypatch):
    monkeypatch.setenv("MEMTRACE_ADMIN_API_ENABLED", "true")
    monkeypatch.setenv("MEMTRACE_AUTH_ENABLED", "true")
    monkeypatch.setenv("MEMTRACE_GOVERNANCE_ENABLED", "true")
    repo = _override()
    raw = await _add_owner_key(repo)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        direct = await client.post(
            "/v1/admin/maintenance/runs",
            json={"workspace_id": "ws_1", "operations": ["score_memory", "score_memory"]},
            headers={"X-API-Key": raw},
        )
        enqueue = await client.post(
            "/v1/admin/maintenance/runs",
            json={
                "workspace_id": "ws_1",
                "operations": ["score_memory", "score_memory"],
                "enqueue": True,
            },
            headers={"X-API-Key": raw},
        )

    # Duplicate operations must be rejected identically before any run is
    # persisted, regardless of enqueue mode.
    assert direct.status_code == 400
    assert enqueue.status_code == 400
    assert await repo.list_maintenance_runs(workspace_id="ws_1") == []


@pytest.mark.asyncio
async def test_enqueue_redacts_run_reason_and_payload(monkeypatch):
    monkeypatch.setenv("MEMTRACE_ADMIN_API_ENABLED", "true")
    monkeypatch.setenv("MEMTRACE_AUTH_ENABLED", "true")
    monkeypatch.setenv("MEMTRACE_GOVERNANCE_ENABLED", "true")
    monkeypatch.setenv("MEMTRACE_ASYNC_TASKS_ENABLED", "true")
    repo = _override()
    raw = await _add_owner_key(repo)

    captured: list = []

    async def fake_enqueue(envelope):
        captured.append(envelope)
        return "task-id"

    app_state.maintenance_enqueue = fake_enqueue
    unsafe_reason = "cleanup before git push --force to /prod"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/v1/admin/maintenance/runs",
            json={
                "workspace_id": "ws_1",
                "operations": ["score_memory"],
                "enqueue": True,
                "reason": unsafe_reason,
            },
            headers={"X-API-Key": raw},
        )

    assert response.status_code == 200
    body = response.json()
    # Persisted/returned run reason must be redacted, not the raw destructive text.
    assert "git push --force" not in (body["reason"] or "")
    assert "/prod" not in (body["reason"] or "")
    # The enqueued task payload reason must also be redacted.
    assert len(captured) == 1
    payload_reason = captured[0].payload["reason"] or ""
    assert "git push --force" not in payload_reason
    assert "/prod" not in payload_reason
    # The persisted record read back through the API stays redacted.
    runs = await repo.list_maintenance_runs(workspace_id="ws_1")
    assert len(runs) == 1
    assert "git push --force" not in (runs[0].reason or "")


@pytest.mark.asyncio
async def test_start_run_consumes_report_export_quota(monkeypatch):
    monkeypatch.setenv("MEMTRACE_ADMIN_API_ENABLED", "true")
    monkeypatch.setenv("MEMTRACE_AUTH_ENABLED", "true")
    monkeypatch.setenv("MEMTRACE_GOVERNANCE_ENABLED", "true")
    repo = _override()
    raw = await _add_owner_key(repo)
    counter = InMemoryQuotaCounter()
    app.dependency_overrides[get_quota_service] = lambda: QuotaService(
        counter,
        Settings(governance_enabled=True, quota_enabled=True, quota_report_export_per_window=1),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post(
            "/v1/admin/maintenance/runs",
            json={"workspace_id": "ws_1", "operations": ["score_memory"]},
            headers={"X-API-Key": raw},
        )
        second = await client.post(
            "/v1/admin/maintenance/runs",
            json={"workspace_id": "ws_1", "operations": ["score_memory"]},
            headers={"X-API-Key": raw},
        )

    assert first.status_code == 200
    assert second.status_code == 429
