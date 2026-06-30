"""Workspace membership table (ROADMAP §3.4).

Revision ID: 0013_workspace_membership
Revises: 0012_maintenance_admin_governance
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0013_workspace_membership"
down_revision = "0012_maintenance_admin_governance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workspace_memberships",
        sa.Column("membership_id", sa.String(), nullable=False),
        sa.Column("workspace_id", sa.String(), nullable=False),
        sa.Column("principal_id", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("membership_id"),
    )
    op.create_index("ix_workspace_memberships_workspace_id", "workspace_memberships", ["workspace_id"])
    op.create_index("ix_workspace_memberships_principal_id", "workspace_memberships", ["principal_id"])
    op.create_index(
        "uq_workspace_memberships_workspace_principal",
        "workspace_memberships",
        ["workspace_id", "principal_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_workspace_memberships_workspace_principal", table_name="workspace_memberships")
    op.drop_index("ix_workspace_memberships_principal_id", table_name="workspace_memberships")
    op.drop_index("ix_workspace_memberships_workspace_id", table_name="workspace_memberships")
    op.drop_table("workspace_memberships")
