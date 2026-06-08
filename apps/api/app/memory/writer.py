"""Rule-based memory writer (P0).

Deterministic regex/keyword rules turn selected trace events into memory items.
This is intentionally small and exhaustively testable; LLM extraction is P2.

Rules (mvp.md section 5):
- Project preference     : user msg "这个项目使用 X" / "用 X" -> project memory key=project.runtime
- Negative constraint    : "不用 Y" / "不使用 Y"               -> key=project.runtime.excluded
- Explicit correction    : "不是 X，是 Y" / "不用 X，用 Y"      -> new memory + supersede old same-key
- Tool evidence failed   : tool_result status=failed            -> tool_evidence branch_status=failed risk+=0.3
- Tool evidence success  : tool_result status=success           -> tool_evidence branch_status=completed
- Working state          : finish_step                          -> working_state summary of step result
- Secret protection      : content matches secret pattern       -> no retrievable memory (handled upstream)

Returned objects are NOT persisted here; the runtime facade persists them so the
writer stays storage-agnostic and pure.
"""
from __future__ import annotations

import re
from typing import Optional

from app.runtime.models import (
    AgentEvent,
    AgentStep,
    BranchStatus,
    EventType,
    MemoryItem,
    MemoryScope,
    MemoryType,
    RiskFlags,
    StepStatus,
)

# --------------------------------------------------------------------------- #
# Keyword tables (deterministic; cover demo + benchmark vocabulary)
# --------------------------------------------------------------------------- #
_RUNTIME_TOKENS = {
    "bun": "bun",
    "node.js": "nodejs",
    "nodejs": "nodejs",
    "node": "nodejs",
    "npm": "npm",
    "pnpm": "pnpm",
    "yarn": "yarn",
    "deno": "deno",
    "python": "python",
    "pytest": "pytest",
}

# correction: "不是 X，是 Y" / "不是X 是Y" / "不用 X，用 Y"
_CORRECTION_PATTERNS = [
    re.compile(r"不是\s*(?P<old>[A-Za-z0-9_.\-]+)[，,\s]*是\s*(?P<new>[A-Za-z0-9_.\-]+)"),
    re.compile(r"不用\s*(?P<old>[A-Za-z0-9_.\-]+)[，,\s]*用\s*(?P<new>[A-Za-z0-9_.\-]+)"),
]
# positive: "使用 X" / "用 X" / "uses X"
_POSITIVE_PATTERNS = [
    re.compile(r"(?:使用|用)\s*(?P<rt>[A-Za-z0-9_.\-]+)"),
    re.compile(r"(?i)\buses?\s+(?P<rt>[A-Za-z0-9_.\-]+)"),
]
# negative: "不用 Y" / "不使用 Y" / "should not use Y"
_NEGATIVE_PATTERNS = [
    re.compile(r"不(?:使用|用)\s*(?P<rt>[A-Za-z0-9_.\-]+)"),
    re.compile(r"(?i)should not use\s+(?P<rt>[A-Za-z0-9_.\-]+)"),
    re.compile(r"(?i)\bnot\s+use\s+(?P<rt>[A-Za-z0-9_.\-]+)"),
]

_DESTRUCTIVE_PATTERNS = [
    re.compile(r"(?i)--force\b"),
    re.compile(r"(?i)\brm\s+-rf\b"),
    re.compile(r"(?i)\bdrop\s+table\b"),
    re.compile(r"(?i)\bgit\s+push\s+--force\b"),
    re.compile(r"(?i)\btruncate\b"),
]
_PRODUCTION_PATTERNS = [
    re.compile(r"(?i)\bproduction\b"),
    re.compile(r"(?i)\bprod\b"),
    re.compile(r"(?i)production[_-]?key\b"),
]
_TOOL_SENSITIVE_TOKENS = ("--force", "rm -rf", "drop table", "production", "prod-", "secret")


def _norm_runtime(token: str) -> Optional[str]:
    return _RUNTIME_TOKENS.get(token.strip().lower())


def detect_risk_flags(content: str | None) -> RiskFlags:
    text = content or ""
    destructive = any(p.search(text) for p in _DESTRUCTIVE_PATTERNS)
    production = any(p.search(text) for p in _PRODUCTION_PATTERNS)
    low = text.lower()
    tool_sensitive = destructive or production or any(t in low for t in _TOOL_SENSITIVE_TOKENS)
    return RiskFlags(
        tool_sensitive=tool_sensitive,
        destructive_command=destructive,
        production_env=production,
    )


