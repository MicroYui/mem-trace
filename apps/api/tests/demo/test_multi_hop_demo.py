"""Deterministic markers for the multi-hop retrieval demo (ROADMAP §4).

Locks the demo's before/after contract so a retrieval regression can't silently
break the showcase: a single pass finds only the query's direct match, one hop
recovers the entity-linked ``x-tenant`` fact and flips the action, the distractor
never leaks, the hop is budget-bounded, and ``multi_hop_hops`` appears in the
policy snapshot only when the feature is enabled.
"""
from __future__ import annotations

import asyncio

import pytest

from app.config import get_settings
from app.demo.run_multi_hop_demo import _render_markdown, run_multi_hop_demo


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(scope="module")
def report() -> dict:
    return asyncio.run(run_multi_hop_demo())


def test_single_pass_misses_the_linked_fact(report: dict):
    single = report["configs"]["single_pass"]
    # Only the direct query match; the linked fact is not reachable one-shot.
    assert single["candidates"] == [
        {
            "memory_id": "m_gateway",
            "hop": 0,
            "relevance": single["candidates"][0]["relevance"],
            "content": single["candidates"][0]["content"],
        }
    ]
    assert single["load_bearing_fact_present"] is False
    assert single["final_action"] == "route without x-tenant header"
    # policy snapshot omits the key entirely when the feature is off.
    assert single["policy_multi_hop_hops"] is None
    assert single["profile_multi_hop_candidate_count"] is None


def test_one_hop_recovers_the_linked_fact_and_flips_the_action(report: dict):
    multi = report["configs"]["multi_hop"]
    by_id = {c["memory_id"]: c for c in multi["candidates"]}
    # The direct match stays hop 0; the entity-linked memory is a hop-1 expansion.
    assert by_id["m_gateway"]["hop"] == 0
    assert by_id["m_tenant"]["hop"] == 1
    # The recovered fact reaches the packed context and flips the action.
    assert multi["load_bearing_fact_present"] is True
    assert multi["final_action"] == "route with x-tenant header"
    assert "m_tenant" in multi["accepted_memory_ids"]
    # Enabled: multi_hop_hops surfaces in the policy snapshot and profile.
    assert multi["policy_multi_hop_hops"] == 1
    assert multi["profile_multi_hop_candidate_count"] == 1


def test_expansion_is_targeted_not_indiscriminate(report: dict):
    multi = report["configs"]["multi_hop"]
    # The unrelated distractor shares no entity cue and must never surface.
    assert multi["distractor_leaked"] is False
    assert "m_theme" not in multi["accepted_memory_ids"]
    assert multi["hop_surfaced_memory_ids"] == ["m_tenant"]


def test_hop_is_budget_bounded(report: dict):
    tiny = report["configs"]["multi_hop_tiny_budget"]
    # A 1-token budget is already exceeded by the first pass, so no hop runs.
    assert tiny["hop_surfaced_memory_ids"] == []
    assert tiny["load_bearing_fact_present"] is False


def test_summary_payoff_markers(report: dict):
    s = report["summary"]
    assert s["linked_fact_recovered"] is True
    assert s["action_changed"] is True
    assert s["distractor_leaked"] is False
    assert s["budget_bounded"] is True
    assert s["policy_multi_hop_hops_off"] is None
    assert s["policy_multi_hop_hops_on"] == 1


def test_markdown_renders_without_error(report: dict):
    md = _render_markdown(report)
    assert "Multi-Hop Retrieval Demo" in md
    assert "route with x-tenant header" in md
