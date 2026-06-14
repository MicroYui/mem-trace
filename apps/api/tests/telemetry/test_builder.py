from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.runtime.models import (
    AgentEvent,
    AgentRun,
    AgentStep,
    BenchmarkResultRecord,
    BranchStatus,
    CompactionKind,
    CompactionProvider,
    ContextCompactionLog,
    EventRole,
    EventType,
    GateDecisionType,
    GateLayer,
    MemoryAccessLog,
    MemoryGateLog,
    ProfileEvent,
    ProfilePhase,
    ReplayDiffItem,
    ReplayRetrievalResult,
    RetrievalStrategy,
    RunStatus,
    StepStatus,
)
from app.telemetry import builder, semconv
from app.telemetry.models import TelemetrySpan


NOW = datetime(2026, 6, 14, 12, 0, tzinfo=timezone.utc)


def test_semconv_declares_stable_span_names_and_memtrace_attribute_keys():
    assert semconv.SPAN_NAMES == {
        "run": "memtrace.run",
        "step": "memtrace.step",
        "event": "memtrace.event",
        "retrieve": "memtrace.retrieve",
        "gate": "memtrace.gate",
        "context_pack": "memtrace.context_pack",
        "profile_phase": "memtrace.profile_phase",
        "replay": "memtrace.replay",
        "benchmark_case": "memtrace.benchmark_case",
    }

    required = {
        "memtrace.workspace_id",
        "memtrace.run_id",
        "memtrace.step_id",
        "memtrace.access_id",
        "memtrace.strategy",
        "memtrace.gate.decision",
        "memtrace.policy.version",
        "memtrace.policy.hash",
        "memtrace.context.block_count",
        "memtrace.context.token_count",
        "memtrace.negative_evidence.count",
    }
    assert required.issubset(semconv.MEMTRACE_ATTRIBUTE_KEYS)
    assert semconv.openinference_span_kind("agent") == {
        "openinference.span.kind": "AGENT",
    }
    assert "openinference.span.kind" not in semconv.MEMTRACE_ATTRIBUTE_KEYS

    emitted_by_builders = {
        "memtrace.step.intent",
        "memtrace.step.parent_step_id",
        "memtrace.step.recovery_from_step_id",
        "memtrace.step.state_node_id",
        "memtrace.event.tool_name",
        "memtrace.query.present",
        "memtrace.retrieval.candidate_count",
        "memtrace.retrieval.accepted_count",
        "memtrace.retrieval.rejected_count",
        "memtrace.retrieval.top_k",
        "memtrace.retrieval.latency_ms",
        "memtrace.profile.candidate_count",
        "memtrace.profile.accepted_count",
        "memtrace.profile.rejected_count",
        "memtrace.profile.error_code",
        "memtrace.replay.warning_count",
        "memtrace.compaction.triggered",
        "memtrace.benchmark.positive_contamination_present",
        "memtrace.benchmark.negative_lesson_retained",
        "memtrace.benchmark.negative_lesson_retained_present",
        "memtrace.benchmark.retained_negative_evidence_count_present",
        "memtrace.benchmark.compaction_triggered_present",
        "memtrace.benchmark.unsafe_negative_leakage_present",
    }
    assert emitted_by_builders.issubset(semconv.MEMTRACE_ATTRIBUTE_KEYS)


def test_telemetry_span_rejects_nested_attribute_values():
    with pytest.raises(ValidationError):
        TelemetrySpan(
            name="memtrace.run",
            trace_id="trace",
            span_id="span",
            attributes={"nested": {"not": "otel-safe"}},
        )

    with pytest.raises(ValidationError):
        TelemetrySpan(
            name="memtrace.run",
            trace_id="trace",
            span_id="span",
            attributes={"none": None},
        )


