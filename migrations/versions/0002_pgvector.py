"""enable pgvector semantic retrieval

Revision ID: 0002_pgvector
Revises: 0001_initial
Create Date: 2026-06-09

Promotes memory_items.embedding_vector from a plain float[] to a pgvector
``vector(256)`` column and adds an HNSW cosine index for KNN retrieval. The
pgvector extension is now required (the image is pgvector/pgvector:pg16), so
this migration fails loudly if the extension is unavailable rather than
silently degrading to lexical-only retrieval.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0002_pgvector"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_DIM = 256


def upgrade() -> None:
    # Required for semantic retrieval; fail loudly if the extension is missing.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    # P0 never persisted embeddings (lexical retrieval), so existing rows hold
    # NULLs only and the type change is safe. The USING cast keeps any values
    # that do exist.
    op.execute(
        f"ALTER TABLE memory_items "
        f"ALTER COLUMN embedding_vector TYPE vector({_DIM}) "
        f"USING embedding_vector::vector({_DIM});"
    )

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_memory_items_embedding_hnsw "
        "ON memory_items USING hnsw (embedding_vector vector_cosine_ops);"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_memory_items_embedding_hnsw;")
    op.execute(
        "ALTER TABLE memory_items "
        "ALTER COLUMN embedding_vector TYPE double precision[] "
        "USING embedding_vector::double precision[];"
    )
