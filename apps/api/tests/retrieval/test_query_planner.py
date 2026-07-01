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
from app.retrieval.query_planner import (
    decide_need_retrieval,
    hint_boost,
    plan_query,
    rewrite_query,
)
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


# --------------------- need-retrieval decision ----------------------- #


def test_decide_need_retrieval_skips_trivial_filler_query():
    decision = decide_need_retrieval("ok thanks, continue")
    assert decision.should_retrieve is False
    assert decision.reason == "no_retrieval_signal"


def test_decide_need_retrieval_keeps_query_with_entity():
    decision = decide_need_retrieval("set project.runtime")
    assert decision.should_retrieve is True
    assert decision.reason == "has_retrieval_signal"


def test_decide_need_retrieval_keeps_query_with_content_word():
    decision = decide_need_retrieval("how do i run the tests")
    assert decision.should_retrieve is True  # "tests" is a content signal token


def test_decide_need_retrieval_empty_query_skips():
    assert decide_need_retrieval("").should_retrieve is False
    assert decide_need_retrieval(None).should_retrieve is False


def test_decide_need_retrieval_uses_task_intent():
    decision = decide_need_retrieval("go", task_intent="debug the migration")
    assert decision.should_retrieve is True


# --------------------------- query rewrite --------------------------- #


def test_rewrite_query_expands_structural_entity_into_components():
    rewrite = rewrite_query("set project.runtime please")
    assert "project" in rewrite.added_terms
    assert "runtime" in rewrite.added_terms
    assert rewrite.text.startswith("set project.runtime please")
    assert rewrite.reason == "expanded"


def test_rewrite_query_without_entities_is_unchanged():
    rewrite = rewrite_query("how do i run the tests")
    assert rewrite.added_terms == ()
    assert rewrite.text == "how do i run the tests"
    assert rewrite.reason == "no_rewrite"


def test_rewrite_query_does_not_duplicate_existing_tokens():
    # "runtime" already appears verbatim, so it must not be re-appended.
    rewrite = rewrite_query("runtime project.runtime")
    assert rewrite.added_terms.count("runtime") == 0
    assert "project" in rewrite.added_terms


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


@pytest.mark.asyncio
async def test_query_planner_full_skips_retrieval_for_trivial_query(monkeypatch):
    monkeypatch.setenv("MEMTRACE_RETRIEVAL_QUERY_PLANNER", "full")
    monkeypatch.setenv("MEMTRACE_RETRIEVAL_USE_VECTOR", "false")
    get_settings.cache_clear()
    repo = InMemoryRepository()
    ws = "ws_full_skip"
    await repo.add_memory(_mem(ws, "m1", "runtime.flag here"))
    controller = RetrievalController(repo)
    assert controller._query_planner == "full"  # noqa: SLF001
    cands = await controller._select_candidates(  # noqa: SLF001
        workspace_id=ws, run_id="r", query="ok thanks continue", top_k=10
    )
    assert cands == []  # need-retrieval decision skips the whole pass


@pytest.mark.asyncio
async def test_query_planner_full_rewrite_surfaces_prose_memory(monkeypatch):
    monkeypatch.setenv("MEMTRACE_RETRIEVAL_QUERY_PLANNER", "full")
    monkeypatch.setenv("MEMTRACE_RETRIEVAL_USE_VECTOR", "false")
    get_settings.cache_clear()
    repo = InMemoryRepository()
    ws = "ws_full_rewrite"
    # Prose spells "runtime" but never the dotted key; the tokenizer keeps
    # "project.runtime" whole, so only query rewrite (component expansion) makes
    # this candidate match.
    await repo.add_memory(_mem(ws, "m_prose", "the runtime is bun"))
    controller = RetrievalController(repo)
    cands = await controller._select_candidates(  # noqa: SLF001
        workspace_id=ws, run_id="r", query="project.runtime", top_k=10
    )
    assert "m_prose" in {c.memory.memory_id for c in cands}


@pytest.mark.asyncio
async def test_query_planner_hints_does_not_rewrite_prose_memory(monkeypatch):
    # Contrast: under hints (no rewrite) the dotted query misses the prose memory.
    monkeypatch.setenv("MEMTRACE_RETRIEVAL_QUERY_PLANNER", "hints")
    monkeypatch.setenv("MEMTRACE_RETRIEVAL_USE_VECTOR", "false")
    get_settings.cache_clear()
    repo = InMemoryRepository()
    ws = "ws_hints_prose"
    await repo.add_memory(_mem(ws, "m_prose", "the runtime is bun"))
    controller = RetrievalController(repo)
    cands = await controller._select_candidates(  # noqa: SLF001
        workspace_id=ws, run_id="r", query="project.runtime", top_k=10
    )
    assert all(c.memory.memory_id != "m_prose" for c in cands)


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


