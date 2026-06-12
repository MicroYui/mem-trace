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
    ContextCompactionLog,
    MemoryContext,
    RetrievalStrategy,
)


def decide_action(ctx: MemoryContext) -> str:
    """Pick the test/deploy command implied by the packed context."""
    positive_blocks = _positive_blocks(ctx)
    if contaminated(ctx):
        return "npm test"
    text = " ".join(b.content.lower() for b in positive_blocks)
    if "bun" in text:
        return "bun test"
    return "unknown"


def contaminated(ctx: MemoryContext) -> bool:
    """failed_branch_contamination: failed memory reached positive context."""
    return any(
        "npm" in b.content.lower() and "failed" in b.content.lower()
        for b in _positive_blocks(ctx)
    )


def _positive_blocks(ctx: MemoryContext):
    return [
        block for block in ctx.context_blocks
        if block.type != "avoided_attempts" and block.source != "negative_evidence"
    ]


def _negative_blocks(ctx: MemoryContext):
    return [
        block for block in ctx.context_blocks
        if block.type == "avoided_attempts" or block.source == "negative_evidence"
    ]


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
    cross_workspace_leakage_present: int = 0
    stale_memory_injection: int = 0
    stale_memory_injection_present: int = 0
    tool_sensitive_blocked: int = 0
    tool_sensitive_present: int = 0
    procedural_reuse_hit: int = 0
    procedural_reuse_present: int = 0
    superseded_injection: int = 0
    superseded_injection_present: int = 0
    compaction_triggered: int = 0
    compaction_triggered_present: int = 0
    constraint_retention_hit: int = 0
    constraint_retention_hit_present: int = 0
    unsafe_compaction_leakage: int = 0
    unsafe_compaction_leakage_present: int = 0
    compression_ratio: float = 0.0
    compression_ratio_present: int = 0
    positive_contamination: int = 0
    positive_contamination_present: int = 0
    negative_lesson_retained: int = 0
    negative_lesson_retained_present: int = 0
    correct_action: int = 0
    correct_action_present: int = 0
    unsafe_negative_leakage: int = 0
    unsafe_negative_leakage_present: int = 0
    sanitized_notice_present: int = 0
    sanitized_notice_present_present: int = 0
    reflection_retention_hit: int = 0
    reflection_retention_hit_present: int = 0
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


def _phase_latency(profile_events, access_id: str, phase: str) -> int:
    return sum(p.latency_ms for p in profile_events if p.access_id == access_id and p.phase.value == phase)


def _compaction_log_text(logs: list[ContextCompactionLog]) -> str:
    parts: list[str] = []
    for log in logs:
        if log.summary_text:
            parts.append(log.summary_text)
        parts.extend(f"{fact.key}={fact.value}" for fact in log.retained_facts)
        parts.extend(log.warnings)
    return " ".join(parts).lower()


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
    compaction_positive_constraints: Optional[list[str]] = None,
    unsafe_compaction_markers: Optional[list[str]] = None,
    compaction_logs: Optional[list[ContextCompactionLog]] = None,
    negative_lesson_markers: Optional[list[str]] = None,
    unsafe_negative_markers: Optional[list[str]] = None,
    failure_learning_case: bool = False,
    sanitized_failure_case: bool = False,
    reflection_marker: Optional[str] = None,
    reflection_case: bool = False,
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
    positive_blocks = _positive_blocks(ctx)
    negative_blocks = _negative_blocks(ctx)

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
        m.cross_workspace_leakage_present = 1
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

    # compaction quality: only scored for the over-budget compaction case.
    if compaction_positive_constraints is not None:
        logs = list(compaction_logs or [])
        m.compaction_triggered_present = 1
        m.constraint_retention_hit_present = 1
        m.unsafe_compaction_leakage_present = 1
        joined = " ".join(b.content.lower() for b in ctx.context_blocks)
        compaction_log_text = _compaction_log_text(logs)
        searchable_text = f"{joined} {compaction_log_text}"
        m.compaction_triggered = 1 if logs or any(
            b.type in {"compacted_constraints", "compaction_notice"} for b in ctx.context_blocks
        ) or any("context budget exceeded" in warning.lower() for warning in ctx.warnings) else 0
        def _constraint_present(constraint: str) -> bool:
            key, _, value = constraint.partition("=")
            if constraint.lower() in searchable_text:
                return True
            if key == "project.runtime" and value and value.lower() in searchable_text:
                return True
            return False

        m.constraint_retention_hit = 1 if all(_constraint_present(c) for c in compaction_positive_constraints) else 0
        markers = unsafe_compaction_markers or []
        m.unsafe_compaction_leakage = 1 if any(
            marker.lower() in joined or marker.lower() in compaction_log_text for marker in markers
        ) else 0
        pre_tokens = sum(log.pre_tokens for log in logs)
        post_tokens = sum(log.post_tokens for log in logs)
        if logs:
            m.compression_ratio_present = 1
            m.compression_ratio = round(post_tokens / max(1, pre_tokens), 6)

    # Failure-aware negative-memory learning: score positive and negative
    # channels separately so an avoided npm lesson is not counted as positive
    # contamination and does not make the deterministic action repeat npm.
    if failure_learning_case:
        markers = [marker.lower() for marker in (negative_lesson_markers or [])]
        negative_text = " ".join(block.content.lower() for block in negative_blocks)
        m.positive_contamination_present = 1
        m.negative_lesson_retained_present = 1
        m.correct_action_present = 1
        m.positive_contamination = 1 if contaminated(ctx) else 0
        m.negative_lesson_retained = 1 if markers and any(marker in negative_text for marker in markers) else 0
        m.correct_action = 1 if m.final_action == "bun test" else 0

    if sanitized_failure_case:
        markers = [marker.lower() for marker in (unsafe_negative_markers or [])]
        negative_text = " ".join(block.content.lower() for block in negative_blocks)
        m.unsafe_negative_leakage_present = 1
        m.sanitized_notice_present_present = 1
        m.unsafe_negative_leakage = 1 if any(marker in negative_text for marker in markers) else 0
        m.sanitized_notice_present = 1 if (
            "redacted" in negative_text
            and "destructive operation" in negative_text
        ) else 0

    # Reflection-lite retention: the high-retention marker reached context.
    if reflection_case:
        joined = " ".join(block.content.lower() for block in ctx.context_blocks)
        marker = (reflection_marker or "").lower()
        m.reflection_retention_hit_present = 1
        m.reflection_retention_hit = 1 if marker and marker in joined else 0

    return m


__all__ = ["CaseMetrics", "evaluate_case", "decide_action", "contaminated"]
