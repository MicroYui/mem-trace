"""Task wrappers that call MemoryRuntime-level entrypoints."""
from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from typing import Any

from app.async_tasks.contracts import TaskEnvelope, TaskResult
from app.async_tasks.idempotency import IdempotencyStore, InMemoryIdempotencyStore, RedisIdempotencyStore
from app.async_tasks.runtime_factory import WorkerRuntimeHandle, build_worker_runtime
from app.config import Settings, get_settings
from app.memory.maintenance import run_workspace_maintenance
from app.runtime.models import MaintenanceOperation, SchedulerRunStatus


_runtime_factory: Callable[[], Any] | None = None
_idempotency_store: IdempotencyStore | None = None
_default_in_memory_store = InMemoryIdempotencyStore()
_settings_idempotency_store: IdempotencyStore | None = None
_settings_redis_client: Any | None = None


def set_task_dependencies(
    *,
    runtime_factory: Callable[[], Any] | None,
    idempotency_store: IdempotencyStore | None,
) -> None:
    """Inject eager-test dependencies without touching FastAPI app_state."""
    global _runtime_factory, _idempotency_store
    _runtime_factory = runtime_factory
    _idempotency_store = idempotency_store


def process_event_extraction(envelope_payload: dict[str, Any]) -> dict[str, Any]:
    return _run_coro_sync(_process_event_extraction(envelope_payload))


def process_memory_maintenance(envelope_payload: dict[str, Any]) -> dict[str, Any]:
    return _run_coro_sync(_process_memory_maintenance(envelope_payload))


def _run_coro_sync(coro):
    """Run an async task body from Celery's sync wrapper.

    Celery eager mode can execute this synchronous task wrapper inside an
    already-running FastAPI/pytest event loop. ``asyncio.run(...)`` cannot be
    nested there, so run the coroutine in a short-lived worker thread in that
    case while preserving normal worker-process behavior otherwise.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: dict[str, Any] | None = None
    error: BaseException | None = None

    def runner() -> None:
        nonlocal result, error
        try:
            result = asyncio.run(coro)
        except BaseException as exc:  # noqa: BLE001 - propagate exact task failure to Celery
            error = exc

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join()
    if error is not None:
        raise error
    assert result is not None
    return result


async def _process_event_extraction(envelope_payload: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    envelope = TaskEnvelope.model_validate(envelope_payload)
    store = _idempotency_store or _settings_backed_idempotency_store(settings)
    acquired = await store.acquire(envelope.dedupe_key, settings.async_task_default_ttl_seconds)
    if not acquired:
        return TaskResult(
            task_id=envelope.task_id,
            task_type=envelope.task_type,
            status="skipped",
            duplicate=True,
            metadata={"reason": "duplicate"},
        ).model_dump(mode="json")

    handle = None
    try:
        runtime_or_handle = (_runtime_factory or (lambda: build_worker_runtime(Settings())))()
        if isinstance(runtime_or_handle, WorkerRuntimeHandle):
            handle = runtime_or_handle
            runtime = runtime_or_handle.runtime
        else:
            runtime = runtime_or_handle
        event_id = str(envelope.payload["event_id"])
        created = await runtime.process_event_extraction(event_id)
        return TaskResult(
            task_id=envelope.task_id,
            task_type=envelope.task_type,
            status="completed",
            created_memory_ids=created,
        ).model_dump(mode="json")
    except Exception:
        await store.release(envelope.dedupe_key)
        raise
    finally:
        if handle is not None:
            await handle.aclose()


async def _process_memory_maintenance(envelope_payload: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    envelope = TaskEnvelope.model_validate(envelope_payload)
    store = _idempotency_store or _settings_backed_idempotency_store(settings)
    acquired = await store.acquire(envelope.dedupe_key, settings.async_task_default_ttl_seconds)
    if not acquired:
        return TaskResult(
            task_id=envelope.task_id,
            task_type=envelope.task_type,
            status="skipped",
            duplicate=True,
            metadata={"reason": "duplicate"},
        ).model_dump(mode="json")

    handle = None
    try:
        runtime_or_handle = (_runtime_factory or (lambda: build_worker_runtime(Settings())))()
        if isinstance(runtime_or_handle, WorkerRuntimeHandle):
            handle = runtime_or_handle
            runtime = runtime_or_handle.runtime
        else:
            runtime = runtime_or_handle
        repo = runtime._repo  # noqa: SLF001 - worker boundary intentionally calls runtime-owned repository
        operations = _maintenance_operations_from_payload(envelope.payload)
        run = await run_workspace_maintenance(
            repo,
            workspace_id=envelope.workspace_id,
            operations=operations,
            requested_by=str(envelope.payload.get("requested_by") or "celery"),
            dry_run=bool(envelope.payload.get("dry_run", False)),
            reason=envelope.payload.get("reason"),
            scheduler_run_id=envelope.payload.get("scheduler_run_id"),
        )
        metadata = {
            "scheduler_run_id": run.scheduler_run_id,
            "workspace_id": run.workspace_id,
            "operations": [operation.value for operation in run.operations],
            **run.summary,
        }
        if run.status == SchedulerRunStatus.failed:
            await store.release(envelope.dedupe_key)
            return TaskResult(
                task_id=envelope.task_id,
                task_type=envelope.task_type,
                status="failed",
                error="maintenance run failed",
                metadata=metadata,
            ).model_dump(mode="json")
        return TaskResult(
            task_id=envelope.task_id,
            task_type=envelope.task_type,
            status="completed",
            metadata=metadata,
        ).model_dump(mode="json")
    except Exception:
        await store.release(envelope.dedupe_key)
        raise
    finally:
        if handle is not None:
            await handle.aclose()


def _settings_backed_idempotency_store(settings: Settings) -> IdempotencyStore:
    """Return the production idempotency store without import-time network effects."""
    global _settings_idempotency_store, _settings_redis_client
    if settings.async_tasks_enabled and settings.redis_url:
        if _settings_idempotency_store is None:
            import redis.asyncio as redis

            _settings_redis_client = redis.from_url(settings.redis_url, decode_responses=True)
            _settings_idempotency_store = RedisIdempotencyStore(_settings_redis_client)
        return _settings_idempotency_store
    return _default_in_memory_store


def _maintenance_operations_from_payload(payload: dict[str, Any]) -> list[MaintenanceOperation]:
    if "operations" in payload:
        return [MaintenanceOperation(str(operation)) for operation in payload["operations"]]
    if "operation" in payload:
        return [MaintenanceOperation(str(payload["operation"]))]
    raise ValueError("maintenance operation required")


__all__ = ["process_event_extraction", "process_memory_maintenance", "set_task_dependencies"]
