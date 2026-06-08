"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-08

Creates all MVP P0 tables. Attempts to enable the pgvector extension but does
not fail if it is unavailable (P0 retrieval is lexical; embedding_vector is a
float[] column).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _ts(name: str, nullable: bool = False):
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def upgrade() -> None:
    op.execute("DO $$ BEGIN CREATE EXTENSION IF NOT EXISTS vector; EXCEPTION WHEN OTHERS THEN NULL; END $$;")

    op.create_table(
        "workspaces",
        sa.Column("workspace_id", sa.String, primary_key=True),
        sa.Column("name", sa.String, nullable=True),
        _ts("created_at"),
    )
    op.create_table(
        "sessions",
        sa.Column("session_id", sa.String, primary_key=True),
        sa.Column("workspace_id", sa.String, index=True),
        _ts("created_at"),
    )
    op.create_table(
        "agent_runs",
        sa.Column("run_id", sa.String, primary_key=True),
        sa.Column("workspace_id", sa.String, index=True),
        sa.Column("session_id", sa.String, index=True),
        sa.Column("task", sa.Text, nullable=True),
        sa.Column("status", sa.String),
        _ts("started_at", nullable=True),
        _ts("finished_at", nullable=True),
        sa.Column("run_metadata", JSONB),
        _ts("created_at"),
        _ts("updated_at"),
    )
    op.create_table(
        "agent_steps",
        sa.Column("step_id", sa.String, primary_key=True),
        sa.Column("workspace_id", sa.String, index=True),
        sa.Column("run_id", sa.String, sa.ForeignKey("agent_runs.run_id"), index=True),
        sa.Column("parent_step_id", sa.String, nullable=True),
        sa.Column("recovery_from_step_id", sa.String, nullable=True),
        sa.Column("state_node_id", sa.String, nullable=True),
        sa.Column("intent", sa.String, nullable=True),
        sa.Column("status", sa.String),
        _ts("started_at", nullable=True),
        _ts("finished_at", nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("step_metadata", JSONB),
        _ts("created_at"),
        _ts("updated_at"),
    )
    op.create_table(
        "agent_events",
        sa.Column("event_id", sa.String, primary_key=True),
        sa.Column("workspace_id", sa.String, index=True),
        sa.Column("session_id", sa.String, nullable=True),
        sa.Column("run_id", sa.String, sa.ForeignKey("agent_runs.run_id"), index=True),
        sa.Column("step_id", sa.String, index=True),
        sa.Column("state_node_id", sa.String, nullable=True),
        sa.Column("sequence_no", sa.BigInteger, index=True),
        sa.Column("event_source", sa.String, nullable=True),
        sa.Column("visibility", sa.String),
        sa.Column("role", sa.String),
        sa.Column("event_type", sa.String),
        sa.Column("content", sa.Text, nullable=True),
        sa.Column("content_digest", sa.String, nullable=True),
        sa.Column("raw_payload_ref", sa.String, nullable=True),
        sa.Column("redaction_status", sa.String),
        sa.Column("causality_id", sa.String, nullable=True),
        sa.Column("tool_name", sa.String, nullable=True),
        sa.Column("tool_args_digest", sa.String, nullable=True),
        sa.Column("status", sa.String, nullable=True),
        sa.Column("token_input", sa.Integer),
        sa.Column("token_output", sa.Integer),
        sa.Column("latency_ms", sa.Integer),
        sa.Column("event_metadata", JSONB),
        _ts("created_at"),
        sa.UniqueConstraint("run_id", "sequence_no", name="uq_event_run_seq"),
    )
    op.create_table(
        "state_nodes",
        sa.Column("node_id", sa.String, primary_key=True),
        sa.Column("workspace_id", sa.String, index=True),
        sa.Column("run_id", sa.String, sa.ForeignKey("agent_runs.run_id"), index=True),
        sa.Column("parent_id", sa.String, nullable=True),
        sa.Column("step_id", sa.String, nullable=True),
        sa.Column("node_type", sa.String),
        sa.Column("status", sa.String),
        sa.Column("goal", sa.Text, nullable=True),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column("raw_event_ids", JSONB),
        sa.Column("memory_refs", JSONB),
        sa.Column("branch_reason", JSONB),
        sa.Column("failure_reason", sa.Text, nullable=True),
        sa.Column("depth", sa.Integer),
        sa.Column("path", sa.Text),
        _ts("created_at"),
        _ts("updated_at"),
    )
    op.create_table(
        "memory_items",
        sa.Column("memory_id", sa.String, primary_key=True),
        sa.Column("workspace_id", sa.String, index=True),
        sa.Column("session_id", sa.String, nullable=True),
        sa.Column("run_id", sa.String, nullable=True, index=True),
        sa.Column("memory_type", sa.String, index=True),
        sa.Column("key", sa.String, nullable=True, index=True),
        sa.Column("value", sa.Text, nullable=True),
        sa.Column("scope", sa.String),
        sa.Column("content", sa.Text),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column("source_event_id", sa.String, nullable=True),
        sa.Column("source_event_ids", JSONB, nullable=True),
        sa.Column("source_run_id", sa.String, nullable=True),
        sa.Column("source_state_node_id", sa.String, nullable=True),
        sa.Column("branch_status", sa.String, index=True),
        sa.Column("confidence", sa.Float),
        sa.Column("importance", sa.Float),
        sa.Column("value_score", sa.Float),
        sa.Column("freshness_score", sa.Float),
        sa.Column("trust_score", sa.Float),
        sa.Column("risk_score", sa.Float),
        sa.Column("embedding_vector", ARRAY(sa.Float), nullable=True),
        sa.Column("risk_flags", JSONB),
        sa.Column("status", sa.String, index=True),
        sa.Column("sensitivity", sa.String),
        sa.Column("embedding_status", sa.String),
        _ts("expires_at", nullable=True),
        _ts("last_accessed_at", nullable=True),
        sa.Column("access_count", sa.Integer),
        _ts("created_at"),
        _ts("updated_at"),
    )
    op.create_table(
        "memory_access_logs",
        sa.Column("access_id", sa.String, primary_key=True),
        sa.Column("workspace_id", sa.String, index=True),
        sa.Column("run_id", sa.String, nullable=True),
        sa.Column("step_id", sa.String, nullable=True),
        sa.Column("query", sa.Text, nullable=True),
        sa.Column("task_intent", sa.String, nullable=True),
        sa.Column("retrieval_strategy", sa.String),
        sa.Column("candidate_count", sa.Integer),
        sa.Column("accepted_count", sa.Integer),
        sa.Column("rejected_count", sa.Integer),
        sa.Column("token_budget", sa.Integer),
        sa.Column("actual_tokens", sa.Integer),
        sa.Column("latency_ms", sa.Integer),
        _ts("created_at"),
    )
    op.create_table(
        "memory_gate_logs",
        sa.Column("gate_id", sa.String, primary_key=True),
        sa.Column("access_id", sa.String, index=True),
        sa.Column("memory_id", sa.String, index=True),
        sa.Column("layer", sa.String),
        sa.Column("decision", sa.String),
        sa.Column("reject_reason", sa.String, nullable=True),
        sa.Column("relevance_score", sa.Float),
        sa.Column("state_match_score", sa.Float),
        sa.Column("freshness_score", sa.Float),
        sa.Column("trust_score", sa.Float),
        sa.Column("risk_score", sa.Float),
        sa.Column("final_score", sa.Float),
        _ts("created_at"),
    )
    op.create_table(
        "profile_events",
        sa.Column("profile_id", sa.String, primary_key=True),
        sa.Column("run_id", sa.String, index=True, nullable=True),
        sa.Column("step_id", sa.String, nullable=True),
        sa.Column("access_id", sa.String, index=True, nullable=True),
        sa.Column("phase", sa.String),
        sa.Column("operation", sa.String, nullable=True),
        sa.Column("latency_ms", sa.Integer),
        sa.Column("input_tokens", sa.Integer),
        sa.Column("output_tokens", sa.Integer),
        sa.Column("llm_calls", sa.Integer),
        sa.Column("db_calls", sa.Integer),
        sa.Column("candidate_count", sa.Integer),
        sa.Column("accepted_count", sa.Integer),
        sa.Column("rejected_count", sa.Integer),
        sa.Column("error_code", sa.String, nullable=True),
        sa.Column("profile_metadata", JSONB),
        _ts("created_at"),
    )
    op.create_table(
        "benchmark_cases",
        sa.Column("case_id", sa.String, primary_key=True),
        sa.Column("name", sa.String),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("config", JSONB),
        _ts("created_at"),
    )
    op.create_table(
        "benchmark_results",
        sa.Column("result_id", sa.String, primary_key=True),
        sa.Column("case_id", sa.String, index=True),
        sa.Column("strategy", sa.String),
        sa.Column("metrics", JSONB),
        _ts("created_at"),
    )


def downgrade() -> None:
    for tbl in [
        "benchmark_results",
        "benchmark_cases",
        "profile_events",
        "memory_gate_logs",
        "memory_access_logs",
        "memory_items",
        "state_nodes",
        "agent_events",
        "agent_steps",
        "agent_runs",
        "sessions",
        "workspaces",
    ]:
        op.drop_table(tbl)
