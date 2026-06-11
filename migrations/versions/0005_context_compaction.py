"""Add durable context compaction logs.

Revision ID: 0005_context_compaction
Revises: 0004_phase3a_observability
Create Date: 2026-06-11
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0005_context_compaction"
down_revision = "0004_phase3a_observability"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "context_compaction_logs",
        sa.Column("compaction_id", sa.String(), nullable=False),
        sa.Column("access_id", sa.String(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=True),
        sa.Column("step_id", sa.String(), nullable=True),
        sa.Column("workspace_id", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("pre_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("post_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("dropped_block_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("compression_ratio", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("summary_text", sa.Text(), nullable=True),
        sa.Column("retained_facts", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("source_memory_ids", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("source_event_ids", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("source_state_node_ids", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("warnings", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("compaction_id"),
    )
    op.create_index("ix_context_compaction_logs_access_id", "context_compaction_logs", ["access_id"])
    op.create_index("ix_context_compaction_logs_workspace_created", "context_compaction_logs", ["workspace_id", "created_at"])
    op.create_index("ix_context_compaction_logs_run_id", "context_compaction_logs", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_context_compaction_logs_workspace_created", table_name="context_compaction_logs")
    op.drop_index("ix_context_compaction_logs_run_id", table_name="context_compaction_logs")
    op.drop_index("ix_context_compaction_logs_access_id", table_name="context_compaction_logs")
    op.drop_table("context_compaction_logs")
