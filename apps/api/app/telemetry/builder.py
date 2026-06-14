"""Pure builders from MemTrace DTOs to internal telemetry spans."""
from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any, Mapping

from app.runtime.models import (
    AgentEvent,
    AgentRun,
    AgentStep,
    BenchmarkResultRecord,
    ContextCompactionLog,
    GateDecisionType,
    MemoryAccessLog,
    MemoryGateLog,
    ProfileEvent,
    ReplayRetrievalResult,
    RunStatus,
    StepStatus,
)
from app.telemetry import semconv
from app.telemetry.models import TelemetryEvent, TelemetrySpan
from app.telemetry.redaction import sanitize_attributes

_OK_RUN_STATUSES = {RunStatus.completed}
_ERROR_RUN_STATUSES = {RunStatus.failed, RunStatus.cancelled}
_OK_STEP_STATUSES = {StepStatus.completed}
_ERROR_STEP_STATUSES = {StepStatus.failed, StepStatus.cancelled, StepStatus.rolled_back}
_ACCEPTED_POSITIVE_DECISIONS = {GateDecisionType.accept}
_WARN_DECISIONS = {GateDecisionType.warn}
_REJECT_DECISIONS = {GateDecisionType.reject}
_DEGRADE_DECISIONS = {GateDecisionType.degrade}


def _digest(namespace: str, value: str, *, length: int) -> str:
    return hashlib.blake2b(f"{namespace}:{value}".encode("utf-8"), digest_size=16).hexdigest()[:length]


def stable_trace_id(run_id: str | None) -> str:
    return _digest("trace", run_id or "unknown", length=32)


def _trace_id(run_id: str | None, fallback_id: str | None) -> str:
    return stable_trace_id(run_id or fallback_id)


def stable_span_id(kind: str, item_id: str | None) -> str:
    return _digest(kind, item_id or "unknown", length=16)


def _enum_value(value: Any) -> Any:
    return getattr(value, "value", value)


def _metadata_key_count(metadata: Mapping[str, Any] | None) -> int:
    return len(metadata or {})


def _status_from_run(status: RunStatus) -> str:
    if status in _OK_RUN_STATUSES:
        return "ok"
    if status in _ERROR_RUN_STATUSES:
        return "error"
    return "unset"


def _status_from_step(status: StepStatus) -> str:
    if status in _OK_STEP_STATUSES:
        return "ok"
    if status in _ERROR_STEP_STATUSES:
        return "error"
    return "unset"


def _span(
    *,
    name: str,
    trace_id: str,
    span_id: str,
    parent_span_id: str | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    attributes: Mapping[str, Any] | None = None,
    events: list[TelemetryEvent] | None = None,
    status: str = "unset",
) -> TelemetrySpan:
    return TelemetrySpan(
        name=name,
        trace_id=trace_id,
        span_id=span_id,
        parent_span_id=parent_span_id,
        start_time=start_time,
        end_time=end_time,
        attributes=sanitize_attributes(attributes or {}),
        events=events or [],
        status=status,
    )


def build_run_span(run: AgentRun) -> TelemetrySpan:
    return _span(
        name=semconv.SPAN_NAMES["run"],
        trace_id=stable_trace_id(run.run_id),
        span_id=stable_span_id("run", run.run_id),
        start_time=run.started_at,
        end_time=run.finished_at,
        status=_status_from_run(run.status),
        attributes={
            **semconv.openinference_span_kind("agent"),
            "memtrace.workspace_id": run.workspace_id,
            "memtrace.session_id": run.session_id,
            "memtrace.run_id": run.run_id,
            "memtrace.status": run.status.value,
            "memtrace.task.present": bool(run.task),
            "memtrace.run.metadata.key_count": _metadata_key_count(run.metadata),
        },
    )


