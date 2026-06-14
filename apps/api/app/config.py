"""Application configuration."""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment / .env."""

    model_config = SettingsConfigDict(env_prefix="MEMTRACE_", env_file=".env", extra="ignore")

    # Async SQLAlchemy URL (asyncpg driver). Matches docker-compose default port 5433.
    database_url: str = "postgresql+asyncpg://memtrace:memtrace@localhost:5433/memtrace"
    # Sync URL for Alembic migrations.
    sync_database_url: str = "postgresql+psycopg://memtrace:memtrace@localhost:5433/memtrace"

    default_workspace_id: str = "ws_default"
    # Lightweight hosted-demo auth gate (ADR-016). Default-off so local/dev,
    # deterministic benchmarks, and examples continue to run without secrets.
    auth_enabled: bool = False
    api_key: str | None = None
    # Phase 4 governance remains default-off so local/dev/benchmark/reproduce
    # keep their historical no-auth deterministic behavior unless explicitly
    # enabled by the operator.
    governance_enabled: bool = False
    allow_legacy_api_key: bool = False
    api_key_digest_salt: str = ""
    quota_enabled: bool = False
    quota_window_seconds: int = 60
    quota_write_event_per_window: int = 600
    quota_retrieve_context_per_window: int = 600
    quota_report_export_per_window: int = 60
    quota_replay_per_window: int = 120
    quota_async_task_enqueue_per_window: int = 600
    # Maintenance/admin governance depth. Admin APIs are an operator surface and
    # stay default-off; when enabled, admin mutation helpers require a real
    # owner principal and never allow anonymous local bypasses.
    admin_api_enabled: bool = False
    maintenance_default_operations: list[str] = Field(
        default_factory=lambda: [
            "score_memory",
            "conflict_scan",
            "dedup_memory",
            "decay_memory",
            "archive_memory",
            "quarantine_memory",
            "reindex_memory",
            "summary_refresh",
            "procedural_refresh",
            "profile_refresh",
        ]
    )
    maintenance_max_operations_per_run: int = 10
    redaction_policy_default_state: str = "redacted"
    # Optional secret used to compute non-enumerable redaction digests. When
    # unset, secret payload digests are omitted rather than storing bare SHA-256
    # fingerprints of low-entropy sensitive content.
    redaction_digest_secret: str = ""
    raw_payload_retention_enabled: bool = False
    raw_payload_store_url: str = ""
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
    # Multi-signal candidate fusion mode (ROADMAP §4). "linear" keeps the
    # default weighted blend of lexical/vector scores. "rrf" uses Reciprocal
    # Rank Fusion over the lexical and vector rankings, which is robust to the
    # two signals living on different score scales. Default stays "linear" so
    # existing demos/benchmarks are unchanged.
    retrieval_fusion: str = "linear"
    # RRF damping constant; larger values flatten the contribution of top ranks.
    retrieval_rrf_k: int = 60
    # Provider Registry (ROADMAP §10). Deterministic hash embedding remains the
    # default so tests, demos, and benchmarks are reproducible. Runtime/retrieval
    # hot paths use the configured embedding provider first, then degrade to the
    # deterministic 256-dim pgvector-compatible embedding on failure/mismatch.
    embedding_provider: str = "deterministic"
    embedding_api_key: str = ""
    embedding_base_url: str = "https://api.openai.com/v1"
    embedding_model: str = "text-embedding-3-small"
    embedding_timeout_ms: int = 8000
    # Phase 4 async foundation. Defaults are deliberately eager/offline-safe:
    # importing settings or running tests must not open Redis/Celery network
    # connections unless async tasks are explicitly enabled.
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "memory://"
    celery_result_backend: str | None = None
    async_tasks_enabled: bool = False
    celery_task_always_eager: bool = True
    memory_queue_name: str = "memtrace.memory"
    maintenance_queue_name: str = "memtrace.maintenance"
    eval_queue_name: str = "memtrace.eval"
    async_task_default_ttl_seconds: int = 3600
    # OpenTelemetry/OpenInference export (Segment 2). Defaults are deliberately
    # disabled/noop so local/dev/benchmark/reproduce never require files,
    # optional OTel dependencies, or network endpoints.
    telemetry_enabled: bool = False
    telemetry_exporter: str = "noop"
    telemetry_jsonl_path: str = "reports/telemetry.jsonl"
    telemetry_jsonl_append: bool = False
    telemetry_otlp_endpoint: str = ""
    telemetry_headers: dict[str, str] = Field(default_factory=dict)
    telemetry_strict: bool = False
    telemetry_sample_rate: float = 1.0
    telemetry_fail_open: bool = True

    @field_validator("telemetry_sample_rate")
    @classmethod
    def _validate_telemetry_sample_rate(cls, value: float) -> float:
        if value < 0.0 or value > 1.0:
            raise ValueError("telemetry_sample_rate must be between 0.0 and 1.0")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
