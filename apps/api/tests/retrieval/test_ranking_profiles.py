"""Deterministic task-intent ranking profile tests (ROADMAP §4, default-off).

Covers profile selection by intent keyword, the controller re-weighting (a
debug intent boosts tool_evidence enough to flip a tie), the default-off no-op,
and policy-snapshot byte-stability.
"""
from __future__ import annotations

import pytest

from app.config import get_settings
from app.retrieval.controller import RetrievalController
from app.retrieval.gate import GateConfig
from app.retrieval.policy import build_policy_snapshot
from app.retrieval.ranking_profiles import DEFAULT_PROFILE, select_profile
from app.runtime.models import MemoryItem, MemoryType, RetrievalRequest, RetrievalStrategy
from app.runtime.repository import InMemoryRepository


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _mem(ws, memory_id, content, mtype):
    return MemoryItem(
        memory_id=memory_id,
        workspace_id=ws,
        memory_type=mtype,
        content=content,
        summary=content[:60],
    )


# --------------------------- profile selection ---------------------- #


def test_select_profile_matches_intent_keywords():
    assert select_profile("fix the broken test").name == "debug"
    assert select_profile("implement the feature").name == "implement"
    assert select_profile("review the diff").name == "review"


def test_select_profile_defaults_when_empty_or_unmatched():
    assert select_profile(None) is DEFAULT_PROFILE
    assert select_profile("") is DEFAULT_PROFILE
    assert select_profile("retrieve memories").name == "default"


def test_select_profile_is_deterministic_first_match_wins():
    # "fix" (debug) is checked before "implement"; debug wins.
    assert select_profile("fix then implement").name == "debug"


# ----------------------- controller integration ---------------------- #


@pytest.mark.asyncio
async def test_ranking_profiles_off_by_default(monkeypatch):
    monkeypatch.delenv("MEMTRACE_RETRIEVAL_RANKING_PROFILES_ENABLED", raising=False)
    get_settings.cache_clear()
    controller = RetrievalController(InMemoryRepository())
    assert controller._ranking_profiles_enabled is False  # noqa: SLF001


async def _seed_equal(repo, ws):
    # Identical content => equal base relevance. The episodic id sorts first, so
    # it wins the tie by default; the debug profile must flip tool_evidence ahead.
    await repo.add_memory(_mem(ws, "m_a_epi", "gateway service", MemoryType.episodic))
    await repo.add_memory(_mem(ws, "m_z_tool", "gateway service", MemoryType.tool_evidence))


@pytest.mark.asyncio
async def test_ranking_profiles_off_keeps_tie_order(monkeypatch):
    monkeypatch.setenv("MEMTRACE_RETRIEVAL_RANKING_PROFILES_ENABLED", "false")
    monkeypatch.setenv("MEMTRACE_RETRIEVAL_USE_VECTOR", "false")
    get_settings.cache_clear()
    repo = InMemoryRepository()
    ws = "ws_rp_off"
    await _seed_equal(repo, ws)
    controller = RetrievalController(repo)
    cands = await controller._select_candidates(  # noqa: SLF001
        workspace_id=ws, run_id="r", query="gateway service", top_k=10, task_intent="fix the bug"
    )
    assert cands[0].memory.memory_id == "m_a_epi"  # tie-break by id, no re-weight


@pytest.mark.asyncio
async def test_ranking_profiles_debug_boosts_tool_evidence(monkeypatch):
    monkeypatch.setenv("MEMTRACE_RETRIEVAL_RANKING_PROFILES_ENABLED", "true")
    monkeypatch.setenv("MEMTRACE_RETRIEVAL_USE_VECTOR", "false")
    get_settings.cache_clear()
    repo = InMemoryRepository()
    ws = "ws_rp_on"
    await _seed_equal(repo, ws)
    controller = RetrievalController(repo)
    cands = await controller._select_candidates(  # noqa: SLF001
        workspace_id=ws, run_id="r", query="gateway service", top_k=10, task_intent="fix the bug"
    )
    by_id = {c.memory.memory_id: c for c in cands}
    assert cands[0].memory.memory_id == "m_z_tool"  # debug profile flips it ahead
    assert by_id["m_z_tool"].relevance_score > by_id["m_a_epi"].relevance_score


# --------------------------- policy snapshot ------------------------- #


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


def test_policy_snapshot_omits_ranking_profile_when_off():
    assert "ranking_profile" not in _snap(ranking_profile=None)["retrieval"]


def test_policy_snapshot_records_ranking_profile_when_enabled():
    assert _snap(ranking_profile="debug")["retrieval"]["ranking_profile"] == "debug"
