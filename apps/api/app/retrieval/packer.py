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
    StateNodeStatus,
    StateNodeType,
)
from app.retrieval.similarity import tokenize


def estimate_tokens(text: str | None) -> int:
    """Cheap deterministic token estimate (whitespace + CJK aware)."""
    return max(1, len(tokenize(text))) if text else 0


_TYPE_ORDER = {
    "active_state": 0,
    "active_path": 1,
    "tool_evidence": 2,
    "project_memory": 3,
    "profile": 4,
    "procedural": 5,
    "episodic": 6,
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


def build_active_path_block(active_path: list[StateNode]) -> Optional[ContextBlock]:
    """Summarize the active path (root -> current) as a single context block.

    Only completed steps on the path contribute progress text; the current
    active leaf is described separately by the active_state block. Failed /
    rolled_back nodes are never on the active path by construction.
    """
    if not active_path:
        return None
    steps = [
        n for n in active_path
        if n.node_type != StateNodeType.root and n.status == StateNodeStatus.completed
    ]
    if not steps:
        return None
    parts = []
    for n in steps:
        label = n.summary or n.goal or (n.step_id or n.node_id)
        parts.append(label)
    content = "Progress so far: " + " -> ".join(parts) + "."
    leaf = active_path[-1]
    return ContextBlock(
        type="active_path",
        content=content,
        source="state_tree",
        provenance=Provenance(run_id=leaf.run_id, state_node_id=leaf.node_id, step_id=leaf.step_id),
        tokens=estimate_tokens(content),
    )


def pack_context(
    *,
    active_node: Optional[StateNode],
    accepted: list[MemoryItem],
    token_budget: int,
    active_path: Optional[list[StateNode]] = None,
) -> tuple[list[ContextBlock], int]:
    """Build ordered, budget-bounded context blocks.

    Returns (blocks, actual_tokens). Project memories are merged; other accepted
    memories are emitted as their own typed blocks. When `active_path` is given,
    an `active_path` progress block is inserted after the active_state block.
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

    # Active path progress block (P1 active-path context builder).
    if active_path:
        path_block = build_active_path_block(active_path)
        if path_block is not None:
            blocks.append(path_block)

    # Merged project constraints (runtime + excluded keys only).
    proj_block = build_project_constraint_block(accepted)
    _RUNTIME_KEYS = {"project.runtime", "project.runtime.excluded"}
    merged_ids = {
        m.memory_id
        for m in accepted
        if m.memory_type == MemoryType.project and m.key in _RUNTIME_KEYS
    }

    type_map = {
        MemoryType.tool_evidence: "tool_evidence",
        MemoryType.working_state: "active_state",
        MemoryType.profile: "profile",
        MemoryType.procedural: "procedural",
        MemoryType.episodic: "episodic",
    }
    for mem in accepted:
        if mem.memory_id in merged_ids:
            continue
        # Project memories with dynamic keys (e.g. project.database,
        # project.cache_layer from LLM extraction) are not merged into the
        # runtime constraint block, but must still be packed individually.
        btype = "project_memory" if mem.memory_type == MemoryType.project else type_map.get(mem.memory_type, "episodic")
        content = mem.summary or mem.content if mem.memory_type == MemoryType.project else mem.content
        blocks.append(
            ContextBlock(
                type=btype,
                content=content,
                source=mem.memory_type.value,
                memory_id=mem.memory_id,
                reason=f"accepted {mem.memory_type.value}",
                provenance=_provenance(mem),
                tokens=estimate_tokens(content),
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


__all__ = ["pack_context", "build_project_constraint_block", "build_active_path_block", "estimate_tokens"]
