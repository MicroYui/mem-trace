"""Build warning-only negative evidence from gate outcomes.

The controller, access inspection, and replay paths must all use this module so
safe failed attempts, sanitized risky failures, redaction, ordering, and dedupe
semantics cannot drift across read paths.
"""
from __future__ import annotations

from typing import Literal

from app.memory.secrets import contains_secret, redact
from app.retrieval.gate import GateOutcome
from app.runtime.models import (
    BranchStatus,
    GateDecisionType,
    MemoryItem,
    MemoryType,
    NegativeEvidence,
    Provenance,
    RetainedNegativeEvidence,
    Sensitivity,
)

RiskKind = Literal["secret", "destructive", "tool_sensitive", "unknown"]

SANITIZED_TEMPLATES: dict[RiskKind, str] = {
    "secret": "A previous failed attempt involved sensitive credentials or secrets and has been redacted. Do not repeat or expose secret-bearing operations.",
    "destructive": "A previous failed attempt involved a destructive operation and has been redacted. Do not repeat destructive operations of this kind.",
    "tool_sensitive": "A previous failed attempt involved a sensitive tool operation and has been redacted. Do not repeat that sensitive operation pattern.",
    "unknown": "A previous failed attempt involved unsafe operations and has been redacted. Do not repeat that unsafe operation pattern.",
}

_SANITIZED_REASONS = {"failed_branch_sanitized", "rolled_back_sanitized"}
_TYPE_PRIORITY = {
    MemoryType.tool_evidence: 0,
    MemoryType.working_state: 1,
}


def is_failedish(mem: MemoryItem) -> bool:
    return mem.branch_status in (BranchStatus.failed, BranchStatus.rolled_back)


def risk_kind(mem: MemoryItem) -> RiskKind:
    flags = mem.risk_flags
    if mem.sensitivity == Sensitivity.secret or flags.contains_secret:
        return "secret"
    if flags.destructive_command:
        return "destructive"
    if flags.tool_sensitive or flags.production_env:
        return "tool_sensitive"
    return "unknown"


def is_unsafe_failed(mem: MemoryItem) -> bool:
    flags = mem.risk_flags
    return (
        mem.sensitivity == Sensitivity.secret
        or flags.contains_secret
        or flags.destructive_command
        or flags.tool_sensitive
        or flags.production_env
    )


def safe_observability_content(mem: MemoryItem | None, *, reject_reason: str | None = None) -> str:
    """Render memory content for inspect/replay views without unsafe raw leakage.

    Context packing only consumes ``NegativeEvidence.safe_text``. Inspect and
    replay also expose candidate/gate views, so they must not display raw text
    for sanitized failed attempts or failed memories that are unsafe by flags.
    """
    if mem is None:
        return ""
    if _requires_observability_template(mem, reject_reason=reject_reason):
        return SANITIZED_TEMPLATES[risk_kind(mem)]
    redacted = redact(mem.content)
    if contains_secret(mem.content) or redacted != mem.content:
        return SANITIZED_TEMPLATES["secret"]
    return redacted


def safe_observability_key_value(mem: MemoryItem | None, *, reject_reason: str | None = None) -> tuple[str | None, str | None]:
    """Render candidate key/value metadata for replay without raw unsafe leakage."""
    if mem is None:
        return None, None
    if _requires_observability_template(mem, reject_reason=reject_reason):
        return None, None
    key = redact(mem.key) if mem.key is not None else None
    value = redact(mem.value) if mem.value is not None else None
    if (
        (mem.key is not None and (contains_secret(mem.key) or key != mem.key))
        or (mem.value is not None and (contains_secret(mem.value) or value != mem.value))
        or contains_secret(mem.content)
        or redact(mem.content) != mem.content
    ):
        return None, None
    return key, value


def _requires_observability_template(mem: MemoryItem, *, reject_reason: str | None = None) -> bool:
    return (
        reject_reason == "secret"
        or mem.sensitivity == Sensitivity.secret
        or mem.risk_flags.contains_secret
        or reject_reason in _SANITIZED_REASONS
        or (is_failedish(mem) and is_unsafe_failed(mem))
    )


def build_negative_evidence(
    outcomes: list[GateOutcome],
    memories_by_id: dict[str, MemoryItem],
    *,
    max_blocks: int = 3,
) -> list[NegativeEvidence]:
    items: list[NegativeEvidence] = []
    for outcome in outcomes:
        mem = memories_by_id.get(outcome.memory.memory_id)
        if mem is None:
            continue
        # ROADMAP §9.1: a degraded *stale* memory is not failedish; surface it as
        # a warning-only outdated notice rather than an avoided-failure block.
        if outcome.degraded and outcome.reject_reason == "stale_outdated":
            items.append(_outdated_warning(mem))
            continue
        if not is_failedish(mem):
            continue
        if outcome.degraded:
            if is_unsafe_failed(mem):
                items.append(_sanitized(mem, _sanitized_reason(outcome.reject_reason), risk_kind(mem)))
                continue
            items.append(_raw_or_secret_sanitized(mem, outcome.reject_reason or "failed_branch_degraded"))
            continue
        if outcome.decision == GateDecisionType.reject and outcome.reject_reason in _SANITIZED_REASONS:
            kind = risk_kind(mem)
            items.append(_sanitized(mem, outcome.reject_reason or "failed_branch_sanitized", kind))
    return dedupe_negative_evidence(items, max_blocks=max_blocks)


