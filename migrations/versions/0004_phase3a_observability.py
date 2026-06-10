"""add access top_k and eval persistence tables

Revision ID: 0004_phase3a_observability
Revises: 0003_memory_superseded_by
Create Date: 2026-06-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0004_phase3a_observability"
down_revision: Union[str, None] = "0003_memory_superseded_by"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _ts(name: str, nullable: bool = False):
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def upgrade() -> None:
    op.add_column(
        "memory_access_logs",
        sa.Column("top_k", sa.Integer(), nullable=False, server_default="10"),
    )

    op.create_table(
        "eval_cases",
        sa.Column("eval_case_id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("tags", JSONB, nullable=False, server_default="[]"),
        sa.Column("config", JSONB, nullable=False, server_default="{}"),
        _ts("created_at"),
    )
    op.create_table(
        "eval_runs",
        sa.Column("eval_run_id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("workspace_id", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("config", JSONB, nullable=False, server_default="{}"),
        _ts("started_at"),
        _ts("finished_at", nullable=True),
        _ts("created_at"),
    )
    op.create_index("ix_eval_runs_workspace_id", "eval_runs", ["workspace_id"])

    op.create_table(
        "eval_results",
        sa.Column("eval_result_id", sa.String(), primary_key=True),
        sa.Column("eval_run_id", sa.String(), nullable=False),
        sa.Column("eval_case_id", sa.String(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=True),
        sa.Column("access_id", sa.String(), nullable=True),
        sa.Column("strategy", sa.String(), nullable=True),
        sa.Column("metrics", JSONB, nullable=False, server_default="{}"),
        sa.Column("passed", sa.Boolean(), nullable=False, server_default=sa.true()),
        _ts("created_at"),
    )
    op.create_index("ix_eval_results_eval_run_id", "eval_results", ["eval_run_id"])
    op.create_index("ix_eval_results_eval_case_id", "eval_results", ["eval_case_id"])
    op.create_index("ix_eval_results_run_id", "eval_results", ["run_id"])
    op.create_index("ix_eval_results_access_id", "eval_results", ["access_id"])


def downgrade() -> None:
    op.drop_index("ix_eval_results_access_id", table_name="eval_results")
    op.drop_index("ix_eval_results_run_id", table_name="eval_results")
    op.drop_index("ix_eval_results_eval_case_id", table_name="eval_results")
    op.drop_index("ix_eval_results_eval_run_id", table_name="eval_results")
    op.drop_table("eval_results")
    op.drop_index("ix_eval_runs_workspace_id", table_name="eval_runs")
    op.drop_table("eval_runs")
    op.drop_table("eval_cases")
    op.drop_column("memory_access_logs", "top_k")
