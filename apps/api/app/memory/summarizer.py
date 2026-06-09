"""Cold-path run summarizer (P2: completed-run reuse / procedural memory).

When a run finishes, the cold path compresses its trace into durable memory:

- a **completed-run summary** (`memory_type=episodic`) recording the task, final
  status, and the ordered active progress path; and
- a **reusable procedural memory** (`memory_type=procedural`) that distills the
  *successful* approach (active path + successful tool evidence + project
  constraint) so a later, similar run can recall "what worked last time".

This is deterministic and rule-based (no LLM), matching the P0/P1 writer design,
so demo/benchmark results stay reproducible. Functions here are pure: they take
already-loaded domain objects and return new ``MemoryItem`` objects without
touching any repository (the runtime facade persists them).

Failed / rolled-back branches never contribute to the procedural memory: only
nodes on the active path (see ``state_tree.active_path_chain``) and memories
with ``branch_status=completed`` are distilled, so a failed plan A is never
sedimented as a reusable procedure.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.runtime import state_tree
from app.runtime.models import (
    AgentRun,
    BranchStatus,
    MemoryItem,
    MemoryScope,
    MemoryStatus,
    MemoryType,
    RunStatus,
    StateNode,
    StateNodeStatus,
    StateNodeType,
)

# Stable keys so re-running the cold path on the same run upserts (idempotent)
# rather than producing duplicates.
SUMMARY_KEY_PREFIX = "run.summary"
PROCEDURAL_KEY_PREFIX = "procedure"


@dataclass
class RunSummary:
    """Result of summarizing a completed run."""

    episodic: MemoryItem
    procedural: Optional[MemoryItem] = None

    @property
    def created(self) -> list[MemoryItem]:
        items = [self.episodic]
        if self.procedural is not None:
            items.append(self.procedural)
        return items


def _completed_path_nodes(nodes: list[StateNode]) -> list[StateNode]:
    """Ordered completed step/recovery nodes on the active path (root excluded)."""
    chain = state_tree.active_path_chain(nodes)
    return [
        n
        for n in chain
        if n.node_type != StateNodeType.root and n.status == StateNodeStatus.completed
    ]


def _progress_labels(path_nodes: list[StateNode]) -> list[str]:
    labels: list[str] = []
    for n in path_nodes:
        label = n.summary or n.goal or n.step_id or n.node_id
        if label:
            labels.append(label.strip())
    return labels


def _active_node_ids(nodes: list[StateNode]) -> set[str]:
    return state_tree.active_path_node_ids(nodes)


def _successful_tool_evidence(
    memories: list[MemoryItem], active_ids: set[str]
) -> list[MemoryItem]:
    """Tool-evidence memories that succeeded and are on the active path.

    Risky / tool-sensitive evidence is excluded so a destructive command is
    never distilled into a reusable procedure.
    """
    out: list[MemoryItem] = []
    for m in memories:
        if m.memory_type != MemoryType.tool_evidence:
            continue
        if m.branch_status != BranchStatus.completed:
            continue
        if m.risk_flags.tool_sensitive or m.risk_flags.destructive_command:
            continue
        if m.source_state_node_id and m.source_state_node_id not in active_ids:
            continue
        out.append(m)
    return out


def _positive_project_constraint(memories: list[MemoryItem]) -> Optional[MemoryItem]:
    for m in memories:
        if (
            m.memory_type == MemoryType.project
            and m.key == "project.runtime"
            and m.status == MemoryStatus.active
            and m.value
        ):
            return m
    return None


def build_run_summary(
    *,
    run: AgentRun,
    nodes: list[StateNode],
    memories: list[MemoryItem],
    summary: Optional[str] = None,
) -> RunSummary:
    """Build the episodic summary (+ optional procedural memory) for a run.

    `memories` should already be lifecycle-filtered to the run's workspace; only
    active, completed-branch memories on the active path inform the procedural
    distillation. The procedural memory is omitted when the run did not complete
    successfully or has no discernible successful approach.
    """
    path_nodes = _completed_path_nodes(nodes)
    labels = _progress_labels(path_nodes)
    task = (run.task or "this task").strip()

    # ---- completed-run summary (episodic) ------------------------------- #
    status = run.status.value if isinstance(run.status, RunStatus) else str(run.status)
    run_succeeded = status == RunStatus.completed.value
    if labels:
        progress = " -> ".join(labels)
        episodic_content = f"Run for '{task}' finished ({status}). Progress: {progress}."
    else:
        episodic_content = f"Run for '{task}' finished ({status})."
    if summary:
        episodic_content = f"{episodic_content} {summary.strip()}"

    episodic = MemoryItem(
        workspace_id=run.workspace_id,
        session_id=run.session_id,
        run_id=run.run_id,
        memory_type=MemoryType.episodic,
        key=f"{SUMMARY_KEY_PREFIX}.{run.run_id}",
        scope=MemoryScope.workspace,
        content=episodic_content,
        summary=episodic_content[:120],
        source_run_id=run.run_id,
        source_state_node_id=path_nodes[-1].node_id if path_nodes else None,
        # Mirror the run outcome so a failed run's summary is never recalled as a
        # successful path (failed-branch isolation extends to run summaries).
        branch_status=BranchStatus.completed if run_succeeded else BranchStatus.failed,
        confidence=0.7,
        importance=0.5,
        value_score=0.5,
        trust_score=0.6,
    )

    procedural = _build_procedural(
        run=run, task=task, labels=labels, nodes=nodes, memories=memories
    )
    return RunSummary(episodic=episodic, procedural=procedural)


def _build_procedural(
    *,
    run: AgentRun,
    task: str,
    labels: list[str],
    nodes: list[StateNode],
    memories: list[MemoryItem],
) -> Optional[MemoryItem]:
    """Distill the successful approach into a reusable procedural memory.

    Only runs that completed successfully and have a concrete success signal
    (a successful tool evidence, a project constraint, or completed progress)
    yield a procedural memory.
    """
    status_ok = (run.status == RunStatus.completed) or (
        isinstance(run.status, str) and run.status == RunStatus.completed.value
    )
    if not status_ok:
        return None

    active_ids = _active_node_ids(nodes)
    tool_success = _successful_tool_evidence(memories, active_ids)
    project = _positive_project_constraint(memories)

    success_parts: list[str] = []
    if project and project.value:
        success_parts.append(f"use {project.value}")
    for m in tool_success:
        text = (m.summary or m.content or "").strip()
        if text:
            success_parts.append(text)

    if not success_parts and not labels:
        # Nothing actionable to sediment.
        return None

    if success_parts:
        approach = "; ".join(_dedupe_preserve_order(success_parts))
        content = f"For task '{task}', the approach that worked: {approach}."
    else:
        content = f"For task '{task}', the steps that worked: {' -> '.join(labels)}."

    leaf_id = None
    completed_nodes = _completed_path_nodes(nodes)
    if completed_nodes:
        leaf_id = completed_nodes[-1].node_id

    return MemoryItem(
        workspace_id=run.workspace_id,
        session_id=None,
        run_id=run.run_id,
        memory_type=MemoryType.procedural,
        key=f"{PROCEDURAL_KEY_PREFIX}.{run.run_id}",
        scope=MemoryScope.workspace,
        content=content,
        summary=content[:120],
        source_run_id=run.run_id,
        source_state_node_id=leaf_id,
        branch_status=BranchStatus.completed,
        # Procedural memory is a distilled, reusable success path: high trust /
        # value, slow freshness decay (handled by lifecycle scoring later).
        confidence=0.8,
        importance=0.75,
        value_score=0.8,
        freshness_score=1.0,
        trust_score=0.8,
    )


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        key = it.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


__all__ = ["RunSummary", "build_run_summary", "SUMMARY_KEY_PREFIX", "PROCEDURAL_KEY_PREFIX"]
