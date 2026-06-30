"""ROADMAP §5: completed-subgoal compression into a bounded active-path summary.

``build_active_path_block`` lists every completed step on the active path, which
is a *protected* block (never dropped under budget pressure). On long-horizon
runs this grows unbounded. With compression enabled (default-off), the oldest
completed subgoals are folded into a single deterministic summary segment and
only the most recent are shown verbatim, coordinating with §9 Context
Compaction to keep the protected block bounded.
"""
from __future__ import annotations

from app.retrieval.packer import build_active_path_block, estimate_tokens, pack_context
from app.runtime.models import StateNode, StateNodeStatus, StateNodeType


def _root() -> StateNode:
    return StateNode(
        workspace_id="ws", run_id="r", node_type=StateNodeType.root,
        status=StateNodeStatus.active, depth=0, path="root",
    )


def _completed(goal: str, i: int) -> StateNode:
    return StateNode(
        workspace_id="ws", run_id="r", step_id=f"s{i}", node_type=StateNodeType.step,
        status=StateNodeStatus.completed, goal=goal, depth=i + 1, path=f"root/{i}",
    )


def _active_leaf() -> StateNode:
    return StateNode(
        workspace_id="ws", run_id="r", step_id="leaf", node_type=StateNodeType.step,
        status=StateNodeStatus.active, goal="current", depth=99, path="root/leaf",
    )


def test_lists_all_completed_steps_by_default():
    nodes = [_root()] + [_completed(f"step {i}", i) for i in range(6)]
    block = build_active_path_block(nodes)
    assert block is not None
    assert block.type == "active_path"
    for i in range(6):
        assert f"step {i}" in block.content
    assert "earlier completed steps" not in block.content


def test_compresses_old_completed_steps_when_enabled():
    nodes = [_root()] + [_completed(f"step {i}", i) for i in range(10)]
    block = build_active_path_block(nodes, summarize_after=5, keep_recent=3)
    assert block is not None
    assert block.type == "active_path"
    # oldest 7 folded into a summary segment, last 3 shown verbatim
    assert "7 earlier completed steps" in block.content
    assert "step 9" in block.content
    assert "step 8" in block.content
    assert "step 7" in block.content
    assert "step 0" not in block.content
    assert "step 6" not in block.content


def test_no_compression_when_at_or_below_threshold():
    nodes = [_root()] + [_completed(f"step {i}", i) for i in range(5)]
    block = build_active_path_block(nodes, summarize_after=5, keep_recent=3)
    assert block is not None
    assert "earlier completed steps" not in block.content
    for i in range(5):
        assert f"step {i}" in block.content


def test_compressed_block_is_smaller_than_full():
    nodes = [_root()] + [_completed(f"completed subgoal number {i}", i) for i in range(12)]
    full = build_active_path_block(nodes)
    compressed = build_active_path_block(nodes, summarize_after=4, keep_recent=2)
    assert full is not None and compressed is not None
    assert compressed.tokens < full.tokens
    assert compressed.tokens == estimate_tokens(compressed.content)


def test_pack_context_threads_active_path_summary_params():
    path = [_completed(f"step {i}", i) for i in range(10)] + [_active_leaf()]
    result = pack_context(
        active_node=_active_leaf(),
        accepted=[],
        active_path=path,
        token_budget=512,
        active_path_summarize_after=5,
        active_path_keep_recent=2,
    )
    ap = next(b for b in result.blocks if b.type == "active_path")
    assert "8 earlier completed steps" in ap.content
    assert "step 9" in ap.content
    assert "step 0" not in ap.content


def test_controller_threads_summary_settings_only_when_enabled(monkeypatch):
    from app.config import Settings
    from app.retrieval import controller as controller_mod
    from app.runtime.repository import InMemoryRepository

    enabled = Settings(
        summary_node_compression_enabled=True,
        active_path_summary_threshold=3,
        active_path_summary_keep_recent=1,
    )
    monkeypatch.setattr(controller_mod, "get_settings", lambda: enabled)
    c = controller_mod.RetrievalController(InMemoryRepository())
    assert c._active_path_summarize_after == 3
    assert c._active_path_keep_recent == 1

    disabled = Settings(summary_node_compression_enabled=False, active_path_summary_threshold=3)
    monkeypatch.setattr(controller_mod, "get_settings", lambda: disabled)
    c2 = controller_mod.RetrievalController(InMemoryRepository())
    # disabled -> 0 means build_active_path_block lists every completed step
    assert c2._active_path_summarize_after == 0
