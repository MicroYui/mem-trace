"""Context packer: turn accepted memories + active state into structured blocks.

Packing order (mvp.md section 8):
  active_state -> tool_evidence -> project constraints -> user profile
  -> procedural hints -> episodic -> warnings

Positive (`project.runtime`) and negative (`project.runtime.excluded`) project
constraints are merged into one stable sentence so prompts stay consistent.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Mapping, Optional

from app.memory.secrets import redact
from app.retrieval.negative_evidence import to_retained_negative_evidence
from app.runtime.models import (
    ContextBlock,
    CompactionKind,
    CompactionProvider,
    MemoryItem,
    MemoryType,
    NegativeEvidence,
    PendingCompactionLog,
    Provenance,
    RetainedFact,
    RetainedNegativeEvidence,
    StateNode,
    StateNodeStatus,
    StateNodeType,
)


_TOKEN_PATTERN = re.compile(
    r"\[REDACTED\]|[A-Za-z0-9_]+(?:[.-][A-Za-z0-9_]+)*(?:=(?:\[REDACTED\]|[A-Za-z0-9_./:-]+))?|[^\sA-Za-z0-9_]",
    re.UNICODE,
)


def estimate_tokens(text: str | None) -> int:
    """Cheap deterministic budget estimate that preserves stopwords and CJK units."""
    if not text:
        return 0
    return max(1, len(_TOKEN_PATTERN.findall(text)))


_TYPE_ORDER = {
    "active_state": 0,
    "active_path": 1,
    "history_summary": 2,
    "project_memory": 3,
    "avoided_attempts": 4,
    "tool_evidence": 5,
    "profile": 6,
    "procedural": 7,
    "episodic": 8,
}

_PROTECTED_ORDER = {
    "active_state": 0,
    "history_summary": 1,
    "active_path": 2,
    "project_constraints": 3,
    "compacted_constraints": 4,
    "compaction_notice": 5,
}

_RETAINED_FACT_PREFIXES = ("project.", "endpoint.", "profile.", "procedure.")


@dataclass(frozen=True, slots=True)
class PackResult:
    """Structured result from context packing.

    C0 keeps existing packing behavior unchanged while exposing the extra fields
    needed by later context-compaction issues. ``dropped_blocks``, ``notice`` and
    ``retained_constraints`` remain empty/None until C1 introduces compaction
    compensation.
    """

    blocks: list[ContextBlock]
    used: int
    pre_compaction_tokens: int
    dropped_blocks: list[ContextBlock] = field(default_factory=list)
    notice: ContextBlock | None = None
    retained_constraints: list[RetainedFact] = field(default_factory=list)
    pending_compaction_logs: list[PendingCompactionLog] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _block_order(block: ContextBlock) -> int:
    return _TYPE_ORDER.get(block.type, 99)


def _protected_order(block: ContextBlock) -> int:
    if block.source == "project_constraints":
        return _PROTECTED_ORDER["project_constraints"]
    return _PROTECTED_ORDER.get(block.type, 99)


def _provenance(mem: MemoryItem) -> Provenance:
    return Provenance(
        run_id=mem.source_run_id or mem.run_id,
        step_id=None,
        event_id=mem.source_event_id,
        state_node_id=mem.source_state_node_id,
    )


def _copy_block(block: ContextBlock, *, content: str, reason_suffix: str) -> ContextBlock:
    reason = block.reason or ""
    reason = f"{reason}; {reason_suffix}" if reason else reason_suffix
    return block.model_copy(update={"content": content, "tokens": estimate_tokens(content), "reason": reason})


def _safe_content(text: str | None) -> str:
    """Apply final defense-in-depth redaction before prompt context packing."""
    return redact(text or "")


def _safe_block(block: ContextBlock) -> ContextBlock:
    safe = _safe_content(block.content)
    tokens = estimate_tokens(safe)
    if safe == block.content and tokens == block.tokens:
        return block
    return block.model_copy(update={"content": safe, "tokens": tokens})


def _truncate_text(text: str, max_tokens: int, *, suffix: str = " … (truncated)") -> str:
    """Deterministically truncate text to fit the approximate token budget."""
    if max_tokens <= 0:
        return ""
    if estimate_tokens(text) <= max_tokens:
        return text
    has_whitespace = bool(re.search(r"\s", text))
    units = text.split() if has_whitespace else list(text)
    suffix_tokens = estimate_tokens(suffix)
    if max_tokens <= suffix_tokens + 1:
        suffix = ""
        suffix_tokens = 0
    keep = max(1, min(len(units), max_tokens - suffix_tokens))
    while keep > 0:
        head = " ".join(units[:keep]) if has_whitespace else "".join(units[:keep])
        candidate = head + suffix
        if estimate_tokens(candidate) <= max_tokens:
            return candidate
        keep -= 1
    while suffix and estimate_tokens(suffix) > max_tokens:
        suffix = suffix[:-1]
    return suffix


def fit_block(block: ContextBlock, max_tokens: int) -> ContextBlock:
    """Fit a protected block into its slice by truncating, never dropping."""
    if block.tokens <= max_tokens:
        return block
    content = _truncate_text(block.content, max_tokens)
    return _copy_block(block, content=content, reason_suffix="protected block truncated to fit budget")


def _reserve_for_compaction(token_budget: int, reserve_tokens: int = 64) -> int:
    if token_budget <= 0:
        return 0
    configured = max(0, reserve_tokens)
    if token_budget < 32:
        return min(configured, max(1, token_budget - 2))
    return min(configured, max(16, token_budget // 8))


def _is_protected(block: ContextBlock) -> bool:
    return block.type in {"active_state", "active_path", "history_summary", "compacted_constraints", "compaction_notice"} or block.source == "project_constraints"


def _ordered_blocks(blocks: list[ContextBlock]) -> list[ContextBlock]:
    protected = sorted([block for block in blocks if _is_protected(block)], key=_protected_order)
    ordinary = sorted([block for block in blocks if not _is_protected(block)], key=_block_order)
    return [*protected, *ordinary]


def extract_retained_facts(
    dropped_blocks: list[ContextBlock],
    memory_by_id: Mapping[str, MemoryItem],
) -> list[RetainedFact]:
    """Extract retained facts from dropped blocks using MemoryItem key/value.

    The rendered block text is intentionally ignored so C1 preserves structured
    key=value facts without parsing prompt strings.
    """
    facts: list[RetainedFact] = []
    for block in dropped_blocks:
        if not block.memory_id:
            continue
        mem = memory_by_id.get(block.memory_id)
        if mem is None or not mem.key or mem.value is None:
            continue
        if not mem.key.startswith(_RETAINED_FACT_PREFIXES):
            continue
        facts.append(
            RetainedFact(
                key=_safe_content(mem.key),
                value=_safe_content(str(mem.value)),
                source_memory_id=mem.memory_id,
                provenance=_provenance(mem),
            )
        )
    facts.sort(key=lambda f: (f.key, f.value, f.source_memory_id or ""))
    return facts


def extract_retained_negative_evidence(
    dropped_blocks: list[ContextBlock],
    negative_by_memory_id: Mapping[str, NegativeEvidence],
    negative_by_state_reason: Mapping[tuple[str, str], NegativeEvidence],
) -> list[RetainedNegativeEvidence]:
    """Extract safe retained negative lessons from dropped avoided-attempt blocks.

    The rendered prompt text is intentionally ignored. Retention is rebuilt only
    from the safe ``NegativeEvidence`` DTOs supplied to the packer.
    """
    retained: list[RetainedNegativeEvidence] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for block in dropped_blocks:
        if block.type != "avoided_attempts" or block.source != "negative_evidence":
            continue
        evidence: NegativeEvidence | None = None
        if block.memory_id:
            evidence = negative_by_memory_id.get(block.memory_id)
        if evidence is None and block.provenance is not None and block.provenance.state_node_id:
            evidence = negative_by_state_reason.get((block.provenance.state_node_id, block.reason or ""))
        if evidence is None:
            continue
        if evidence.provenance is None and block.provenance is not None:
            evidence = evidence.model_copy(update={"provenance": block.provenance})
        item = to_retained_negative_evidence(evidence)
        identity = (
            item.source_memory_id or "",
            item.source_state_node_id or "",
            item.mode,
            item.reason,
            item.safe_text,
        )
        if identity in seen:
            continue
        seen.add(identity)
        retained.append(item)
    retained.sort(
        key=lambda item: (
            item.source_state_node_id or "",
            item.source_memory_id or "",
            item.mode,
            item.reason,
            item.safe_text,
        )
    )
    return retained


def build_compacted_constraints_block(facts: list[RetainedFact], *, max_tokens: int | None = None) -> ContextBlock | None:
    if not facts:
        return None
    content = "Compacted: " + "; ".join(
        f"{_safe_content(f.key)}={_safe_content(f.value)}" for f in facts
    ) + "."
    content = _safe_content(content)
    if max_tokens is not None:
        content = _truncate_text(content, max_tokens)
    return ContextBlock(
        type="compacted_constraints",
        content=content,
        source="context_compaction",
        reason="retained key=value constraints from dropped blocks",
        tokens=estimate_tokens(content),
    )


def build_compaction_notice(dropped: list[ContextBlock], *, kind: str = "budget_notice", max_tokens: int | None = None) -> ContextBlock:
    content = f"dropped {len(dropped)} blocks; kind={kind}."
    if max_tokens is not None:
        content = _truncate_text(content, max_tokens)
    return ContextBlock(
        type="compaction_notice",
        content=content,
        source="context_compaction",
        reason=f"kind={kind}",
        tokens=estimate_tokens(content),
    )


def build_negative_evidence_block(ev: NegativeEvidence) -> ContextBlock:
    if ev.mode == "raw_failed_attempt":
        content = (
            "AVOIDED — a previous attempt failed; do NOT re-execute:\n"
            f"{ev.safe_text}\n"
            "(Shown as negative evidence only — do not run this.)"
        )
    else:
        content = ev.safe_text
    provenance = ev.provenance
    if provenance is None and ev.source_state_node_id:
        provenance = Provenance(state_node_id=ev.source_state_node_id)
    return ContextBlock(
        type="avoided_attempts",
        content=content,
        source="negative_evidence",
        memory_id=ev.source_memory_id,
        reason=ev.reason,
        provenance=provenance,
        tokens=estimate_tokens(content),
    )


def _unique_nonempty(values) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


def _build_pending_budget_notice_log(
    *,
    dropped: list[ContextBlock],
    reserved_blocks: list[ContextBlock],
    retained_facts: list[RetainedFact],
    retained_negative_evidence: list[RetainedNegativeEvidence],
    memory_by_id: Mapping[str, MemoryItem],
) -> PendingCompactionLog:
    pre_tokens = sum(block.tokens for block in dropped)
    post_tokens = sum(block.tokens for block in reserved_blocks)
    dropped_memories = [memory_by_id[block.memory_id] for block in dropped if block.memory_id in memory_by_id]
    return PendingCompactionLog(
        kind=CompactionKind.budget_notice,
        provider=CompactionProvider.rule,
        pre_tokens=pre_tokens,
        post_tokens=post_tokens,
        dropped_block_count=len(dropped),
        compression_ratio=round(post_tokens / max(1, pre_tokens), 6),
        summary_text="\n".join(block.content for block in reserved_blocks) if reserved_blocks else None,
        retained_facts=list(retained_facts),
        retained_negative_evidence=list(retained_negative_evidence),
        source_memory_ids=_unique_nonempty(block.memory_id for block in dropped),
        source_event_ids=_unique_nonempty(
            [
                *(block.provenance.event_id for block in dropped if block.provenance is not None),
                *(memory.source_event_id for memory in dropped_memories),
                *(event_id for memory in dropped_memories for event_id in (memory.source_event_ids or [])),
            ]
        ),
        source_state_node_ids=_unique_nonempty(
            [
                *(block.provenance.state_node_id for block in dropped if block.provenance is not None),
                *(memory.source_state_node_id for memory in dropped_memories),
            ]
        ),
        warnings=[],
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
    content = _safe_content(content)
    return ContextBlock(
        type="project_memory",
        content=content,
        source="project_constraints",
        memory_id=src.memory_id if src else None,
        reason="merged project runtime constraints",
        provenance=_provenance(src) if src else None,
        tokens=estimate_tokens(content),
    )


def build_active_path_block(
    active_path: list[StateNode],
    *,
    summarize_after: int = 0,
    keep_recent: int = 3,
) -> Optional[ContextBlock]:
    """Summarize the active path (root -> current) as a single context block.

    Only completed steps on the path contribute progress text; the current
    active leaf is described separately by the active_state block. Failed /
    rolled_back nodes are never on the active path by construction.

    ROADMAP §5 (default-off): when ``summarize_after > 0`` and the number of
    completed steps exceeds it, the oldest completed subgoals are folded into a
    single deterministic summary segment (``[N earlier completed steps
    summarized]``) and only the most recent ``keep_recent`` are shown verbatim,
    keeping this protected block bounded on long-horizon runs. With the default
    ``summarize_after == 0`` every completed step is listed (unchanged behavior).
    """
    if not active_path:
        return None
    steps = [
        n for n in active_path
        if n.node_type != StateNodeType.root and n.status == StateNodeStatus.completed
    ]
    if not steps:
        return None
    labels = [_safe_content(n.summary or n.goal or (n.step_id or n.node_id)) for n in steps]
    keep = max(0, keep_recent)
    if summarize_after > 0 and len(steps) > summarize_after and len(steps) - keep > 0:
        folded = len(steps) - keep
        parts = [f"[{folded} earlier completed steps summarized]", *labels[folded:]]
    else:
        parts = labels
    content = _safe_content("Progress so far: " + " -> ".join(parts) + ".")
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
    prelude_blocks: Optional[list[ContextBlock]] = None,
    negative_evidence: Optional[list[NegativeEvidence]] = None,
    compaction_notice_reserve_tokens: int = 64,
    active_path_summarize_after: int = 0,
    active_path_keep_recent: int = 3,
) -> PackResult:
    """Build ordered, budget-bounded context blocks.

    Returns a :class:`PackResult`. Project memories are merged; other accepted
    memories are emitted as their own typed blocks. When `active_path` is given,
    an `active_path` progress block is inserted after the active_state block.
    """
    blocks: list[ContextBlock] = []

    # Active state block (from state tree, not a memory item).
    if active_node is not None:
        content = _safe_content(active_node.goal or active_node.summary or f"Current {active_node.node_type.value} step.")
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
        path_block = build_active_path_block(
            active_path,
            summarize_after=active_path_summarize_after,
            keep_recent=active_path_keep_recent,
        )
        if path_block is not None:
            blocks.append(path_block)

    if prelude_blocks:
        blocks.extend(_safe_block(block) for block in prelude_blocks)

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
        content = _safe_content((mem.summary or mem.content) if mem.memory_type == MemoryType.project else mem.content)
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

    if negative_evidence:
        blocks.extend(_safe_block(build_negative_evidence_block(ev)) for ev in negative_evidence)

    if any(block.type == "history_summary" for block in blocks):
        blocks = _ordered_blocks(blocks)
    else:
        blocks.sort(key=_block_order)
    pre_compaction_tokens = sum(b.tokens for b in blocks)
    memory_by_id = {m.memory_id: m for m in accepted}
    negative_by_memory_id = {ev.source_memory_id: ev for ev in (negative_evidence or []) if ev.source_memory_id}
    negative_by_state_reason = {
        (ev.source_state_node_id, ev.reason): ev
        for ev in (negative_evidence or [])
        if ev.source_state_node_id
    }

    if pre_compaction_tokens <= token_budget:
        return PackResult(blocks=blocks, used=pre_compaction_tokens, pre_compaction_tokens=pre_compaction_tokens)

    reserve = _reserve_for_compaction(token_budget, compaction_notice_reserve_tokens)

    warnings: list[str] = []
    protected_blocks = sorted([b for b in blocks if _is_protected(b)], key=_protected_order)
    ordinary_blocks = [b for b in blocks if not _is_protected(b)]
    protected_floor = min(token_budget, sum(b.tokens for b in protected_blocks))
    effective_budget = max(0, token_budget - reserve, protected_floor)

    packed: list[ContextBlock] = []
    used = 0
    for block in protected_blocks:
        remaining = max(0, effective_budget - used)
        fitted = fit_block(block, remaining) if block.tokens > remaining else block
        if fitted.tokens < block.tokens:
            warnings.append(f"protected block {block.type} truncated to fit budget")
        packed.append(fitted)
        used += fitted.tokens

    dropped: list[ContextBlock] = []
    for block in ordinary_blocks:
        if used + block.tokens <= effective_budget:
            packed.append(block)
            used += block.tokens
        else:
            dropped.append(block)

    notice: ContextBlock | None = None
    retained_facts: list[RetainedFact] = []
    retained_negative_evidence: list[RetainedNegativeEvidence] = []
    pending_logs: list[PendingCompactionLog] = []
    if dropped and reserve > 0:
        retained_facts = extract_retained_facts(dropped, memory_by_id)
        retained_negative_evidence = extract_retained_negative_evidence(
            dropped,
            negative_by_memory_id,
            negative_by_state_reason,
        )
        notice_budget = min(6, reserve)
        constraints_budget = max(0, reserve - notice_budget)
        constraints_block = build_compacted_constraints_block(retained_facts, max_tokens=constraints_budget) if constraints_budget else None
        notice = build_compaction_notice(dropped, max_tokens=notice_budget)
        reserved_blocks = [b for b in (constraints_block, notice) if b is not None and b.tokens > 0]
        reserved_tokens = sum(b.tokens for b in reserved_blocks)
        while reserved_blocks and used + reserved_tokens > token_budget and packed:
            overflow = used + reserved_tokens - token_budget
            shrink_index = next((i for i in range(len(packed) - 1, -1, -1) if packed[i].tokens > 0), None)
            if shrink_index is None:
                break
            candidate = packed[shrink_index]
            if not _is_protected(candidate):
                used -= candidate.tokens
                dropped.append(packed.pop(shrink_index))
                retained_facts = extract_retained_facts(dropped, memory_by_id)
                retained_negative_evidence = extract_retained_negative_evidence(
                    dropped,
                    negative_by_memory_id,
                    negative_by_state_reason,
                )
                constraints_block = build_compacted_constraints_block(retained_facts, max_tokens=constraints_budget) if constraints_budget else None
                reserved_blocks = [b for b in (constraints_block, notice) if b is not None and b.tokens > 0]
                reserved_tokens = sum(b.tokens for b in reserved_blocks)
                continue
            new_budget = max(0, candidate.tokens - overflow)
            fitted_candidate = fit_block(candidate, new_budget)
            if fitted_candidate.tokens < candidate.tokens:
                warnings.append(f"protected block {candidate.type} truncated to fit budget")
            used += fitted_candidate.tokens - candidate.tokens
            packed[shrink_index] = fitted_candidate
            reserved_tokens = sum(b.tokens for b in reserved_blocks)
        for block in reserved_blocks:
            if used + block.tokens <= token_budget:
                packed.append(block)
                used += block.tokens
            else:
                remaining = token_budget - used
                if remaining <= 0:
                    continue
                fitted = fit_block(block, remaining)
                if fitted.tokens < block.tokens:
                    warnings.append(f"protected block {block.type} truncated to fit budget")
                if fitted.tokens > 0:
                    packed.append(fitted)
                    used += fitted.tokens
                if block.type == "compaction_notice":
                    notice = fitted
        final_reserved_blocks = [block for block in packed if block.type in {"compacted_constraints", "compaction_notice"}]
        if final_reserved_blocks:
            pending_logs.append(
                _build_pending_budget_notice_log(
                    dropped=dropped,
                    reserved_blocks=final_reserved_blocks,
                    retained_facts=retained_facts,
                    retained_negative_evidence=retained_negative_evidence,
                    memory_by_id=memory_by_id,
                )
            )

    packed.sort(key=_protected_order)
    return PackResult(
        blocks=packed,
        used=used,
        pre_compaction_tokens=pre_compaction_tokens,
        dropped_blocks=dropped,
        notice=notice,
        retained_constraints=retained_facts,
        pending_compaction_logs=pending_logs,
        warnings=warnings,
    )


__all__ = [
    "PackResult",
    "pack_context",
    "build_project_constraint_block",
    "build_active_path_block",
    "build_compacted_constraints_block",
    "build_compaction_notice",
    "build_negative_evidence_block",
    "extract_retained_facts",
    "extract_retained_negative_evidence",
    "fit_block",
    "estimate_tokens",
]