def test_build_run_step_event_spans_are_stable_and_do_not_export_raw_content():
    run = AgentRun(
        run_id="run_123",
        workspace_id="ws_1",
        session_id="sess_1",
        task="Ship telemetry",
        status=RunStatus.completed,
        started_at=NOW,
        finished_at=NOW,
        metadata={"authorization": "Bearer sk-1234567890abcdef1234"},
    )
    step = AgentStep(
        step_id="step_123",
        workspace_id="ws_1",
        run_id="run_123",
        intent="implement",
        status=StepStatus.completed,
        started_at=NOW,
        finished_at=NOW,
    )
    event = AgentEvent(
        event_id="evt_123",
        workspace_id="ws_1",
        session_id="sess_1",
        run_id="run_123",
        step_id="step_123",
        sequence_no=7,
        event_source="sdk",
        role=EventRole.user,
        event_type=EventType.message,
        content="my password is hunter2 and token=secret-value",
        raw_payload_ref="vault://raw/event/evt_123",
        token_input=5,
        token_output=0,
        latency_ms=11,
        metadata={
            "raw_context": "ordinary non-secret context block text should not be exported",
            "prompt": "ordinary prompt text should not be exported",
            "content": "ordinary event content should not be exported",
        },
        created_at=NOW,
    )

    run_span = builder.build_run_span(run)
    step_span = builder.build_step_span(step, run=run)
    event_span = builder.build_event_span(event)

    assert run_span.name == "memtrace.run"
    assert run_span.trace_id == builder.stable_trace_id("run_123")
    assert run_span.span_id == builder.stable_span_id("run", "run_123")
    assert run_span.status == "ok"
    assert run_span.attributes["memtrace.workspace_id"] == "ws_1"
    assert run_span.attributes["memtrace.run_id"] == "run_123"
    assert "sk-1234567890abcdef1234" not in run_span.model_dump_json()

    assert step_span.name == "memtrace.step"
    assert step_span.trace_id == run_span.trace_id
    assert step_span.parent_span_id == run_span.span_id
    assert step_span.attributes["memtrace.step_id"] == "step_123"
    assert step_span.status == "ok"

    assert event_span.name == "memtrace.event"
    assert event_span.trace_id == run_span.trace_id
    assert event_span.parent_span_id == step_span.span_id
    assert event_span.attributes["memtrace.event_id"] == "evt_123"
    assert event_span.attributes["memtrace.event.content_length"] == len(event.content or "")
    assert event_span.attributes["memtrace.event.token_input"] == 5
    assert event_span.attributes["memtrace.event.token_output"] == 0
    assert "password is hunter2" not in event_span.model_dump_json()
    assert "token=secret-value" not in event_span.model_dump_json()
    assert "raw_payload_ref" not in event_span.model_dump_json()
    assert "ordinary non-secret context block text" not in event_span.model_dump_json()
    assert "ordinary prompt text" not in event_span.model_dump_json()
    assert "ordinary event content" not in event_span.model_dump_json()


def test_builders_do_not_export_arbitrary_raw_metadata_values():
    run = AgentRun(
        run_id="run_metadata",
        workspace_id="ws_1",
        session_id="sess_1",
        status=RunStatus.completed,
        metadata={"message": "private user task text should not leave telemetry"},
    )
    event = AgentEvent(
        event_id="evt_metadata",
        workspace_id="ws_1",
        session_id="sess_1",
        run_id="run_metadata",
        step_id="step_metadata",
        sequence_no=1,
        role=EventRole.user,
        event_type=EventType.message,
        metadata={"input": "raw tool argument should not leave telemetry"},
        created_at=NOW,
    )
    profile = ProfileEvent(
        profile_id="profile_metadata",
        workspace_id="ws_1",
        run_id="run_metadata",
        phase=ProfilePhase.generation,
        operation="llm",
        metadata={"output": "raw model completion should not leave telemetry"},
        created_at=NOW,
    )

    dumped = "\n".join(
        [
            builder.build_run_span(run).model_dump_json(),
            builder.build_event_span(event).model_dump_json(),
            builder.build_profile_phase_spans([profile])[0].model_dump_json(),
        ]
    )

    assert "private user task text" not in dumped
    assert "raw tool argument" not in dumped
    assert "raw model completion" not in dumped
    assert "metadata.key_count" in dumped


