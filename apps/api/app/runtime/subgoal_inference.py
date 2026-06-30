"""Deterministic subgoal auto-inference over the execution state tree (ROADMAP §5).

The default state tree emits only ``root``/``step``/``recovery`` nodes. A long
run, though, pursues a sequence of higher-level *subgoals*, each spanning several
steps. This module infers those subgoals deterministically from the steps' goals
without changing the stored tree: consecutive step/recovery nodes that share a
normalized goal are grouped into one inferred ``subgoal``.

It is a pure, side-effect-free read-side analysis. Nothing here mutates the
state tree or the stored ``node_type``; it is exposed for opt-in consumers
(the runtime read method, context compaction, MAGE operations). Default-off via
``MEMTRACE_STATE_TREE_SUBGOAL_INFERENCE_ENABLED`` at the call site.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.runtime.models import StateNode, StateNodeType


@dataclass(frozen=True, slots=True)
class InferredSubgoal:
    """A deterministic grouping of consecutive same-goal step nodes."""

    key: str
    goal: str | None
    node_ids: tuple[str, ...]
    node_type: str = StateNodeType.subgoal.value


_GROUPABLE = {StateNodeType.step, StateNodeType.recovery}


def _ordered_steps(nodes: list[StateNode]) -> list[StateNode]:
    steps = [n for n in nodes if n.node_type in _GROUPABLE]
    steps.sort(key=lambda n: (n.path or "", n.created_at, n.node_id))
    return steps


def infer_subgoals(nodes: list[StateNode]) -> list[InferredSubgoal]:
    """Group the run's step/recovery nodes into inferred subgoals by goal.

    Consecutive steps sharing a normalized (case-folded, trimmed) goal form one
    subgoal; a goal change starts a new one. Steps with no goal are grouped with
    adjacent goal-less steps. Deterministic order; keys are ``subgoal-1``, ….
    """
    steps = _ordered_steps(nodes)
    subgoals: list[InferredSubgoal] = []
    current_key: object = object()  # sentinel distinct from any real goal
    current_goal: str | None = None
    current_ids: list[str] = []
    index = 0

    def flush() -> None:
        nonlocal index
        if current_ids:
            index += 1
            subgoals.append(
                InferredSubgoal(
                    key=f"subgoal-{index}",
                    goal=current_goal,
                    node_ids=tuple(current_ids),
                )
            )

    for node in steps:
        normalized = (node.goal or "").strip().lower()
        if normalized != current_key:
            flush()
            current_key = normalized
            current_goal = node.goal
            current_ids = []
        current_ids.append(node.node_id)
    flush()
    return subgoals


__all__ = ["InferredSubgoal", "infer_subgoals"]
