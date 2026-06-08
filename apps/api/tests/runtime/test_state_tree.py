"""Pure state-tree helper tests."""
from __future__ import annotations

from app.runtime import state_tree as st
from app.runtime.models import StateNodeStatus, StateNodeType, StepStatus


def _root():
    return st.make_root_node(workspace_id="ws", run_id="r")


def test_make_step_node_increments_depth_and_path():
    root = _root()
    node = st.make_step_node(workspace_id="ws", run_id="r", step_id="s1", parent=root)
    assert node.depth == 1
    assert node.parent_id == root.node_id
    assert node.path.startswith(root.path + "/")


def test_apply_finish_maps_status():
    root = _root()
    n = st.make_step_node(workspace_id="ws", run_id="r", step_id="s1", parent=root)
    st.apply_finish(n, StepStatus.completed)
    assert n.status == StateNodeStatus.completed
    st.apply_finish(n, StepStatus.failed)
    assert n.status == StateNodeStatus.failed


def test_recovery_parent_resolves_failed_nodes_parent():
    root = _root()
    failed = st.make_step_node(workspace_id="ws", run_id="r", step_id="s1", parent=root)
    nodes = {root.node_id: root, failed.node_id: failed}
    assert st.recovery_parent(failed, nodes).node_id == root.node_id


def test_descendants_collects_transitive_children():
    root = _root()
    a = st.make_step_node(workspace_id="ws", run_id="r", step_id="a", parent=root)
    b = st.make_step_node(workspace_id="ws", run_id="r", step_id="b", parent=a)
    c = st.make_step_node(workspace_id="ws", run_id="r", step_id="c", parent=b)
    ds = st.descendants(a.node_id, [root, a, b, c])
    ids = {n.node_id for n in ds}
    assert ids == {b.node_id, c.node_id}


def test_apply_rollback_preserves_failure_reason():
    root = _root()
    n = st.make_step_node(workspace_id="ws", run_id="r", step_id="s1", parent=root)
    n.status = StateNodeStatus.failed
    n.failure_reason = "orig"
    st.apply_rollback(n, reason="rollback-reason")
    assert n.status == StateNodeStatus.rolled_back
    assert n.failure_reason == "orig"  # original kept
    assert n.branch_reason["rollback_reason"] == "rollback-reason"


def test_active_path_excludes_failed_and_descendants():
    root = _root()
    ok = st.make_step_node(workspace_id="ws", run_id="r", step_id="ok", parent=root)
    ok.status = StateNodeStatus.completed
    failed = st.make_step_node(workspace_id="ws", run_id="r", step_id="f", parent=root)
    failed.status = StateNodeStatus.rolled_back
    child = st.make_step_node(workspace_id="ws", run_id="r", step_id="c", parent=failed)
    recovery = st.make_step_node(
        workspace_id="ws", run_id="r", step_id="rec", parent=root, node_type=StateNodeType.recovery
    )
    active = st.active_path_node_ids([root, ok, failed, child, recovery])
    assert root.node_id in active
    assert recovery.node_id in active
    assert failed.node_id not in active
    assert child.node_id not in active  # descendant of failed
