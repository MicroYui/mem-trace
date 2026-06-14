"""Optional P4-A5 async infrastructure smoke tests."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.memory.redis_candidate_buffer import RedisCandidateBuffer
from app.runtime.models import AgentEvent, EventRole, EventType


ROOT = Path(__file__).resolve().parents[4]


def test_dev_compose_adds_redis_and_worker_without_changing_core_compose():
    core = (ROOT / "docker-compose.yml").read_text()
    dev = (ROOT / "docker-compose.dev.yml").read_text()

    assert "pgvector/pgvector:pg16" in core
    assert "redis:" not in core
    assert "memtrace-redis" not in core
    assert "memtrace-worker" not in core

    assert "memtrace-redis" in dev
    assert "memtrace-worker" in dev
    assert "MEMTRACE_ASYNC_TASKS_ENABLED" in dev
    assert "MEMTRACE_CELERY_TASK_ALWAYS_EAGER" in dev
    assert "app.async_tasks.celery_app:celery_app" in dev


@pytest.mark.skipif(
    not os.environ.get("MEMTRACE_TEST_REDIS_URL"),
    reason="set MEMTRACE_TEST_REDIS_URL to run optional Redis smoke",
)
async def test_optional_redis_candidate_buffer_smoke():
    import redis.asyncio as redis

    url = os.environ["MEMTRACE_TEST_REDIS_URL"]
    client = redis.from_url(url, decode_responses=True)
    prefix = "memtrace:test:async-infra"
    buffer = RedisCandidateBuffer(client, prefix=prefix)
    try:
        async for key in client.scan_iter(f"{prefix}:*"):
            await client.delete(key)

        event = AgentEvent(
            workspace_id="ws:tenant",
            session_id="session:with:colon",
            run_id="run_redis_smoke",
            step_id="step_redis_smoke",
            sequence_no=1,
            role=EventRole.user,
            event_type=EventType.message,
            content="my key is [REDACTED]",
        )

        await buffer.append(event)

        assert [item.content for item in await buffer.pending("session:with:colon")] == ["my key is [REDACTED]"]
        assert await buffer.sessions(workspace_id="ws:tenant") == ["session:with:colon"]
        drained = await buffer.drain("session:with:colon")
        assert [item.event_id for item in drained] == [event.event_id]
        assert await buffer.total_size() == 0
    finally:
        async for key in client.scan_iter(f"{prefix}:*"):
            await client.delete(key)
        await client.aclose()
