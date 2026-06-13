"""FastAPI dependency wiring.

A single shared engine/session factory + SqlRepository + MemoryRuntime are
created at startup and injected into routes.
"""
from __future__ import annotations

from secrets import compare_digest
from typing import Optional

from fastapi import Header, HTTPException, status

from app.config import Settings, get_settings
from app.memory.summarizer_provider import SummarizerProvider
from app.providers.base import ProviderKind
from app.providers.factory import build_provider_registry
from app.providers.registry import ProviderRegistry
from app.runtime.memory_runtime import MemoryRuntime
from app.runtime.models import ExtractionMode
from app.storage.db import make_engine, make_session_factory
from app.storage.sql_repository import SqlRepository


def _build_summarizer_provider(settings: Settings) -> SummarizerProvider:
    """Compatibility wrapper around the provider registry summarizer slot."""
    provider = build_provider_registry(settings).get(ProviderKind.summarizer)
    assert isinstance(provider, SummarizerProvider)
    return provider


class AppState:
    def __init__(self) -> None:
        self.engine = None
        self.runtime: Optional[MemoryRuntime] = None
        self.provider_registry: Optional[ProviderRegistry] = None

    def startup(self) -> None:
        settings = get_settings()
        self.engine = make_engine()
        sf = make_session_factory(self.engine)
        repo = SqlRepository(sf)
        self.provider_registry = build_provider_registry(settings)
        provider = self.provider_registry.get(ProviderKind.extraction)
        summarizer_provider = self.provider_registry.get(ProviderKind.summarizer)

        self.runtime = MemoryRuntime(
            repo,
            default_workspace_id=settings.default_workspace_id,
            token_budget=settings.retrieval_token_budget,
            extraction_mode=ExtractionMode(settings.extraction_mode),
            extraction_provider=provider,
            summarizer_provider=summarizer_provider if isinstance(summarizer_provider, SummarizerProvider) else None,
            provider_registry=self.provider_registry,
        )

    async def shutdown(self) -> None:
        if self.engine is not None:
            await self.engine.dispose()


app_state = AppState()


def get_runtime() -> MemoryRuntime:
    assert app_state.runtime is not None, "runtime not initialized"
    return app_state.runtime


def get_provider_registry() -> ProviderRegistry:
    assert app_state.provider_registry is not None, "provider registry not initialized"
    return app_state.provider_registry


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


__all__ = [
    "app_state",
    "get_runtime",
    "get_provider_registry",
    "require_api_key",
    "AppState",
    "_build_summarizer_provider",
]
