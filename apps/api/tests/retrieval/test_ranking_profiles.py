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


# ------------------- overlapping-keyword determinism ----------------- #


def test_overlapping_keywords_pick_first_in_order():
    # The tie-breaker when an intent matches several keyword sets is _KEYWORDS
    # *insertion order*, not where the words sit in the string. Read the live
    # order so the test tracks the module rather than a hard-coded assumption.
    from app.retrieval.ranking_profiles import _KEYWORDS

    order = list(_KEYWORDS)
    assert order.index("debug") < order.index("implement")
    # "implement a fix" carries an implement keyword ("implement") *and* a debug
    # keyword ("fix"). Even though "implement" appears earlier in the string, the
    # debug set is scanned first (insertion order), so debug wins.
    assert select_profile("implement a fix").name == "debug"
    # Symmetric proof it is insertion order, not string position: swapping the
    # word order still resolves to debug.
    assert select_profile("fix by implementing").name == "debug"
    # No intent -> the shared DEFAULT profile, which is an identity (no weights).
    assert select_profile(None) is DEFAULT_PROFILE
    assert DEFAULT_PROFILE.type_weights == {}


# ------------------ profile re-weight after hybrid blend ------------- #


@pytest.mark.asyncio
async def test_profile_reweights_after_hybrid_blend(monkeypatch):
    # Contract: ranking profiles re-weight the *fused* relevance, i.e. the score
    # produced after the hybrid BM25 signal is blended in. Equal content ties the
    # fused score, so the debug profile's 1.3x tool_evidence multiplier alone must
    # deterministically flip the ordering.
    monkeypatch.setenv("MEMTRACE_RETRIEVAL_RANKING_PROFILES_ENABLED", "true")
    monkeypatch.setenv("MEMTRACE_RETRIEVAL_HYBRID_BACKEND", "inmemory")
    monkeypatch.setenv("MEMTRACE_RETRIEVAL_USE_VECTOR", "false")
    get_settings.cache_clear()
    repo = InMemoryRepository()
    ws = "ws_rp_hybrid"
    await _seed_equal(repo, ws)
    controller = RetrievalController(repo)
    assert controller._hybrid_backend is not None  # noqa: SLF001
    cands = await controller._select_candidates(  # noqa: SLF001
        workspace_id=ws, run_id="r", query="gateway service", top_k=10, task_intent="fix the bug"
    )
    by_id = {c.memory.memory_id: c for c in cands}
    tool = by_id["m_z_tool"]
    epi = by_id["m_a_epi"]
    # The hybrid backend really contributed a BM25 signal to both candidates, so
    # the fused base score is what the profile multiplier acts on.
    assert tool.bm25_score > 0.0
    assert epi.bm25_score > 0.0
    # Boosted tool_evidence ranks first, ahead of the id-earlier episodic tie.
    assert cands[0].memory.memory_id == "m_z_tool"
    assert tool.relevance_score > epi.relevance_score
    # episodic keeps its fused base (debug profile leaves episodic at weight 1.0),
    # so the boosted score is exactly the fused base times the 1.3 multiplier —
    # proving the re-weight ran after fusion, not on a pre-blend lexical score.
    assert tool.relevance_score == round(epi.relevance_score * 1.3, 6)
