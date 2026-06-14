"""Multi-signal candidate fusion tests (ROADMAP §4).

Covers Reciprocal Rank Fusion (RRF) as an alternative to the default linear
weighted blend, and that the retrieval policy snapshot records the fusion mode.
"""
from __future__ import annotations

import pytest

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
