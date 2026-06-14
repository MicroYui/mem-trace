"""Add memory retention signals.

Revision ID: 0009_memory_retention_signals
Revises: 0008_phase4_lifecycle
Create Date: 2026-06-14
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0009_memory_retention_signals"
down_revision = "0008_phase4_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "memory_retention_signals",
        sa.Column("memory_id", sa.String(), nullable=False),
        sa.Column("workspace_id", sa.String(), nullable=False),
        sa.Column("retention_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("reflection_priority", sa.Float(), nullable=False, server_default="0"),
        sa.Column("reason", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("policy_version", sa.String(), nullable=False),
        sa.Column("scored_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("memory_id"),
    )
    op.create_index("ix_memory_retention_signals_workspace_id", "memory_retention_signals", ["workspace_id"])
    op.create_index(
        "ix_memory_retention_signals_workspace_reflection",
        "memory_retention_signals",
        ["workspace_id", "reflection_priority"],
    )


def downgrade() -> None:
    op.drop_index("ix_memory_retention_signals_workspace_reflection", table_name="memory_retention_signals")
    op.drop_index("ix_memory_retention_signals_workspace_id", table_name="memory_retention_signals")
    op.drop_table("memory_retention_signals")
