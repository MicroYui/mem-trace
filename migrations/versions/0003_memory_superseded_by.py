"""record memory supersession lineage

Revision ID: 0003_memory_superseded_by
Revises: 0002_pgvector
Create Date: 2026-06-09

Adds memory_items.superseded_by so the dedup/merge + conflict resolver can
record WHICH active memory replaced a memory that it flips to ``superseded``.
This gives an auditable lineage (provenance) instead of a lossy status-only
transition. The column is nullable: only memories retired by the resolver
carry a pointer to their successor.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003_memory_superseded_by"
down_revision: Union[str, None] = "0002_pgvector"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "memory_items",
        sa.Column("superseded_by", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("memory_items", "superseded_by")
