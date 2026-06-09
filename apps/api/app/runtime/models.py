"""Core domain models, enums, and request/result schemas for MemTrace P0.

These are storage-agnostic Pydantic v2 models. They are the single shared
vocabulary used by the runtime facade, repositories, retrieval/gate/profiler,
HTTP layer, and demo.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

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
    """Strategy modes used by demo/benchmark to prove the differentiation."""

    baseline_0 = "baseline_0"  # no memory
    baseline_1 = "baseline_1"  # vector/lexical memory only, ignores state + gate
    variant_1 = "variant_1"  # state-aware rerank, failed branch only downweighted
    variant_2 = "variant_2"  # state-aware + hard/risk admission gate


class ProfilePhase(str, Enum):
    retrieval = "retrieval"
    gate = "gate"
    context_packing = "context_packing"


class ExtractionMode(str, Enum):
    """Freshness-vs-latency policy for turning events into memory (architecture.md §12.1).

    - ``sync``: extract inline on write_event (default; deterministic demo/benchmark).
    - ``buffered``: append the event to a candidate buffer and defer extraction
      until an explicit or lazy flush (a natural window boundary such as
      retrieve_context / finish_step). Raw events are still persisted on write,
      so the buffer only holds derivation work, never unrecoverable facts.
    """

    sync = "sync"
    buffered = "buffered"


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
    actual_tokens: int = 0
    latency_ms: int = 0
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


class DashboardTables(_Base):
    """Minimal P1 table-style dashboard payload."""

    runs: list[AgentRun] = Field(default_factory=list)
    accesses: list[MemoryAccessLog] = Field(default_factory=list)
    profile_events: list[ProfileEvent] = Field(default_factory=list)
    benchmark_cases: list[BenchmarkCaseRecord] = Field(default_factory=list)
    benchmark_results: list[BenchmarkResultRecord] = Field(default_factory=list)
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
    metadata: dict[str, Any] = Field(default_factory=dict)


class WriteEventResult(_Base):
    event: AgentEvent
    created_memory_ids: list[str] = Field(default_factory=list)
    # True when the event was appended to the candidate buffer instead of being
    # extracted inline; extraction is deferred to a flush.
    buffered: bool = False


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
