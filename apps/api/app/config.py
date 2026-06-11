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
    # Reserved budget for C1 context-compaction notice/retained constraints.
    # The C1 rule path is always on; later LLM rolling summaries are gated
    # separately so benchmark/default behavior stays deterministic.
    compaction_notice_reserve_tokens: int = 64
    # C3/C4 context-compaction controls. ``compaction_enabled`` gates the future
    # rolling-history fold only; it does not disable C1's default-on budget
    # notice/retained-constraint safety path. The summarizer provider is always
    # available as a deterministic rule fallback, while the LLM path is opt-in.
    compaction_enabled: bool = False
    llm_summarizer_enabled: bool = False
    compaction_history_token_threshold: int = 2048
    compaction_summary_budget_tokens: int = 192
    compaction_timeout_ms: int = 1500
    # Extraction freshness/latency policy (architecture.md §12.1): "sync" extracts
    # inline on write_event (default; keeps demo/benchmark deterministic), while
    # "buffered" defers extraction to an explicit or lazy flush.
    extraction_mode: str = "sync"
    # Config-gated LLM extraction pipeline (P2). Disabled by default so demo and
    # benchmark stay fully deterministic on the rule-based writer. When enabled,
    # user-message events are turned into memory candidates by an injected
    # ExtractionProvider (see app/memory/llm_extractor.py); deps wires a real
    # LLMExtractionProvider when an API key is configured, else a deterministic
    # FakeExtractionProvider.
    llm_extraction_enabled: bool = False
    # Real LLM provider settings (OpenAI-compatible /chat/completions). The
    # provider is only wired when llm_extraction_enabled is True AND llm_api_key
    # is non-empty; otherwise deps falls back to the deterministic provider.
    # Extraction is a cold-path operation, so the timeout is more generous than
    # the retrieval hot path. On any failure the runtime degrades to the rule
    # writer, so these stay safe to leave at defaults.
    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    llm_timeout_ms: int = 8000
    llm_max_tokens: int = 512
    # Whether to send response_format=json_object. Off by default because some
    # OpenAI-compatible endpoints reject it (e.g. certain Volcengine Ark models);
    # the system prompt + fence-stripping parser already enforce JSON output.
    llm_use_json_response_format: bool = False
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
