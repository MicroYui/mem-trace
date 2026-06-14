from __future__ import annotations

import asyncio
import time

from app.async_tasks.celery_app import make_celery_app
from app.async_tasks.contracts import TaskEnvelope
from app.async_tasks.idempotency import InMemoryIdempotencyStore
from app.async_tasks import tasks as task_module
from app.async_tasks.tasks import process_event_extraction, process_memory_maintenance, set_task_dependencies
from app.config import Settings
from app.memory import maintenance
from app.runtime.models import MaintenanceOperation
from app.runtime.models import MemoryItem, MemoryType
from app.runtime.repository import InMemoryRepository


def _settings() -> Settings:
    return Settings(
        async_tasks_enabled=False,
        celery_task_always_eager=True,
        celery_broker_url="memory://",
        celery_result_backend=None,
    )


def test_make_celery_app_registers_queues_and_json_serialization():
    app = make_celery_app(_settings())

    assert {queue.name for queue in app.conf.task_queues} == {
        "memtrace.memory",
        "memtrace.maintenance",
        "memtrace.eval",
    }
    assert app.conf.task_always_eager is True
    assert app.conf.task_serializer == "json"
    assert app.conf.accept_content == ["json"]
    assert app.conf.result_serializer == "json"
    assert app.conf.result_backend is None
    assert "memory.extract_event" in app.tasks
    assert "maintenance.memory" in app.tasks


def test_eager_task_executes_inline_without_redis_or_fastapi_runtime():
    calls: list[str] = []

    class FakeRuntime:
        async def process_event_extraction(self, event_id: str) -> list[str]:
            calls.append(event_id)
            return ["mem_1"]

    set_task_dependencies(runtime_factory=lambda: FakeRuntime(), idempotency_store=InMemoryIdempotencyStore())
    envelope = TaskEnvelope(
        task_type="memory.extract_event",
        workspace_id="ws1",
        dedupe_key="extract:event_1",
        payload={"event_id": "event_1"},
    )

    try:
        result = process_event_extraction(envelope.model_dump(mode="json"))
    finally:
        set_task_dependencies(runtime_factory=None, idempotency_store=None)

    assert calls == ["event_1"]
    assert result["status"] == "completed"
    assert result["created_memory_ids"] == ["mem_1"]
    assert result["duplicate"] is False


async def test_eager_task_executes_from_running_event_loop_without_runtime_error():
    calls: list[str] = []

    class FakeRuntime:
        async def process_event_extraction(self, event_id: str) -> list[str]:
            calls.append(event_id)
            return ["mem_1"]

    set_task_dependencies(runtime_factory=lambda: FakeRuntime(), idempotency_store=InMemoryIdempotencyStore())
    celery_app = make_celery_app(_settings())
    envelope = TaskEnvelope(
        task_type="memory.extract_event",
        workspace_id="ws1",
        dedupe_key="extract:event_loop",
        payload={"event_id": "event_loop"},
    )

    try:
        result = celery_app.tasks["memory.extract_event"].apply_async(args=[envelope.model_dump(mode="json")])
    finally:
        set_task_dependencies(runtime_factory=None, idempotency_store=None)

    assert result.result["status"] == "completed"
    assert result.result["created_memory_ids"] == ["mem_1"]
    assert calls == ["event_loop"]


async def test_eager_task_from_running_event_loop_propagates_task_errors():
    class FakeRuntime:
        async def process_event_extraction(self, event_id: str) -> list[str]:
            raise RuntimeError(f"boom:{event_id}")

    set_task_dependencies(runtime_factory=lambda: FakeRuntime(), idempotency_store=InMemoryIdempotencyStore())
    celery_app = make_celery_app(_settings())
    envelope = TaskEnvelope(
        task_type="memory.extract_event",
        workspace_id="ws1",
        dedupe_key="extract:event_loop_error",
        payload={"event_id": "event_loop_error"},
    )

    try:
        try:
            celery_app.tasks["memory.extract_event"].apply_async(args=[envelope.model_dump(mode="json")])
        except RuntimeError as exc:
            assert str(exc) == "boom:event_loop_error"
        else:  # pragma: no cover - assertion clarity if eager propagation regresses
            raise AssertionError("expected task error to propagate")
    finally:
        set_task_dependencies(runtime_factory=None, idempotency_store=None)