def build_step_span(step: AgentStep, *, run: AgentRun | None = None) -> TelemetrySpan:
    return _span(
        name=semconv.SPAN_NAMES["step"],
        trace_id=stable_trace_id(run.run_id if run is not None else step.run_id),
        span_id=stable_span_id("step", step.step_id),
        parent_span_id=stable_span_id("run", step.run_id),
        start_time=step.started_at,
        end_time=step.finished_at,
        status=_status_from_step(step.status),
        attributes={
            **semconv.openinference_span_kind("chain"),
            "memtrace.workspace_id": step.workspace_id,
            "memtrace.run_id": step.run_id,
            "memtrace.step_id": step.step_id,
            "memtrace.status": step.status.value,
            "memtrace.step.intent": step.intent,
            "memtrace.step.parent_step_id": step.parent_step_id,
            "memtrace.step.recovery_from_step_id": step.recovery_from_step_id,
            "memtrace.step.state_node_id": step.state_node_id,
            "memtrace.step.metadata.key_count": _metadata_key_count(step.metadata),
        },
    )


def build_event_span(event: AgentEvent) -> TelemetrySpan:
    return _span(
        name=semconv.SPAN_NAMES["event"],
        trace_id=stable_trace_id(event.run_id),
        span_id=stable_span_id("event", event.event_id),
        parent_span_id=stable_span_id("step", event.step_id),
        start_time=event.created_at,
        end_time=event.created_at,
        status="error" if event.status == "failed" or event.event_type.value == "error" else "unset",
        attributes={
            **semconv.openinference_span_kind("tool" if event.event_type.value.startswith("tool") else "agent"),
            "memtrace.workspace_id": event.workspace_id,
            "memtrace.session_id": event.session_id,
            "memtrace.run_id": event.run_id,
            "memtrace.step_id": event.step_id,
            "memtrace.event_id": event.event_id,
            "memtrace.event.sequence_no": event.sequence_no,
            "memtrace.event.source": event.event_source,
            "memtrace.event.role": event.role.value,
            "memtrace.event.type": event.event_type.value,
            "memtrace.event.visibility": event.visibility,
            "memtrace.event.content_length": len(event.content or ""),
            "memtrace.event.token_input": event.token_input,
            "memtrace.event.token_output": event.token_output,
            "memtrace.event.latency_ms": event.latency_ms,
            "memtrace.event.tool_name": event.tool_name,
            "memtrace.status": event.status,
            "memtrace.event.metadata.key_count": _metadata_key_count(event.metadata),
        },
    )


def build_gate_event(gate_log: MemoryGateLog) -> TelemetryEvent:
    return TelemetryEvent(
        name=semconv.SPAN_NAMES["gate"],
        timestamp=gate_log.created_at,
        attributes=sanitize_attributes(
            {
                "memtrace.access_id": gate_log.access_id,
                "memtrace.gate.memory_id": gate_log.memory_id,
                "memtrace.gate.layer": gate_log.layer.value,
                "memtrace.gate.decision": gate_log.decision.value,
                "memtrace.gate.reject_reason": gate_log.reject_reason,
                "memtrace.gate.relevance_score": gate_log.relevance_score,
                "memtrace.gate.state_match_score": gate_log.state_match_score,
                "memtrace.gate.freshness_score": gate_log.freshness_score,
                "memtrace.gate.trust_score": gate_log.trust_score,
                "memtrace.gate.risk_score": gate_log.risk_score,
                "memtrace.gate.final_score": gate_log.final_score,
            }
        ),
    )


def _count_decisions(gate_logs: list[MemoryGateLog]) -> dict[str, int]:
    return {
        "accept": sum(1 for log in gate_logs if log.decision in _ACCEPTED_POSITIVE_DECISIONS),
        "warn": sum(1 for log in gate_logs if log.decision in _WARN_DECISIONS),
        "reject": sum(1 for log in gate_logs if log.decision in _REJECT_DECISIONS),
        "degrade": sum(1 for log in gate_logs if log.decision in _DEGRADE_DECISIONS),
    }


