"""Add memory lifecycle audit records.

Revision ID: 0008_phase4_lifecycle
Revises: 0007_i7_retained_negative_evidence
Create Date: 2026-06-14
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0008_phase4_lifecycle"
down_revision = "0007_i7_retained_negative_evidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "memory_items",
        sa.Column(
            "lifecycle_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_table(
        "memory_lifecycle_audits",
        sa.Column("audit_id", sa.String(), nullable=False),
        sa.Column("workspace_id", sa.String(), nullable=False),
        sa.Column("memory_id", sa.String(), nullable=False),
        sa.Column("from_status", sa.String(), nullable=False),
        sa.Column("to_status", sa.String(), nullable=False),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("actor", sa.String(), nullable=False),
        sa.Column("scheduler_run_id", sa.String(), nullable=True),
        sa.Column("audit_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("audit_id"),
    )
    op.create_index("ix_memory_lifecycle_audits_workspace_id", "memory_lifecycle_audits", ["workspace_id"])
    op.create_index("ix_memory_lifecycle_audits_memory_id", "memory_lifecycle_audits", ["memory_id"])
    op.create_index(
        "ix_memory_lifecycle_audits_workspace_memory_created",
        "memory_lifecycle_audits",
        ["workspace_id", "memory_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_memory_lifecycle_audits_workspace_memory_created", table_name="memory_lifecycle_audits")
    op.drop_index("ix_memory_lifecycle_audits_memory_id", table_name="memory_lifecycle_audits")
    op.drop_index("ix_memory_lifecycle_audits_workspace_id", table_name="memory_lifecycle_audits")
    op.drop_table("memory_lifecycle_audits")
    op.drop_column("memory_items", "lifecycle_metadata")