def test_build_retrieval_span_maps_gate_profile_compaction_without_positive_degrade_count():
    access = MemoryAccessLog(
        access_id="acc_1",
        workspace_id="ws_1",
        run_id="run_1",
        step_id="step_1",
        query="How to recover? token=secret-value",
        retrieval_strategy=RetrievalStrategy.variant_2,
        candidate_count=4,
        accepted_count=1,
        rejected_count=2,
        token_budget=64,
        top_k=5,
        actual_tokens=42,
        latency_ms=17,
        policy_version="retrieval-policy-v2",
        policy_hash="hash123",
        policy_snapshot={"embedding": {"authorization": "Bearer sk-1234567890abcdef1234"}},
        created_at=NOW,
    )
    gate_logs = [
        MemoryGateLog(
            access_id="acc_1",
            memory_id="mem_accept",
            layer=GateLayer.soft_ranking,
            decision=GateDecisionType.accept,
            final_score=0.9,
        ),
        MemoryGateLog(
            access_id="acc_1",
            memory_id="mem_warn",
            layer=GateLayer.soft_ranking,
            decision=GateDecisionType.warn,
            reject_reason="low_state_match",
            final_score=0.7,
        ),
        MemoryGateLog(
            access_id="acc_1",
            memory_id="mem_degrade",
            layer=GateLayer.hard_policy,
            decision=GateDecisionType.degrade,
            reject_reason="failed_branch_degraded",
            final_score=0.5,
        ),
        MemoryGateLog(
            access_id="acc_1",
            memory_id="mem_reject",
            layer=GateLayer.risk_policy,
            decision=GateDecisionType.reject,
            reject_reason="secret",
            final_score=0.1,
        ),
    ]
    profile_events = [
        ProfileEvent(
            profile_id="prof_1",
            run_id="run_1",
            step_id="step_1",
            access_id="acc_1",
            phase=ProfilePhase.retrieval,
            operation="select_candidates",
            latency_ms=3,
            candidate_count=4,
            metadata={"token": "secret-value"},
        )
    ]
    compaction_logs = [
        ContextCompactionLog(
            access_id="acc_1",
            run_id="run_1",
            step_id="step_1",
            workspace_id="ws_1",
            kind=CompactionKind.budget_notice,
            provider=CompactionProvider.rule,
            pre_tokens=100,
            post_tokens=42,
            dropped_block_count=3,
            compression_ratio=0.42,
            retained_negative_evidence=[],
            warnings=["dropped safe evidence"],
        )
    ]

    span = builder.build_retrieval_span(access, gate_logs, profile_events, compaction_logs)

    assert span.name == "memtrace.retrieve"
    assert span.attributes["memtrace.strategy"] == "variant_2"
    assert span.attributes["memtrace.context.token_budget"] == 64
    assert span.attributes["memtrace.context.token_count"] == 42
    assert span.attributes["memtrace.gate.accept_count"] == 1
    assert span.attributes["memtrace.gate.warn_count"] == 1
    assert span.attributes["memtrace.gate.reject_count"] == 1
    assert span.attributes["memtrace.gate.degrade_count"] == 1
    assert span.attributes["memtrace.negative_evidence.count"] == 1
    assert span.attributes["memtrace.context.block_count"] == 0
    assert span.attributes["memtrace.compaction.count"] == 1
    assert span.attributes["memtrace.compaction.dropped_block_count"] == 3
    assert span.attributes["memtrace.policy.version"] == "retrieval-policy-v2"
    assert span.attributes["memtrace.policy.hash"] == "hash123"
    assert "sk-1234567890abcdef1234" not in span.model_dump_json()
    assert "token=secret-value" not in span.model_dump_json()
    assert [event.name for event in span.events] == ["memtrace.gate", "memtrace.gate", "memtrace.gate", "memtrace.gate"]
    assert span.events[2].attributes["memtrace.gate.decision"] == "degrade"

    phase_spans = builder.build_profile_phase_spans(profile_events, parent_span_id=span.span_id)
    assert len(phase_spans) == 1
    assert phase_spans[0].name == "memtrace.profile_phase"
    assert phase_spans[0].parent_span_id == span.span_id
    assert "secret-value" not in phase_spans[0].model_dump_json()


