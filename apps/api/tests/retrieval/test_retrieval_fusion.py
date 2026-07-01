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


@pytest.mark.asyncio
async def test_rrf_three_signal_end_to_end(monkeypatch):
    """All three live retrieval signals fuse through the real controller path.

    Enables RRF fusion with the in-memory BM25 hybrid backend and the
    deterministic ``stable_embedding`` vector signal, then seeds a corpus crafted
    so lexical overlap, vector cosine, and Okapi BM25 each rank a *different*
    memory first:

    - ``m_lex`` covers all three query tokens (best lexical coverage) but is
      padded with six unique tokens that dilute its vector cosine.
    - ``m_vec`` is just the two common tokens, so its concentrated vector wins.
    - ``m_bm`` repeats the rare ``gamma`` token; ``gamma`` is infrequent across
      the corpus, so its IDF makes ``m_bm`` win BM25 while it stays low on
      lexical coverage and only mid on vector.

    Asserts (1) the BM25-only winner still places among the candidates, (2) the
    final fused ordering equals an independent RRF sum over the three ranked
    lists, and (3) dropping the BM25 list changes that ordering — proving the
    third list genuinely contributes to the fused order rather than riding along.
    """
    monkeypatch.setenv("MEMTRACE_RETRIEVAL_FUSION", "rrf")
    monkeypatch.setenv("MEMTRACE_RETRIEVAL_HYBRID_BACKEND", "inmemory")
    monkeypatch.setenv("MEMTRACE_RETRIEVAL_USE_VECTOR", "true")
    get_settings.cache_clear()

    repo = InMemoryRepository()
    ws = "ws_rrf_three_signal"
    contents = {
        "m_lex": "alpha beta gamma e1 e2 e3 e4 e5 e6",
        "m_vec": "alpha beta",
        "m_bm": "gamma gamma",
        # Fillers keep the common tokens frequent (low IDF) so gamma stays rare.
        "m_f1": "alpha p1 p2 p3 p4 p5 p6 p7 p8 p9",
        "m_f2": "beta q1 q2 q3 q4 q5 q6 q7 q8 q9",
        "m_f3": "alpha beta r1 r2 r3 r4 r5 r6 r7",
    }
    for memory_id, content in contents.items():
        await repo.add_memory(_mem(ws, memory_id, content))

    controller = RetrievalController(repo)
    # All three signals must actually be live for this to exercise multi-path RRF.
    assert controller._fusion == "rrf"  # noqa: SLF001
    assert controller._use_vector is True  # noqa: SLF001
    assert controller._hybrid_backend is not None  # noqa: SLF001
    assert controller._hybrid_backend.available  # noqa: SLF001

    candidates = await controller._select_candidates(  # noqa: SLF001
        workspace_id=ws, run_id="r", query="alpha beta gamma", top_k=10
    )
    by_id = {c.memory.memory_id: c for c in candidates}
    # Every seeded memory shares a query token, so all are positive candidates;
    # the fused ranked lists therefore cover exactly the seeded corpus.
    assert set(by_id) == set(contents)

    def _ranked(attr: str) -> list[str]:
        present = [
            (c.memory.memory_id, getattr(c, attr)) for c in candidates if getattr(c, attr) > 0.0
        ]
        present.sort(key=lambda pair: (-pair[1], pair[0]))
        return [memory_id for memory_id, _ in present]

    lexical_ranked = _ranked("lexical_score")
    vector_ranked = _ranked("vector_score")
    bm25_ranked = _ranked("bm25_score")

    # Each signal ranks a *different* memory first (three distinct winners).
    assert lexical_ranked[0] == "m_lex"
    assert vector_ranked[0] == "m_vec"
    assert bm25_ranked[0] == "m_bm"
    assert len({lexical_ranked[0], vector_ranked[0], bm25_ranked[0]}) == 3

    # The BM25-only winner is low on lexical and only mid on vector, yet it still
    # places among the candidates because the third (BM25) list feeds the fusion.
    assert "m_bm" in by_id
    assert lexical_ranked[0] != "m_bm"
    assert vector_ranked[0] != "m_bm"

    k = controller._rrf_k  # noqa: SLF001

    def _rrf(ranked_lists: list[list[str]]) -> dict[str, float]:
        scores: dict[str, float] = {}
        for ranked in ranked_lists:
            for rank, memory_id in enumerate(ranked):
                scores[memory_id] = scores.get(memory_id, 0.0) + 1.0 / (k + rank + 1)
        return scores

    # Final ordering is consistent with an RRF sum over the three ranked lists,
    # and each fused relevance score equals that reciprocal-rank sum.
    fused = _rrf([lexical_ranked, vector_ranked, bm25_ranked])
    expected_order = sorted(fused, key=lambda memory_id: (-fused[memory_id], memory_id))
    actual_order = [c.memory.memory_id for c in candidates]
    assert actual_order == expected_order
    for candidate in candidates:
        assert candidate.relevance_score == pytest.approx(
            round(fused[candidate.memory.memory_id], 6)
        )

    # Removing the BM25 list changes the fused order: with all three signals
    # m_lex leads, but on lexical+vector alone m_vec leads. This swap proves the
    # BM25 ranked list actually shapes the fused order.
    two_signal = _rrf([lexical_ranked, vector_ranked])
    two_signal_order = sorted(two_signal, key=lambda memory_id: (-two_signal[memory_id], memory_id))
    assert two_signal_order != expected_order
    assert expected_order[0] == "m_lex"
    assert two_signal_order[0] == "m_vec"
