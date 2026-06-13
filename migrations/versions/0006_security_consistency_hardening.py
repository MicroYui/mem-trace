"""Record security and consistency hardening migration boundary.

Revision ID: 0006_security_consistency_hardening
Revises: 0005_context_compaction
Create Date: 2026-06-13
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0006_security_consistency_hardening"
down_revision = "0005_context_compaction"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # H5 sequence uniqueness is already enforced by 0001_initial as
    # uq_event_run_seq. Keep this revision as the hardening boundary without
    # adding a duplicate unique constraint under a second name.
    op.add_column("memory_access_logs", sa.Column("policy_version", sa.String(), nullable=True))
    op.add_column("memory_access_logs", sa.Column("policy_hash", sa.String(), nullable=True))
    op.add_column("memory_access_logs", sa.Column("policy_snapshot", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("memory_access_logs", "policy_snapshot")
    op.drop_column("memory_access_logs", "policy_hash")
    op.drop_column("memory_access_logs", "policy_version")
