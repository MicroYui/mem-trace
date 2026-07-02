"""Live SQL candidate-prefilter verification (opt-in; needs a reachable Postgres).

Skips cleanly when the configured database is unreachable, so it never breaks the
default no-network suite. When a DB is up (e.g. `docker compose up -d postgres`
+ `alembic upgrade head`), it verifies the SqlRepository prefilter is correct AND
prints the retrieve latency with the bounded prefilter off vs on at scale.
"""
from __future__ import annotations

import time

import pytest
from sqlalchemy import text

from app.config import get_settings
from app.runtime.memory_runtime import MemoryRuntime
from app.runtime.models import (
    MemoryItem,
    MemoryScope,
    MemoryType,
    RetrievalRequest,
    RetrievalStrategy,
    StartRunRequest,
    StartStepRequest,
)
from app.storage.db import make_engine, make_session_factory
from app.storage.sql_repository import SqlRepository

_WS = "perf_sql_ws"
_N = 3000
_TOPICS = ["cache layer", "database", "test runner", "message broker", "cloud provider"]


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


def _mem(i: int, content: str) -> MemoryItem:
    return MemoryItem(memory_id=f"psql_m_{i}", workspace_id=_WS, memory_type=MemoryType.episodic,
                      scope=MemoryScope.workspace, content=content, summary=content[:60])


async def _seed(repo: SqlRepository, engine) -> None:
    # idempotent: clear this test's rows first (fixed ids would collide on re-run)
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM memory_items WHERE workspace_id = :ws"), {"ws": _WS})
    for i in range(_N):
        topic = _TOPICS[i % len(_TOPICS)]
        await repo.add_memory(_mem(i, f"note {i}: the {topic} for module {i} is value_{i}"))
    # a unique-token target so recall is unambiguous
    await repo.add_memory(_mem(9999, "the escalation contact is zoe-pager for production incidents"))


@pytest.mark.asyncio
async def test_sql_prefilter_correct_and_faster(monkeypatch):
    engine = await _engine_or_skip()
    try:
        repo = SqlRepository(make_session_factory(engine))
        await _seed(repo, engine)

        # 1) prefilter returns the unique-token target
        ids = await repo.prefilter_candidate_ids(
            workspace_id=_WS, query="who is the escalation contact zoe-pager", limit=800)
        assert "psql_m_9999" in ids
        assert len(ids) <= 800

        # 2) bounded loader returns only requested ids (+ types)
        got = await repo.list_candidate_memories(
            workspace_id=_WS, ids=["psql_m_9999", "psql_m_1"], include_types=())
        assert {m.memory_id for m in got} == {"psql_m_9999", "psql_m_1"}

        # 3) full retrieval recalls the target under the bounded prefilter, and we
        #    print off-vs-on latency (correctness asserted; timing informational).
        query = "who is the escalation contact zoe-pager"

        async def _retrieve_ms(limit: int) -> tuple[float, list[str]]:
            monkeypatch.setenv("MEMTRACE_RETRIEVAL_CANDIDATE_LIMIT", str(limit))
            get_settings.cache_clear()
            rt = MemoryRuntime(repo, default_workspace_id=_WS)
            run = await rt.start_run(StartRunRequest(session_id="perf", task="perf", workspace_id=_WS))
            step = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="answer"))
            await rt.retrieve_context(RetrievalRequest(  # warmup
                run_id=run.run_id, step_id=step.step_id, query=query, strategy=RetrievalStrategy.variant_2))
            t0 = time.perf_counter()
            ctx = await rt.retrieve_context(RetrievalRequest(
                run_id=run.run_id, step_id=step.step_id, query=query, strategy=RetrievalStrategy.variant_2))
            ms = (time.perf_counter() - t0) * 1000.0
            block_text = " ".join((b.content or "").lower() for b in ctx.context_blocks)
            return ms, block_text

        off_ms, off_text = await _retrieve_ms(0)
        on_ms, on_text = await _retrieve_ms(800)
        assert "zoe-pager" in off_text  # full scan recalls it
        assert "zoe-pager" in on_text   # bounded prefilter also recalls it
        print(f"\n[sql perf] N={_N + 1}  retrieve p1: off(candidate_limit=0)={off_ms:.1f}ms  on(=800)={on_ms:.1f}ms")
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM memory_items WHERE workspace_id = :ws"), {"ws": _WS})
        await engine.dispose()
