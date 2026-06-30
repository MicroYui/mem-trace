"""Optional provenance-graph neighbor expansion tests (ROADMAP §4, default-off).

Covers deterministic BFS relatedness, edge assembly from repository provenance,
the Neo4j backend's degrade-safe behavior with an injected fake driver, the
default-off controller no-op, conflict-linked neighbor surfacing with the
lifecycle filter preserved, and config / policy-snapshot byte-stability.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import get_settings
from app.retrieval.controller import RetrievalController
from app.retrieval.gate import GateConfig
from app.retrieval.graph import (
    CONFLICTS_WITH,
    InMemoryProvenanceGraph,
    Neo4jProvenanceGraph,
    ProvenanceEdge,
    build_graph_backend,
    provenance_edges,
)
from app.retrieval.policy import build_policy_snapshot
from app.runtime.models import (
    MemoryConflictRecord,
    MemoryItem,
    MemoryStatus,
    MemoryType,
    RetrievalRequest,
    RetrievalStrategy,
)
from app.runtime.repository import InMemoryRepository


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _mem(ws, memory_id, content, *, status=MemoryStatus.active, superseded_by=None):
    return MemoryItem(
        memory_id=memory_id,
        workspace_id=ws,
        memory_type=MemoryType.episodic,
        content=content,
        summary=content[:60],
        status=status,
        superseded_by=superseded_by,
    )


# --------------------------- pure graph ----------------------------- #


@pytest.mark.asyncio
async def test_inmemory_graph_bfs_relatedness_decays_with_distance():
    backend = InMemoryProvenanceGraph()
    edges = [ProvenanceEdge("a", "b", CONFLICTS_WITH), ProvenanceEdge("b", "c", CONFLICTS_WITH)]
    related = await backend.related(["a"], edges, max_hops=2)
    assert related["b"] == 1.0  # 1 hop
    assert related["c"] == 0.5  # 2 hops
    assert "a" not in related  # seed excluded


@pytest.mark.asyncio
async def test_inmemory_graph_respects_max_hops():
    backend = InMemoryProvenanceGraph()
    edges = [ProvenanceEdge("a", "b", CONFLICTS_WITH), ProvenanceEdge("b", "c", CONFLICTS_WITH)]
    related = await backend.related(["a"], edges, max_hops=1)
    assert "b" in related and "c" not in related


def test_provenance_edges_from_superseded_and_conflicts():
    ws = "ws"
    mems = [_mem(ws, "new", "x"), _mem(ws, "old", "y", superseded_by="new")]
    conflicts = [MemoryConflictRecord(workspace_id=ws, subject_key="k", memory_ids=["p", "q"])]
    edges = provenance_edges(mems, conflicts)
    assert ProvenanceEdge("old", "new", "SUPERSEDES") in edges
    assert ProvenanceEdge("p", "q", CONFLICTS_WITH) in edges


# ----------------------------- neo4j -------------------------------- #


class _FakeSession:
    def __init__(self, *, fail=False):
        self.fail = fail

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def run(self, cypher, **params):
        if self.fail:
            raise RuntimeError("boom")
        if "RETURN" in cypher:  # the related query
            return [{"id": "n1", "dist": 1}, {"id": "n2", "dist": 2}]
        return []


class _FakeDriver:
    def __init__(self, *, fail=False):
        self.fail = fail

    def session(self, *, database):
        return _FakeSession(fail=self.fail)


@pytest.mark.asyncio
async def test_neo4j_backend_returns_relatedness_with_fake_driver():
    backend = Neo4jProvenanceGraph(url="bolt://x", driver=_FakeDriver())
    assert backend.available is True
    related = await backend.related(
        ["s"], [ProvenanceEdge("s", "n1", CONFLICTS_WITH)], max_hops=2
    )
    assert related == {"n1": 1.0, "n2": 0.5}


@pytest.mark.asyncio
async def test_neo4j_backend_degrades_on_error():
    backend = Neo4jProvenanceGraph(url="bolt://x", driver=_FakeDriver(fail=True))
    related = await backend.related(["s"], [ProvenanceEdge("s", "n1", CONFLICTS_WITH)], max_hops=2)
    assert related == {}


def test_neo4j_backend_unavailable_without_driver_or_package():
    assert Neo4jProvenanceGraph(url="", driver=None).available is False


# ----------------------- controller integration ---------------------- #


@pytest.mark.asyncio
async def test_graph_off_by_default(monkeypatch):
    monkeypatch.delenv("MEMTRACE_RETRIEVAL_GRAPH_BACKEND", raising=False)
    get_settings.cache_clear()
    controller = RetrievalController(InMemoryRepository())
    assert controller._graph_backend is None  # noqa: SLF001


@pytest.mark.asyncio
async def test_graph_expansion_surfaces_conflicting_neighbor(monkeypatch):
    monkeypatch.setenv("MEMTRACE_RETRIEVAL_GRAPH_BACKEND", "inmemory")
    monkeypatch.setenv("MEMTRACE_RETRIEVAL_USE_VECTOR", "false")
    get_settings.cache_clear()
    repo = InMemoryRepository()
    ws = "ws_graph"
    # m_hit matches the query; m_partner shares no query token but conflicts with it.
    await repo.add_memory(_mem(ws, "m_hit", "gateway routing config"))
    await repo.add_memory(_mem(ws, "m_partner", "billing pipeline ledger"))
    await repo.upsert_memory_conflict(
        MemoryConflictRecord(workspace_id=ws, subject_key="endpoint", memory_ids=["m_hit", "m_partner"])
    )
    controller = RetrievalController(repo)
    cands = await controller._select_candidates(  # noqa: SLF001
        workspace_id=ws, run_id="r", query="gateway", top_k=10
    )
    by_id = {c.memory.memory_id: c for c in cands}
    assert "m_partner" in by_id  # surfaced purely via the conflict edge
    assert by_id["m_partner"].graph_score == 1.0


@pytest.mark.asyncio
async def test_graph_expansion_skips_retired_neighbor(monkeypatch):
    # A superseded (non-retrievable) neighbor must never be surfaced.
    monkeypatch.setenv("MEMTRACE_RETRIEVAL_GRAPH_BACKEND", "inmemory")
    monkeypatch.setenv("MEMTRACE_RETRIEVAL_USE_VECTOR", "false")
    get_settings.cache_clear()
    repo = InMemoryRepository()
    ws = "ws_graph_retired"
    await repo.add_memory(_mem(ws, "m_hit", "gateway routing"))
    await repo.add_memory(
        _mem(ws, "m_old", "billing ledger", status=MemoryStatus.superseded)
    )
    await repo.upsert_memory_conflict(
        MemoryConflictRecord(workspace_id=ws, subject_key="k", memory_ids=["m_hit", "m_old"])
    )
    controller = RetrievalController(repo)
    cands = await controller._select_candidates(  # noqa: SLF001
        workspace_id=ws, run_id="r", query="gateway", top_k=10
    )
    assert all(c.memory.memory_id != "m_old" for c in cands)  # lifecycle filter holds


# --------------------------- config + policy ------------------------- #


def test_invalid_graph_backend_rejected(monkeypatch):
    monkeypatch.setenv("MEMTRACE_RETRIEVAL_GRAPH_BACKEND", "dgraph")
    get_settings.cache_clear()
    with pytest.raises(ValidationError, match="retrieval_graph_backend must be one of"):
        get_settings()


def test_invalid_graph_max_hops_rejected(monkeypatch):
    monkeypatch.setenv("MEMTRACE_RETRIEVAL_GRAPH_MAX_HOPS", "9")
    get_settings.cache_clear()
    with pytest.raises(ValidationError, match="retrieval_graph_max_hops must be between"):
        get_settings()


def test_build_graph_backend_modes():
    class _S:
        retrieval_graph_backend = "inmemory"
    assert isinstance(build_graph_backend(_S()), InMemoryProvenanceGraph)
    _S.retrieval_graph_backend = "off"
    assert build_graph_backend(_S()) is None


def _snap(**kw):
    req = RetrievalRequest(run_id="r", query="q", strategy=RetrievalStrategy.variant_2)
    return build_policy_snapshot(
        req,
        gate_config=GateConfig.for_strategy(req.strategy),
        effective_token_budget=512,
        vector_enabled=True,
        vector_weight=0.5,
        compaction_notice_reserve_tokens=8,
        **kw,
    )


def test_policy_snapshot_omits_graph_when_off():
    assert "graph_backend" not in _snap(graph_backend=None)["retrieval"]


def test_policy_snapshot_records_graph_when_enabled():
    snap = _snap(graph_backend="inmemory", graph_weight=0.15, graph_max_hops=2)["retrieval"]
    assert snap["graph_backend"] == "inmemory"
    assert snap["graph_weight"] == 0.15
    assert snap["graph_max_hops"] == 2
