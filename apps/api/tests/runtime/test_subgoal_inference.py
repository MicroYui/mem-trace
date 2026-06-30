"""Deterministic subgoal auto-inference tests (ROADMAP §5, default-off).

Covers the extended node_type vocabulary, the pure grouping logic, and the
runtime read method's default-off gate.
"""
from __future__ import annotations

import pytest

from app.config import get_settings
from app.runtime.memory_runtime import MemoryRuntime
from app.runtime.models import (
    StartRunRequest,
    StartStepRequest,
    StateNode,
    StateNodeType,
)
from app.runtime.repository import InMemoryRepository
from app.runtime.subgoal_inference import infer_subgoals


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _node(node_id, *, goal, path, ntype=StateNodeType.step):
    return StateNode(
        node_id=node_id,
        workspace_id="ws",
        run_id="run_1",
        node_type=ntype,
        goal=goal,
        path=path,
    )


# --------------------------- node vocabulary ------------------------ #


def test_extended_node_types_exist():
    assert StateNodeType.subgoal.value == "subgoal"
    assert StateNodeType.tool_call.value == "tool_call"
    assert StateNodeType.summary.value == "summary"


# --------------------------- pure inference ------------------------- #


def test_infer_subgoals_groups_consecutive_same_goal_steps():
    nodes = [
        _node("n1", goal="set up auth", path="0001"),
        _node("n2", goal="set up auth", path="0002"),
        _node("n3", goal="add billing", path="0003"),
    ]
    subgoals = infer_subgoals(nodes)
    assert len(subgoals) == 2
    assert subgoals[0].node_ids == ("n1", "n2")
    assert subgoals[0].goal == "set up auth"
    assert subgoals[0].node_type == "subgoal"
    assert subgoals[1].node_ids == ("n3",)


def test_infer_subgoals_is_case_insensitive_and_ordered_by_path():
    nodes = [
        _node("n2", goal="Add Billing", path="0002"),
        _node("n1", goal="add billing", path="0001"),  # same goal, earlier path
    ]
    subgoals = infer_subgoals(nodes)
    assert len(subgoals) == 1
    assert subgoals[0].node_ids == ("n1", "n2")  # reordered by path


def test_infer_subgoals_ignores_root_nodes():
    nodes = [
        _node("root", goal="run", path="0000", ntype=StateNodeType.root),
        _node("n1", goal="task a", path="0001"),
    ]
    subgoals = infer_subgoals(nodes)
    assert all("root" not in sg.node_ids for sg in subgoals)
    assert subgoals[0].node_ids == ("n1",)


def test_infer_subgoals_includes_recovery_nodes():
    nodes = [
        _node("n1", goal="fix", path="0001"),
        _node("r1", goal="fix", path="0002", ntype=StateNodeType.recovery),
    ]
    subgoals = infer_subgoals(nodes)
    assert subgoals[0].node_ids == ("n1", "r1")


# ----------------------- runtime read method ------------------------ #


@pytest.mark.asyncio
async def test_infer_run_subgoals_off_by_default(monkeypatch):
    monkeypatch.delenv("MEMTRACE_STATE_TREE_SUBGOAL_INFERENCE_ENABLED", raising=False)
    get_settings.cache_clear()
    repo = InMemoryRepository()
    runtime = MemoryRuntime(repo)
    run = await runtime.start_run(StartRunRequest(workspace_id="ws", session_id="s"))
    assert await runtime.infer_run_subgoals(run.run_id) == []


@pytest.mark.asyncio
async def test_infer_run_subgoals_enabled_returns_groups(monkeypatch):
    monkeypatch.setenv("MEMTRACE_STATE_TREE_SUBGOAL_INFERENCE_ENABLED", "true")
    get_settings.cache_clear()
    repo = InMemoryRepository()
    runtime = MemoryRuntime(repo)
    run = await runtime.start_run(StartRunRequest(workspace_id="ws", session_id="s"))
    await runtime.start_step(StartStepRequest(run_id=run.run_id, goal="task a"))
    await runtime.start_step(StartStepRequest(run_id=run.run_id, goal="task a"))
    await runtime.start_step(StartStepRequest(run_id=run.run_id, goal="task b"))
    subgoals = await runtime.infer_run_subgoals(run.run_id)
    goals = [sg.goal for sg in subgoals]
    assert "task a" in goals and "task b" in goals
