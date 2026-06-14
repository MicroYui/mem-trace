"""SQLAlchemy 2.0 ORM models for MemTrace P0 (PostgreSQL + pgvector).

PostgreSQL is the source of truth. `state_nodes.raw_event_ids` / `memory_refs`
are denormalized caches; events bind via `agent_events.state_node_id` and
memories via `memory_items.source_state_node_id`.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from pgvector.sqlalchemy import Vector

EMBED_DIM = 256


class Base(DeclarativeBase):
    pass


class WorkspaceORM(Base):
    __tablename__ = "workspaces"
    workspace_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SessionORM(Base):
    __tablename__ = "sessions"
    session_id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RunORM(Base):
    __tablename__ = "agent_runs"
    run_id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String, index=True)
    session_id: Mapped[str] = mapped_column(String, index=True)
    task: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    run_metadata: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class StepORM(Base):
    __tablename__ = "agent_steps"
    step_id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String, index=True)
    run_id: Mapped[str] = mapped_column(String, ForeignKey("agent_runs.run_id"), index=True)
    parent_step_id: Mapped[str | None] = mapped_column(String, nullable=True)
    recovery_from_step_id: Mapped[str | None] = mapped_column(String, nullable=True)
    state_node_id: Mapped[str | None] = mapped_column(String, nullable=True)
    intent: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    step_metadata: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class EventORM(Base):
    __tablename__ = "agent_events"
    __table_args__ = (UniqueConstraint("run_id", "sequence_no", name="uq_event_run_seq"),)
    event_id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String, index=True)
    session_id: Mapped[str | None] = mapped_column(String, nullable=True)
    run_id: Mapped[str] = mapped_column(String, ForeignKey("agent_runs.run_id"), index=True)
    step_id: Mapped[str] = mapped_column(String, index=True)
    state_node_id: Mapped[str | None] = mapped_column(String, nullable=True)
    sequence_no: Mapped[int] = mapped_column(BigInteger, index=True)
    event_source: Mapped[str | None] = mapped_column(String, nullable=True)
    visibility: Mapped[str] = mapped_column(String, default="visible")
    role: Mapped[str] = mapped_column(String)
    event_type: Mapped[str] = mapped_column(String)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_digest: Mapped[str | None] = mapped_column(String, nullable=True)
    raw_payload_ref: Mapped[str | None] = mapped_column(String, nullable=True)
    redaction_status: Mapped[str] = mapped_column(String, default="none")
    causality_id: Mapped[str | None] = mapped_column(String, nullable=True)
    tool_name: Mapped[str | None] = mapped_column(String, nullable=True)
    tool_args_digest: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str | None] = mapped_column(String, nullable=True)
    token_input: Mapped[int] = mapped_column(Integer, default=0)
    token_output: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    event_metadata: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class StateNodeORM(Base):
    __tablename__ = "state_nodes"
    node_id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String, index=True)
    run_id: Mapped[str] = mapped_column(String, ForeignKey("agent_runs.run_id"), index=True)
    parent_id: Mapped[str | None] = mapped_column(String, nullable=True)
    step_id: Mapped[str | None] = mapped_column(String, nullable=True)
    node_type: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    goal: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_event_ids: Mapped[list] = mapped_column(JSONB, default=list)
    memory_refs: Mapped[list] = mapped_column(JSONB, default=list)
    branch_reason: Mapped[dict] = mapped_column(JSONB, default=dict)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    depth: Mapped[int] = mapped_column(Integer, default=0)
    path: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MemoryORM(Base):
    __tablename__ = "memory_items"
    memory_id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String, index=True)
    session_id: Mapped[str | None] = mapped_column(String, nullable=True)
    run_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    memory_type: Mapped[str] = mapped_column(String, index=True)
    key: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    scope: Mapped[str] = mapped_column(String, default="workspace")
    content: Mapped[str] = mapped_column(Text, default="")
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_event_id: Mapped[str | None] = mapped_column(String, nullable=True)
    source_event_ids: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    source_run_id: Mapped[str | None] = mapped_column(String, nullable=True)
    source_state_node_id: Mapped[str | None] = mapped_column(String, nullable=True)
    branch_status: Mapped[str] = mapped_column(String, index=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    importance: Mapped[float] = mapped_column(Float, default=0.5)
    value_score: Mapped[float] = mapped_column(Float, default=0.5)
    freshness_score: Mapped[float] = mapped_column(Float, default=1.0)
    trust_score: Mapped[float] = mapped_column(Float, default=0.5)
    risk_score: Mapped[float] = mapped_column(Float, default=0.0)
    # Semantic retrieval vector (pgvector). Cosine distance is used for KNN;
    # embeddings are deterministic hashed bag-of-words so results are
    # reproducible without an external embedding provider.
    embedding_vector: Mapped[list | None] = mapped_column(Vector(EMBED_DIM), nullable=True)
    risk_flags: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String, index=True)
    lifecycle_metadata: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=sa.text("'{}'::jsonb"))
    superseded_by: Mapped[str | None] = mapped_column(String, nullable=True)
    sensitivity: Mapped[str] = mapped_column(String, default="internal")
    embedding_status: Mapped[str] = mapped_column(String, default="pending")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    access_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AccessLogORM(Base):
    __tablename__ = "memory_access_logs"
    access_id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String, index=True)
    run_id: Mapped[str | None] = mapped_column(String, nullable=True)
    step_id: Mapped[str | None] = mapped_column(String, nullable=True)
    query: Mapped[str | None] = mapped_column(Text, nullable=True)
    task_intent: Mapped[str | None] = mapped_column(String, nullable=True)
    retrieval_strategy: Mapped[str] = mapped_column(String)
    candidate_count: Mapped[int] = mapped_column(Integer, default=0)
    accepted_count: Mapped[int] = mapped_column(Integer, default=0)
    rejected_count: Mapped[int] = mapped_column(Integer, default=0)
    token_budget: Mapped[int] = mapped_column(Integer, default=0)
    actual_tokens: Mapped[int] = mapped_column(Integer, default=0)
    top_k: Mapped[int] = mapped_column(Integer, default=10, server_default="10")
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    policy_version: Mapped[str | None] = mapped_column(String, nullable=True)
    policy_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    policy_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MemoryLifecycleAuditORM(Base):
    __tablename__ = "memory_lifecycle_audits"
    __table_args__ = (
        Index("ix_memory_lifecycle_audits_workspace_memory_created", "workspace_id", "memory_id", "created_at"),
    )
    audit_id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String, index=True)
    memory_id: Mapped[str] = mapped_column(String, index=True)
    from_status: Mapped[str] = mapped_column(String)
    to_status: Mapped[str] = mapped_column(String)
    reason: Mapped[str] = mapped_column(String)
    actor: Mapped[str] = mapped_column(String)
    scheduler_run_id: Mapped[str | None] = mapped_column(String, nullable=True)
    audit_metadata: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=sa.text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MemoryRetentionSignalORM(Base):
    __tablename__ = "memory_retention_signals"
    __table_args__ = (
        Index("ix_memory_retention_signals_workspace_reflection", "workspace_id", "reflection_priority"),
    )
    memory_id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String, index=True)
    retention_score: Mapped[float] = mapped_column(Float, default=0.0)
    reflection_priority: Mapped[float] = mapped_column(Float, default=0.0)
    reason: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=sa.text("'{}'::jsonb"))
    policy_version: Mapped[str] = mapped_column(String)
    scored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MemoryVersionORM(Base):
    __tablename__ = "memory_versions"
    __table_args__ = (
        UniqueConstraint("memory_id", "version_no", name="uq_memory_versions_memory_version_no"),
        Index("ix_memory_versions_workspace_memory_created", "workspace_id", "memory_id", "created_at"),
    )
    version_id: Mapped[str] = mapped_column(String, primary_key=True)
    memory_id: Mapped[str] = mapped_column(String, index=True)
    workspace_id: Mapped[str] = mapped_column(String, index=True)
    version_no: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=sa.text("'{}'::jsonb"))
    change_reason: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MemoryConflictORM(Base):
    __tablename__ = "memory_conflicts"
    __table_args__ = (
        Index("ix_memory_conflicts_workspace_status_created", "workspace_id", "status", "created_at"),
    )
    conflict_id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String, index=True)
    subject_key: Mapped[str] = mapped_column(String, index=True)
    memory_ids: Mapped[list] = mapped_column(JSONB, default=list, server_default=sa.text("'[]'::jsonb"))
    status: Mapped[str] = mapped_column(String, index=True)
    detected_by: Mapped[str] = mapped_column(String)
    explanation: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ApiKeyORM(Base):
    __tablename__ = "api_keys"
    __table_args__ = (
        sa.UniqueConstraint("key_prefix", name="uq_api_keys_key_prefix"),
        Index("ix_api_keys_prefix_revoked", "key_prefix", "revoked_at"),
    )
    api_key_id: Mapped[str] = mapped_column(String, primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String, index=True)
    principal_id: Mapped[str] = mapped_column(String, index=True)
    key_prefix: Mapped[str] = mapped_column(String, index=True)
    key_digest: Mapped[str] = mapped_column(String)
    roles: Mapped[list] = mapped_column(JSONB, default=list, server_default=sa.text("'[]'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class GateLogORM(Base):
    __tablename__ = "memory_gate_logs"
    gate_id: Mapped[str] = mapped_column(String, primary_key=True)
    access_id: Mapped[str] = mapped_column(String, index=True)
    memory_id: Mapped[str] = mapped_column(String, index=True)
    layer: Mapped[str] = mapped_column(String)
    decision: Mapped[str] = mapped_column(String)
    reject_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    relevance_score: Mapped[float] = mapped_column(Float, default=0.0)
    state_match_score: Mapped[float] = mapped_column(Float, default=0.0)
    freshness_score: Mapped[float] = mapped_column(Float, default=0.0)
    trust_score: Mapped[float] = mapped_column(Float, default=0.0)
    risk_score: Mapped[float] = mapped_column(Float, default=0.0)
    final_score: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ProfileEventORM(Base):
    __tablename__ = "profile_events"
    profile_id: Mapped[str] = mapped_column(String, primary_key=True)
    run_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    step_id: Mapped[str | None] = mapped_column(String, nullable=True)
    access_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    phase: Mapped[str] = mapped_column(String)
    operation: Mapped[str | None] = mapped_column(String, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    llm_calls: Mapped[int] = mapped_column(Integer, default=0)
    db_calls: Mapped[int] = mapped_column(Integer, default=0)
    candidate_count: Mapped[int] = mapped_column(Integer, default=0)
    accepted_count: Mapped[int] = mapped_column(Integer, default=0)
    rejected_count: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String, nullable=True)
    profile_metadata: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ContextCompactionORM(Base):
    __tablename__ = "context_compaction_logs"
    __table_args__ = (
        Index("ix_context_compaction_logs_workspace_created", "workspace_id", "created_at"),
    )
    compaction_id: Mapped[str] = mapped_column(String, primary_key=True)
    access_id: Mapped[str] = mapped_column(String, index=True)
    run_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    step_id: Mapped[str | None] = mapped_column(String, nullable=True)
    workspace_id: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String)
    provider: Mapped[str] = mapped_column(String)
    pre_tokens: Mapped[int] = mapped_column(Integer, default=0)
    post_tokens: Mapped[int] = mapped_column(Integer, default=0)
    dropped_block_count: Mapped[int] = mapped_column(Integer, default=0)
    compression_ratio: Mapped[float] = mapped_column(Float, default=1.0)
    summary_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    retained_facts: Mapped[list] = mapped_column(JSONB, default=list)
    retained_negative_evidence: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=sa.text("'[]'::jsonb"),
    )
    source_memory_ids: Mapped[list] = mapped_column(JSONB, default=list)
    source_event_ids: Mapped[list] = mapped_column(JSONB, default=list)
    source_state_node_ids: Mapped[list] = mapped_column(JSONB, default=list)
    warnings: Mapped[list] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BenchmarkCaseORM(Base):
    __tablename__ = "benchmark_cases"
    case_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BenchmarkResultORM(Base):
    __tablename__ = "benchmark_results"
    result_id: Mapped[str] = mapped_column(String, primary_key=True)
    case_id: Mapped[str] = mapped_column(String, index=True)
    strategy: Mapped[str] = mapped_column(String)
    metrics: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class EvalCaseORM(Base):
    __tablename__ = "eval_cases"
    eval_case_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list] = mapped_column(JSONB, default=list)
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class EvalRunORM(Base):
    __tablename__ = "eval_runs"
    eval_run_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    workspace_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    status: Mapped[str] = mapped_column(String)
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class EvalResultORM(Base):
    __tablename__ = "eval_results"
    eval_result_id: Mapped[str] = mapped_column(String, primary_key=True)
    eval_run_id: Mapped[str] = mapped_column(String, index=True)
    eval_case_id: Mapped[str] = mapped_column(String, index=True)
    run_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    access_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    strategy: Mapped[str | None] = mapped_column(String, nullable=True)
    metrics: Mapped[dict] = mapped_column(JSONB, default=dict)
    passed: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


__all__ = [
    "Base",
    "EMBED_DIM",
    "WorkspaceORM",
    "SessionORM",
    "RunORM",
    "StepORM",
    "EventORM",
    "StateNodeORM",
    "MemoryORM",
    "MemoryLifecycleAuditORM",
    "MemoryRetentionSignalORM",
    "MemoryVersionORM",
    "MemoryConflictORM",
    "ApiKeyORM",
    "AccessLogORM",
    "GateLogORM",
    "ProfileEventORM",
    "ContextCompactionORM",
    "BenchmarkCaseORM",
    "BenchmarkResultORM",
    "EvalCaseORM",
    "EvalRunORM",
    "EvalResultORM",
]
