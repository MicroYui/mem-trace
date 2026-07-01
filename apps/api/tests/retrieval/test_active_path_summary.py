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


def test_keep_recent_zero_folds_all_completed_steps():
    # keep_recent=0 means no completed step is shown verbatim: with compression
    # active (summarize_after > 0) every completed step on the active path is
    # folded into the single deterministic summary segment, leaving only that
    # line in the protected block.
    nodes = [_root()] + [_completed(f"step {i}", i) for i in range(6)]
    block = build_active_path_block(nodes, summarize_after=3, keep_recent=0)
    assert block is not None
    assert block.type == "active_path"
    # all six completed steps folded into one summary segment ...
    assert "6 earlier completed steps summarized" in block.content
    # ... and none shown verbatim.
    for i in range(6):
        assert f"step {i}" not in block.content
    # The block is EXACTLY the summary segment: no recent-step tail remains.
    assert block.content == "Progress so far: [6 earlier completed steps summarized]."
    assert block.tokens == estimate_tokens(block.content)


def test_summary_block_survives_tight_budget():
    # Same long completed active path, packed twice under the SAME tight budget:
    # compression OFF (full verbatim block) vs ON (bounded summarized block).
    # active_path is a protected block, so under budget pressure it is never
    # dropped but is truncated/degraded when it does not fit. Compression keeps
    # the block bounded so it survives the tight budget intact and smaller.
    path = [_completed(f"completed subgoal number {i}", i) for i in range(8)]
    off_full = build_active_path_block(path)  # summarize_after=0 -> verbatim
    assert off_full is not None
    # Budget between the summarized size and the full size: the full verbatim
    # block cannot survive intact, the summarized one can.
    budget = 40
    assert off_full.tokens > budget  # sanity: the full block does not fit

    off = pack_context(
        active_node=None,
        accepted=[],
        active_path=path,
        token_budget=budget,
    )
    on = pack_context(
        active_node=None,
        accepted=[],
        active_path=path,
        token_budget=budget,
        active_path_summarize_after=3,
        active_path_keep_recent=2,
    )
    off_ap = next(b for b in off.blocks if b.type == "active_path")
    on_ap = next(b for b in on.blocks if b.type == "active_path")

    # ON: retains a smaller, summarized progress block, intact within budget,
    # still carrying the most recent verbatim progress.
    assert "earlier completed steps summarized" in on_ap.content
    assert "(truncated)" not in on_ap.content
    assert "completed subgoal number 7" in on_ap.content
    assert on_ap.tokens < off_full.tokens
    assert on.used <= budget

    # OFF: no summarized block exists; the full verbatim block is degraded
    # (truncated) under the same budget and loses the most recent progress.
    assert "earlier completed steps summarized" not in off_ap.content
    assert "(truncated)" in off_ap.content
    assert off_ap.tokens < off_full.tokens
    assert "completed subgoal number 7" not in off_ap.content