def test_task_idempotency_skips_duplicate_until_release():
    calls: list[str] = []
    store = InMemoryIdempotencyStore()

    class FakeRuntime:
        async def process_event_extraction(self, event_id: str) -> list[str]:
            calls.append(event_id)
            return [f"mem_{len(calls)}"]

    envelope = TaskEnvelope(
        task_type="memory.extract_event",
        workspace_id="ws1",
        dedupe_key="extract:event_1",
        payload={"event_id": "event_1"},
    )
    set_task_dependencies(runtime_factory=lambda: FakeRuntime(), idempotency_store=store)
    try:
        first = process_event_extraction(envelope.model_dump(mode="json"))
        second = process_event_extraction(envelope.model_dump(mode="json"))
        asyncio.run(store.release("extract:event_1"))
        third = process_event_extraction(envelope.model_dump(mode="json"))
    finally:
        set_task_dependencies(runtime_factory=None, idempotency_store=None)

    assert [first["duplicate"], second["duplicate"], third["duplicate"]] == [False, True, False]
    assert calls == ["event_1", "event_1"]


def test_maintenance_task_uses_workspace_operation_and_idempotency():
    store = InMemoryIdempotencyStore()
    repo = InMemoryRepository()
    asyncio.run(
        repo.add_memory(
            MemoryItem(workspace_id="ws_maint", memory_type=MemoryType.project, content="Use bun")
        )
    )

    class FakeRuntime:
        _repo = repo

    envelope = TaskEnvelope(
        task_type="maintenance.memory",
        workspace_id="ws_maint",
        dedupe_key="maintenance:score_memory:ws_maint:window_1",
        payload={"operation": "score_memory", "scheduler_run_id": "window_1"},
    )
    set_task_dependencies(runtime_factory=lambda: FakeRuntime(), idempotency_store=store)
    try:
        first = process_memory_maintenance(envelope.model_dump(mode="json"))
        second = process_memory_maintenance(envelope.model_dump(mode="json"))
    finally:
        set_task_dependencies(runtime_factory=None, idempotency_store=None)

    assert first["status"] == "completed"
    assert first["metadata"]["operations"] == ["score_memory"]
    assert first["metadata"]["completed_count"] == 1
    assert second["duplicate"] is True

    runs = asyncio.run(repo.list_maintenance_runs(workspace_id="ws_maint"))
    assert len(runs) == 1
    attempts = asyncio.run(repo.list_maintenance_task_attempts(scheduler_run_id=runs[0].scheduler_run_id))
    assert len(attempts) == 1
    assert attempts[0].result["scored_count"] == 1


def test_maintenance_task_accepts_operations_list_payload():
    store = InMemoryIdempotencyStore()
    repo = InMemoryRepository()

    class FakeRuntime:
        _repo = repo

    envelope = TaskEnvelope(
        task_type="maintenance.memory",
        workspace_id="ws_maint",
        dedupe_key="maintenance:multi:ws_maint:window_1",
        payload={"operations": ["score_memory", "profile_refresh"], "requested_by": "celery:test"},
    )
    set_task_dependencies(runtime_factory=lambda: FakeRuntime(), idempotency_store=store)
    try:
        result = process_memory_maintenance(envelope.model_dump(mode="json"))
    finally:
        set_task_dependencies(runtime_factory=None, idempotency_store=None)

    assert result["status"] == "completed"
    assert result["metadata"]["operations"] == ["score_memory", "profile_refresh"]
    assert result["metadata"]["completed_count"] == 2


