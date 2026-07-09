"""accelerate the lexical candidate prefilter with a pg_trgm GIN index

Revision ID: 0014_content_trgm_index
Revises: 0013_workspace_membership
Create Date: 2026-07-02

``SqlRepository.prefilter_candidate_ids`` narrows retrieval with
``content ILIKE '%token%'`` predicates. Without an index that is a sequential
scan (O(N) in the database), which is why the bounded prefilter only gives an
~8x win on Postgres vs ~39x in-memory. A ``pg_trgm`` GIN index on
``memory_items.content`` lets Postgres accelerate the existing leading-wildcard
ILIKE predicates, making the prefilter sublinear on large workspaces — no query
change, identical behavior, just faster. Purely additive (an index); default
retrieval is unaffected.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0014_content_trgm_index"
down_revision: Union[str, None] = "0013_workspace_membership"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_memory_items_content_trgm "
        "ON memory_items USING gin (content gin_trgm_ops);"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_memory_items_content_trgm;")
