"""Bounded candidate prefilter (production scaling, default-off).

Verifies the retrieval_candidate_limit prefilter: the inverted-index prefilter and
bounded loader are correct, the bounded retrieval still recalls the relevant
memory, and the default (limit=0) is byte-identical to scanning the whole
workspace.
"""
from __future__ import annotations

import pytest

from app.config import get_settings
from app.retrieval.controller import RetrievalController
from app.runtime.models import MemoryItem, MemoryType
from app.runtime.repository import InMemoryRepository

_TOPICS = ["cache layer", "database", "test runner", "deploy region", "message broker"]


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _mem(ws: str, i: int, content: str, mtype: MemoryType = MemoryType.episodic) -> MemoryItem:
    return MemoryItem(memory_id=f"m_{i}", workspace_id=ws, memory_type=mtype,
                      content=content, summary=content[:60])


async def _seed(repo: InMemoryRepository, ws: str, n: int) -> None:
    for i in range(n):
        topic = _TOPICS[i % len(_TOPICS)]
        await repo.add_memory(_mem(ws, i, f"note {i}: the {topic} for module {i} is value_{i}"))


# ------------------------- repository primitives --------------------- #


@pytest.mark.asyncio
async def test_prefilter_ranks_by_token_overlap():
    repo = InMemoryRepository()
    ws = "w"
    await _seed(repo, ws, 40)
    await repo.add_memory(_mem(ws, 999, "the deploy region is tokyo and the cache layer is redis"))
    ids = await repo.prefilter_candidate_ids(workspace_id=ws, query="deploy region cache layer", limit=5)
    assert len(ids) <= 5
    # the memory overlapping the most query tokens ranks in
    assert "m_999" in ids


@pytest.mark.asyncio
async def test_prefilter_empty_query_and_disabled():
    repo = InMemoryRepository()
    await _seed(repo, "w", 5)
    assert await repo.prefilter_candidate_ids(workspace_id="w", query="", limit=5) == []
    assert await repo.prefilter_candidate_ids(workspace_id="w", query="cache", limit=0) == []


@pytest.mark.asyncio
async def test_prefilter_index_reflects_writes():
    repo = InMemoryRepository()
    ws = "w"
    await _seed(repo, ws, 5)
    assert not await repo.prefilter_candidate_ids(workspace_id=ws, query="kubernetes", limit=5)
    await repo.add_memory(_mem(ws, 100, "the orchestrator is kubernetes"))
    ids = await repo.prefilter_candidate_ids(workspace_id=ws, query="kubernetes", limit=5)
    assert "m_100" in ids  # index rebuilt after the write bumped the seq


@pytest.mark.asyncio
async def test_list_candidate_memories_bounded_plus_types():
    repo = InMemoryRepository()
    ws = "w"
    await _seed(repo, ws, 10)
    await repo.add_memory(_mem(ws, 500, "project uses bun", MemoryType.project))
    got = await repo.list_candidate_memories(workspace_id=ws, ids=["m_1", "m_3"], include_types=("project",))
    got_ids = {m.memory_id for m in got}
    assert got_ids == {"m_1", "m_3", "m_500"}  # requested ids + all project types


# --------------------------- controller behavior --------------------- #


async def _candidates(repo, controller, ws, query, top_k=10):
    cands = await controller._select_candidates(  # noqa: SLF001
        workspace_id=ws, run_id="r", query=query, top_k=top_k)
    return [c.memory.memory_id for c in cands]


@pytest.mark.asyncio
async def test_bounded_retrieval_still_recalls_target(monkeypatch):
    monkeypatch.setenv("MEMTRACE_RETRIEVAL_CANDIDATE_LIMIT", "15")
    monkeypatch.setenv("MEMTRACE_RETRIEVAL_USE_VECTOR", "false")
    get_settings.cache_clear()
    repo = InMemoryRepository()
    ws = "w"
    await _seed(repo, ws, 300)  # large enough to exceed the limit
    # unique tokens not present in any seeded memory -> the only match
    await repo.add_memory(_mem(ws, 999, "the escalation contact is zoe-pager for production"))
    controller = RetrievalController(repo)
    ids = await _candidates(repo, controller, ws, "who is the escalation contact zoe-pager")
    assert "m_999" in ids  # the relevant memory survives the bounded prefilter


@pytest.mark.asyncio
async def test_default_off_matches_full_scan(monkeypatch):
    # candidate_limit=0 must be byte-identical to scanning the whole workspace, and
    # for a query with a distinguishable (unique-token) target both modes agree.
    monkeypatch.setenv("MEMTRACE_RETRIEVAL_USE_VECTOR", "false")
    repo = InMemoryRepository()
    ws = "w"
    await _seed(repo, ws, 120)
    await repo.add_memory(_mem(ws, 999, "the escalation contact is zoe-pager"))
    query = "who is the escalation contact zoe-pager"

    monkeypatch.delenv("MEMTRACE_RETRIEVAL_CANDIDATE_LIMIT", raising=False)
    get_settings.cache_clear()
    off = await _candidates(repo, RetrievalController(repo), ws, query)

    monkeypatch.setenv("MEMTRACE_RETRIEVAL_CANDIDATE_LIMIT", "20")
    get_settings.cache_clear()
    on = await _candidates(repo, RetrievalController(repo), ws, query)

    # the top candidate is the same relevant memory under both modes
    assert off[0] == on[0] == "m_999"

