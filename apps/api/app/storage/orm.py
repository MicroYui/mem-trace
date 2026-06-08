"""SQLAlchemy 2.0 ORM models for MemTrace P0 (PostgreSQL + pgvector).

PostgreSQL is the source of truth. `state_nodes.raw_event_ids` / `memory_refs`
are denormalized caches; events bind via `agent_events.state_node_id` and
memories via `memory_items.source_state_node_id`.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    ARRAY,
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

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
    # P0 retrieval is lexical; embedding stored as float[] so the schema runs
    # without the pgvector extension. Swap to pgvector.Vector when available.
    embedding_vector: Mapped[list | None] = mapped_column(ARRAY(Float), nullable=True)
    risk_flags: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String, index=True)
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
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


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
    "AccessLogORM",
    "GateLogORM",
    "ProfileEventORM",
    "BenchmarkCaseORM",
    "BenchmarkResultORM",
]
