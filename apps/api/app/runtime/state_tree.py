"""Pure state-tree transition helpers.

These functions construct and mutate `StateNode` objects without touching any
repository. Keeping them pure makes the failed-branch / recovery invariants
exhaustively unit-testable.

Key invariants (see mvp.md section 6):
- `start_step` creates an active node immediately (not on finish).
- A recovery node attaches to the *parent of the failed node*, never under the
  failed node, so the active path never traverses a failed branch.
- `failed` means the step failed but is not yet rolled back; `rolled_back` means
  it was explicitly removed from the active path by `rollback_branch`.
- `failure_reason` is preserved across rollback; `branch_reason` records audit
  fields (rollback_reason / recovery_from).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from app.runtime.models import (
    StateNode,
    StateNodeStatus,
    StateNodeType,
    StepStatus,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def make_root_node(*, workspace_id: str, run_id: str, goal: Optional[str] = None) -> StateNode:
    """Create the run's root state node."""
    return StateNode(
        workspace_id=workspace_id,
        run_id=run_id,
        parent_id=None,
        step_id=None,
        node_type=StateNodeType.root,
        status=StateNodeStatus.active,
        goal=goal,
        depth=0,
        path="root",
    )


def make_step_node(
    *,
    workspace_id: str,
    run_id: str,
    step_id: str,
    parent: StateNode,
    node_type: StateNodeType = StateNodeType.step,
    goal: Optional[str] = None,
    branch_reason: Optional[dict] = None,
) -> StateNode:
    """Create a step/recovery node as a child of `parent`.

    The caller is responsible for choosing the correct parent. For recovery
    nodes the parent must be the failed node's parent (resolve via
    `recovery_parent`).
    """
    depth = parent.depth + 1
    node = StateNode(
        workspace_id=workspace_id,
        run_id=run_id,
        parent_id=parent.node_id,
        step_id=step_id,
        node_type=node_type,
        status=StateNodeStatus.active,
        goal=goal,
        depth=depth,
        branch_reason=branch_reason or {},
    )
    node.path = f"{parent.path}/{node.node_id}"
    return node


def recovery_parent(failed_node: StateNode, all_nodes: dict[str, StateNode]) -> Optional[StateNode]:
    """Resolve where a recovery node should attach: the failed node's parent.

    Returns None only if the failed node has no parent (should not happen for a
    step node, but handled defensively).
    """
    if failed_node.parent_id is None:
        return None
    return all_nodes.get(failed_node.parent_id)


def apply_finish(node: StateNode, step_status: StepStatus) -> StateNode:
    """Map a finished step status onto the state node status."""
    if step_status == StepStatus.completed:
        node.status = StateNodeStatus.completed
    elif step_status == StepStatus.failed:
        node.status = StateNodeStatus.failed
    elif step_status == StepStatus.cancelled:
        node.status = StateNodeStatus.rolled_back
    node.updated_at = _now()
    return node


def descendants(node_id: str, all_nodes: list[StateNode]) -> list[StateNode]:
    """Return node_id's descendants (transitive children), excluding itself."""
    by_parent: dict[Optional[str], list[StateNode]] = {}
    for n in all_nodes:
        by_parent.setdefault(n.parent_id, []).append(n)

    out: list[StateNode] = []
    stack = list(by_parent.get(node_id, []))
    while stack:
        cur = stack.pop()
        out.append(cur)
        stack.extend(by_parent.get(cur.node_id, []))
    return out


def apply_rollback(node: StateNode, *, reason: Optional[str], recovery_from_step_id: Optional[str] = None) -> StateNode:
    """Mark a node rolled_back while preserving its original failure_reason.

    Records audit info under branch_reason without overwriting failure_reason.
    """
    if node.status == StateNodeStatus.failed and not node.failure_reason and reason:
        node.failure_reason = reason
    node.status = StateNodeStatus.rolled_back
    br = dict(node.branch_reason or {})
    br.setdefault("type", "rollback")
    if reason is not None:
        br["rollback_reason"] = reason
    if recovery_from_step_id is not None:
        br["recovery_from_step_id"] = recovery_from_step_id
    node.branch_reason = br
    node.updated_at = _now()
    return node


def active_path_node_ids(all_nodes: list[StateNode]) -> set[str]:
    """Return node ids that are on the active path: not failed/rolled_back, and
    with no failed/rolled_back ancestor."""
    by_id = {n.node_id: n for n in all_nodes}
    dead = {StateNodeStatus.failed, StateNodeStatus.rolled_back}
    active: set[str] = set()
    for n in all_nodes:
        if n.status in dead:
            continue
        ok = True
        cur: Optional[StateNode] = n
        while cur is not None:
            if cur.status in dead:
                ok = False
                break
            cur = by_id.get(cur.parent_id) if cur.parent_id else None
        if ok:
            active.add(n.node_id)
    return active


def active_path_chain(all_nodes: list[StateNode]) -> list[StateNode]:
    """Return the active path as an ordered progress list (root -> current).

    In the P0/P1 simplified tree, steps are siblings under root (or under a
    shared parent), so a strict parent walk would skip completed sibling steps.
    The active path is therefore all on-path nodes that are NOT failed/
    rolled_back and NOT descendants of a failed node, ordered by (depth,
    created_at). Failed branches are excluded by `active_path_node_ids`.
    """
    if not all_nodes:
        return []
    active_ids = active_path_node_ids(all_nodes)
    on_path = [n for n in all_nodes if n.node_id in active_ids]
    if not on_path:
        return []
    on_path.sort(key=lambda n: (n.depth, n.created_at))
    return on_path


__all__ = [
    "make_root_node",
    "make_step_node",
    "recovery_parent",
    "apply_finish",
    "apply_rollback",
    "descendants",
    "active_path_node_ids",
    "active_path_chain",
]
