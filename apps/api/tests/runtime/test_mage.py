"""Deterministic MAGE state-tree operation planner tests (ROADMAP §5/§9, default-off).

Covers each of Grow/Compress/Maintain/Revise, the empty plan, and the runtime
read method's default-off gate.
"""
from __future__ import annotations

import pytest

from app.config import get_settings
from app.runtime.mage import MagePlan, plan_mage
from app.runtime.memory_runtime import MemoryRuntime
from app.runtime.models import (
    MemoryItem,
    MemoryStatus,
    MemoryType,
    StartRunRequest,
    StartStepRequest,
    StateNode,
    StateNodeStatus,
    StateNodeType,
)
from app.runtime.repository import InMemoryRepository


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _node(node_id, *, goal=None, path="0001", status=StateNodeStatus.active,
          ntype=StateNodeType.step, parent_id=None):
    return StateNode(
        node_id=node_id, workspace_id="ws", run_id="run_1", node_type=ntype,
        status=status, goal=goal, path=path, parent_id=parent_id,
    )


def _mem(memory_id, *, node_id, freshness=1.0, status=MemoryStatus.active):
    return MemoryItem(
        memory_id=memory_id, workspace_id="ws", memory_type=MemoryType.episodic,
        content="c", summary="c", source_state_node_id=node_id,
        freshness_score=freshness, status=status,
    )


# --------------------------- pure planner --------------------------- #


def test_plan_mage_grow_marks_active_frontier():
    root = _node("root", ntype=StateNodeType.root, path="0000")
    leaf = _node("leaf", parent_id="root", path="0001")
    plan = plan_mage([root, leaf], [])
    assert any(op.target_ids == ("leaf",) for op in plan.grow)
    assert all(op.target_ids != ("root",) for op in plan.grow)  # root never grows


def test_plan_mage_compress_completed_subgoal():
    nodes = [
        _node(f"n{i}", goal="big task", path=f"000{i}", status=StateNodeStatus.completed)
        for i in range(1, 4)  # 3 completed same-goal steps
    ]
    plan = plan_mage(nodes, [], compress_min_steps=3)
    assert len(plan.compress) == 1
    assert plan.compress[0].target_ids == ("n1", "n2", "n3")


def test_plan_mage_no_compress_when_subgoal_too_small():
    nodes = [_node("n1", goal="t", path="0001", status=StateNodeStatus.completed)]
    plan = plan_mage(nodes, [], compress_min_steps=3)
    assert plan.compress == ()


def test_plan_mage_revise_failed_branch():
    nodes = [_node("f1", status=StateNodeStatus.failed), _node("r1", status=StateNodeStatus.rolled_back)]
    plan = plan_mage(nodes, [])
    revised = {op.target_ids[0] for op in plan.revise}
    assert revised == {"f1", "r1"}


def test_plan_mage_maintain_stale_memory_on_completed_node():
    node = _node("done", status=StateNodeStatus.completed)
    fresh = _mem("m_fresh", node_id="done", freshness=0.9)
    stale = _mem("m_stale", node_id="done", freshness=0.1)
    plan = plan_mage([node], [fresh, stale])
    assert len(plan.maintain) == 1
    assert plan.maintain[0].target_ids == ("m_stale",)  # only the stale one


def test_plan_mage_empty_when_nothing_applies():
    # A single active root with no memories => no ops.
    plan = plan_mage([_node("root", ntype=StateNodeType.root)], [])
    assert plan.is_empty()


# ----------------------- runtime read method ------------------------ #


@pytest.mark.asyncio
async def test_plan_run_mage_off_by_default(monkeypatch):
    monkeypatch.delenv("MEMTRACE_STATE_TREE_MAGE_ENABLED", raising=False)
    get_settings.cache_clear()
    repo = InMemoryRepository()
    runtime = MemoryRuntime(repo)
    run = await runtime.start_run(StartRunRequest(workspace_id="ws", session_id="s"))
    plan = await runtime.plan_run_mage(run.run_id)
    assert isinstance(plan, MagePlan)
    assert plan.is_empty()


@pytest.mark.asyncio
async def test_plan_run_mage_enabled_marks_active_frontier(monkeypatch):
    monkeypatch.setenv("MEMTRACE_STATE_TREE_MAGE_ENABLED", "true")
    get_settings.cache_clear()
    repo = InMemoryRepository()
    runtime = MemoryRuntime(repo)
    run = await runtime.start_run(StartRunRequest(workspace_id="ws", session_id="s"))
    await runtime.start_step(StartStepRequest(run_id=run.run_id, goal="do work"))
    plan = await runtime.plan_run_mage(run.run_id)
    # The active step is the work frontier; grow should mark it.
    assert not plan.is_empty()
    assert plan.grow


# ------------------------- appended regressions -------------------------- #


def test_compress_boundary_at_threshold():
    # Read the ACTUAL default threshold from plan_mage's signature so the
    # boundary is tested against the real contract, not a hardcoded copy.
    import inspect

    threshold = inspect.signature(plan_mage).parameters["compress_min_steps"].default
    assert isinstance(threshold, int) and threshold >= 2

    # EXACTLY `threshold` completed same-goal steps -> compress fires once.
    at_threshold = [
        _node(f"n{i}", goal="big task", path=f"{i:04d}", status=StateNodeStatus.completed)
        for i in range(1, threshold + 1)
    ]
    plan = plan_mage(at_threshold, [])  # uses the actual default compress_min_steps
    assert len(plan.compress) == 1
    op = plan.compress[0]
    assert op.op == "compress"
    assert op.target_ids == tuple(f"n{i}" for i in range(1, threshold + 1))

    # One below threshold (threshold - 1 nodes) -> Compress must NOT fire.
    below = [
        _node(f"b{i}", goal="big task", path=f"{i:04d}", status=StateNodeStatus.completed)
        for i in range(1, threshold)
    ]
    plan_below = plan_mage(below, [])
    assert plan_below.compress == ()


def test_maintain_flags_dormant_memory_with_high_freshness():
    # A completed-node memory that is decayed-by-status (dormant/archived) must
    # be flagged for Maintain even when its freshness is maximal — the status
    # branch of the stale predicate is independent of freshness.
    node = _node("done", status=StateNodeStatus.completed)
    dormant = _mem("m_dormant", node_id="done", freshness=1.0, status=MemoryStatus.dormant)
    archived = _mem("m_archived", node_id="done", freshness=1.0, status=MemoryStatus.archived)
    fresh_active = _mem("m_active", node_id="done", freshness=1.0, status=MemoryStatus.active)
    plan = plan_mage([node], [dormant, archived, fresh_active])
    assert len(plan.maintain) == 1
    op = plan.maintain[0]
    assert op.op == "maintain"
    # Both decayed-status memories are flagged despite freshness 1.0; the fresh
    # active memory is not. target_ids is sorted memory_id order.
    assert op.target_ids == ("m_archived", "m_dormant")
