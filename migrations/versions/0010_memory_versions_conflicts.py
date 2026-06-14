"""Add memory versions and conflicts.

Revision ID: 0010_memory_versions_conflicts
Revises: 0009_memory_retention_signals
Create Date: 2026-06-14
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0010_memory_versions_conflicts"
down_revision = "0009_memory_retention_signals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "memory_versions",
        sa.Column("version_id", sa.String(), nullable=False),
        sa.Column("memory_id", sa.String(), nullable=False),
        sa.Column("workspace_id", sa.String(), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("change_reason", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("version_id"),
        sa.UniqueConstraint("memory_id", "version_no", name="uq_memory_versions_memory_version_no"),
    )
    op.create_index("ix_memory_versions_memory_id", "memory_versions", ["memory_id"])
    op.create_index("ix_memory_versions_workspace_id", "memory_versions", ["workspace_id"])
    op.create_index(
        "ix_memory_versions_workspace_memory_created",
        "memory_versions",
        ["workspace_id", "memory_id", "created_at"],
    )

    op.create_table(
        "memory_conflicts",
        sa.Column("conflict_id", sa.String(), nullable=False),
        sa.Column("workspace_id", sa.String(), nullable=False),
        sa.Column("subject_key", sa.String(), nullable=False),
        sa.Column("memory_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("detected_by", sa.String(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("conflict_id"),
    )
    op.create_index("ix_memory_conflicts_workspace_id", "memory_conflicts", ["workspace_id"])
    op.create_index("ix_memory_conflicts_subject_key", "memory_conflicts", ["subject_key"])
    op.create_index("ix_memory_conflicts_status", "memory_conflicts", ["status"])
    op.create_index(
        "ix_memory_conflicts_workspace_status_created",
        "memory_conflicts",
        ["workspace_id", "status", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_memory_conflicts_workspace_status_created", table_name="memory_conflicts")
    op.drop_index("ix_memory_conflicts_status", table_name="memory_conflicts")
    op.drop_index("ix_memory_conflicts_subject_key", table_name="memory_conflicts")
    op.drop_index("ix_memory_conflicts_workspace_id", table_name="memory_conflicts")
    op.drop_table("memory_conflicts")
    op.drop_index("ix_memory_versions_workspace_memory_created", table_name="memory_versions")
    op.drop_index("ix_memory_versions_workspace_id", table_name="memory_versions")
    op.drop_index("ix_memory_versions_memory_id", table_name="memory_versions")
    op.drop_table("memory_versions")
