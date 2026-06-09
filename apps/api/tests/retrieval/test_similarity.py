"""Deterministic embedding + vector KNN retrieval tests.

Covers the pgvector restoration: embeddings must be process-stable (so they can
be persisted and queried later), cosine similarity must behave, and the
in-memory vector search must rank a semantically close memory above an unrelated
one. The hybrid lexical+vector blend is exercised end-to-end via the runtime
facade elsewhere; here we pin the building blocks.
"""
from __future__ import annotations

from app.retrieval.similarity import cosine_similarity, stable_embedding
from app.runtime.models import BranchStatus, MemoryItem, MemoryType
from app.runtime.repository import InMemoryRepository, ensure_embedding


def test_stable_embedding_is_deterministic_and_normalized():
    a = stable_embedding("run tests with bun", dim=256)
    b = stable_embedding("run tests with bun", dim=256)
    assert a == b  # process-stable (blake2b, not salted hash)
    assert len(a) == 256
    norm = sum(x * x for x in a) ** 0.5
    assert abs(norm - 1.0) < 1e-6


def test_cosine_similarity_bounds():
    v = stable_embedding("bun test runner", dim=128)
    assert abs(cosine_similarity(v, v) - 1.0) < 1e-6
    other = stable_embedding("completely different topic xyz", dim=128)
    assert 0.0 <= cosine_similarity(v, other) < 1.0
    assert cosine_similarity(v, None) == 0.0
    assert cosine_similarity(v, [0.0, 1.0]) == 0.0  # dim mismatch -> 0


async def test_ensure_embedding_backfills_on_add():
    repo = InMemoryRepository()
    mem = MemoryItem(workspace_id="ws", memory_type=MemoryType.project,
                     content="This project uses Bun", branch_status=BranchStatus.completed)
    assert mem.embedding_vector is None
    await repo.add_memory(mem)
    stored = await repo.get_memory(mem.memory_id)
    assert stored.embedding_vector is not None
    assert stored.embedding_status.value == "embedded"


async def test_vector_search_ranks_semantically_closer_memory_first():
    repo = InMemoryRepository()
    close = MemoryItem(workspace_id="ws", memory_type=MemoryType.tool_evidence,
                       content="run tests with bun test", branch_status=BranchStatus.completed)
    far = MemoryItem(workspace_id="ws", memory_type=MemoryType.episodic,
                     content="unrelated note about weather forecast", branch_status=BranchStatus.completed)
    await repo.add_memory(close)
    await repo.add_memory(far)

    q = stable_embedding("how do I run tests with bun", dim=256)
    results = await repo.search_memories_by_vector(embedding=q, workspace_id="ws", top_k=10)
    assert results, "expected at least one vector hit"
    assert results[0][0].memory_id == close.memory_id
    assert results[0][1] >= results[-1][1]


async def test_vector_search_is_workspace_scoped():
    repo = InMemoryRepository()
    await repo.add_memory(MemoryItem(workspace_id="ws_a", memory_type=MemoryType.project,
                                     content="uses bun", branch_status=BranchStatus.completed))
    await repo.add_memory(MemoryItem(workspace_id="ws_b", memory_type=MemoryType.project,
                                     content="uses bun", branch_status=BranchStatus.completed))
    q = stable_embedding("bun", dim=256)
    results = await repo.search_memories_by_vector(embedding=q, workspace_id="ws_a", top_k=10)
    assert all(m.workspace_id == "ws_a" for m, _ in results)