def dedupe_negative_evidence(items: list[NegativeEvidence], *, max_blocks: int = 3) -> list[NegativeEvidence]:
    selected: dict[str, NegativeEvidence] = {}
    order: list[str] = []
    for item in items:
        key = item.source_state_node_id or item.source_memory_id or f"idx:{len(order)}"
        existing = selected.get(key)
        if existing is None:
            selected[key] = item
            order.append(key)
            continue
        if _priority(item) < _priority(existing):
            selected[key] = item
    return [selected[key] for key in order[: max(0, max_blocks)]]


def to_retained_negative_evidence(evidence: NegativeEvidence) -> RetainedNegativeEvidence:
    """Convert safe negative evidence into compaction-retained metadata.

    The conversion intentionally copies only fields from the safe
    ``NegativeEvidence`` DTO. It never reads source memory content.
    """
    return RetainedNegativeEvidence(
        source_memory_id=evidence.source_memory_id,
        source_state_node_id=evidence.source_state_node_id,
        mode=evidence.mode,
        risk_kind=_normalize_retained_risk_kind(evidence.risk_kind),
        reason=evidence.reason,
        safe_text=redact(evidence.safe_text),
        provenance=evidence.provenance,
    )


def _normalize_retained_risk_kind(kind: str | None) -> str | None:
    if kind is None:
        return None
    aliases = {
        "destructive_command": "destructive",
        "destructive": "destructive",
        "production_env": "tool_sensitive",
        "tool_sensitive": "tool_sensitive",
        "secret": "secret",
    }
    return aliases.get(kind, kind)


def _raw_or_secret_sanitized(mem: MemoryItem, reason: str) -> NegativeEvidence:
    redacted = redact(mem.content)
    if contains_secret(mem.content) or redacted != mem.content:
        return _sanitized(mem, _sanitized_reason(reason), "secret")
    return NegativeEvidence(
        source_memory_id=mem.memory_id,
        source_state_node_id=mem.source_state_node_id,
        memory_type=mem.memory_type,
        branch_status=mem.branch_status,
        mode="raw_failed_attempt",
        risk_kind=None,
        reason=reason,
        safe_text=redacted,
        provenance=_provenance(mem),
    )


def _outdated_warning(mem: MemoryItem) -> NegativeEvidence:
    """Render a stale memory as a warning-only outdated notice (ROADMAP §9.1).

    Defense-in-depth: even though the gate's safety floor rejects
    secret/destructive/tool-sensitive memories before they can reach the stale
    branch, secret-bearing content is still collapsed to a generic notice here so
    no raw value can leak through this read path.
    """
    redacted = redact(mem.content)
    if contains_secret(mem.content) or redacted != mem.content:
        safe = "Previously recorded information has expired and was withheld as potentially outdated."
    else:
        safe = f"OUTDATED — previously recorded but now expired; verify before relying on it: {redacted}"
    return NegativeEvidence(
        source_memory_id=mem.memory_id,
        source_state_node_id=mem.source_state_node_id,
        memory_type=mem.memory_type,
        branch_status=mem.branch_status,
        mode="outdated_warning",
        risk_kind=None,
        reason="stale_outdated",
        safe_text=safe,
        provenance=_provenance(mem),
    )


def _sanitized(mem: MemoryItem, reason: str, kind: RiskKind) -> NegativeEvidence:
    return NegativeEvidence(
        source_memory_id=mem.memory_id,
        source_state_node_id=mem.source_state_node_id,
        memory_type=mem.memory_type,
        branch_status=mem.branch_status,
        mode="sanitized_risk_notice",
        risk_kind=kind,
        reason=reason,
        safe_text=SANITIZED_TEMPLATES[kind],
        provenance=_provenance(mem),
    )


def _sanitized_reason(reason: str | None) -> str:
    if not reason:
        return "failed_branch_sanitized"
    if reason.endswith("_degraded"):
        return reason.removesuffix("_degraded") + "_sanitized"
    return reason


def _provenance(mem: MemoryItem) -> Provenance:
    return Provenance(
        run_id=mem.source_run_id or mem.run_id,
        event_id=mem.source_event_id,
        state_node_id=mem.source_state_node_id,
    )


def _priority(item: NegativeEvidence) -> int:
    if item.memory_type is None:
        return 99
    return _TYPE_PRIORITY.get(item.memory_type, 2)


__all__ = [
    "SANITIZED_TEMPLATES",
    "build_negative_evidence",
    "dedupe_negative_evidence",
    "is_failedish",
    "is_unsafe_failed",
    "risk_kind",
    "safe_observability_content",
    "safe_observability_key_value",
    "to_retained_negative_evidence",
]
