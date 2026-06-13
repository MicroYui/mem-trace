"""FastAPI dependency wiring.

A single shared engine/session factory + SqlRepository + MemoryRuntime are
created at startup and injected into routes.
"""
from __future__ import annotations

import logging
from secrets import compare_digest
from typing import Optional

from fastapi import Header, HTTPException, status

from app.config import Settings, get_settings
from app.memory.llm_extractor import (
    ExtractionProvider,
    FakeExtractionProvider,
    LLMExtractionProvider,
)
from app.memory.summarizer_provider import (
    LLMSummarizerProvider,
    RuleSummarizerProvider,
    SummarizerProvider,
)
from app.runtime.memory_runtime import MemoryRuntime
from app.runtime.models import ExtractionMode
from app.storage.db import make_engine, make_session_factory
from app.storage.sql_repository import SqlRepository

logger = logging.getLogger(__name__)


def _build_summarizer_provider(settings: Settings) -> SummarizerProvider:
    """Build the C3 summarizer provider using extraction-style tri-state wiring."""
    if settings.llm_summarizer_enabled:
        if settings.llm_api_key:
            return LLMSummarizerProvider(
                api_key=settings.llm_api_key,
                base_url=settings.llm_base_url,
                model=settings.llm_model,
                timeout_s=settings.compaction_timeout_ms / 1000,
                max_tokens=settings.llm_max_tokens,
                use_json_response_format=settings.llm_use_json_response_format,
            )
        logger.warning(
            "MEMTRACE_LLM_SUMMARIZER_ENABLED is set but MEMTRACE_LLM_API_KEY "
            "is empty; using deterministic RuleSummarizerProvider."
        )
    return RuleSummarizerProvider()


class AppState:
    def __init__(self) -> None:
        self.engine = None
        self.runtime: Optional[MemoryRuntime] = None

    def startup(self) -> None:
        settings = get_settings()
        self.engine = make_engine()
        sf = make_session_factory(self.engine)
        repo = SqlRepository(sf)
        # Config-gated LLM extraction (P2). Default-off keeps demo/benchmark
        # deterministic. When enabled with an API key we wire the real
        # OpenAI-compatible LLMExtractionProvider; enabled without a key falls
        # back to the deterministic FakeExtractionProvider so the pipeline still
        # runs (and the runtime degrades to the rule writer on any LLM failure).
        provider: Optional[ExtractionProvider] = None
        if settings.llm_extraction_enabled:
            if settings.llm_api_key:
                provider = LLMExtractionProvider(
                    api_key=settings.llm_api_key,
                    base_url=settings.llm_base_url,
                    model=settings.llm_model,
                    timeout_s=settings.llm_timeout_ms / 1000,
                    max_tokens=settings.llm_max_tokens,
                    use_json_response_format=settings.llm_use_json_response_format,
                )
            else:
                logger.warning(
                    "MEMTRACE_LLM_EXTRACTION_ENABLED is set but MEMTRACE_LLM_API_KEY "
                    "is empty; using deterministic FakeExtractionProvider."
                )
                provider = FakeExtractionProvider()
        summarizer_provider = _build_summarizer_provider(settings)

        self.runtime = MemoryRuntime(
            repo,
            default_workspace_id=settings.default_workspace_id,
            token_budget=settings.retrieval_token_budget,
            extraction_mode=ExtractionMode(settings.extraction_mode),
            extraction_provider=provider,
            summarizer_provider=summarizer_provider,
        )

    async def shutdown(self) -> None:
        if self.engine is not None:
            await self.engine.dispose()


app_state = AppState()


def get_runtime() -> MemoryRuntime:
    assert app_state.runtime is not None, "runtime not initialized"
    return app_state.runtime


async def require_api_key(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
) -> None:
    settings = get_settings()
    if not settings.auth_enabled:
        return
    expected = settings.api_key
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="auth enabled but api key is not configured",
        )
    supplied = None
    if authorization and authorization.lower().startswith("bearer "):
        supplied = authorization.split(" ", 1)[1]
    elif x_api_key:
        supplied = x_api_key
    if not supplied:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing api key")
    if not compare_digest(supplied.encode("utf-8"), expected.encode("utf-8")):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid api key")


__all__ = ["app_state", "get_runtime", "require_api_key", "AppState"]
