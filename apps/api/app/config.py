"""Application configuration."""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment / .env."""

    model_config = SettingsConfigDict(env_prefix="MEMTRACE_", env_file=".env", extra="ignore")

    # Async SQLAlchemy URL (asyncpg driver). Matches docker-compose default port 5433.
    database_url: str = "postgresql+asyncpg://memtrace:memtrace@localhost:5433/memtrace"
    # Sync URL for Alembic migrations.
    sync_database_url: str = "postgresql+psycopg://memtrace:memtrace@localhost:5433/memtrace"

    default_workspace_id: str = "ws_default"
    embedding_dim: int = 256
    retrieval_token_budget: int = 512
    retrieval_timeout_ms: int = 2000
    # Blend deterministic vector (pgvector KNN) similarity with lexical overlap.
    # When the backend lacks usable embeddings the controller falls back to
    # lexical-only scoring, so this stays safe to leave enabled.
    retrieval_use_vector: bool = True
    # Weight of the vector cosine signal in the blended relevance score; the
    # lexical signal gets the remaining weight.
    retrieval_vector_weight: float = 0.5


@lru_cache
def get_settings() -> Settings:
    return Settings()
