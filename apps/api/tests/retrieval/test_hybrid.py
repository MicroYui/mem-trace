"""Optional hybrid BM25 retrieval backend tests (ROADMAP §4, default-off).

Covers the deterministic Okapi BM25 (IDF favors rare query terms), the
Elasticsearch backend's degrade-safe behavior with an injected fake client,
the default-off controller no-op, the blended ranking when enabled, and config /
policy-snapshot byte-stability.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import get_settings
from app.retrieval.controller import RetrievalController
from app.retrieval.gate import GateConfig
from app.retrieval.hybrid import (
    ElasticsearchBM25Backend,
    InMemoryBM25Backend,
    build_hybrid_backend,
)
from app.retrieval.policy import build_policy_snapshot
from app.runtime.models import MemoryItem, MemoryType, RetrievalRequest, RetrievalStrategy
from app.runtime.repository import InMemoryRepository


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _mem(ws: str, memory_id: str, content: str) -> MemoryItem:
    return MemoryItem(
        memory_id=memory_id,
        workspace_id=ws,
        memory_type=MemoryType.episodic,
        content=content,
        summary=content[:60],
    )


# --------------------------- deterministic BM25 --------------------- #


@pytest.mark.asyncio
async def test_inmemory_bm25_idf_favors_rare_term():
    backend = InMemoryBM25Backend()
    ws = "ws"
    corpus = [
        _mem(ws, "m_common", "gateway gateway gateway gateway"),  # only the common term
        _mem(ws, "m_rare", "gateway billing"),  # has the rare term
    ] + [_mem(ws, f"m_f{i}", f"gateway filler{i}") for i in range(5)]
    scores = await backend.bm25_scores(
        query="gateway billing", memories=corpus, workspace_id=ws, top_k=10
    )
    assert scores["m_rare"] > scores["m_common"]  # IDF(billing) >> IDF(gateway)
    assert all(0.0 <= v <= 1.0 for v in scores.values())


@pytest.mark.asyncio
async def test_inmemory_bm25_empty_query_returns_nothing():
    backend = InMemoryBM25Backend()
    assert await backend.bm25_scores(
        query="", memories=[_mem("ws", "m", "x")], workspace_id="ws", top_k=5
    ) == {}


# ----------------------- elasticsearch backend ---------------------- #


class _FakeES:
    """Minimal fake Elasticsearch client recording indexed docs."""

    def __init__(self, *, fail: bool = False):
        self.fail = fail
        self.docs: dict[str, dict] = {}
        self.indices = self  # so client.indices.refresh works

    def index(self, *, index, id, document):  # noqa: A002 - mirror ES kwarg
        if self.fail:
            raise RuntimeError("boom")
        self.docs[id] = document

    def refresh(self, *, index):
        if self.fail:
            raise RuntimeError("boom")

    def search(self, *, index, query, size):
        if self.fail:
            raise RuntimeError("boom")
        # Return canned scores: m_b ranks above m_a.
        return {"hits": {"hits": [
            {"_id": "m_b", "_score": 4.0},
            {"_id": "m_a", "_score": 2.0},
        ]}}


@pytest.mark.asyncio
async def test_elasticsearch_backend_returns_normalized_scores_with_fake_client():
    backend = ElasticsearchBM25Backend(url="http://es:9200", client=_FakeES())
    assert backend.available is True
    ws = "ws"
    scores = await backend.bm25_scores(
        query="auth", memories=[_mem(ws, "m_a", "a"), _mem(ws, "m_b", "b")],
        workspace_id=ws, top_k=10,
    )
    assert scores == {"m_b": 1.0, "m_a": 0.5}  # normalized by max _score


@pytest.mark.asyncio
async def test_elasticsearch_backend_degrades_on_error():
    backend = ElasticsearchBM25Backend(url="http://es:9200", client=_FakeES(fail=True))
    scores = await backend.bm25_scores(
        query="auth", memories=[_mem("ws", "m_a", "a")], workspace_id="ws", top_k=10
    )
    assert scores == {}  # any error -> empty, retrieval falls back


@pytest.mark.asyncio
async def test_elasticsearch_backend_unavailable_without_client_or_package():
    # No client injected and a bogus url: if the elasticsearch package is absent
    # this is unavailable; if present, construction against a dead url may still
    # succeed lazily. Either way it must never raise on construction.
    backend = ElasticsearchBM25Backend(url="", client=None)
    assert backend.available is False


# ----------------------- controller integration ---------------------- #


@pytest.mark.asyncio
async def test_hybrid_off_by_default(monkeypatch):
    monkeypatch.delenv("MEMTRACE_RETRIEVAL_HYBRID_BACKEND", raising=False)
    get_settings.cache_clear()
    controller = RetrievalController(InMemoryRepository())
    assert controller._hybrid_backend is None  # noqa: SLF001


@pytest.mark.asyncio
async def test_hybrid_off_keeps_bm25_score_zero(monkeypatch):
    monkeypatch.setenv("MEMTRACE_RETRIEVAL_HYBRID_BACKEND", "off")
    monkeypatch.setenv("MEMTRACE_RETRIEVAL_USE_VECTOR", "false")
    get_settings.cache_clear()
    repo = InMemoryRepository()
    ws = "ws_off"
    await repo.add_memory(_mem(ws, "m1", "deploy the gateway service"))
    controller = RetrievalController(repo)
    cands = await controller._select_candidates(  # noqa: SLF001
        workspace_id=ws, run_id="r", query="gateway", top_k=10
    )
    assert all(c.bm25_score == 0.0 for c in cands)


@pytest.mark.asyncio
async def test_hybrid_inmemory_populates_bm25_and_blends(monkeypatch):
    monkeypatch.setenv("MEMTRACE_RETRIEVAL_HYBRID_BACKEND", "inmemory")
    monkeypatch.setenv("MEMTRACE_RETRIEVAL_USE_VECTOR", "false")
    get_settings.cache_clear()
    repo = InMemoryRepository()
    ws = "ws_hybrid"
    await repo.add_memory(_mem(ws, "m_rare", "gateway billing"))
    await repo.add_memory(_mem(ws, "m_common", "gateway gateway gateway gateway"))
    for i in range(5):
        await repo.add_memory(_mem(ws, f"m_f{i}", f"gateway filler{i}"))
    controller = RetrievalController(repo)
    assert controller._hybrid_backend is not None  # noqa: SLF001
    cands = await controller._select_candidates(  # noqa: SLF001
        workspace_id=ws, run_id="r", query="gateway billing", top_k=10
    )
    by_id = {c.memory.memory_id: c for c in cands}
    assert by_id["m_rare"].bm25_score > 0.0
    # The rare-term doc wins on the blended relevance score.
    assert by_id["m_rare"].relevance_score >= by_id["m_common"].relevance_score


# --------------------------- config + policy ------------------------- #


def test_invalid_hybrid_backend_rejected(monkeypatch):
    monkeypatch.setenv("MEMTRACE_RETRIEVAL_HYBRID_BACKEND", "pinecone")
    get_settings.cache_clear()
    with pytest.raises(ValidationError, match="retrieval_hybrid_backend must be one of"):
        get_settings()


def test_build_hybrid_backend_modes(monkeypatch):
    class _S:
        retrieval_hybrid_backend = "inmemory"
        es_url = ""
        es_index_prefix = "memtrace"
    assert isinstance(build_hybrid_backend(_S()), InMemoryBM25Backend)
    _S.retrieval_hybrid_backend = "off"
    assert build_hybrid_backend(_S()) is None


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


def test_policy_snapshot_omits_hybrid_when_off():
    assert "hybrid_backend" not in _snap(hybrid_backend=None)["retrieval"]
    assert "hybrid_backend" not in _snap(hybrid_backend="off")["retrieval"]


def test_policy_snapshot_records_hybrid_when_enabled():
    snap = _snap(hybrid_backend="inmemory", hybrid_weight=0.3)
    assert snap["retrieval"]["hybrid_backend"] == "inmemory"
    assert snap["retrieval"]["hybrid_weight"] == 0.3
