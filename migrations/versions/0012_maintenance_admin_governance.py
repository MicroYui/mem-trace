"""Maintenance scheduler and admin governance records

Revision ID: 0012_maintenance_admin_governance
Revises: 0011_governance
Create Date: 2026-06-14
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0012_maintenance_admin_governance"
down_revision = "0011_governance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "maintenance_runs",
        sa.Column("scheduler_run_id", sa.String(), nullable=False),
        sa.Column("workspace_id", sa.String(), nullable=False),
        sa.Column("requested_by", sa.String(), nullable=False, server_default="system"),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("operations", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("dry_run", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("summary", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("warnings", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("scheduler_run_id"),
    )
    op.create_index("ix_maintenance_runs_workspace_id", "maintenance_runs", ["workspace_id"])
    op.create_index("ix_maintenance_runs_status", "maintenance_runs", ["status"])
    op.create_index("ix_maintenance_runs_workspace_created", "maintenance_runs", ["workspace_id", "created_at"])
    op.create_index(
        "ix_maintenance_runs_workspace_status_created",
        "maintenance_runs",
        ["workspace_id", "status", "created_at"],
    )

    op.create_table(
        "maintenance_task_attempts",
        sa.Column("attempt_id", sa.String(), nullable=False),
        sa.Column("scheduler_run_id", sa.String(), nullable=False),
        sa.Column("workspace_id", sa.String(), nullable=False),
        sa.Column("operation", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=True),
        sa.Column("attempt_no", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("result", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("attempt_id"),
        sa.UniqueConstraint("scheduler_run_id", "operation", name="uq_maintenance_task_attempts_run_operation"),
    )
    op.create_index("ix_maintenance_task_attempts_scheduler_run_id", "maintenance_task_attempts", ["scheduler_run_id"])
    op.create_index("ix_maintenance_task_attempts_workspace_id", "maintenance_task_attempts", ["workspace_id"])
    op.create_index("ix_maintenance_task_attempts_status", "maintenance_task_attempts", ["status"])
    op.create_index(
        "ix_maintenance_task_attempts_run_created",
        "maintenance_task_attempts",
        ["scheduler_run_id", "created_at"],
    )

    op.create_table(
        "admin_action_audits",
        sa.Column("admin_action_id", sa.String(), nullable=False),
        sa.Column("workspace_id", sa.String(), nullable=False),
        sa.Column("principal_id", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("target_type", sa.String(), nullable=False),
        sa.Column("target_id", sa.String(), nullable=True),
        sa.Column("audit_metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("admin_action_id"),
    )
    op.create_index("ix_admin_action_audits_workspace_id", "admin_action_audits", ["workspace_id"])
    op.create_index("ix_admin_action_audits_principal_id", "admin_action_audits", ["principal_id"])
    op.create_index(
        "ix_admin_action_audits_workspace_created",
        "admin_action_audits",
        ["workspace_id", "created_at"],
    )

    op.create_table(
        "quota_limits",
        sa.Column("quota_limit_id", sa.String(), nullable=False),
        sa.Column("workspace_id", sa.String(), nullable=False),
        sa.Column("principal_id", sa.String(), nullable=True),
        sa.Column("unit", sa.String(), nullable=False),
        sa.Column("limit", sa.Integer(), nullable=False),
        sa.Column("window_seconds", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("quota_limit_id"),
    )
    op.create_index("ix_quota_limits_workspace_id", "quota_limits", ["workspace_id"])
    op.create_index("ix_quota_limits_principal_id", "quota_limits", ["principal_id"])
    op.create_index("ix_quota_limits_workspace_unit", "quota_limits", ["workspace_id", "unit"])
    op.create_index(
        "uq_quota_limits_workspace_unit",
        "quota_limits",
        ["workspace_id", "unit"],
        unique=True,
        postgresql_where=sa.text("principal_id IS NULL"),
    )
    op.create_index(
        "uq_quota_limits_workspace_principal_unit",
        "quota_limits",
        ["workspace_id", "principal_id", "unit"],
        unique=True,
        postgresql_where=sa.text("principal_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_quota_limits_workspace_principal_unit", table_name="quota_limits")
    op.drop_index("uq_quota_limits_workspace_unit", table_name="quota_limits")
    op.drop_index("ix_quota_limits_workspace_unit", table_name="quota_limits")
    op.drop_index("ix_quota_limits_principal_id", table_name="quota_limits")
    op.drop_index("ix_quota_limits_workspace_id", table_name="quota_limits")
    op.drop_table("quota_limits")

    op.drop_index("ix_admin_action_audits_workspace_created", table_name="admin_action_audits")
    op.drop_index("ix_admin_action_audits_principal_id", table_name="admin_action_audits")
    op.drop_index("ix_admin_action_audits_workspace_id", table_name="admin_action_audits")
    op.drop_table("admin_action_audits")

    op.drop_index("ix_maintenance_task_attempts_run_created", table_name="maintenance_task_attempts")
    op.drop_index("ix_maintenance_task_attempts_status", table_name="maintenance_task_attempts")
    op.drop_index("ix_maintenance_task_attempts_workspace_id", table_name="maintenance_task_attempts")
    op.drop_index("ix_maintenance_task_attempts_scheduler_run_id", table_name="maintenance_task_attempts")
    op.drop_table("maintenance_task_attempts")

    op.drop_index("ix_maintenance_runs_workspace_status_created", table_name="maintenance_runs")
    op.drop_index("ix_maintenance_runs_workspace_created", table_name="maintenance_runs")
    op.drop_index("ix_maintenance_runs_status", table_name="maintenance_runs")
    op.drop_index("ix_maintenance_runs_workspace_id", table_name="maintenance_runs")
    op.drop_table("maintenance_runs")
