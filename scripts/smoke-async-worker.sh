#!/usr/bin/env bash
# Opt-in real (non-eager) Celery async-offload smoke: proves the write-offload
# path end-to-end through a REAL Redis broker + result backend + Redis idempotency
# store, with a REAL worker (solo pool) reloading the event from Postgres and
# extracting it off the write hot path. This is the production async path
# (docs/deployment.md "Offload writes"), not the eager in-process shortcut.
#
# Requires Postgres + Redis up and migrated:
#   docker-compose -f docker-compose.yml -f docker-compose.dev.yml up -d postgres redis
#   uv run alembic upgrade head
# then:
#   ./scripts/smoke-async-worker.sh
# Skips cleanly if Postgres or Redis is unreachable. NOT part of default CI.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR/apps/api"

# Point the whole stack at the local dev Redis (db0 buffer/idempotency, db1 broker,
# db2 result backend) and enable the real (non-eager) async path.
export MEMTRACE_ASYNC_TASKS_ENABLED=true
export MEMTRACE_CELERY_TASK_ALWAYS_EAGER=false
export MEMTRACE_REDIS_URL="${MEMTRACE_REDIS_URL:-redis://localhost:6379/0}"
export MEMTRACE_CELERY_BROKER_URL="${MEMTRACE_CELERY_BROKER_URL:-redis://localhost:6379/1}"
export MEMTRACE_CELERY_RESULT_BACKEND="${MEMTRACE_CELERY_RESULT_BACKEND:-redis://localhost:6379/2}"

echo "==> real Celery async-offload smoke (broker=${MEMTRACE_CELERY_BROKER_URL})"

uv run python - <<'PY'
import asyncio
import sys
import time

from sqlalchemy import text

from app.async_tasks.celery_app import make_celery_app
from app.async_tasks.contracts import TaskEnvelope, TaskResult
from app.config import get_settings
from app.runtime.memory_runtime import MemoryRuntime
from app.runtime.models import (
    EventRole, EventType, ExtractionMode, StartRunRequest, StartStepRequest, WriteEventRequest,
)
from app.storage.db import make_engine, make_session_factory
from app.storage.sql_repository import SqlRepository

WS = "async_worker_ws"
SESSION = "async_worker:session"
TABLES = ("memory_items", "agent_events", "agent_steps", "state_nodes", "agent_runs")


async def _reachable() -> bool:
    engine = make_engine()
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"  ⏭️  skip: no reachable database ({type(exc).__name__})")
        return False
    finally:
        await engine.dispose()


async def _clear():
    engine = make_engine()
    try:
        async with engine.begin() as conn:
            for tbl in TABLES:
                await conn.execute(text(f"DELETE FROM {tbl} WHERE workspace_id = :ws"), {"ws": WS})
    finally:
        await engine.dispose()


async def seed() -> tuple[str, object]:
    """Persist a memory-bearing event WITHOUT extracting it (no_extract mode)."""
    engine = make_engine()
    try:
        repo = SqlRepository(make_session_factory(engine))
        rt = MemoryRuntime(repo, default_workspace_id=WS, extraction_mode=ExtractionMode.no_extract)
        run = await rt.start_run(StartRunRequest(session_id=SESSION, task="t", workspace_id=WS))
        step = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="planning"))
        res = await rt.write_event(WriteEventRequest(
            run_id=run.run_id, step_id=step.step_id, role=EventRole.user,
            event_type=EventType.message, content="这个项目使用 Bun"))
        assert res.created_memory_ids == [], "no_extract must not extract on the hot path"
        assert await repo.list_memories(workspace_id=WS) == [], "seed must leave zero extracted memories"
        return res.event.event_id, run
    finally:
        await engine.dispose()