def build_retrieval_span(
    access: MemoryAccessLog,
    gate_logs: list[MemoryGateLog] | None = None,
    profile_events: list[ProfileEvent] | None = None,
    compaction_logs: list[ContextCompactionLog] | None = None,
) -> TelemetrySpan:
    gates = list(gate_logs or [])
    profiles = list(profile_events or [])
    compactions = list(compaction_logs or [])
    decision_counts = _count_decisions(gates)
    compaction_dropped = sum(log.dropped_block_count for log in compactions)
    compaction_ratio_values = [log.compression_ratio for log in compactions]
    avg_compaction_ratio = sum(compaction_ratio_values) / len(compaction_ratio_values) if compaction_ratio_values else 0.0
    return _span(
        name=semconv.SPAN_NAMES["retrieve"],
        trace_id=_trace_id(access.run_id, access.access_id),
        span_id=stable_span_id("retrieve", access.access_id),
        parent_span_id=stable_span_id("step", access.step_id) if access.step_id else None,
        start_time=access.created_at,
        status="ok",
        events=[build_gate_event(log) for log in gates],
        attributes={
            **semconv.openinference_span_kind("retriever"),
            "memtrace.workspace_id": access.workspace_id,
            "memtrace.run_id": access.run_id,
            "memtrace.step_id": access.step_id,
            "memtrace.access_id": access.access_id,
            "memtrace.strategy": access.retrieval_strategy.value,
            "memtrace.context.token_budget": access.token_budget,
            "memtrace.context.token_count": access.actual_tokens,
            "memtrace.context.block_count": 0,
            "memtrace.retrieval.candidate_count": access.candidate_count,
            "memtrace.retrieval.accepted_count": access.accepted_count,
            "memtrace.retrieval.rejected_count": access.rejected_count,
            "memtrace.retrieval.top_k": access.top_k,
            "memtrace.retrieval.latency_ms": access.latency_ms,
            "memtrace.gate.accept_count": decision_counts["accept"],
            "memtrace.gate.warn_count": decision_counts["warn"],
            "memtrace.gate.reject_count": decision_counts["reject"],
            "memtrace.gate.degrade_count": decision_counts["degrade"],
            "memtrace.negative_evidence.count": decision_counts["degrade"],
            "memtrace.profile.phase_count": len(profiles),
            "memtrace.compaction.count": len(compactions),
            "memtrace.compaction.dropped_block_count": compaction_dropped,
            "memtrace.compaction.compression_ratio": avg_compaction_ratio,
            "memtrace.policy.version": access.policy_version,
            "memtrace.policy.hash": access.policy_hash,
            "memtrace.policy.snapshot": access.policy_snapshot,
            "memtrace.query.present": bool(access.query),
        },
    )


def build_profile_phase_spans(profile_events: list[ProfileEvent], *, parent_span_id: str | None = None) -> list[TelemetrySpan]:
    spans: list[TelemetrySpan] = []
    for event in profile_events:
        spans.append(
            _span(
                name=semconv.SPAN_NAMES["profile_phase"],
                trace_id=_trace_id(event.run_id, event.access_id or event.profile_id),
                span_id=stable_span_id("profile", event.profile_id),
                parent_span_id=parent_span_id or (stable_span_id("retrieve", event.access_id) if event.access_id else None),
                start_time=event.created_at,
                end_time=event.created_at,
                status="error" if event.error_code else "ok",
                attributes={
                    "memtrace.run_id": event.run_id,
                    "memtrace.step_id": event.step_id,
                    "memtrace.access_id": event.access_id,
                    "memtrace.profile.phase": event.phase.value,
                    "memtrace.profile.operation": event.operation,
                    "memtrace.profile.latency_ms": event.latency_ms,
                    "memtrace.profile.input_tokens": event.input_tokens,
                    "memtrace.profile.output_tokens": event.output_tokens,
                    "memtrace.profile.llm_calls": event.llm_calls,
                    "memtrace.profile.db_calls": event.db_calls,
                    "memtrace.profile.candidate_count": event.candidate_count,
                    "memtrace.profile.accepted_count": event.accepted_count,
                    "memtrace.profile.rejected_count": event.rejected_count,
                    "memtrace.profile.error_code": event.error_code,
                    "memtrace.profile.metadata.key_count": _metadata_key_count(event.metadata),
                },
            )
        )
    return spans


