"""Multi-store eventual-consistency reconciler tests (ROADMAP §4, default-safe).

Covers the no-backend default (everything not_applicable), pushing pending
memories into an available backend, failure -> failed (retry next run), the
graph store path, and the maintenance op wrapper.
"""
from __future__ import annotations

import pytest

from app.config import get_settings
from app.memory import scheduler
from app.memory.secondary_index import (
    FAILED,
    INDEXED,
    NOT_APPLICABLE,
    mark_memory_pending_secondary_index,
    reconcile_secondary_indexes,
)
from app.retrieval.hybrid import InMemoryBM25Backend
from app.runtime.models import MemoryItem, MemoryType
from app.runtime.repository import InMemoryRepository


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _mem(ws, memory_id, content, **md):
    return MemoryItem(
        memory_id=memory_id,
        workspace_id=ws,
        memory_type=MemoryType.episodic,
        content=content,
        summary=content[:60],
        lifecycle_metadata=dict(md),
    )


class _AlwaysFailHybrid:
    name = "fail"

    @property
    def available(self):
        return True

    async def bm25_scores(self, **kwargs):
        raise RuntimeError("boom")


@pytest.mark.asyncio
async def test_reconcile_marks_not_applicable_without_backends():
    repo = InMemoryRepository()
    ws = "ws_na"
    await repo.add_memory(_mem(ws, "m1", "hello"))
    result = await reconcile_secondary_indexes(repo, workspace_id=ws)
    assert result["indexed_count"] == 0
    stored = (await repo.list_memories(workspace_id=ws))[0]
    assert stored.lifecycle_metadata["index_status"] == NOT_APPLICABLE
    assert stored.lifecycle_metadata["graph_status"] == NOT_APPLICABLE


@pytest.mark.asyncio
async def test_reconcile_indexes_pending_into_available_backend():
    repo = InMemoryRepository()
    ws = "ws_idx"
    await repo.add_memory(_mem(ws, "m1", "deploy gateway", index_status="pending"))
    result = await reconcile_secondary_indexes(
        repo, workspace_id=ws, hybrid_backend=InMemoryBM25Backend()
    )
    assert result["indexed_count"] == 1
    stored = (await repo.list_memories(workspace_id=ws))[0]
    assert stored.lifecycle_metadata["index_status"] == INDEXED
    assert "last_indexed_at" in stored.lifecycle_metadata


@pytest.mark.asyncio
async def test_reconcile_marks_failed_for_retry_on_backend_error():
    repo = InMemoryRepository()
    ws = "ws_fail"
    await repo.add_memory(_mem(ws, "m1", "deploy gateway", index_status="pending"))
    result = await reconcile_secondary_indexes(
        repo, workspace_id=ws, hybrid_backend=_AlwaysFailHybrid()
    )
    assert result["failed_count"] == 1
    stored = (await repo.list_memories(workspace_id=ws))[0]
    assert stored.lifecycle_metadata["index_status"] == FAILED  # retried next run


@pytest.mark.asyncio
async def test_reconcile_skips_already_indexed():
    repo = InMemoryRepository()
    ws = "ws_skip"
    await repo.add_memory(_mem(ws, "m1", "deploy gateway", index_status="indexed", graph_status="not_applicable"))
    result = await reconcile_secondary_indexes(
        repo, workspace_id=ws, hybrid_backend=InMemoryBM25Backend()
    )
    assert result["indexed_count"] == 0  # nothing to do


def test_mark_pending_helper_sets_both_stores():
    md = mark_memory_pending_secondary_index({"existing": 1})
    assert md["index_status"] == "pending"
    assert md["graph_status"] == "pending"
    assert md["existing"] == 1


@pytest.mark.asyncio
async def test_reindex_secondary_op_is_safe_noop_by_default(monkeypatch):
    monkeypatch.delenv("MEMTRACE_RETRIEVAL_HYBRID_BACKEND", raising=False)
    monkeypatch.delenv("MEMTRACE_RETRIEVAL_GRAPH_BACKEND", raising=False)
    get_settings.cache_clear()
    repo = InMemoryRepository()
    ws = "ws_op"
    await repo.add_memory(_mem(ws, "m1", "hello"))
    result = await scheduler.reindex_secondary(repo, workspace_id=ws, scheduler_run_id="sched_x")
    assert result["hybrid_available"] is False
    assert result["graph_available"] is False
    assert result["scheduler_run_id"] == "sched_x"