# --------------------------------------------------------------------------- #
# Writer
# --------------------------------------------------------------------------- #
class MemoryWriteResult:
    """A new memory plus optional same-key memories to supersede."""

    def __init__(self, memory: MemoryItem, supersede_keys: Optional[list[tuple[str, str]]] = None):
        self.memory = memory
        # list of (key, scope) tuples whose existing actives should be superseded
        self.supersede_keys = supersede_keys or []


def write_from_user_message(event: AgentEvent) -> list[MemoryWriteResult]:
    """Extract project preference / negative constraint / explicit correction."""
    content = event.content or ""
    results: list[MemoryWriteResult] = []

    # Explicit correction takes precedence and supersedes the old value.
    for pat in _CORRECTION_PATTERNS:
        m = pat.search(content)
        if not m:
            continue
        new_rt = _norm_runtime(m.group("new"))
        if not new_rt:
            continue
        mem = _project_memory(event, key="project.runtime", value=new_rt, content=content)
        results.append(MemoryWriteResult(mem, supersede_keys=[("project.runtime", MemoryScope.workspace.value)]))
        return results  # correction is decisive; skip generic positive/negative

    # Positive constraint
    for pat in _POSITIVE_PATTERNS:
        for m in pat.finditer(content):
            rt = _norm_runtime(m.group("rt"))
            if rt:
                results.append(
                    MemoryWriteResult(
                        _project_memory(event, key="project.runtime", value=rt, content=content)
                    )
                )
                break
        if results:
            break

    # Negative constraint
    for pat in _NEGATIVE_PATTERNS:
        for m in pat.finditer(content):
            rt = _norm_runtime(m.group("rt"))
            if rt:
                results.append(
                    MemoryWriteResult(
                        _project_memory(
                            event,
                            key="project.runtime.excluded",
                            value=rt,
                            content=content,
                        )
                    )
                )
                break

    return results


def _project_memory(event: AgentEvent, *, key: str, value: str, content: str) -> MemoryItem:
    return MemoryItem(
        workspace_id=event.workspace_id,
        session_id=event.session_id,
        run_id=event.run_id,
        memory_type=MemoryType.project,
        key=key,
        value=value,
        scope=MemoryScope.workspace,
        content=content.strip(),
        summary=f"{key}={value}",
        source_event_id=event.event_id,
        source_run_id=event.run_id,
        source_state_node_id=event.state_node_id,
        branch_status=BranchStatus.completed,
        confidence=0.9,
        importance=0.8,
        trust_score=0.8,
        risk_flags=detect_risk_flags(content),
    )


def write_from_tool_result(event: AgentEvent) -> Optional[MemoryItem]:
    """Tool evidence from a tool_result event."""
    if event.event_type != EventType.tool_result:
        return None
    status = (event.status or "").lower()
    content = event.content or ""
    risk = detect_risk_flags(content)
    if status == "failed":
        branch = BranchStatus.failed
        risk_score = 0.3 + (0.3 if risk.tool_sensitive else 0.0)
        trust = 0.3
    else:
        branch = BranchStatus.completed
        risk_score = 0.3 if risk.tool_sensitive else 0.0
        trust = 0.7
    return MemoryItem(
        workspace_id=event.workspace_id,
        session_id=event.session_id,
        run_id=event.run_id,
        memory_type=MemoryType.tool_evidence,
        content=content.strip(),
        summary=content.strip()[:120],
        source_event_id=event.event_id,
        source_run_id=event.run_id,
        source_state_node_id=event.state_node_id,
        branch_status=branch,
        confidence=0.7,
        importance=0.6,
        trust_score=trust,
        risk_score=risk_score,
        risk_flags=risk,
    )


def write_from_finish_step(step: AgentStep, *, summary: Optional[str]) -> MemoryItem:
    """Working-state memory summarizing a finished step."""
    if step.status == StepStatus.completed:
        branch = BranchStatus.completed
    elif step.status == StepStatus.failed:
        branch = BranchStatus.failed
    else:
        branch = BranchStatus.active
    text = summary or step.error_message or f"step {step.intent or step.step_id} {step.status.value}"
    return MemoryItem(
        workspace_id=step.workspace_id,
        session_id=None,
        run_id=step.run_id,
        memory_type=MemoryType.working_state,
        content=text,
        summary=text[:120],
        source_event_id=None,
        source_run_id=step.run_id,
        source_state_node_id=step.state_node_id,
        branch_status=branch,
        confidence=0.6,
        importance=0.5,
        trust_score=0.5,
    )


__all__ = [
    "MemoryWriteResult",
    "detect_risk_flags",
    "write_from_user_message",
    "write_from_tool_result",
    "write_from_finish_step",
]