def build_replay_span(replay: ReplayRetrievalResult) -> TelemetrySpan:
    critical = sum(1 for diff in replay.diffs if diff.severity == "critical")
    warning = sum(1 for diff in replay.diffs if diff.severity == "warning")
    info = sum(1 for diff in replay.diffs if diff.severity == "info")
    policy_drift = sum(1 for diff in replay.diffs if diff.kind == "policy_drift")
    return _span(
        name=semconv.SPAN_NAMES["replay"],
        trace_id=_trace_id(replay.run_id, replay.access_id),
        span_id=stable_span_id("replay", replay.access_id),
        parent_span_id=stable_span_id("retrieve", replay.access_id),
        status="error" if critical else "ok",
        attributes={
            "memtrace.workspace_id": replay.workspace_id,
            "memtrace.run_id": replay.run_id,
            "memtrace.step_id": replay.step_id,
            "memtrace.access_id": replay.access_id,
            "memtrace.strategy": replay.strategy.value,
            "memtrace.context.token_budget": replay.token_budget,
            "memtrace.replay.diff_count": len(replay.diffs),
            "memtrace.replay.critical_diff_count": critical,
            "memtrace.replay.warning_diff_count": warning,
            "memtrace.replay.info_diff_count": info,
            "memtrace.replay.policy_drift_count": policy_drift,
            "memtrace.negative_evidence.count": int(replay.metrics.get("negative_evidence_block_count", 0)),
            "memtrace.replay.warning_count": len(replay.warnings),
        },
    )


def _metric(metrics: Mapping[str, Any], key: str, default: int | float = 0) -> int | float:
    value = metrics.get(key, default)
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else default


_BENCHMARK_METRIC_ATTRIBUTES: dict[str, str] = {
    "task_success": "memtrace.benchmark.task_success",
    "positive_contamination": "memtrace.benchmark.positive_contamination",
    "positive_contamination_present": "memtrace.benchmark.positive_contamination_present",
    "negative_lesson_retained": "memtrace.benchmark.negative_lesson_retained",
    "negative_lesson_retained_present": "memtrace.benchmark.negative_lesson_retained_present",
    "retained_negative_evidence_count": "memtrace.negative_evidence.count",
    "retained_negative_evidence_count_present": "memtrace.benchmark.retained_negative_evidence_count_present",
    "compaction_triggered": "memtrace.compaction.triggered",
    "compaction_triggered_present": "memtrace.benchmark.compaction_triggered_present",
    "compression_ratio": "memtrace.compaction.compression_ratio",
    "unsafe_negative_leakage": "memtrace.benchmark.unsafe_negative_leakage",
    "unsafe_negative_leakage_present": "memtrace.benchmark.unsafe_negative_leakage_present",
}


def build_benchmark_case_span(
    record: BenchmarkResultRecord,
    *,
    acceptance: Mapping[str, bool] | None = None,
) -> TelemetrySpan:
    metrics = record.metrics
    attrs: dict[str, Any] = {
        "memtrace.benchmark.case_id": record.case_id,
        "memtrace.benchmark.result_id": record.result_id,
        "memtrace.strategy": record.strategy,
    }
    for metric_key, attr_key in _BENCHMARK_METRIC_ATTRIBUTES.items():
        attrs[attr_key] = _metric(metrics, metric_key, 0.0 if metric_key == "compression_ratio" else 0)
    for name, passed in sorted((acceptance or {}).items()):
        attrs[f"memtrace.benchmark.acceptance.{name}"] = bool(passed)
    return _span(
        name=semconv.SPAN_NAMES["benchmark_case"],
        trace_id=stable_trace_id(f"benchmark:{record.case_id}"),
        span_id=stable_span_id("benchmark", record.result_id),
        start_time=record.created_at,
        end_time=record.created_at,
        status="ok" if _metric(metrics, "task_success") else "error",
        attributes=attrs,
    )


__all__ = [
    "build_benchmark_case_span",
    "build_event_span",
    "build_gate_event",
    "build_profile_phase_spans",
    "build_replay_span",
    "build_retrieval_span",
    "build_run_span",
    "build_step_span",
    "stable_span_id",
    "stable_trace_id",
]
