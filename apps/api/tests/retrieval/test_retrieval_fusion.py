"""Multi-signal candidate fusion tests (ROADMAP §4).

Covers Reciprocal Rank Fusion (RRF) as an alternative to the default linear
weighted blend, and that the retrieval policy snapshot records the fusion mode.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import get_settings
from app.retrieval.controller import RetrievalController
from app.retrieval.policy import build_policy_snapshot
from app.retrieval.gate import GateConfig
from app.runtime.models import (
    MemoryItem,
    MemoryType,
    RetrievalRequest,
    RetrievalStrategy,
)
from app.runtime.repository import InMemoryRepository


def _mem(repo_ws: str, memory_id: str, content: str) -> MemoryItem:
    return MemoryItem(
        memory_id=memory_id,
        workspace_id=repo_ws,
        memory_type=MemoryType.episodic,
        content=content,
        summary=content[:60],
    )


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def _seed(repo: InMemoryRepository, ws: str) -> None:
    await repo.add_memory(_mem(ws, "m_lex", "deploy the bun runtime service quickly"))
    await repo.add_memory(_mem(ws, "m_vec", "completely unrelated pottery glaze notes"))
    await repo.add_memory(_mem(ws, "m_both", "bun runtime pottery service notes"))


@pytest.mark.asyncio
async def test_rrf_fusion_produces_positive_fused_scores(monkeypatch):
    monkeypatch.setenv("MEMTRACE_RETRIEVAL_FUSION", "rrf")
    get_settings.cache_clear()
    repo = InMemoryRepository()
    ws = "ws_rrf"
    await _seed(repo, ws)
    controller = RetrievalController(repo)
    assert controller._fusion == "rrf"  # noqa: SLF001

    candidates = await controller._select_candidates(  # noqa: SLF001
        workspace_id=ws, run_id="r", query="bun runtime service", top_k=10
    )
    # At least one candidate fused a positive RRF score and ordering is stable.
    assert candidates
    scores = [c.relevance_score for c in candidates]
    assert scores == sorted(scores, reverse=True)
    assert any(s > 0 for s in scores)


@pytest.mark.asyncio
async def test_linear_is_default_fusion(monkeypatch):
    monkeypatch.delenv("MEMTRACE_RETRIEVAL_FUSION", raising=False)
    get_settings.cache_clear()
    controller = RetrievalController(InMemoryRepository())
    assert controller._fusion == "linear"  # noqa: SLF001


def test_policy_snapshot_omits_fusion_in_linear_mode():
    req = RetrievalRequest(run_id="r", query="q", strategy=RetrievalStrategy.variant_2)
    snap = build_policy_snapshot(
        req,
        gate_config=GateConfig.for_strategy(req.strategy),
        effective_token_budget=512,
        vector_enabled=True,
        vector_weight=0.5,
        compaction_notice_reserve_tokens=8,
        fusion="linear",
    )
    assert "fusion" not in snap["retrieval"]


def test_policy_snapshot_records_rrf_fusion():
    req = RetrievalRequest(run_id="r", query="q", strategy=RetrievalStrategy.variant_2)
    snap = build_policy_snapshot(
        req,
        gate_config=GateConfig.for_strategy(req.strategy),
        effective_token_budget=512,
        vector_enabled=True,
        vector_weight=0.5,
        compaction_notice_reserve_tokens=8,
        fusion="rrf",
        rrf_k=60,
    )
    assert snap["retrieval"]["fusion"] == "rrf"
    assert snap["retrieval"]["rrf_k"] == 60


def test_invalid_retrieval_fusion_setting_is_rejected(monkeypatch):
    monkeypatch.setenv("MEMTRACE_RETRIEVAL_FUSION", "weighted-graph")
    get_settings.cache_clear()

    with pytest.raises(ValidationError, match="retrieval_fusion must be one of"):
        get_settings()


def test_rrf_scores_are_exact_rank_sums_with_stable_ties():
    controller = RetrievalController(InMemoryRepository())
    controller._rrf_k = 10  # noqa: SLF001
    raw = [
        (_mem("ws", "m_a", "a"), 0.5, 0.1),
        (_mem("ws", "m_b", "b"), 0.5, 0.9),
        (_mem("ws", "m_c", "c"), 0.2, 0.9),
        (_mem("ws", "m_zero", "zero"), 0.0, 0.0),
    ]

    scores = controller._rrf_scores(raw)  # noqa: SLF001

    assert scores == {
        "m_a": pytest.approx(1 / 11 + 1 / 13),
        "m_b": pytest.approx(1 / 12 + 1 / 11),
        "m_c": pytest.approx(1 / 13 + 1 / 12),
    }
    assert "m_zero" not in scores


def test_rrf_scores_include_bm25_as_third_list():
    controller = RetrievalController(InMemoryRepository())
    controller._rrf_k = 10  # noqa: SLF001
    raw = [
        (_mem("ws", "m_a", "a"), 0.5, 0.0),
        (_mem("ws", "m_b", "b"), 0.2, 0.0),
    ]
    # lexical ranks: m_a(0), m_b(1). vector: none. bm25 ranks: m_b(0), m_a(1).
    bm25 = {"m_b": 0.9, "m_a": 0.1}
    scores = controller._rrf_scores(raw, bm25)  # noqa: SLF001
    assert scores["m_a"] == pytest.approx(1 / 11 + 1 / 12)  # lex rank0 + bm25 rank1
    assert scores["m_b"] == pytest.approx(1 / 12 + 1 / 11)  # lex rank1 + bm25 rank0


@pytest.mark.asyncio
async def test_rrf_request_falls_back_to_linear_policy_when_vector_disabled(monkeypatch):
    monkeypatch.setenv("MEMTRACE_RETRIEVAL_FUSION", "rrf")
    monkeypatch.setenv("MEMTRACE_RETRIEVAL_USE_VECTOR", "false")
    get_settings.cache_clear()
    repo = InMemoryRepository()
    ws = "ws_rrf_no_vector"
    await _seed(repo, ws)
    controller = RetrievalController(repo)

    trace = await controller.trace(
        RetrievalRequest(run_id="r", query="bun runtime service", strategy=RetrievalStrategy.baseline_1),
        workspace_id=ws,
    )

    assert trace.candidates
    assert all(candidate.vector_score == 0.0 for candidate in trace.candidates)
    assert trace.candidates[0].relevance_score == trace.candidates[0].lexical_score
    assert "fusion" not in trace.access_record.policy_snapshot["retrieval"]
