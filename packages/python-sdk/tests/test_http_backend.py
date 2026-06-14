from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from app.api.deps import app_state, get_repository, get_runtime
from app.config import get_settings
from app.main import app
from app.runtime.memory_runtime import MemoryRuntime
from app.runtime.repository import InMemoryRepository
from memtrace_sdk import BadRequestError, ForbiddenError, MemTrace, NotFoundError
from memtrace_sdk.backends import HttpBackend
from memtrace_sdk.types import (
    EventRole,
    EventType,
    FinishStepRequest,
    MemoryConflictRecord,
    MemoryItem,
    MemoryScope,
    MemoryStatus,
    MemoryType,
    MemoryVersionRecord,
    ObservabilityReportRequest,
    RetrievalRequest,
    StartRunRequest,
    StartStepRequest,
    StepStatus,
    WriteEventRequest,
)


def _override_runtime(runtime: MemoryRuntime) -> None:
    app.dependency_overrides[get_runtime] = lambda: runtime
    app_state.repository = runtime._repo  # noqa: SLF001 - test dependency override must match runtime storage
    app.dependency_overrides[get_repository] = lambda: runtime._repo  # noqa: SLF001


@pytest.fixture(autouse=True)
def _clear_overrides():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
    app.dependency_overrides.clear()
    app_state.repository = None


async def _http_client_for(runtime: MemoryRuntime) -> MemTrace:
    _override_runtime(runtime)
    transport = httpx.ASGITransport(app=app)
    http_client = httpx.AsyncClient(transport=transport, base_url="http://test")
    return MemTrace.http("http://test", client=http_client)


async def test_http_backend_runs_golden_path_over_asgi_transport() -> None:
    runtime = MemoryRuntime(InMemoryRepository(), default_workspace_id="ws_http")
    client = await _http_client_for(runtime)

    try:
        run = await client.start_run(StartRunRequest(session_id="http-s1", task="remember runtime"))
        step = await client.start_step(StartStepRequest(run_id=run.run_id, intent="record constraint"))
        write = await client.write_event(
            WriteEventRequest(
                run_id=run.run_id,
                step_id=step.step_id,
                role=EventRole.user,
                event_type=EventType.message,
                content="这个项目使用 Bun",
            )
        )
        finish = await client.finish_step(
            FinishStepRequest(
                run_id=run.run_id,
                step_id=step.step_id,
                status=StepStatus.completed,
                summary="recorded Bun runtime constraint",
            )
        )
        context = await client.retrieve_context(
            RetrievalRequest(run_id=run.run_id, step_id=step.step_id, query="Bun runtime project")
        )
        inspection = await client.inspect_access(context.access_id)
        fetched_step = await client.get_step(step.step_id)
        steps = await client.get_steps(run.run_id)
        timeline = await client.get_timeline(run.run_id)

        assert write.event.event_source == "sdk"
        assert timeline[0].event_source == "sdk"
        assert fetched_step.step_id == step.step_id
        assert finish.step.status == StepStatus.completed
        assert steps == [finish.step]
        assert any(block.type == "project_memory" and "uses Bun" in block.content for block in context.context_blocks)
        assert inspection.access_id == context.access_id
    finally:
        await client.aclose()


async def test_http_backend_api_key_reaches_token_protected_route(monkeypatch) -> None:
    monkeypatch.setenv("MEMTRACE_AUTH_ENABLED", "true")
    monkeypatch.setenv("MEMTRACE_API_KEY", "dev-secret")
    get_settings.cache_clear()
    runtime = MemoryRuntime(InMemoryRepository(), default_workspace_id="ws_http_auth")
    _override_runtime(runtime)
    http_client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    client = MemTrace.http("http://test", api_key="dev-secret", client=http_client)

    try:
        run = await client.start_run(StartRunRequest(session_id="http-auth-s1", task="auth smoke"))
    finally:
        await client.aclose()
        await http_client.aclose()

    assert run.session_id == "http-auth-s1"


async def test_http_backend_maps_404_and_400_to_sdk_errors(tmp_path: Path) -> None:
    runtime = MemoryRuntime(InMemoryRepository(), default_workspace_id="ws_http")
    client = await _http_client_for(runtime)

    try:
        with pytest.raises(NotFoundError):
            await client.inspect_access("acc_missing")

        with pytest.raises(NotFoundError):
            await client.get_step("step_missing")

        outside = tmp_path / ".." / "outside"
        with pytest.raises(BadRequestError):
            await client.write_observability_report(ObservabilityReportRequest(output_dir=str(outside)))
    finally:
        await client.aclose()


