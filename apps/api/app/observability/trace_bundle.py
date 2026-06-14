"""Redacted trace bundle export and validation.

Bundles are read-only debug artifacts. They preserve ids and schema shape for
local reproduction while redacting string payloads by default. This module does
not implement import/write-back semantics.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.memory.secrets import is_secret_like_key, redact
from app.retrieval.negative_evidence import SANITIZED_TEMPLATES
from app.runtime.models import (
    AgentEvent,
    AgentRun,
    AgentStep,
    ContextCompactionLog,
    MemoryAccessLog,
    MemoryGateLog,
    MemoryItem,
    ProfileEvent,
    RetainedFact,
    RetainedNegativeEvidence,
    StateNode,
)
from app.runtime.repository import Repository


SCHEMA_VERSION = "trace-bundle-v1"


class _BundleBase(BaseModel):
    model_config = ConfigDict(use_enum_values=False)


class TraceBundle(_BundleBase):
    schema_version: str = SCHEMA_VERSION
    redacted: bool = True
    runs: list[AgentRun] = Field(default_factory=list)
    steps: list[AgentStep] = Field(default_factory=list)
    events: list[AgentEvent] = Field(default_factory=list)
    state_nodes: list[StateNode] = Field(default_factory=list)
    memories: list[MemoryItem] = Field(default_factory=list)
    access_logs: list[MemoryAccessLog] = Field(default_factory=list)
    gate_logs: list[MemoryGateLog] = Field(default_factory=list)
    profile_events: list[ProfileEvent] = Field(default_factory=list)
    compaction_logs: list[ContextCompactionLog] = Field(default_factory=list)


class TraceBundleValidation(_BundleBase):
    schema_version: str | None = None
    valid: bool = False
    counts: dict[str, int] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)


async def export_run_bundle(repo: Repository, run_id: str, *, redacted: bool = True) -> TraceBundle:
    run = await repo.get_run(run_id)
    if run is None:
        raise ValueError(f"run not found: {run_id}")

    access_logs = [log for log in await repo.list_access_logs(workspace_id=run.workspace_id) if log.run_id == run_id]
    gate_logs = await _gate_logs_for_accesses(repo, access_logs)
    memories = await _run_and_gate_referenced_memories(repo, run.workspace_id, run_id, gate_logs)
    return _bundle(
        redacted=redacted,
        runs=[run],
        steps=await repo.list_steps(run_id),
        events=await repo.list_events(run_id),
        state_nodes=await repo.list_state_nodes(run_id),
        memories=memories,
        access_logs=access_logs,
        gate_logs=gate_logs,
        profile_events=await repo.list_profile_events(run_id=run_id),
        compaction_logs=await repo.list_compaction_logs(run_id=run_id, workspace_id=run.workspace_id),
    )


async def export_access_bundle(repo: Repository, access_id: str, *, redacted: bool = True) -> TraceBundle:
    access = await repo.get_access_log(access_id)
    if access is None:
        raise ValueError(f"access not found: {access_id}")

    run = await repo.get_run(access.run_id) if access.run_id else None
    step = await repo.get_step(access.step_id) if access.step_id else None
    if step is not None and step.run_id != access.run_id:
        step = None
    events = [
        event
        for event in await repo.list_events(access.run_id)
        if access.run_id and access.step_id and event.step_id == access.step_id
    ] if access.run_id and access.step_id else []
    state_nodes = [
        node
        for node in await repo.list_state_nodes(access.run_id)
        if access.run_id and access.step_id and node.step_id == access.step_id
    ] if access.run_id and access.step_id else []
    gate_logs = await repo.list_gate_logs(access_id)
    memories: list[MemoryItem] = []
    seen: set[str] = set()
    for gate in gate_logs:
        memory = await repo.get_memory(gate.memory_id)
        if memory is not None and memory.memory_id not in seen:
            seen.add(memory.memory_id)
            memories.append(memory)

    return _bundle(
        redacted=redacted,
        runs=[run] if run is not None else [],
        steps=[step] if step is not None else [],
        events=events,
        state_nodes=state_nodes,
        memories=memories,
        access_logs=[access],
        gate_logs=gate_logs,
        profile_events=await repo.list_profile_events(access_id=access_id),
        compaction_logs=await repo.list_compaction_logs(access_id=access_id, workspace_id=access.workspace_id),
    )


def validate_bundle_schema(bundle: TraceBundle | dict[str, Any]) -> TraceBundleValidation:
    try:
        parsed = bundle if isinstance(bundle, TraceBundle) else TraceBundle.model_validate(bundle)
    except ValidationError as exc:
        schema_version = bundle.get("schema_version") if isinstance(bundle, dict) else None
        return TraceBundleValidation(schema_version=schema_version, valid=False, errors=[str(exc)])

    if parsed.schema_version != SCHEMA_VERSION:
        return TraceBundleValidation(
            schema_version=parsed.schema_version,
            valid=False,
            errors=[f"unsupported schema_version: {parsed.schema_version}"],
        )
    return TraceBundleValidation(
        schema_version=parsed.schema_version,
        valid=True,
        counts={
            "runs": len(parsed.runs),
            "steps": len(parsed.steps),
            "events": len(parsed.events),
            "state_nodes": len(parsed.state_nodes),
            "memories": len(parsed.memories),
            "access_logs": len(parsed.access_logs),
            "gate_logs": len(parsed.gate_logs),
            "profile_events": len(parsed.profile_events),
            "compaction_logs": len(parsed.compaction_logs),
        },
        errors=[],
    )


async def _gate_logs_for_accesses(repo: Repository, access_logs: list[MemoryAccessLog]) -> list[MemoryGateLog]:
    rows: list[MemoryGateLog] = []
    for access in access_logs:
        rows.extend(await repo.list_gate_logs(access.access_id))
    rows.sort(key=lambda row: (row.created_at, row.gate_id))
    return rows


async def _run_and_gate_referenced_memories(
    repo: Repository,
    workspace_id: str,
    run_id: str,
    gate_logs: list[MemoryGateLog],
) -> list[MemoryItem]:
    memories: dict[str, MemoryItem] = {}
    for memory in await repo.list_memories(workspace_id=workspace_id, run_id=run_id):
        memories[memory.memory_id] = memory
    for gate in gate_logs:
        if gate.memory_id in memories:
            continue
        memory = await repo.get_memory(gate.memory_id)
        if memory is not None and memory.workspace_id == workspace_id:
            memories[memory.memory_id] = memory
    return sorted(memories.values(), key=lambda memory: (memory.created_at, memory.memory_id))


def _bundle(
    *,
    redacted: bool,
    runs: list[AgentRun],
    steps: list[AgentStep],
    events: list[AgentEvent],
    state_nodes: list[StateNode],
    memories: list[MemoryItem],
    access_logs: list[MemoryAccessLog],
    gate_logs: list[MemoryGateLog],
    profile_events: list[ProfileEvent],
    compaction_logs: list[ContextCompactionLog],
) -> TraceBundle:
    if not redacted:
        return TraceBundle(
            redacted=False,
            runs=runs,
            steps=steps,
            events=events,
            state_nodes=state_nodes,
            memories=memories,
            access_logs=access_logs,
            gate_logs=gate_logs,
            profile_events=profile_events,
            compaction_logs=compaction_logs,
        )
    return TraceBundle(
        redacted=True,
        runs=[_redact_run(row) for row in runs],
        steps=[_redact_step(row) for row in steps],
        events=[_redact_event(row) for row in events],
        state_nodes=[_redact_state_node(row) for row in state_nodes],
        memories=[_redact_memory(row) for row in memories],
        access_logs=[_redact_access(row) for row in access_logs],
        gate_logs=[_redact_gate(row) for row in gate_logs],
        profile_events=[_redact_profile(row) for row in profile_events],
        compaction_logs=[_redact_compaction(row) for row in compaction_logs],
    )


def _redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_value(item) for item in value)
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            safe_key = redact(str(key))
            # Secret-like keys (e.g. password/token/authorization) get their whole
            # value redacted, mirroring reports.py, so non-pattern-matching values
            # (numbers, opaque strings, nested dicts) cannot leak.
            out[safe_key] = "[REDACTED]" if is_secret_like_key(str(key)) else _redact_value(item)
        return out
    return value


def _redact_run(run: AgentRun) -> AgentRun:
    return run.model_copy(update={"task": redact(run.task), "metadata": _redact_value(run.metadata)})


def _redact_step(step: AgentStep) -> AgentStep:
    return step.model_copy(
        update={
            "intent": redact(step.intent),
            "error_message": redact(step.error_message),
            "metadata": _redact_value(step.metadata),
        }
    )


def _redact_event(event: AgentEvent) -> AgentEvent:
    return event.model_copy(
        update={
            "event_source": redact(event.event_source),
            "content": redact(event.content),
            "content_digest": redact(event.content_digest),
            "raw_payload_ref": redact(event.raw_payload_ref),
            "causality_id": redact(event.causality_id),
            "tool_name": redact(event.tool_name),
            "tool_args_digest": redact(event.tool_args_digest),
            "status": redact(event.status),
            "metadata": _redact_value(event.metadata),
        }
    )


def _redact_state_node(node: StateNode) -> StateNode:
    return node.model_copy(
        update={
            "goal": redact(node.goal),
            "summary": redact(node.summary),
            "branch_reason": _redact_value(node.branch_reason),
            "failure_reason": redact(node.failure_reason),
        }
    )


def _redact_memory(memory: MemoryItem) -> MemoryItem:
    return memory.model_copy(
        update={
            "key": redact(memory.key),
            "value": redact(memory.value),
            "content": redact(memory.content),
            "summary": redact(memory.summary),
            "lifecycle_metadata": _redact_value(memory.lifecycle_metadata),
        }
    )


def _redact_access(access: MemoryAccessLog) -> MemoryAccessLog:
    return access.model_copy(
        update={
            "query": redact(access.query),
            "task_intent": redact(access.task_intent),
            "policy_snapshot": _redact_value(access.policy_snapshot),
        }
    )


def _redact_gate(gate: MemoryGateLog) -> MemoryGateLog:
    return gate.model_copy(update={"reject_reason": redact(gate.reject_reason)})


def _redact_profile(profile: ProfileEvent) -> ProfileEvent:
    return profile.model_copy(
        update={
            "operation": redact(profile.operation),
            "error_code": redact(profile.error_code),
            "metadata": _redact_value(profile.metadata),
        }
    )


def _redact_compaction(log: ContextCompactionLog) -> ContextCompactionLog:
    facts = [
        fact.model_copy(
            update={
                "key": redact(fact.key),
                "value": "[REDACTED]" if is_secret_like_key(fact.key) else redact(fact.value),
            }
        )
        if isinstance(fact, RetainedFact)
        else fact
        for fact in log.retained_facts
    ]
    retained_negative_evidence = [
        item.model_copy(update={"reason": redact(item.reason), "safe_text": _redact_retained_negative_text(item)})
        if isinstance(item, RetainedNegativeEvidence)
        else item
        for item in log.retained_negative_evidence
    ]
    return log.model_copy(
        update={
            "summary_text": redact(log.summary_text),
            "retained_facts": facts,
            "retained_negative_evidence": retained_negative_evidence,
            "warnings": _redact_value(log.warnings),
        }
    )


def _redact_retained_negative_text(item: RetainedNegativeEvidence) -> str:
    if item.risk_kind in SANITIZED_TEMPLATES:
        return SANITIZED_TEMPLATES[item.risk_kind]
    redacted = redact(item.safe_text)
    if _contains_retained_negative_unsafe_marker(redacted):
        return SANITIZED_TEMPLATES["unknown"]
    if item.mode == "sanitized_risk_notice":
        return SANITIZED_TEMPLATES["unknown"]
    return redacted


def _contains_retained_negative_unsafe_marker(text: str) -> bool:
    lowered = text.lower()
    return any(
        marker in lowered
        for marker in (
            "rm -rf",
            "/prod",
            "sk-",
            "password",
            "authorization",
        )
    )


__all__ = [
    "TraceBundle",
    "TraceBundleValidation",
    "export_access_bundle",
    "export_run_bundle",
    "validate_bundle_schema",
]