def test_maintenance_task_failed_run_returns_failed_and_releases_idempotency(monkeypatch):
    store = InMemoryIdempotencyStore()
    repo = InMemoryRepository()
    calls = 0

    async def boom(*args, **kwargs):  # noqa: ANN002, ANN003
        nonlocal calls
        calls += 1
        raise RuntimeError("maintenance failed")

    class FakeRuntime:
        _repo = repo

    envelope = TaskEnvelope(
        task_type="maintenance.memory",
        workspace_id="ws_maint",
        dedupe_key="maintenance:failed:ws_maint:window_1",
        payload={"operation": "score_memory", "requested_by": "celery:test"},
    )
    monkeypatch.setitem(maintenance.OPERATION_HANDLERS, MaintenanceOperation.score_memory, boom)
    set_task_dependencies(runtime_factory=lambda: FakeRuntime(), idempotency_store=store)
    try:
        first = process_memory_maintenance(envelope.model_dump(mode="json"))
        second = process_memory_maintenance(envelope.model_dump(mode="json"))
    finally:
        set_task_dependencies(runtime_factory=None, idempotency_store=None)

    assert first["status"] == "failed"
    assert first["error"] == "maintenance run failed"
    assert first["metadata"]["failed_count"] == 1
    assert second["status"] == "failed"
    assert calls == 2


async def test_in_memory_idempotency_store_expires_keys():
    store = InMemoryIdempotencyStore()

    assert await store.acquire("k", ttl_seconds=1) is True
    assert await store.acquire("k", ttl_seconds=1) is False
    store._entries["k"] = time.monotonic() - 1  # noqa: SLF001 - force expiry in a pure unit test
    assert await store.acquire("k", ttl_seconds=1) is True


def test_default_task_dependencies_keep_process_local_idempotency():
    calls: list[str] = []

    class FakeRuntime:
        async def process_event_extraction(self, event_id: str) -> list[str]:
            calls.append(event_id)
            return ["mem_1"]

    envelope = TaskEnvelope(
        task_type="memory.extract_event",
        workspace_id="ws1",
        dedupe_key="extract:event_default_store",
        payload={"event_id": "event_1"},
    )
    set_task_dependencies(runtime_factory=lambda: FakeRuntime(), idempotency_store=None)
    try:
        first = process_event_extraction(envelope.model_dump(mode="json"))
        second = process_event_extraction(envelope.model_dump(mode="json"))
    finally:
        set_task_dependencies(runtime_factory=None, idempotency_store=None)

    assert first["duplicate"] is False
    assert second["duplicate"] is True
    assert calls == ["event_1"]


def test_default_task_dependencies_use_redis_store_when_async_enabled(monkeypatch):
    calls: list[str] = []

    class FakeRuntime:
        async def process_event_extraction(self, event_id: str) -> list[str]:
            calls.append(event_id)
            return ["mem_1"]

    class FakeRedis:
        def __init__(self) -> None:
            self.keys: set[str] = set()

        async def set(self, key, value, *, nx, ex):
            assert nx is True
            assert ex >= 1
            if key in self.keys:
                return False
            self.keys.add(key)
            return True

        async def delete(self, key):
            self.keys.discard(key)

    fake_redis = FakeRedis()
    seen_urls: list[str] = []

    def fake_from_url(url, *, decode_responses):
        seen_urls.append(url)
        assert decode_responses is True
        return fake_redis

    monkeypatch.setattr(task_module, "get_settings", lambda: Settings(async_tasks_enabled=True, redis_url="redis://example/0"))
    monkeypatch.setattr("redis.asyncio.from_url", fake_from_url)
    monkeypatch.setattr(task_module, "_settings_idempotency_store", None)
    monkeypatch.setattr(task_module, "_settings_redis_client", None)
    envelope = TaskEnvelope(
        task_type="memory.extract_event",
        workspace_id="ws1",
        dedupe_key="extract:event_redis_store",
        payload={"event_id": "event_1"},
    )
    set_task_dependencies(runtime_factory=lambda: FakeRuntime(), idempotency_store=None)
    try:
        first = process_event_extraction(envelope.model_dump(mode="json"))
        second = process_event_extraction(envelope.model_dump(mode="json"))
    finally:
        set_task_dependencies(runtime_factory=None, idempotency_store=None)
        monkeypatch.setattr(task_module, "_settings_idempotency_store", None)
        monkeypatch.setattr(task_module, "_settings_redis_client", None)

    assert seen_urls == ["redis://example/0"]
    assert first["duplicate"] is False
    assert second["duplicate"] is True
    assert calls == ["event_1"]
