"""Rule-based benchmark evaluator (mvp.md section 10.3).

Computes retrieval-level and task-level metrics from a MemoryContext plus its
AccessInspection, with no LLM. The "final action" is decided deterministically
from the packed context (same rule as the demo): a surviving failed-branch npm
memory leads a naive agent to retry npm; otherwise the Bun constraint wins.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from app.runtime.models import (
    AccessInspection,
    BranchStatus,
    GateDecisionType,
    MemoryContext,
    RetrievalStrategy,
)


def decide_action(ctx: MemoryContext) -> str:
    """Pick the test/deploy command implied by the packed context."""
    if contaminated(ctx):
        return "npm test"
    text = " ".join(b.content.lower() for b in ctx.context_blocks)
    if "bun" in text:
        return "bun test"
    return "unknown"


def contaminated(ctx: MemoryContext) -> bool:
    """failed_branch_contamination: a failed/rolled-back memory reached context."""
    return any(
        "npm" in b.content.lower() and "failed" in b.content.lower()
        for b in ctx.context_blocks
    )


@dataclass
class CaseMetrics:
    case_id: str
    strategy: str
    candidate_count: int = 0
    accepted_count: int = 0
    rejected_count: int = 0
    actual_tokens: int = 0
    retrieval_latency_ms: int = 0
    gate_latency_ms: int = 0
    total_latency_ms: int = 0
    final_action: str = "unknown"
    task_success: int = 0
    failed_branch_contamination: int = 0
    correct_active_path_hit: int = 0
    cross_workspace_leakage: int = 0
    stale_memory_injection: int = 0
    stale_memory_injection_present: int = 0
    tool_sensitive_blocked: int = 0
    tool_sensitive_present: int = 0
    procedural_reuse_hit: int = 0
    procedural_reuse_present: int = 0
    superseded_injection: int = 0
    superseded_injection_present: int = 0
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


def _phase_latency(profile_events, access_id: str, phase: str) -> int:
    return sum(p.latency_ms for p in profile_events if p.access_id == access_id and p.phase.value == phase)


def evaluate_case(
    *,
    case_id: str,
    strategy: RetrievalStrategy,
    ctx: MemoryContext,
    access: Optional[AccessInspection],
    profile_events,
    other_workspace_markers: Optional[list[str]] = None,
    procedural_reuse_case: bool = False,
    correction_case: bool = False,
    stale_markers: Optional[list[str]] = None,
) -> CaseMetrics:
    """Build metrics for one (case, strategy) run.

    `other_workspace_markers` are substrings that, if present in any accepted
    context block, indicate cross-workspace leakage (e.g. the rival runtime
    name seeded in another workspace). `procedural_reuse_case` marks the
    completed-run reuse case so the procedural recall metric is scored.
    `correction_case` marks the explicit-correction case so the
    superseded-memory injection metric is scored. `stale_markers` are substrings
    of an expired memory that, if present in context, indicate stale injection.
    """
    m = CaseMetrics(case_id=case_id, strategy=strategy.value)
    prof = ctx.profile or {}
    m.candidate_count = int(prof.get("candidate_count", 0))
    m.accepted_count = int(prof.get("accepted_count", 0))
    m.rejected_count = int(prof.get("rejected_count", 0))
    m.actual_tokens = int(prof.get("actual_tokens", 0))
    m.total_latency_ms = int(prof.get("latency_ms", 0))
    m.warnings = list(ctx.warnings)

    if access is not None:
        m.retrieval_latency_ms = _phase_latency(profile_events, access.access_id, "retrieval")
        m.gate_latency_ms = _phase_latency(profile_events, access.access_id, "gate")

    # task-level
    m.final_action = decide_action(ctx)
    m.task_success = 1 if m.final_action == "bun test" else 0

    # failed-branch contamination
    m.failed_branch_contamination = 1 if contaminated(ctx) else 0

    # correct active path hit: a project/active block present and not contaminated
    has_project = any(b.type == "project_memory" for b in ctx.context_blocks)
    m.correct_active_path_hit = 1 if (has_project and not contaminated(ctx)) else 0

    # cross-workspace leakage
    if other_workspace_markers:
        joined = " ".join(b.content.lower() for b in ctx.context_blocks)
        m.cross_workspace_leakage = 1 if any(mk.lower() in joined for mk in other_workspace_markers) else 0

    # stale injection: an expired memory (identified by its markers) that still
    # reached context. Only scored for the stale case; other cases seed no stale
    # memory, so the metric stays 0 there.
    if stale_markers:
        joined = " ".join(b.content.lower() for b in ctx.context_blocks)
        m.stale_memory_injection_present = 1
        m.stale_memory_injection = 1 if any(mk.lower() in joined for mk in stale_markers) else 0
    else:
        m.stale_memory_injection = 0

    # tool-sensitive handling (from gate decisions)
    if access is not None:
        # tool-sensitive memory identified by its gate reject reason
        ts = [g for g in access.gate_decisions if g.reject_reason in ("tool_sensitive", "destructive_command")]
        present_in_ctx = any("--force" in b.content.lower() or "production" in b.content.lower()
                             for b in ctx.context_blocks)
        # present if either rejected for tool-sensitivity or leaked into context
        m.tool_sensitive_present = 1 if (ts or present_in_ctx) else 0
        if m.tool_sensitive_present:
            m.tool_sensitive_blocked = 1 if (ts and not present_in_ctx) else 0

    # procedural reuse: a procedural success memory was recalled into context
    if procedural_reuse_case:
        m.procedural_reuse_present = 1
        m.procedural_reuse_hit = 1 if any(b.type == "procedural" for b in ctx.context_blocks) else 0

    # superseded injection: the corrected-away Node preference must never appear.
    # project_memory blocks render the normalized runtime value, so a leaked
    # superseded "nodejs" preference surfaces as "This project uses Nodejs.".
    if correction_case:
        m.superseded_injection_present = 1
        proj_text = " ".join(
            b.content.lower() for b in ctx.context_blocks if b.type == "project_memory"
        )
        m.superseded_injection = 1 if "nodejs" in proj_text else 0

    return m


__all__ = ["CaseMetrics", "evaluate_case", "decide_action", "contaminated"]
