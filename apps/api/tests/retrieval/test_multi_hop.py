"""Deterministic multi-hop iterative retrieval tests (ROADMAP §4 / draft §5).

Default-off. When `MEMTRACE_RETRIEVAL_MULTI_HOP_HOPS > 0`, the controller derives
entity cues from the first-pass candidates and runs extra hops to pull in
complementary memories the query never names, bounded by the token budget.
Covers the pure cue derivation, the linked-evidence expansion, the default-off
no-op, the budget bound, hop provenance, and policy-snapshot byte-stability.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import get_settings
from app.retrieval.controller import RetrievalController
from app.retrieval.gate import GateConfig
from app.retrieval.policy import build_policy_snapshot
from app.retrieval.query_planner import derive_hop_cues
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


# --------------------------- pure cue derivation --------------------- #


def test_derive_hop_cues_extracts_entity_like_only():
    cues = derive_hop_cues(
        ["auth flow uses service.gateway for routing"], exclude=set(), max_cues=8
    )
    assert cues == ("service.gateway",)  # plain words are not cues


def test_derive_hop_cues_excludes_already_covered_and_caps():
    cues = derive_hop_cues(
        ["a.b c.d e.f", "g.h"], exclude={"a.b"}, max_cues=2
    )
    assert "a.b" not in cues
    assert len(cues) == 2


def test_derive_hop_cues_dedupes_across_contents_in_order():
    cues = derive_hop_cues(["x.y then x.y", "z.w"], exclude=set(), max_cues=8)
    assert cues == ("x.y", "z.w")


# ----------------------- controller integration ---------------------- #


async def _seed_linked(repo: InMemoryRepository, ws: str) -> None:
    # A answers the query and references service.gateway; B is reachable ONLY
    # via that shared entity (it shares no token with the "auth flow" query).
    await repo.add_memory(_mem(ws, "m_a", "auth flow uses service.gateway for routing"))
    await repo.add_memory(_mem(ws, "m_b", "service.gateway forwards requests to billing"))


@pytest.mark.asyncio
async def test_multi_hop_off_by_default(monkeypatch):
    monkeypatch.delenv("MEMTRACE_RETRIEVAL_MULTI_HOP_HOPS", raising=False)
    get_settings.cache_clear()
    controller = RetrievalController(InMemoryRepository())
    assert controller._multi_hop_hops == 0  # noqa: SLF001


@pytest.mark.asyncio
async def test_single_pass_misses_linked_memory(monkeypatch):
    monkeypatch.setenv("MEMTRACE_RETRIEVAL_MULTI_HOP_HOPS", "0")
    monkeypatch.setenv("MEMTRACE_RETRIEVAL_USE_VECTOR", "false")
    get_settings.cache_clear()
    repo = InMemoryRepository()
    ws = "ws_single"
    await _seed_linked(repo, ws)
    controller = RetrievalController(repo)
    cands = await controller._select_candidates_multi_hop(  # noqa: SLF001
        workspace_id=ws, run_id="r", query="auth flow", top_k=10, token_budget=512
    )
    ids = {c.memory.memory_id for c in cands}
    assert ids == {"m_a"}  # B not reachable from the query alone


@pytest.mark.asyncio
async def test_multi_hop_surfaces_linked_memory(monkeypatch):
    monkeypatch.setenv("MEMTRACE_RETRIEVAL_MULTI_HOP_HOPS", "1")
    monkeypatch.setenv("MEMTRACE_RETRIEVAL_USE_VECTOR", "false")
    get_settings.cache_clear()
    repo = InMemoryRepository()
    ws = "ws_hop"
    await _seed_linked(repo, ws)
    controller = RetrievalController(repo)
    assert controller._multi_hop_hops == 1  # noqa: SLF001
    cands = await controller._select_candidates_multi_hop(  # noqa: SLF001
        workspace_id=ws, run_id="r", query="auth flow", top_k=10, token_budget=512
    )
    by_id = {c.memory.memory_id: c for c in cands}
    assert "m_b" in by_id  # reached via the shared service.gateway cue
    assert by_id["m_a"].hop == 0
    assert by_id["m_b"].hop == 1  # provenance marks it as a hop expansion


@pytest.mark.asyncio
async def test_multi_hop_is_budget_bounded(monkeypatch):
    monkeypatch.setenv("MEMTRACE_RETRIEVAL_MULTI_HOP_HOPS", "1")
    monkeypatch.setenv("MEMTRACE_RETRIEVAL_USE_VECTOR", "false")
    get_settings.cache_clear()
    repo = InMemoryRepository()
    ws = "ws_budget"
    await _seed_linked(repo, ws)
    controller = RetrievalController(repo)
    # A tiny budget is already exceeded by the first-pass content, so no hop runs.
    cands = await controller._select_candidates_multi_hop(  # noqa: SLF001
        workspace_id=ws, run_id="r", query="auth flow", top_k=10, token_budget=1
    )
    assert {c.memory.memory_id for c in cands} == {"m_a"}


# --------------------------- config + policy ------------------------- #


def test_invalid_multi_hop_hops_rejected(monkeypatch):
    monkeypatch.setenv("MEMTRACE_RETRIEVAL_MULTI_HOP_HOPS", "9")
    get_settings.cache_clear()
    with pytest.raises(ValidationError, match="retrieval_multi_hop_hops must be between"):
        get_settings()


def test_invalid_multi_hop_max_cues_rejected(monkeypatch):
    monkeypatch.setenv("MEMTRACE_RETRIEVAL_MULTI_HOP_MAX_CUES", "0")
    get_settings.cache_clear()
    with pytest.raises(ValidationError, match="retrieval_multi_hop_max_cues must be between"):
        get_settings()


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


def test_policy_snapshot_omits_multi_hop_when_off():
    assert "multi_hop_hops" not in _snap(multi_hop_hops=0)["retrieval"]


def test_policy_snapshot_records_multi_hop_when_enabled():
    assert _snap(multi_hop_hops=2)["retrieval"]["multi_hop_hops"] == 2


# ---------------- include_all short-circuit + graph dedupe ----------- #


@pytest.mark.asyncio
async def test_multi_hop_skipped_under_include_all(monkeypatch):
    # include_all (the long-context dump-everything baseline) must short-circuit
    # the cue-driven hops (controller.py ~line 748): even with HOPS enabled the
    # multi-hop pass returns exactly the single dump-everything pass, and no
    # candidate carries hop provenance because no cue expansion ran.
    monkeypatch.setenv("MEMTRACE_RETRIEVAL_MULTI_HOP_HOPS", "1")
    monkeypatch.setenv("MEMTRACE_RETRIEVAL_USE_VECTOR", "false")
    get_settings.cache_clear()
    repo = InMemoryRepository()
    ws = "ws_include_all"
    await _seed_linked(repo, ws)
    controller = RetrievalController(repo)
    assert controller._multi_hop_hops == 1  # noqa: SLF001
    hopped = await controller._select_candidates_multi_hop(  # noqa: SLF001
        workspace_id=ws,
        run_id="r",
        query="auth flow",
        top_k=10,
        token_budget=512,
        include_all=True,
    )
    base = await controller._select_candidates(  # noqa: SLF001
        workspace_id=ws, run_id="r", query="auth flow", top_k=10, include_all=True
    )
    # Byte-identical to the single dump-everything pass: hops were short-circuited.
    assert [(c.memory.memory_id, c.hop) for c in hopped] == [
        (c.memory.memory_id, c.hop) for c in base
    ]
    # No cue-driven hop ran, so nothing is marked as a hop expansion. m_b may be
    # present only because include_all dumps everything, and then only at hop 0.
    assert all(c.hop == 0 for c in hopped)


@pytest.mark.asyncio
async def test_multi_hop_and_graph_expansion_dedupe(monkeypatch):
    # m_b is reachable via BOTH the shared service.gateway cue (a hop-1 expansion)
    # and the provenance graph (an open conflict edge m_a<->m_b surfaces it at
    # hop 0 inside the base pass). The two paths must not double-count: m_b appears
    # exactly once with a single, internally-consistent hop provenance.
    from app.runtime.models import MemoryConflictRecord

    monkeypatch.setenv("MEMTRACE_RETRIEVAL_MULTI_HOP_HOPS", "1")
    monkeypatch.setenv("MEMTRACE_RETRIEVAL_USE_VECTOR", "false")
    monkeypatch.setenv("MEMTRACE_RETRIEVAL_GRAPH_BACKEND", "inmemory")
    get_settings.cache_clear()
    repo = InMemoryRepository()
    ws = "ws_hop_graph"
    await _seed_linked(repo, ws)
    # Open conflict pair => a CONFLICTS_WITH provenance edge between m_a and m_b.
    await repo.upsert_memory_conflict(
        MemoryConflictRecord(
            workspace_id=ws,
            subject_key="service.gateway.routing",
            memory_ids=["m_a", "m_b"],
            status="open",
        )
    )
    controller = RetrievalController(repo)
    assert controller._multi_hop_hops == 1  # noqa: SLF001
    assert controller._graph_backend is not None  # noqa: SLF001
    cands = await controller._select_candidates_multi_hop(  # noqa: SLF001
        workspace_id=ws, run_id="r", query="auth flow", top_k=10, token_budget=512
    )
    ids = [c.memory.memory_id for c in cands]
    # No duplicates anywhere, and m_b surfaced exactly once despite two paths.
    assert len(ids) == len(set(ids))
    assert ids.count("m_b") == 1
    by_id = {c.memory.memory_id: c for c in cands}
    assert "m_a" in by_id and "m_b" in by_id
    assert by_id["m_a"].hop == 0
    # m_b entered via the graph inside the base pass (hop 0, graph_score set); the
    # cue hop then found it again but deduped it rather than re-appending.
    assert by_id["m_b"].hop == 0
    assert by_id["m_b"].graph_score > 0.0
