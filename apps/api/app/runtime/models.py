"""Core domain models, enums, and request/result schemas for MemTrace P0.

These are storage-agnostic Pydantic v2 models. They are the single shared
vocabulary used by the runtime facade, repositories, retrieval/gate/profiler,
HTTP layer, and demo.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


# --------------------------------------------------------------------------- #
# Enums
# --------------------------------------------------------------------------- #
class RunStatus(str, Enum):
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class StepStatus(str, Enum):
    active = "active"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"
    rolled_back = "rolled_back"


class StateNodeType(str, Enum):
    root = "root"
    step = "step"
    recovery = "recovery"
    # Extended node vocabulary (ROADMAP §5). `subgoal` groups consecutive steps
    # pursuing one goal (deterministic auto-inference, default-off); `tool_call`
    # marks a tool-invocation node; `summary` marks a compacted-history node. The
    # default execution tree still emits only root/step/recovery, so these are
    # available for opt-in analysis/compaction without changing default behavior.
    subgoal = "subgoal"
    tool_call = "tool_call"
    summary = "summary"


class StateNodeStatus(str, Enum):
    active = "active"
    completed = "completed"
    failed = "failed"
    rolled_back = "rolled_back"


class EventRole(str, Enum):
    user = "user"
    assistant = "assistant"
    tool = "tool"
    system = "system"
    runtime = "runtime"


class EventType(str, Enum):
    message = "message"
    tool_call = "tool_call"
    tool_result = "tool_result"
    error = "error"
    checkpoint = "checkpoint"


class ToolStatus(str, Enum):
    success = "success"
    failed = "failed"


class MemoryType(str, Enum):
    working_state = "working_state"
    profile = "profile"
    project = "project"
    episodic = "episodic"
    tool_evidence = "tool_evidence"
    procedural = "procedural"


class MemoryScope(str, Enum):
    workspace = "workspace"
    user = "user"
    session = "session"


class BranchStatus(str, Enum):
    active = "active"
    failed = "failed"
    rolled_back = "rolled_back"
    completed = "completed"


class MemoryStatus(str, Enum):
    active = "active"
    dormant = "dormant"
    archived = "archived"
    superseded = "superseded"
    conflicted = "conflicted"
    quarantined = "quarantined"
    pinned = "pinned"
    deleted = "deleted"


class WorkspacePermission(str, Enum):
    owner = "owner"
    writer = "writer"
    reader = "reader"
    report_reader = "report_reader"


class Sensitivity(str, Enum):
    public = "public"
    internal = "internal"
    private = "private"
    secret = "secret"


class EmbeddingStatus(str, Enum):
    pending = "pending"
    embedded = "embedded"
    failed = "failed"
    stale = "stale"


class GateLayer(str, Enum):
    hard_policy = "hard_policy"
    risk_policy = "risk_policy"
    soft_ranking = "soft_ranking"


class GateDecisionType(str, Enum):
    accept = "accept"
    reject = "reject"
    degrade = "degrade"
    warn = "warn"


class RetrievalStrategy(str, Enum):
    """Strategy modes used by demo/benchmark to prove the differentiation.

    Ordered as the 6-strategy benchmark layers (ROADMAP §7):
    no-memory -> long-context -> vector -> state-aware -> +gate -> +reflection.
    """

    baseline_0 = "baseline_0"  # no memory
    long_context = "long_context"  # all-context baseline: same gate/log path, policies disabled, include_all + unbounded budget
    baseline_1 = "baseline_1"  # vector/lexical memory only, ignores state + gate
    variant_1 = "variant_1"  # state-aware rerank, failed branch only downweighted
    variant_2 = "variant_2"  # state-aware + hard/risk admission gate
    variant_3 = "variant_3"  # variant_2 + deterministic reflection-lite retention rerank


class ProfilePhase(str, Enum):
    retrieval = "retrieval"
    gate = "gate"
    context_packing = "context_packing"
    context_compaction = "context_compaction"
    ingestion = "ingestion"
    construction = "construction"
    rerank = "rerank"
    generation = "generation"
    maintenance = "maintenance"
    quality = "quality"
    safety = "safety"


class ExtractionMode(str, Enum):
    """Freshness-vs-latency policy for turning events into memory (architecture.md §12.1).

    - ``sync``: extract inline on write_event (default; deterministic demo/benchmark).
    - ``buffered``: backward-compatible alias for lazy deferred extraction.
    - ``async``: enqueue extraction for an async worker; code uses ``async_``
      because ``async`` is a Python keyword.
    - ``sync_flush``: defer extraction until an explicit flush only.
    - ``lazy``: defer extraction until explicit flush or a natural window boundary.
    - ``no_extract``: persist the event without deriving memory.
    """

    sync = "sync"
    buffered = "buffered"
    async_ = "async"
    sync_flush = "sync_flush"
    lazy = "lazy"
    no_extract = "no_extract"


class MaintenanceOperation(str, Enum):
    score_memory = "score_memory"
    decay_memory = "decay_memory"
    archive_memory = "archive_memory"
    quarantine_memory = "quarantine_memory"
    conflict_scan = "conflict_scan"
    dedup_memory = "dedup_memory"
    reindex_memory = "reindex_memory"
    reindex_secondary = "reindex_secondary"
    summary_refresh = "summary_refresh"
    procedural_refresh = "procedural_refresh"
    profile_refresh = "profile_refresh"


class SchedulerRunStatus(str, Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class SchedulerTaskStatus(str, Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    skipped = "skipped"


QuotaUnitName = Literal[
    "write_event",
    "retrieve_context",
    "report_export",
    "replay",
    "async_task_enqueue",
]


class CompactionKind(str, Enum):
    budget_notice = "budget_notice"
    history_summary = "history_summary"


class CompactionProvider(str, Enum):
    rule = "rule"
    llm = "llm"
    fallback_rule = "fallback_rule"


# --------------------------------------------------------------------------- #
# Domain models
# --------------------------------------------------------------------------- #
class _Base(BaseModel):
    model_config = ConfigDict(use_enum_values=False)


class AgentRun(_Base):
    run_id: str = Field(default_factory=lambda: _new_id("run"))
    workspace_id: str
    session_id: str
    task: Optional[str] = None
    status: RunStatus = RunStatus.running
    started_at: datetime = Field(default_factory=_now)
    finished_at: Optional[datetime] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class AgentStep(_Base):
    step_id: str = Field(default_factory=lambda: _new_id("step"))
    workspace_id: str
    run_id: str
    parent_step_id: Optional[str] = None
    recovery_from_step_id: Optional[str] = None
    state_node_id: Optional[str] = None
    intent: Optional[str] = None
    status: StepStatus = StepStatus.active
    started_at: datetime = Field(default_factory=_now)
    finished_at: Optional[datetime] = None
    error_message: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class AgentEvent(_Base):
    event_id: str = Field(default_factory=lambda: _new_id("evt"))
    workspace_id: str
    session_id: Optional[str] = None
    run_id: str
    step_id: str
    state_node_id: Optional[str] = None
    sequence_no: int = 0
    event_source: Optional[str] = None
    visibility: str = "visible"
    role: EventRole = EventRole.runtime
    event_type: EventType = EventType.message
    content: Optional[str] = None
    content_digest: Optional[str] = None
    raw_payload_ref: Optional[str] = None
    redaction_status: str = "none"
    causality_id: Optional[str] = None
    tool_name: Optional[str] = None
    tool_args_digest: Optional[str] = None
    status: Optional[str] = None
    token_input: int = 0
    token_output: int = 0
    latency_ms: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_now)


class StateNode(_Base):
    node_id: str = Field(default_factory=lambda: _new_id("node"))
    workspace_id: str
    run_id: str
    parent_id: Optional[str] = None
    step_id: Optional[str] = None
    node_type: StateNodeType = StateNodeType.step
    status: StateNodeStatus = StateNodeStatus.active
    goal: Optional[str] = None
    summary: Optional[str] = None
    raw_event_ids: list[str] = Field(default_factory=list)
    memory_refs: list[str] = Field(default_factory=list)
    branch_reason: dict[str, Any] = Field(default_factory=dict)
    failure_reason: Optional[str] = None
    depth: int = 0
    path: str = ""
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class RiskFlags(_Base):
    tool_sensitive: bool = False
    contains_secret: bool = False
    destructive_command: bool = False
    production_env: bool = False


class MemoryItem(_Base):
    memory_id: str = Field(default_factory=lambda: _new_id("mem"))
    workspace_id: str
    session_id: Optional[str] = None
    run_id: Optional[str] = None
    memory_type: MemoryType
    key: Optional[str] = None
    value: Optional[str] = None
    scope: MemoryScope = MemoryScope.workspace
    content: str = ""
    summary: Optional[str] = None
    source_event_id: Optional[str] = None
    source_event_ids: Optional[list[str]] = None
    source_run_id: Optional[str] = None
    source_state_node_id: Optional[str] = None
    branch_status: BranchStatus = BranchStatus.active
    confidence: float = 0.5
    importance: float = 0.5
    value_score: float = 0.5
    freshness_score: float = 1.0
    trust_score: float = 0.5
    risk_score: float = 0.0
    embedding_vector: Optional[list[float]] = None
    risk_flags: RiskFlags = Field(default_factory=RiskFlags)
    status: MemoryStatus = MemoryStatus.active
    lifecycle_metadata: dict[str, Any] = Field(default_factory=dict)
    superseded_by: Optional[str] = None
    sensitivity: Sensitivity = Sensitivity.internal
    embedding_status: EmbeddingStatus = EmbeddingStatus.pending
    expires_at: Optional[datetime] = None
    last_accessed_at: Optional[datetime] = None
    access_count: int = 0
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class MemoryAccessLog(_Base):
    access_id: str = Field(default_factory=lambda: _new_id("acc"))
    workspace_id: str
    run_id: Optional[str] = None
    step_id: Optional[str] = None
    query: Optional[str] = None
    task_intent: Optional[str] = None
    retrieval_strategy: RetrievalStrategy = RetrievalStrategy.variant_2
    candidate_count: int = 0
    accepted_count: int = 0
    rejected_count: int = 0
    token_budget: int = 0
    top_k: int = 10
    actual_tokens: int = 0
    latency_ms: int = 0
    policy_version: Optional[str] = None
    policy_hash: Optional[str] = None
    policy_snapshot: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_now)


class MemoryGateLog(_Base):
    gate_id: str = Field(default_factory=lambda: _new_id("gate"))
    access_id: str
    memory_id: str
    layer: GateLayer
    decision: GateDecisionType
    reject_reason: Optional[str] = None
    relevance_score: float = 0.0
    state_match_score: float = 0.0
    freshness_score: float = 0.0
    trust_score: float = 0.0
    risk_score: float = 0.0
    final_score: float = 0.0
    created_at: datetime = Field(default_factory=_now)


class MemoryLifecycleAuditRecord(_Base):
    audit_id: str = Field(default_factory=lambda: _new_id("maudit"))
    workspace_id: str
    memory_id: str
    from_status: MemoryStatus
    to_status: MemoryStatus
    reason: str
    actor: str
    scheduler_run_id: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_now)


class MemoryRetentionSignal(_Base):
    memory_id: str
    workspace_id: str
    retention_score: float
    reflection_priority: float
    reason: dict[str, Any] = Field(default_factory=dict)
    policy_version: str
    scored_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class MemoryVersionRecord(_Base):
    version_id: str = Field(default_factory=lambda: _new_id("mver"))
    memory_id: str
    workspace_id: str
    version_no: int
    snapshot: dict[str, Any] = Field(default_factory=dict)
    change_reason: str
    created_at: datetime = Field(default_factory=_now)


class MemoryConflictRecord(_Base):
    conflict_id: str = Field(default_factory=lambda: _new_id("mconf"))
    workspace_id: str
    subject_key: str
    memory_ids: list[str] = Field(default_factory=list)
    status: str = "open"
    detected_by: str = "conflict_scan_v1"
    explanation: str = ""
    created_at: datetime = Field(default_factory=_now)
    resolved_at: Optional[datetime] = None


class ApiKeyRecord(_Base):
    api_key_id: str = Field(default_factory=lambda: _new_id("apikey"))
    workspace_id: str
    principal_id: str
    key_prefix: str
    key_digest: str
    roles: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_now)
    last_used_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None


class MaintenanceRunRecord(_Base):
    scheduler_run_id: str = Field(default_factory=lambda: _new_id("msrun"))
    workspace_id: str
    requested_by: str = "system"
    reason: Optional[str] = None
    operations: list[MaintenanceOperation] = Field(default_factory=list)
    dry_run: bool = False
    status: SchedulerRunStatus = SchedulerRunStatus.pending
    summary: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class MaintenanceTaskAttemptRecord(_Base):
    attempt_id: str = Field(default_factory=lambda: _new_id("mstat"))
    scheduler_run_id: str
    workspace_id: str
    operation: MaintenanceOperation
    status: SchedulerTaskStatus = SchedulerTaskStatus.pending
    idempotency_key: Optional[str] = None
    attempt_no: int = 1
    result: dict[str, Any] = Field(default_factory=dict)
    error_summary: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class AdminActionAuditRecord(_Base):
    admin_action_id: str = Field(default_factory=lambda: _new_id("admact"))
    workspace_id: str
    principal_id: str
    action: str
    target_type: str
    target_id: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_now)


class QuotaLimitRecord(_Base):
    quota_limit_id: str = Field(default_factory=lambda: _new_id("qlim"))
    workspace_id: str
    principal_id: Optional[str] = None
    unit: QuotaUnitName
    limit: int
    window_seconds: int
    created_by: str
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class StartMaintenanceRunRequest(_Base):
    workspace_id: str
    operations: Optional[list[MaintenanceOperation]] = None
    dry_run: bool = False
    reason: Optional[str] = None
    enqueue: bool = False


class CreateApiKeyRequest(_Base):
    workspace_id: str
    principal_id: str
    roles: list[WorkspacePermission]


class PublicApiKey(_Base):
    api_key_id: str
    workspace_id: str
    principal_id: str
    key_prefix: str
    roles: list[str] = Field(default_factory=list)
    created_at: datetime
    last_used_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None


class CreatedApiKeyResponse(_Base):
    api_key: PublicApiKey
    raw_api_key: str


class UpsertQuotaLimitRequest(_Base):
    workspace_id: str
    principal_id: Optional[str] = None
    unit: QuotaUnitName
    limit: int
    window_seconds: int


class AdminMemoryStatusRequest(_Base):
    to_status: MemoryStatus
    reason: str


class ResolveMemoryConflictRequest(_Base):
    action: Literal["mark_false_positive", "choose_winner", "apply_suggested"]
    winner_memory_id: Optional[str] = None
    reason: str


class Principal(_Base):
    principal_id: str
    kind: Literal["anonymous", "legacy_api_key", "api_key"]
    workspace_ids: list[str] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)
    api_key_id: Optional[str] = None


class ProfileEvent(_Base):
    profile_id: str = Field(default_factory=lambda: _new_id("prof"))
    run_id: Optional[str] = None
    step_id: Optional[str] = None
    access_id: Optional[str] = None
    phase: ProfilePhase
    operation: Optional[str] = None
    latency_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    llm_calls: int = 0
    db_calls: int = 0
    candidate_count: int = 0
    accepted_count: int = 0
    rejected_count: int = 0
    error_code: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_now)


class BenchmarkCaseRecord(_Base):
    case_id: str
    name: str
    description: Optional[str] = None
    config: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_now)


class BenchmarkResultRecord(_Base):
    result_id: str = Field(default_factory=lambda: _new_id("bench"))
    case_id: str
    strategy: str
    metrics: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_now)


class EvalCaseRecord(_Base):
    eval_case_id: str
    name: str
    description: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    config: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_now)


class EvalRunRecord(_Base):
    eval_run_id: str = Field(default_factory=lambda: _new_id("evalrun"))
    name: Optional[str] = None
    workspace_id: Optional[str] = None
    status: str = "completed"
    config: dict[str, Any] = Field(default_factory=dict)
    started_at: datetime = Field(default_factory=_now)
    finished_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=_now)


class EvalResultRecord(_Base):
    eval_result_id: str = Field(default_factory=lambda: _new_id("evalres"))
    eval_run_id: str
    eval_case_id: str
    run_id: Optional[str] = None
    access_id: Optional[str] = None
    strategy: RetrievalStrategy | str | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    passed: bool = True
    created_at: datetime = Field(default_factory=_now)


class ContextCompactionLog(_Base):
    compaction_id: str = Field(default_factory=lambda: _new_id("cmp"))
    access_id: str
    run_id: Optional[str] = None
    step_id: Optional[str] = None
    workspace_id: str
    kind: CompactionKind
    provider: CompactionProvider
    pre_tokens: int = 0
    post_tokens: int = 0
    dropped_block_count: int = 0
    compression_ratio: float = 1.0
    summary_text: Optional[str] = None
    retained_facts: list["RetainedFact"] = Field(default_factory=list)
    retained_negative_evidence: list["RetainedNegativeEvidence"] = Field(default_factory=list)
    source_memory_ids: list[str] = Field(default_factory=list)
    source_event_ids: list[str] = Field(default_factory=list)
    source_state_node_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_now)


@dataclass(frozen=True, slots=True)
class PendingCompactionLog:
    kind: CompactionKind
    provider: CompactionProvider
    pre_tokens: int
    post_tokens: int
    dropped_block_count: int
    compression_ratio: float
    summary_text: str | None
    retained_facts: list["RetainedFact"]
    retained_negative_evidence: list["RetainedNegativeEvidence"]
    source_memory_ids: list[str]
    source_event_ids: list[str]
    source_state_node_ids: list[str]
    warnings: list[str]

    def materialize(
        self,
        *,
        access_id: str,
        run_id: str | None,
        step_id: str | None,
        workspace_id: str,
    ) -> ContextCompactionLog:
        return ContextCompactionLog(
            access_id=access_id,
            run_id=run_id,
            step_id=step_id,
            workspace_id=workspace_id,
            kind=self.kind,
            provider=self.provider,
            pre_tokens=self.pre_tokens,
            post_tokens=self.post_tokens,
            dropped_block_count=self.dropped_block_count,
            compression_ratio=self.compression_ratio,
            summary_text=self.summary_text,
            retained_facts=list(self.retained_facts),
            retained_negative_evidence=list(self.retained_negative_evidence),
            source_memory_ids=list(self.source_memory_ids),
            source_event_ids=list(self.source_event_ids),
            source_state_node_ids=list(self.source_state_node_ids),
            warnings=list(self.warnings),
        )


# --------------------------------------------------------------------------- #
# Context blocks (retrieve_context output)
# --------------------------------------------------------------------------- #
class Provenance(_Base):
    run_id: Optional[str] = None
    step_id: Optional[str] = None
    event_id: Optional[str] = None
    state_node_id: Optional[str] = None


class ContextBlock(_Base):
    type: str
    content: str
    source: Optional[str] = None
    memory_id: Optional[str] = None
    reason: Optional[str] = None
    provenance: Optional[Provenance] = None
    tokens: int = 0


class RetainedFact(_Base):
    """A structured key=value fact retained during context compaction."""

    key: str
    value: str
    source_memory_id: Optional[str] = None
    provenance: Optional[Provenance] = None


class NegativeEvidence(_Base):
    """Warning-only evidence derived from failed/rolled-back memories.

    This DTO deliberately carries only safe rendered text for the packer. For
    unsafe failed attempts, ``safe_text`` is a fixed sanitized template and no
    raw memory content is exposed downstream.
    """

    source_memory_id: Optional[str] = None
    source_state_node_id: Optional[str] = None
    memory_type: Optional[MemoryType] = None
    branch_status: BranchStatus
    mode: Literal["raw_failed_attempt", "sanitized_risk_notice", "outdated_warning"]
    risk_kind: Optional[Literal["secret", "destructive", "tool_sensitive", "unknown"]] = None
    reason: str
    safe_text: str
    provenance: Optional[Provenance] = None


class RetainedNegativeEvidence(_Base):
    """Safe metadata retained when negative evidence is dropped by compaction.

    This is deliberately separate from positive ``RetainedFact`` and carries
    only the already-sanitized negative-evidence text, never raw memory content.
    """

    source_memory_id: Optional[str] = None
    source_state_node_id: Optional[str] = None
    mode: Literal["raw_failed_attempt", "sanitized_risk_notice", "outdated_warning"]
    risk_kind: Optional[str] = None
    reason: str
    safe_text: str
    provenance: Optional[Provenance] = None
    created_from_block_type: Literal["avoided_attempts"] = "avoided_attempts"


class GateDecisionView(_Base):
    """Flattened gate decision for access inspection output."""

    memory_id: str
    content: str
    layer: GateLayer
    decision: GateDecisionType
    reject_reason: Optional[str] = None
    relevance_score: float = 0.0
    state_match_score: float = 0.0
    freshness_score: float = 0.0
    trust_score: float = 0.0
    risk_score: float = 0.0
    final_score: float = 0.0
    branch_status: Optional[BranchStatus] = None


class MemoryContext(_Base):
    access_id: str
    query: Optional[str] = None
    context_blocks: list[ContextBlock] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    profile: dict[str, Any] = Field(default_factory=dict)


class AccessInspection(_Base):
    """GET /v1/access/{access_id} payload."""

    access_id: str
    query: Optional[str] = None
    task_intent: Optional[str] = None
    retrieval_strategy: RetrievalStrategy
    candidates: list[GateDecisionView] = Field(default_factory=list)
    gate_decisions: list[GateDecisionView] = Field(default_factory=list)
    context_blocks: list[ContextBlock] = Field(default_factory=list)
    profile: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    policy_version: Optional[str] = None
    policy_hash: Optional[str] = None
    policy_snapshot: dict[str, Any] = Field(default_factory=dict)


class ReplayCandidateView(_Base):
    memory_id: str
    content: str = ""
    memory_type: Optional[MemoryType] = None
    key: Optional[str] = None
    value: Optional[str] = None
    status: Optional[MemoryStatus] = None
    branch_status: Optional[BranchStatus] = None
    sensitivity: Optional[Sensitivity] = None
    risk_flags: RiskFlags = Field(default_factory=RiskFlags)
    lexical_score: float = 0.0
    vector_score: float = 0.0
    relevance_score: float = 0.0
    state_match_score: float = 0.0


class ReplayGateDecisionView(_Base):
    memory_id: str
    layer: GateLayer
    decision: GateDecisionType
    reject_reason: Optional[str] = None
    relevance_score: float = 0.0
    state_match_score: float = 0.0
    freshness_score: float = 0.0
    trust_score: float = 0.0
    risk_score: float = 0.0
    final_score: float = 0.0


class ReplayDiffItem(_Base):
    kind: str
    memory_id: Optional[str] = None
    field: Optional[str] = None
    original: Any = None
    replayed: Any = None
    severity: str = "info"


class ReplayRetrievalResult(_Base):
    access_id: str
    run_id: Optional[str] = None
    step_id: Optional[str] = None
    workspace_id: str
    query: Optional[str] = None
    strategy: RetrievalStrategy
    token_budget: int
    top_k: int
    original_candidates: list[ReplayCandidateView] = Field(default_factory=list)
    original_gate_decisions: list[ReplayGateDecisionView] = Field(default_factory=list)
    original_context_blocks_reconstructed: list[ContextBlock] = Field(default_factory=list)
    replayed_candidates: list[ReplayCandidateView] = Field(default_factory=list)
    replayed_gate_decisions: list[ReplayGateDecisionView] = Field(default_factory=list)
    replayed_context_blocks: list[ContextBlock] = Field(default_factory=list)
    compaction_logs: list[ContextCompactionLog] = Field(default_factory=list)
    diffs: list[ReplayDiffItem] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class RunReplayResult(_Base):
    run_id: str
    access_count: int = 0
    replayed: list[ReplayRetrievalResult] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)


class ObservabilitySummary(_Base):
    workspace_id: Optional[str] = None
    run_id: Optional[str] = None
    access_count: int = 0
    candidate_count: int = 0
    accepted_count: int = 0
    rejected_count: int = 0
    failed_branch_rejected: int = 0
    failed_branch_injected: int = 0
    degraded_negative_evidence_count: int = 0
    sanitized_failure_notice_count: int = 0
    negative_evidence_block_count: int = 0
    retained_negative_evidence_count: int = 0
    sanitized_retained_negative_evidence_count: int = 0
    stale_rejected: int = 0
    stale_injected: int = 0
    tool_sensitive_blocked: int = 0
    destructive_command_blocked: int = 0
    risk_blocked: int = 0
    workspace_mismatch_rejected: int = 0
    workspace_leakage: int = 0
    superseded_injected: int = 0
    avg_latency_ms: float = 0.0
    avg_actual_tokens: float = 0.0
    compaction_trigger_rate: float = 0.0
    avg_compression_ratio: float = 0.0
    total_dropped_blocks: int = 0
    history_summary_count: int = 0
    by_strategy: dict[str, dict[str, float]] = Field(default_factory=dict)


class ObservabilityReportRequest(_Base):
    workspace_id: Optional[str] = None
    run_id: Optional[str] = None
    output_dir: str = "reports"
    include_replay: bool = True


class ObservabilityReportResult(_Base):
    json_path: str
    markdown_path: str
    html_path: str
    summary: ObservabilitySummary


class TelemetryExportRequest(_Base):
    include_steps: bool = True
    include_events: bool = True


class TelemetryExportResponse(_Base):
    exported_span_count: int = 0
    dropped_span_count: int = 0
    warnings: list[str] = Field(default_factory=list)


class DashboardTables(_Base):
    """Minimal P1 table-style dashboard payload."""

    runs: list[AgentRun] = Field(default_factory=list)
    accesses: list[MemoryAccessLog] = Field(default_factory=list)
    profile_events: list[ProfileEvent] = Field(default_factory=list)
    benchmark_cases: list[BenchmarkCaseRecord] = Field(default_factory=list)
    benchmark_results: list[BenchmarkResultRecord] = Field(default_factory=list)
    eval_cases: list[EvalCaseRecord] = Field(default_factory=list)
    eval_runs: list[EvalRunRecord] = Field(default_factory=list)
    eval_results: list[EvalResultRecord] = Field(default_factory=list)
    memory_versions: list[MemoryVersionRecord] = Field(default_factory=list)
    memory_conflicts: list[MemoryConflictRecord] = Field(default_factory=list)
    maintenance_runs: list[MaintenanceRunRecord] = Field(default_factory=list)
    maintenance_task_attempts: list[MaintenanceTaskAttemptRecord] = Field(default_factory=list)
    admin_action_audits: list[AdminActionAuditRecord] = Field(default_factory=list)
    quota_limits: list[QuotaLimitRecord] = Field(default_factory=list)
    observability_summary: Optional[ObservabilitySummary] = None
    benchmark_summary: dict[str, dict[str, float]] = Field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Request / result models
# --------------------------------------------------------------------------- #
class StartRunRequest(_Base):
    session_id: str
    task: Optional[str] = None
    workspace_id: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class StartStepRequest(_Base):
    run_id: str
    intent: Optional[str] = None
    parent_step_id: Optional[str] = None
    recovery_from_step_id: Optional[str] = None
    goal: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class WriteEventRequest(_Base):
    run_id: str
    step_id: str
    role: EventRole = EventRole.runtime
    event_type: EventType = EventType.message
    content: Optional[str] = None
    tool_name: Optional[str] = None
    status: Optional[str] = None
    token_input: int = 0
    token_output: int = 0
    latency_ms: int = 0
    # Per-request override of the runtime extraction mode. ``sync`` forces inline
    # extraction even when the runtime defaults to buffered (architecture.md
    # §12.1 sync_flush: explicit correction / key preference). ``None`` uses the
    # runtime default.
    extraction_mode: Optional[ExtractionMode] = None
    event_source: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class WriteEventResult(_Base):
    event: AgentEvent
    created_memory_ids: list[str] = Field(default_factory=list)
    # True when the event was appended to the candidate buffer instead of being
    # extracted inline; extraction is deferred to a flush.
    buffered: bool = False
    # True when extraction was queued for an async worker instead of running
    # inline or entering the local lazy buffer.
    queued: bool = False
    task_id: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)


class FlushRequest(_Base):
    session_id: str


class FlushResult(_Base):
    session_id: str
    processed_event_count: int = 0
    created_memory_ids: list[str] = Field(default_factory=list)


class FinishStepRequest(_Base):
    run_id: str
    step_id: str
    status: StepStatus = StepStatus.completed
    error_message: Optional[str] = None
    summary: Optional[str] = None


class FinishStepResult(_Base):
    step: AgentStep
    state_node: StateNode
    created_memory_ids: list[str] = Field(default_factory=list)


class RollbackRequest(_Base):
    run_id: str
    step_id: str
    reason: Optional[str] = None


class RollbackResult(_Base):
    rolled_back_step_ids: list[str] = Field(default_factory=list)
    rolled_back_node_ids: list[str] = Field(default_factory=list)
    affected_memory_ids: list[str] = Field(default_factory=list)


class CompleteRunRequest(_Base):
    run_id: Optional[str] = None
    status: RunStatus = RunStatus.completed
    summary: Optional[str] = None


class CompleteRunResult(_Base):
    run: AgentRun
    summary_memory_id: Optional[str] = None
    procedural_memory_id: Optional[str] = None
    created_memory_ids: list[str] = Field(default_factory=list)


class RetrievalRequest(_Base):
    run_id: str
    step_id: Optional[str] = None
    query: str
    task_intent: Optional[str] = None
    workspace_id: Optional[str] = None
    strategy: RetrievalStrategy = RetrievalStrategy.variant_2
    token_budget: Optional[int] = None
    top_k: int = 10