def test_optional_run_id_builders_do_not_collapse_unrelated_records_into_unknown_trace():
    first_access = MemoryAccessLog(
        access_id="acc_a",
        workspace_id="ws_1",
        run_id=None,
        retrieval_strategy=RetrievalStrategy.variant_2,
    )
    second_access = MemoryAccessLog(
        access_id="acc_b",
        workspace_id="ws_1",
        run_id=None,
        retrieval_strategy=RetrievalStrategy.variant_2,
    )

    first_span = builder.build_retrieval_span(first_access)
    second_span = builder.build_retrieval_span(second_access)

    assert first_span.trace_id == builder.stable_trace_id("acc_a")
    assert second_span.trace_id == builder.stable_trace_id("acc_b")
    assert first_span.trace_id != second_span.trace_id


def test_build_replay_span_exports_minimal_summary_without_raw_context_blocks():
    replay = ReplayRetrievalResult(
        access_id="acc_1",
        run_id="run_1",
        step_id="step_1",
        workspace_id="ws_1",
        query="why did rm -rf /prod fail?",
        strategy=RetrievalStrategy.variant_2,
        token_budget=64,
        top_k=5,
        diffs=[
            ReplayDiffItem(kind="policy_drift", field="policy_hash", severity="warning", original="old", replayed="new"),
            ReplayDiffItem(kind="context_block_added", field="content", severity="critical", replayed="raw secret sk-1234567890abcdef1234"),
            ReplayDiffItem(kind="candidate_order", severity="info"),
        ],
        metrics={"negative_evidence_block_count": 2, "policy_drift": "policy_drift"},
        warnings=["raw context had rm -rf /prod"],
    )

    span = builder.build_replay_span(replay)

    assert span.name == "memtrace.replay"
    assert span.attributes["memtrace.access_id"] == "acc_1"
    assert span.attributes["memtrace.replay.diff_count"] == 3
    assert span.attributes["memtrace.replay.critical_diff_count"] == 1
    assert span.attributes["memtrace.replay.warning_diff_count"] == 1
    assert span.attributes["memtrace.replay.info_diff_count"] == 1
    assert span.attributes["memtrace.replay.policy_drift_count"] == 1
    assert span.attributes["memtrace.negative_evidence.count"] == 2
    dumped = span.model_dump_json()
    assert "sk-1234567890abcdef1234" not in dumped
    assert "rm -rf" not in dumped
    assert "raw context" not in dumped


def test_build_benchmark_case_span_projects_present_metrics_and_acceptance_flags():
    record = BenchmarkResultRecord(
        case_id="case_13_compaction_retains_negative_lesson",
        strategy="variant_2",
        metrics={
            "task_success": 1,
            "positive_contamination": 0,
            "positive_contamination_present": 1,
            "negative_lesson_retained": 1,
            "negative_lesson_retained_present": 1,
            "retained_negative_evidence_count": 1,
            "retained_negative_evidence_count_present": 1,
            "compaction_triggered": 1,
            "compaction_triggered_present": 1,
            "unsafe_negative_leakage": 0,
            "unsafe_negative_leakage_present": 1,
            "note": "do not leak sk-1234567890abcdef1234",
            "raw_context": "ordinary non-secret context block text should not be exported",
            "prompt": "ordinary prompt text should not be exported",
        },
    )

    span = builder.build_benchmark_case_span(
        record,
        acceptance={"variant_2_retains_negative_lesson_under_compaction": True},
    )

    assert span.name == "memtrace.benchmark_case"
    assert span.attributes["memtrace.benchmark.case_id"] == "case_13_compaction_retains_negative_lesson"
    assert span.attributes["memtrace.strategy"] == "variant_2"
    assert span.attributes["memtrace.benchmark.task_success"] == 1
    assert span.attributes["memtrace.benchmark.positive_contamination"] == 0
    assert span.attributes["memtrace.negative_evidence.count"] == 1
    assert span.attributes["memtrace.compaction.triggered"] == 1
    assert span.attributes["memtrace.benchmark.acceptance.variant_2_retains_negative_lesson_under_compaction"] is True
    dumped = span.model_dump_json()
    assert "sk-1234567890abcdef1234" not in dumped
    assert "ordinary non-secret context block text" not in dumped
    assert "ordinary prompt text" not in dumped
