"""MemTrace telemetry semantic constants.

``memtrace.*`` keys are the stable contract. OpenInference keys are emitted only
through explicit compatibility helpers.
"""
from __future__ import annotations

MAX_ATTRIBUTE_STRING_LENGTH = 512
MAX_ATTRIBUTE_LIST_LENGTH = 16
MAX_ATTRIBUTE_DICT_KEYS = 32
MAX_SERIALIZED_ATTRIBUTE_BYTES = 4096

SPAN_NAMES = {
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

MEMTRACE_ATTRIBUTE_KEYS = frozenset(
    {
        "memtrace.workspace_id",
        "memtrace.session_id",
        "memtrace.run_id",
        "memtrace.step_id",
        "memtrace.event_id",
        "memtrace.access_id",
        "memtrace.strategy",
        "memtrace.status",
        "memtrace.task.present",
        "memtrace.run.metadata_json",
        "memtrace.step.intent",
        "memtrace.step.parent_step_id",
        "memtrace.step.recovery_from_step_id",
        "memtrace.step.state_node_id",
        "memtrace.step.metadata_json",
        "memtrace.event.sequence_no",
        "memtrace.event.source",
        "memtrace.event.role",
        "memtrace.event.type",
        "memtrace.event.visibility",
        "memtrace.event.content_length",
        "memtrace.event.token_input",
        "memtrace.event.token_output",
        "memtrace.event.latency_ms",
        "memtrace.event.tool_name",
        "memtrace.event.metadata_json",
        "memtrace.gate.memory_id",
        "memtrace.gate.layer",
        "memtrace.gate.decision",
        "memtrace.gate.reject_reason",
        "memtrace.gate.relevance_score",
        "memtrace.gate.state_match_score",
        "memtrace.gate.freshness_score",
        "memtrace.gate.trust_score",
        "memtrace.gate.risk_score",
        "memtrace.gate.accept_count",
        "memtrace.gate.warn_count",
        "memtrace.gate.reject_count",
        "memtrace.gate.degrade_count",
        "memtrace.gate.final_score",
        "memtrace.policy.version",
        "memtrace.policy.hash",
        "memtrace.policy.snapshot_json",
        "memtrace.context.block_count",
        "memtrace.context.token_budget",
        "memtrace.context.token_count",
        "memtrace.query.present",
        "memtrace.retrieval.candidate_count",
        "memtrace.retrieval.accepted_count",
        "memtrace.retrieval.rejected_count",
        "memtrace.retrieval.top_k",
        "memtrace.retrieval.latency_ms",
        "memtrace.profile.phase",
        "memtrace.profile.operation",
        "memtrace.profile.latency_ms",
        "memtrace.profile.input_tokens",
        "memtrace.profile.output_tokens",
        "memtrace.profile.llm_calls",
        "memtrace.profile.db_calls",
        "memtrace.profile.candidate_count",
        "memtrace.profile.accepted_count",
        "memtrace.profile.rejected_count",
        "memtrace.profile.error_code",
        "memtrace.profile.metadata_json",
        "memtrace.compaction.count",
        "memtrace.compaction.triggered",
        "memtrace.compaction.dropped_block_count",
        "memtrace.compaction.compression_ratio",
        "memtrace.negative_evidence.count",
        "memtrace.replay.diff_count",
        "memtrace.replay.critical_diff_count",
        "memtrace.replay.warning_diff_count",
        "memtrace.replay.info_diff_count",
        "memtrace.replay.policy_drift_count",
        "memtrace.replay.warning_count",
        "memtrace.benchmark.case_id",
        "memtrace.benchmark.result_id",
        "memtrace.benchmark.task_success",
        "memtrace.benchmark.positive_contamination",
        "memtrace.benchmark.positive_contamination_present",
        "memtrace.benchmark.negative_lesson_retained",
        "memtrace.benchmark.negative_lesson_retained_present",
        "memtrace.benchmark.retained_negative_evidence_count_present",
        "memtrace.benchmark.compaction_triggered_present",
        "memtrace.benchmark.unsafe_negative_leakage",
        "memtrace.benchmark.unsafe_negative_leakage_present",
        "memtrace.benchmark.acceptance.*",
    }
)


def openinference_span_kind(kind: str) -> dict[str, str]:
    """Return an explicit OpenInference compatibility attribute."""
    return {"openinference.span.kind": kind.upper()}


__all__ = [
    "MAX_ATTRIBUTE_DICT_KEYS",
    "MAX_ATTRIBUTE_LIST_LENGTH",
    "MAX_ATTRIBUTE_STRING_LENGTH",
    "MAX_SERIALIZED_ATTRIBUTE_BYTES",
    "MEMTRACE_ATTRIBUTE_KEYS",
    "SPAN_NAMES",
    "openinference_span_kind",
]
