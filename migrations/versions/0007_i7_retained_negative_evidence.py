"""Add retained negative evidence to compaction logs.

Revision ID: 0007_i7_retained_negative_evidence
Revises: 0006_security_consistency_hardening
Create Date: 2026-06-13
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0007_i7_retained_negative_evidence"
down_revision = "0006_security_consistency_hardening"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "context_compaction_logs",
        sa.Column(
            "retained_negative_evidence",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("context_compaction_logs", "retained_negative_evidence")