def test_query_planner_full_setting_is_accepted_and_snapshotted(monkeypatch):
    monkeypatch.setenv("MEMTRACE_RETRIEVAL_QUERY_PLANNER", "full")
    get_settings.cache_clear()
    assert get_settings().retrieval_query_planner == "full"
    snap = _snap(query_planner="full", query_planner_weight=0.1)
    assert snap["retrieval"]["query_planner"] == "full"


def test_invalid_query_planner_setting_is_rejected(monkeypatch):
    monkeypatch.setenv("MEMTRACE_RETRIEVAL_QUERY_PLANNER", "rewrite")
    get_settings.cache_clear()
    with pytest.raises(ValidationError, match="retrieval_query_planner must be one of"):
        get_settings()


# ------------------- full mode: enabled-state regressions ------------------- #


def _project_mem(ws: str, memory_id: str, content: str) -> MemoryItem:
    return MemoryItem(
        memory_id=memory_id,
        workspace_id=ws,
        memory_type=MemoryType.project,
        content=content,
        summary=content[:60],
    )


@pytest.mark.asyncio
async def test_full_mode_trivial_query_skips_even_project_constraint(monkeypatch):
    # A no-signal greeting query short-circuits at the need-retrieval decision
    # (controller ~808) and returns BEFORE memories are loaded, so the
    # project-constraint force-include (~899) is never reached. Even a project
    # memory — which the force-include would otherwise always surface — stays
    # out, proving the skip precedes memory loading rather than filtering after.
    monkeypatch.setenv("MEMTRACE_RETRIEVAL_QUERY_PLANNER", "full")
    monkeypatch.setenv("MEMTRACE_RETRIEVAL_USE_VECTOR", "false")
    get_settings.cache_clear()
    repo = InMemoryRepository()
    ws = "ws_full_project_skip"
    await repo.add_memory(_project_mem(ws, "m_proj", "always use runtime.flag = bun"))
    controller = RetrievalController(repo)
    assert controller._query_planner == "full"  # noqa: SLF001
    cands = await controller._select_candidates(  # noqa: SLF001
        workspace_id=ws, run_id="r", query="ok thanks continue", top_k=10
    )
    assert cands == []


@pytest.mark.asyncio
async def test_full_mode_task_intent_keeps_and_rewrites(monkeypatch):
    # A trivial surface query ("go") still retrieves when the task_intent carries
    # a dotted entity: decide_need_retrieval keeps the pass on via the intent
    # signal, and rewrite_query expands "service.gateway" into its component
    # words so a prose memory spelling them out is surfaced. Without the rewrite
    # the plain query "go" shares no token with the prose, so a non-empty result
    # containing m_prose proves both the need decision and the rewrite fired.
    monkeypatch.setenv("MEMTRACE_RETRIEVAL_QUERY_PLANNER", "full")
    monkeypatch.setenv("MEMTRACE_RETRIEVAL_USE_VECTOR", "false")
    get_settings.cache_clear()
    repo = InMemoryRepository()
    ws = "ws_full_intent"
    await repo.add_memory(_mem(ws, "m_prose", "the service gateway is down"))
    controller = RetrievalController(repo)
    cands = await controller._select_candidates(  # noqa: SLF001
        workspace_id=ws,
        run_id="r",
        query="go",
        top_k=10,
        task_intent="debug service.gateway",
    )
    assert cands  # retrieval RAN — the intent signal kept need-retrieval on
    assert "m_prose" in {c.memory.memory_id for c in cands}


@pytest.mark.asyncio
async def test_full_mode_rewrite_splits_path(monkeypatch):
    # A path-bearing query is rewritten into its component words. The tokenizer
    # keeps "app.py" whole and splits on "/", so the rewrite must contribute the
    # bare "app" component for the prose memory (which only says "app") to match.
    monkeypatch.setenv("MEMTRACE_RETRIEVAL_QUERY_PLANNER", "full")
    monkeypatch.setenv("MEMTRACE_RETRIEVAL_USE_VECTOR", "false")
    get_settings.cache_clear()
    repo = InMemoryRepository()
    ws = "ws_full_path"
    await repo.add_memory(_mem(ws, "m_prose", "edit the app module"))
    controller = RetrievalController(repo)
    cands = await controller._select_candidates(  # noqa: SLF001
        workspace_id=ws, run_id="r", query="open src/app.py", top_k=10
    )
    assert "m_prose" in {c.memory.memory_id for c in cands}
