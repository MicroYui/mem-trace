"""Cross-worker async buffer validation (opt-in; needs BOTH Redis and Postgres).

Proves the production async-scale claim behind the shared Redis candidate buffer
(docs/deployment.md "Offload writes" / ROADMAP §3.4): a memory-bearing event that
"worker 1" writes in ``buffered`` mode and never flushes locally is drained and
extracted by a *separate* "worker 2" through the shared Redis buffer, with the
persisted event reloaded from the shared Postgres source of truth. Also verifies
cross-worker idempotency: a second flush from either worker creates nothing.

This is the scale property the in-process buffer cannot give (each process has its
own buffer); Redis makes the buffer shared so any worker can flush any session.

Skips cleanly when either backend is unreachable, so it never breaks the default
no-network suite. Run it with, e.g.:

    docker-compose -f docker-compose.yml -f docker-compose.dev.yml up -d postgres redis
    uv run alembic upgrade head
    MEMTRACE_TEST_REDIS_URL=redis://localhost:6379/15 \
      uv run --extra dev pytest apps/api/tests/integration/test_async_cross_worker.py -q -s
"""
from __future__ import annotations

import os

import pytest
from sqlalchemy import text

from app.config import get_settings
from app.memory.redis_candidate_buffer import RedisCandidateBuffer
from app.runtime.memory_runtime import MemoryRuntime
from app.runtime.models import (
    EventRole,
    EventType,
    ExtractionMode,
    StartRunRequest,
    StartStepRequest,
    WriteEventRequest,
)
from app.storage.db import make_engine, make_session_factory
from app.storage.sql_repository import SqlRepository

_WS = "xworker_ws"
_SESSION = "xworker:session"
_PREFIX = "memtrace:test:xworker"
_REDIS_URL = os.environ.get("MEMTRACE_TEST_REDIS_URL")
# workspace-scoped tables extraction/tracing touch, ordered children-before-parents
# (only agent_events/agent_steps/state_nodes FK agent_runs; memory_items has no FK).
_TABLES = ("memory_items", "agent_events", "agent_steps", "state_nodes", "agent_runs")


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def _engine_or_skip():
    engine = make_engine()
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        await engine.dispose()
        pytest.skip(f"no reachable database ({type(exc).__name__}): {exc}")
    return engine


@pytest.mark.skipif(not _REDIS_URL, reason="set MEMTRACE_TEST_REDIS_URL to run the cross-worker async validation")
async def test_buffered_write_on_worker1_is_flushed_and_extracted_by_worker2():
    import redis.asyncio as redis

    engine = await _engine_or_skip()
    # Two Redis clients over the same URL+prefix model two worker processes that
    # share one logical buffer; two SqlRepositories over the same engine model two
    # workers sharing one Postgres source of truth.
    client1 = redis.from_url(_REDIS_URL, decode_responses=True)
    client2 = redis.from_url(_REDIS_URL, decode_responses=True)
    buffer1 = RedisCandidateBuffer(client1, prefix=_PREFIX)
    buffer2 = RedisCandidateBuffer(client2, prefix=_PREFIX)

    async def _clear_redis():
        async for key in client1.scan_iter(f"{_PREFIX}:*"):
            await client1.delete(key)

    async def _clear_pg():
        async with engine.begin() as conn:
            for tbl in _TABLES:
                await conn.execute(text(f"DELETE FROM {tbl} WHERE workspace_id = :ws"), {"ws": _WS})

    try:
        await _clear_redis()
        await _clear_pg()

        repo1 = SqlRepository(make_session_factory(engine))
        repo2 = SqlRepository(make_session_factory(engine))
        worker1 = MemoryRuntime(repo1, default_workspace_id=_WS, candidate_buffer=buffer1,
                                extraction_mode=ExtractionMode.buffered)
        worker2 = MemoryRuntime(repo2, default_workspace_id=_WS, candidate_buffer=buffer2,
                                extraction_mode=ExtractionMode.buffered)

        # --- worker 1: write a memory-bearing event, but DO NOT finish the step ---
        # (finish_step is the natural boundary that would drain/extract locally; by
        #  leaving it open we force the extraction to happen on the *other* worker.)
        run = await worker1.start_run(StartRunRequest(session_id=_SESSION, task="t", workspace_id=_WS))
        step = await worker1.start_step(StartStepRequest(run_id=run.run_id, intent="planning"))
        write = await worker1.write_event(WriteEventRequest(
            run_id=run.run_id, step_id=step.step_id, role=EventRole.user,
            event_type=EventType.message, content="这个项目使用 Bun"))

        assert write.buffered is True
        assert write.created_memory_ids == []  # deferred, not extracted on worker 1
        assert await repo1.list_memories(workspace_id=_WS) == []  # nothing in Postgres yet

        # the pending event is visible to worker 2 THROUGH the shared Redis buffer
        pending = await buffer2.pending(_SESSION)
        assert [e.content for e in pending] == ["这个项目使用 Bun"]
        assert await buffer2.total_size() == 1

        # --- worker 2: flush the shared session; drains Redis + extracts from shared PG ---
        flush = await worker2.flush_session(_SESSION, workspace_id=_WS)
        assert flush.processed_event_count == 1
        assert len(flush.created_memory_ids) == 1

        # the memory now exists in Postgres, extracted by worker 2 from worker 1's event
        mems = await repo2.list_memories(workspace_id=_WS)
        assert len(mems) == 1
        mem = mems[0]
        assert mem.key == "project.runtime"
        assert str(mem.value).lower() == "bun"  # value may be ontology-normalized to lowercase
        assert (mem.source_event_id == write.event.event_id
                or write.event.event_id in (mem.source_event_ids or []))

        # the shared buffer is now empty from either worker's view
        assert await buffer1.total_size() == 0

        # --- cross-worker idempotency: re-flush by either worker creates nothing ---
        again2 = await worker2.flush_session(_SESSION, workspace_id=_WS)
        assert again2.processed_event_count == 0
        assert again2.created_memory_ids == []
        again1 = await worker1.flush_session(_SESSION, workspace_id=_WS)
        assert again1.created_memory_ids == []
        assert len(await repo1.list_memories(workspace_id=_WS)) == 1

        print("\n[x-worker] worker1 buffered write -> worker2 drained shared Redis + extracted 1 "
              "memory from shared PG; re-flush from either worker is idempotent (still 1 memory)")
    finally:
        await _clear_redis()
        await _clear_pg()
        await client1.aclose()
        await client2.aclose()
        await engine.dispose()