async def test_http_backend_maps_403_to_forbidden_error(monkeypatch) -> None:
    monkeypatch.setenv("MEMTRACE_AUTH_ENABLED", "true")
    monkeypatch.setenv("MEMTRACE_API_KEY", "dev-secret")
    get_settings.cache_clear()
    runtime = MemoryRuntime(InMemoryRepository(), default_workspace_id="ws_http_auth")
    _override_runtime(runtime)
    http_client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    client = MemTrace.http("http://test", api_key="wrong-secret", client=http_client)

    try:
        with pytest.raises(ForbiddenError):
            await client.start_run(StartRunRequest(session_id="http-auth-s1", task="auth smoke"))
    finally:
        await client.aclose()
        await http_client.aclose()


async def test_http_backend_maps_missing_api_key_401_to_forbidden_error(monkeypatch) -> None:
    monkeypatch.setenv("MEMTRACE_AUTH_ENABLED", "true")
    monkeypatch.setenv("MEMTRACE_API_KEY", "dev-secret")
    get_settings.cache_clear()
    runtime = MemoryRuntime(InMemoryRepository(), default_workspace_id="ws_http_auth")
    _override_runtime(runtime)
    http_client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    client = MemTrace.http("http://test", client=http_client)

    try:
        with pytest.raises(ForbiddenError):
            await client.start_run(StartRunRequest(session_id="http-auth-s1", task="auth smoke"))
    finally:
        await client.aclose()
        await http_client.aclose()


async def test_http_backend_exposes_memory_versions_and_conflicts() -> None:
    repo = InMemoryRepository()
    runtime = MemoryRuntime(repo, default_workspace_id="ws_http_phase4")
    memory = await repo.add_memory(
        MemoryItem(
            memory_id="mem_sdk_versioned",
            workspace_id="ws_http_phase4",
            memory_type=MemoryType.project,
            key="project.runtime",
            value="bun",
            scope=MemoryScope.workspace,
            content="project.runtime=bun",
            status=MemoryStatus.active,
        )
    )
    await repo.add_memory_version(
        MemoryVersionRecord(
            memory_id=memory.memory_id,
            workspace_id=memory.workspace_id,
            version_no=1,
            snapshot={"value": "bun"},
            change_reason="test",
        )
    )
    await repo.upsert_memory_conflict(
        MemoryConflictRecord(
            conflict_id="mconf_sdk",
            workspace_id="ws_http_phase4",
            subject_key="project.runtime",
            memory_ids=[memory.memory_id, "mem_other"],
            status="open",
        )
    )
    client = await _http_client_for(runtime)

    try:
        versions = await client.list_memory_versions(memory.memory_id)
        conflicts = await client.list_memory_conflicts(workspace_id="ws_http_phase4")
    finally:
        await client.aclose()

    assert [version.version_no for version in versions] == [1]
    assert [conflict.conflict_id for conflict in conflicts] == ["mconf_sdk"]


async def test_http_backend_closes_only_owned_clients() -> None:
    owned_backend = HttpBackend("http://test")
    owned_client = owned_backend._client  # noqa: SLF001 - lifecycle contract assertion

    await owned_backend.aclose()

    assert owned_client.is_closed

    injected = httpx.AsyncClient(base_url="http://test")
    injected_backend = HttpBackend("http://test", client=injected)

    await injected_backend.aclose()

    assert not injected.is_closed
    await injected.aclose()


async def test_http_backend_flush_session_accepts_path_sensitive_session_ids() -> None:
    runtime = MemoryRuntime(InMemoryRepository(), default_workspace_id="ws_http")
    client = await _http_client_for(runtime)

    try:
        result = await client.flush_session("tenant/session")
    finally:
        await client.aclose()

    assert result.session_id == "tenant/session"


async def test_http_backend_maps_422_validation_error_to_bad_request() -> None:
    """FastAPI 422 validation errors must map to SDK BadRequestError, matching the
    TS SDK and the in-process backend's BadRequestError semantics."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"detail": [{"msg": "field required"}]})

    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport, base_url="http://test")
    client = MemTrace.http("http://test", client=http_client)
    try:
        with pytest.raises(BadRequestError):
            await client.start_run(StartRunRequest(workspace_id="ws", session_id="s", task="t"))
    finally:
        await client.aclose()


async def test_http_backend_flush_session_passes_workspace_id_under_auth(monkeypatch) -> None:
    """With auth enabled and a scoped principal, flush_session must forward
    workspace_id or the server returns 403."""
    monkeypatch.setenv("MEMTRACE_AUTH_ENABLED", "true")
    monkeypatch.setenv("MEMTRACE_API_KEY", "dev-secret")
    get_settings.cache_clear()
    runtime = MemoryRuntime(InMemoryRepository(), default_workspace_id="ws_http_auth")
    _override_runtime(runtime)
    http_client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    client = MemTrace.http("http://test", api_key="dev-secret", client=http_client)
    try:
        result = await client.flush_session("sess-1", workspace_id="ws_http_auth")
    finally:
        await client.aclose()

    assert result.session_id == "sess-1"
