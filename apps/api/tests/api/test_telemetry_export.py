from __future__ import annotations

import httpx
from fastapi import FastAPI

from app.api.deps import get_quota_service, get_runtime, get_telemetry_service, require_api_key
from app.api.routes import router
from app.config import Settings
from app.governance.quota import InMemoryQuotaCounter, QuotaService
from app.runtime.memory_runtime import MemoryRuntime
from app.runtime.models import (
    EventRole,
    EventType,
    Principal,
    StartRunRequest,
    StartStepRequest,
    WorkspacePermission,
    WriteEventRequest,
)
from app.runtime.repository import InMemoryRepository
from app.telemetry.exporters import InMemoryTelemetryExporter
from app.telemetry.service import TelemetryService


class PayloadLeakingExporter:
    def export_spans(self, spans):
        raise RuntimeError('{"span_id":"span_1","attributes":{"prompt":"raw prompt","password":"hunter2"}}')


def _app_for(runtime: MemoryRuntime, telemetry: TelemetryService, principal: Principal | None = None) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_runtime] = lambda: runtime
    app.dependency_overrides[get_telemetry_service] = lambda: telemetry
    if principal is not None:
        app.dependency_overrides[require_api_key] = lambda: principal
    return app


def _report_reader_principal() -> Principal:
    return Principal(
        principal_id="report_reader",
        kind="api_key",
        workspace_ids=["ws_tel"],
        roles=[WorkspacePermission.report_reader.value],
    )


async def _seed_run(runtime: MemoryRuntime) -> str:
    run = await runtime.start_run(StartRunRequest(session_id="s_tel", task="telemetry export", workspace_id="ws_tel"))
    step = await runtime.start_step(StartStepRequest(run_id=run.run_id, intent="record"))
    await runtime.write_event(
        WriteEventRequest(
            run_id=run.run_id,
            step_id=step.step_id,
            role=EventRole.user,
            event_type=EventType.message,
            content="raw export text with password=hunter2",
        )
    )
    return run.run_id


async def test_export_run_telemetry_endpoint_returns_counts_without_raw_spans() -> None:
    runtime = MemoryRuntime(InMemoryRepository(), default_workspace_id="ws_tel")
    run_id = await _seed_run(runtime)
    exporter = InMemoryTelemetryExporter()
    telemetry = TelemetryService(exporter=exporter)
    app = _app_for(runtime, telemetry)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(f"/v1/telemetry/export/runs/{run_id}", json={})

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["exported_span_count"] >= 3
    assert payload["dropped_span_count"] == 0
    assert payload["warnings"] == []
    assert "spans" not in payload
    rendered_response = resp.text
    assert "hunter2" not in rendered_response
    assert "raw export text" not in rendered_response


async def test_export_run_telemetry_endpoint_404_for_missing_run() -> None:
    runtime = MemoryRuntime(InMemoryRepository(), default_workspace_id="ws_tel")
    app = _app_for(runtime, TelemetryService(exporter=InMemoryTelemetryExporter()))

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/v1/telemetry/export/runs/run_missing", json={})

    assert resp.status_code == 404
    assert resp.json()["detail"] == "run not found"


async def test_export_run_telemetry_endpoint_requires_report_reader_permission() -> None:
    runtime = MemoryRuntime(InMemoryRepository(), default_workspace_id="ws_tel")
    run_id = await _seed_run(runtime)
    principal = Principal(
        principal_id="reader_only",
        kind="api_key",
        workspace_ids=["ws_tel"],
        roles=[WorkspacePermission.reader.value],
    )
    app = _app_for(runtime, TelemetryService(exporter=InMemoryTelemetryExporter()), principal=principal)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(f"/v1/telemetry/export/runs/{run_id}", json={})

    assert resp.status_code == 403


async def test_export_run_telemetry_endpoint_consumes_report_export_quota() -> None:
    runtime = MemoryRuntime(InMemoryRepository(), default_workspace_id="ws_tel")
    run_id = await _seed_run(runtime)
    app = _app_for(
        runtime,
        TelemetryService(exporter=InMemoryTelemetryExporter()),
        principal=_report_reader_principal(),
    )
    counter = InMemoryQuotaCounter()
    app.dependency_overrides[get_quota_service] = lambda: QuotaService(
        counter,
        Settings(governance_enabled=True, quota_enabled=True, quota_report_export_per_window=1),
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.post(f"/v1/telemetry/export/runs/{run_id}", json={})
        second = await client.post(f"/v1/telemetry/export/runs/{run_id}", json={})

    assert first.status_code == 200
    assert second.status_code == 429


async def test_export_run_telemetry_endpoint_sanitizes_exporter_failure_warnings() -> None:
    runtime = MemoryRuntime(InMemoryRepository(), default_workspace_id="ws_tel")
    run_id = await _seed_run(runtime)
    app = _app_for(runtime, TelemetryService(exporter=PayloadLeakingExporter()))

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(f"/v1/telemetry/export/runs/{run_id}", json={})

    assert resp.status_code == 200
    payload = resp.json()
    assert payload["warnings"] == ["telemetry export failed"]
    rendered = resp.text
    assert "span_1" not in rendered
    assert "raw prompt" not in rendered
    assert "hunter2" not in rendered