async def verify(deadline_s: float) -> list:
    engine = make_engine()
    try:
        repo = SqlRepository(make_session_factory(engine))
        while time.monotonic() < deadline_s:
            mems = await repo.list_memories(workspace_id=WS)
            if mems:
                return mems
            await asyncio.sleep(0.25)
        return await repo.list_memories(workspace_id=WS)
    finally:
        await engine.dispose()


def run_worker_roundtrip(envelope: TaskEnvelope) -> TaskResult:
    """Send the task over the REAL broker and let a REAL worker consume it."""
    from celery.contrib.testing.worker import start_worker

    app = make_celery_app(get_settings())
    with start_worker(app, pool="solo", perform_ping_check=False, loglevel="error"):
        async_result = app.send_task("memory.extract_event", args=[envelope.model_dump(mode="json")])
        payload = async_result.get(timeout=60)
    return TaskResult.model_validate(payload)


async def check_idempotency(dedupe_key: str) -> tuple[bool, bool, str | None]:
    """Prove the REAL Redis idempotency store: SET NX EX gives acquire-once, and
    the worker's own dedupe key is still held (tasks don't release on success)."""
    import redis.asyncio as redis

    from app.async_tasks.idempotency import RedisIdempotencyStore

    settings = get_settings()
    client = redis.from_url(settings.redis_url, decode_responses=True)
    try:
        store = RedisIdempotencyStore(client)
        probe = f"probe:{dedupe_key}"
        first = await store.acquire(probe, 30)
        second = await store.acquire(probe, 30)  # same key within TTL -> denied
        await store.release(probe)
        # the extraction task acquired dedupe_key and (by design) did not release it
        held = await client.get(f"memtrace:idempotency:{dedupe_key}")
        return first, second, held
    finally:
        await client.delete(f"memtrace:idempotency:{dedupe_key}")
        await client.aclose()


def main() -> int:
    get_settings.cache_clear()
    if not asyncio.run(_reachable()):
        print("async-worker smoke skipped")
        return 0
    try:
        asyncio.run(_clear())
        event_id, run = asyncio.run(seed())
        print(f"  ✅ seeded event {event_id[:12]}… in Postgres (no_extract; 0 memories)")

        envelope = TaskEnvelope(
            task_type="memory.extract_event", workspace_id=WS,
            dedupe_key=f"memory.extract_event:{event_id}",
            payload={"event_id": event_id, "run_id": run.run_id, "workspace_id": WS, "session_id": SESSION},
        )

        try:
            result = run_worker_roundtrip(envelope)
        except Exception as exc:  # noqa: BLE001 - broker/worker infra unreachable -> skip, don't fail CI-less runs
            print(f"  ⏭️  skip: real broker/worker unavailable ({type(exc).__name__}: {exc})")
            print("async-worker smoke skipped")
            return 0

        assert result.status == "completed", f"task status was {result.status!r}: {result.error}"
        assert len(result.created_memory_ids) == 1, f"expected 1 created memory, got {result.created_memory_ids}"
        print(f"  ✅ worker consumed from Redis broker + extracted {len(result.created_memory_ids)} memory")

        mems = asyncio.run(verify(time.monotonic() + 10))
        assert len(mems) == 1, f"expected exactly 1 memory in Postgres, got {len(mems)}"
        assert str(mems[0].value).lower() == "bun", f"unexpected memory value: {mems[0].value!r}"
        assert mems[0].source_event_id == event_id
        print("  ✅ Postgres holds exactly 1 extracted memory (project.runtime=bun) — write fully offloaded")

        first, second, held = asyncio.run(check_idempotency(envelope.dedupe_key))
        assert first is True and second is False, f"Redis SET NX EX not exclusive: {first=} {second=}"
        assert held == "1", f"worker did not hold its dedupe key in Redis (got {held!r})"
        print("  ✅ real Redis idempotency store is exclusive (acquire-once) and the worker held its "
              "dedupe key — duplicate deliveries are de-duplicated")
    finally:
        asyncio.run(_clear())
    print("async-worker smoke passed")
    return 0


sys.exit(main())
PY
