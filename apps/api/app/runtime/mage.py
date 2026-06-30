"""Deterministic MAGE state-tree operation planner (ROADMAP §5 / §9, default-off).

The MAGE model (draft §3) frames long-horizon state-tree upkeep as four
operations: **Grow** (extend the active frontier), **Compress** (fold finished
subgoals into summary nodes), **Maintain** (decay/archive memories that have
gone stale), and **Revise** (correct failed/rolled-back branches). This module
computes a deterministic *plan* of those operations from a run's state tree and
memories — it never mutates anything. It is the coordination point the ROADMAP
§9 cross-reference calls for: state-tree summary nodes (§5), lifecycle decay
(§3.2), and context compaction (§9) are surfaced together as one plan.

Pure and side-effect free; exposed read-side via ``MemoryRuntime.plan_run_mage``
behind ``MEMTRACE_STATE_TREE_MAGE_ENABLED`` (default-off → an empty plan).
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from app.runtime.models import (
    MemoryItem,
    MemoryStatus,
    StateNode,
    StateNodeStatus,
    StateNodeType,
)
from app.runtime.subgoal_inference import infer_subgoals

_DECAYED_MEMORY_STATUSES = {MemoryStatus.dormant, MemoryStatus.archived}


@dataclass(frozen=True, slots=True)
class MageOperation:
    """One proposed MAGE operation over a set of node/memory targets."""

    op: str  # "grow" | "compress" | "maintain" | "revise"
    target_ids: tuple[str, ...]
    detail: str


@dataclass(frozen=True, slots=True)
class MagePlan:
    """The four MAGE operation lists for a run (deterministic, read-only)."""

    grow: tuple[MageOperation, ...] = ()
    compress: tuple[MageOperation, ...] = ()
    maintain: tuple[MageOperation, ...] = ()
    revise: tuple[MageOperation, ...] = ()

    def is_empty(self) -> bool:
        return not (self.grow or self.compress or self.maintain or self.revise)


def plan_mage(
    nodes: list[StateNode],
    memories: list[MemoryItem],
    *,
    compress_min_steps: int = 3,
    stale_freshness: float = 0.3,
) -> MagePlan:
    """Compute the MAGE operation plan for a run. Deterministic; no mutation."""
    node_by_id = {n.node_id: n for n in nodes}
    children: dict[str, list[StateNode]] = defaultdict(list)
    for node in nodes:
        if node.parent_id:
            children[node.parent_id].append(node)

    # Grow: active non-root nodes with no active child are the work frontier.
    grow: list[MageOperation] = []
    for node in sorted(nodes, key=lambda n: n.node_id):
        if (
            node.status == StateNodeStatus.active
            and node.node_type != StateNodeType.root
            and not any(c.status == StateNodeStatus.active for c in children[node.node_id])
        ):
            grow.append(MageOperation("grow", (node.node_id,), "active frontier; new work attaches here"))

    # Compress: a fully-completed inferred subgoal of >= compress_min_steps steps
    # is a candidate to fold into a single summary node (§5 × §9).
    compress: list[MageOperation] = []
    for subgoal in infer_subgoals(nodes):
        sg_nodes = [node_by_id[i] for i in subgoal.node_ids if i in node_by_id]
        if len(sg_nodes) >= compress_min_steps and all(
            n.status == StateNodeStatus.completed for n in sg_nodes
        ):
            compress.append(
                MageOperation(
                    "compress",
                    subgoal.node_ids,
                    f"completed subgoal '{subgoal.goal}' ({len(sg_nodes)} steps) -> summary node",
                )
            )

    # Revise: failed / rolled-back branches whose anchored memories should be
    # revised (superseded / surfaced as negative evidence).
    revise: list[MageOperation] = []
    for node in sorted(nodes, key=lambda n: n.node_id):
        if node.status in (StateNodeStatus.failed, StateNodeStatus.rolled_back):
            revise.append(
                MageOperation(
                    "revise",
                    (node.node_id,),
                    f"{node.status.value} branch; anchored memories should be revised",
                )
            )

    # Maintain: memories anchored to completed nodes that have gone stale (low
    # freshness or already dormant/archived) — the §3.2 lifecycle-decay ×
    # §9 compaction coordination point.
    completed_node_ids = {n.node_id for n in nodes if n.status == StateNodeStatus.completed}
    stale_ids = sorted(
        m.memory_id
        for m in memories
        if m.source_state_node_id in completed_node_ids
        and (m.freshness_score <= stale_freshness or m.status in _DECAYED_MEMORY_STATUSES)
    )
    maintain: list[MageOperation] = []
    if stale_ids:
        maintain.append(
            MageOperation(
                "maintain",
                tuple(stale_ids),
                "stale memories on completed subgoals -> decay/archive (§3.2 × §9)",
            )
        )

    return MagePlan(
        grow=tuple(grow),
        compress=tuple(compress),
        maintain=tuple(maintain),
        revise=tuple(revise),
    )


__all__ = ["MageOperation", "MagePlan", "plan_mage"]
