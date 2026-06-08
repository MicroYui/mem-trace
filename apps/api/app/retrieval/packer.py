"""Context packer: turn accepted memories + active state into structured blocks.

Packing order (mvp.md section 8):
  active_state -> tool_evidence -> project constraints -> user profile
  -> procedural hints -> episodic -> warnings

Positive (`project.runtime`) and negative (`project.runtime.excluded`) project
constraints are merged into one stable sentence so prompts stay consistent.
"""
from __future__ import annotations

from typing import Optional

from app.runtime.models import (
    ContextBlock,
    MemoryItem,
    MemoryType,
    Provenance,
    StateNode,
)
from app.retrieval.similarity import tokenize


def estimate_tokens(text: str | None) -> int:
    """Cheap deterministic token estimate (whitespace + CJK aware)."""
    return max(1, len(tokenize(text))) if text else 0


_TYPE_ORDER = {
    "active_state": 0,
    "tool_evidence": 1,
    "project_memory": 2,
    "profile": 3,
    "procedural": 4,
    "episodic": 5,
}


def _block_order(block: ContextBlock) -> int:
    return _TYPE_ORDER.get(block.type, 99)


def _provenance(mem: MemoryItem) -> Provenance:
    return Provenance(
        run_id=mem.source_run_id or mem.run_id,
        step_id=None,
        event_id=mem.source_event_id,
        state_node_id=mem.source_state_node_id,
    )


def build_project_constraint_block(memories: list[MemoryItem]) -> Optional[ContextBlock]:
    """Merge positive + negative runtime constraints into one stable block."""
    positive: Optional[str] = None
    excluded: list[str] = []
    src: Optional[MemoryItem] = None
    for m in memories:
        if m.memory_type != MemoryType.project:
            continue
        if m.key == "project.runtime" and m.value:
            positive = m.value
            src = m
        elif m.key == "project.runtime.excluded" and m.value:
            excluded.append(m.value)
            src = src or m
    if positive is None and not excluded:
        return None

    pos_name = positive.capitalize() if positive else None
    exc_names = ", ".join(sorted({e.capitalize() for e in excluded}))
    if pos_name and exc_names:
        content = f"This project uses {pos_name} and should not use {exc_names}."
    elif pos_name:
        content = f"This project uses {pos_name}."
    else:
        content = f"This project should not use {exc_names}."
    return ContextBlock(
        type="project_memory",
        content=content,
        source="project_constraints",
        memory_id=src.memory_id if src else None,
        reason="merged project runtime constraints",
        provenance=_provenance(src) if src else None,
        tokens=estimate_tokens(content),
    )


def pack_context(
    *,
    active_node: Optional[StateNode],
    accepted: list[MemoryItem],
    token_budget: int,
) -> tuple[list[ContextBlock], int]:
    """Build ordered, budget-bounded context blocks.

    Returns (blocks, actual_tokens). Project memories are merged; other accepted
    memories are emitted as their own typed blocks.
    """
    blocks: list[ContextBlock] = []

    # Active state block (from state tree, not a memory item).
    if active_node is not None:
        content = active_node.goal or active_node.summary or f"Current {active_node.node_type.value} step."
        blocks.append(
            ContextBlock(
                type="active_state",
                content=content,
                source="state_tree",
                provenance=Provenance(
                    run_id=active_node.run_id,
                    state_node_id=active_node.node_id,
                    step_id=active_node.step_id,
                ),
                tokens=estimate_tokens(content),
            )
        )

    # Merged project constraints.
    proj_block = build_project_constraint_block(accepted)
    proj_ids = {m.memory_id for m in accepted if m.memory_type == MemoryType.project}

    type_map = {
        MemoryType.tool_evidence: "tool_evidence",
        MemoryType.working_state: "active_state",
        MemoryType.profile: "profile",
        MemoryType.episodic: "episodic",
    }
    for mem in accepted:
        if mem.memory_id in proj_ids:
            continue
        btype = type_map.get(mem.memory_type, "episodic")
        blocks.append(
            ContextBlock(
                type=btype,
                content=mem.content,
                source=mem.memory_type.value,
                memory_id=mem.memory_id,
                reason=f"accepted {mem.memory_type.value}",
                provenance=_provenance(mem),
                tokens=estimate_tokens(mem.content),
            )
        )
    if proj_block is not None:
        blocks.append(proj_block)

    blocks.sort(key=_block_order)

    # Enforce token budget greedily in packing order.
    packed: list[ContextBlock] = []
    used = 0
    for b in blocks:
        if used + b.tokens > token_budget and packed:
            break
        packed.append(b)
        used += b.tokens
    return packed, used


__all__ = ["pack_context", "build_project_constraint_block", "estimate_tokens"]
