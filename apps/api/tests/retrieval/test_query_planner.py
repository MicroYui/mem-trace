"""Deterministic query-planner tests (ROADMAP §4): entity/keyword hints.

The planner is default-off. When enabled (`MEMTRACE_RETRIEVAL_QUERY_PLANNER=hints`)
it extracts entity-like query terms (dotted keys, paths, identifiers) and gives a
small bounded lexical boost to candidates that mention them. Covers the pure
planner, the controller boost + ranking flip, the default-off no-op, and policy
snapshot byte-stability.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import get_settings
from app.retrieval.controller import RetrievalController
from app.retrieval.gate import GateConfig
from app.retrieval.policy import build_policy_snapshot
from app.retrieval.query_planner import hint_boost, plan_query
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


# --------------------------- pure planner --------------------------- #


def test_plan_query_extracts_entity_like_terms_only():
    plan = plan_query("configure runtime.flag and install the package")
    assert plan.hints == ("runtime.flag",)
    assert plan.reason == "entity_hints"


def test_plan_query_includes_paths_identifiers_and_versioned_tokens():
    plan = plan_query("open src/app.py set api_key bump to v2.0")
    assert "src/app.py" in plan.hints
    assert "api_key" in plan.hints
    assert "v2.0" in plan.hints  # embedded digit => entity-like


def test_plan_query_dedupes_lowercases_and_caps():
    plan = plan_query("A.B a.b " + " ".join(f"k{i}.v" for i in range(20)))
    assert len(plan.hints) <= 8
    assert plan.hints.count("a.b") == 1
    assert all(hint == hint.lower() for hint in plan.hints)


def test_plan_query_without_entities_is_empty():
    plan = plan_query("how do i run the tests")
    assert plan.hints == ()
    assert plan.reason == "no_entity_hints"


def test_plan_query_uses_task_intent_too():
    plan = plan_query("run it", task_intent="debug feature-flag rollout")
    assert "feature-flag" in plan.hints


def test_hint_boost_is_bounded_and_proportional():
    hints = ("a.b", "c.d")
    assert hint_boost("mentions a.b only", hints, weight=0.1) == pytest.approx(0.05)
    assert hint_boost("mentions a.b and c.d", hints, weight=0.1) == pytest.approx(0.1)
    assert hint_boost("nothing here", hints, weight=0.1) == 0.0
    assert hint_boost("a.b", (), weight=0.1) == 0.0
    assert hint_boost("a.b", hints, weight=0.0) == 0.0


# ----------------------- controller integration ---------------------- #


async def _seed(repo: InMemoryRepository, ws: str) -> None:
    # Both memories share exactly one query token (equal plain lexical), but only
    # m_zzz_entity carries the dotted entity term. The memory ids put the entity
    # one LAST, so the default-off tie-break ranks it second; the boost must flip
    # it to first.
    await repo.add_memory(_mem(ws, "m_aaa_other", "value here"))
    await repo.add_memory(_mem(ws, "m_zzz_entity", "runtime.flag here"))


@pytest.mark.asyncio
async def test_query_planner_off_by_default(monkeypatch):
    monkeypatch.delenv("MEMTRACE_RETRIEVAL_QUERY_PLANNER", raising=False)
    get_settings.cache_clear()
    controller = RetrievalController(InMemoryRepository())
    assert controller._query_planner == "off"  # noqa: SLF001


@pytest.mark.asyncio
async def test_query_planner_hints_boosts_entity_candidate_and_flips_ranking(monkeypatch):
    monkeypatch.setenv("MEMTRACE_RETRIEVAL_QUERY_PLANNER", "hints")
    monkeypatch.setenv("MEMTRACE_RETRIEVAL_USE_VECTOR", "false")
    get_settings.cache_clear()
    repo = InMemoryRepository()
    ws = "ws_planner_on"
    await _seed(repo, ws)
    controller = RetrievalController(repo)
    assert controller._query_planner == "hints"  # noqa: SLF001

    cands = await controller._select_candidates(  # noqa: SLF001
        workspace_id=ws, run_id="r", query="configure runtime.flag value", top_k=10
    )
    by_id = {c.memory.memory_id: c for c in cands}
    assert by_id["m_zzz_entity"].relevance_score > by_id["m_aaa_other"].relevance_score
    assert cands[0].memory.memory_id == "m_zzz_entity"


@pytest.mark.asyncio
async def test_query_planner_off_keeps_equal_scores_and_tie_break(monkeypatch):
    monkeypatch.setenv("MEMTRACE_RETRIEVAL_QUERY_PLANNER", "off")
    monkeypatch.setenv("MEMTRACE_RETRIEVAL_USE_VECTOR", "false")
    get_settings.cache_clear()
    repo = InMemoryRepository()
    ws = "ws_planner_off"
    await _seed(repo, ws)
    controller = RetrievalController(repo)

    cands = await controller._select_candidates(  # noqa: SLF001
        workspace_id=ws, run_id="r", query="configure runtime.flag value", top_k=10
    )
    by_id = {c.memory.memory_id: c for c in cands}
    # Equal lexical, no boost => identical score, tie-break by memory_id asc.
    assert by_id["m_zzz_entity"].relevance_score == by_id["m_aaa_other"].relevance_score
    assert cands[0].memory.memory_id == "m_aaa_other"


# --------------------------- policy snapshot -------------------------- #


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


def test_policy_snapshot_omits_query_planner_when_off():
    snap = _snap(query_planner="off")
    assert "query_planner" not in snap["retrieval"]


def test_policy_snapshot_records_query_planner_when_enabled():
    snap = _snap(query_planner="hints", query_planner_weight=0.1)
    assert snap["retrieval"]["query_planner"] == "hints"
    assert snap["retrieval"]["query_planner_weight"] == 0.1


def test_invalid_query_planner_setting_is_rejected(monkeypatch):
    monkeypatch.setenv("MEMTRACE_RETRIEVAL_QUERY_PLANNER", "rewrite")
    get_settings.cache_clear()
    with pytest.raises(ValidationError, match="retrieval_query_planner must be one of"):
        get_settings()
