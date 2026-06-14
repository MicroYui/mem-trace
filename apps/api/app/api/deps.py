"""FastAPI dependency wiring.

A single shared engine/session factory + SqlRepository + MemoryRuntime are
created at startup and injected into routes.
"""
from __future__ import annotations

from typing import Optional

from fastapi import Header, HTTPException, status

from app.async_tasks.celery_app import make_celery_app
from app.async_tasks.contracts import TaskEnvelope
from app.config import Settings, get_settings
from app.governance.auth import anonymous_principal, authenticate_api_key
from app.governance.quota import InMemoryQuotaCounter, QuotaService
from app.memory.candidate_buffer import CandidateBuffer
from app.memory.redis_candidate_buffer import RedisCandidateBuffer
from app.memory.summarizer_provider import SummarizerProvider
from app.providers.base import ProviderKind
from app.providers.factory import build_provider_registry
from app.providers.registry import ProviderRegistry
from app.runtime.memory_runtime import MemoryRuntime
from app.runtime.models import ExtractionMode, Principal
from app.runtime.repository import Repository
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
        self.repository: Optional[Repository] = None
        self.provider_registry: Optional[ProviderRegistry] = None

    def startup(self) -> None:
        settings = get_settings()
        self.engine = make_engine()
        sf = make_session_factory(self.engine)
        repo = SqlRepository(sf)
        self.repository = repo
        self.provider_registry = build_provider_registry(settings)
        provider = self.provider_registry.get(ProviderKind.extraction)
        summarizer_provider = self.provider_registry.get(ProviderKind.summarizer)
        candidate_buffer = CandidateBuffer()
        if settings.async_tasks_enabled and settings.redis_url:
            import redis.asyncio as redis

            candidate_buffer = RedisCandidateBuffer(redis.from_url(settings.redis_url, decode_responses=True))
        celery_app = make_celery_app(settings)

        async def enqueue_memory_extraction(envelope: TaskEnvelope) -> str:
            result = celery_app.tasks["memory.extract_event"].apply_async(
                args=[envelope.model_dump(mode="json")],
                queue=settings.memory_queue_name,
                task_id=envelope.task_id,
            )
            return str(result.id)

        self.runtime = MemoryRuntime(
            repo,
            default_workspace_id=settings.default_workspace_id,
            token_budget=settings.retrieval_token_budget,
            extraction_mode=ExtractionMode(settings.extraction_mode),
            extraction_provider=provider,
            summarizer_provider=summarizer_provider if isinstance(summarizer_provider, SummarizerProvider) else None,
            provider_registry=self.provider_registry,
            candidate_buffer=candidate_buffer,
            task_enqueue=enqueue_memory_extraction if settings.async_tasks_enabled else None,
        )

    async def shutdown(self) -> None:
        if self.engine is not None:
            await self.engine.dispose()


app_state = AppState()
_quota_counter = InMemoryQuotaCounter()


def get_runtime() -> MemoryRuntime:
    assert app_state.runtime is not None, "runtime not initialized"
    return app_state.runtime


def get_repository() -> Repository:
    assert app_state.repository is not None, "repository not initialized"
    return app_state.repository


def get_provider_registry() -> ProviderRegistry:
    assert app_state.provider_registry is not None, "provider registry not initialized"
    return app_state.provider_registry


def get_quota_service() -> QuotaService:
    return QuotaService(_quota_counter, get_settings())


async def require_api_key(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
) -> Principal:
    settings = get_settings()
    if not settings.auth_enabled:
        return anonymous_principal()
    supplied = None
    if authorization and authorization.lower().startswith("bearer "):
        supplied = authorization.split(" ", 1)[1]
    elif x_api_key:
        supplied = x_api_key
    if not supplied:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing api key")
    if app_state.repository is None and settings.api_key and not settings.governance_enabled:
        from secrets import compare_digest

        if compare_digest(supplied.encode("utf-8"), settings.api_key.encode("utf-8")):
            from app.governance.auth import legacy_principal

            return legacy_principal()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid api key")
    try:
        return await authenticate_api_key(supplied, get_repository(), settings)
    except UnicodeEncodeError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid api key") from exc
    except AssertionError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="auth enabled but repository is not configured",
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001 - auth must fail closed
        if settings.api_key and not settings.governance_enabled:
            # The legacy H3 lightweight token gate should keep working in unit
            # tests that call this dependency directly before app startup.
            from secrets import compare_digest

            if compare_digest(supplied.encode("utf-8"), settings.api_key.encode("utf-8")):
                from app.governance.auth import legacy_principal

                return legacy_principal()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid api key")


__all__ = [
    "app_state",
    "get_runtime",
    "get_repository",
    "get_provider_registry",
    "get_quota_service",
    "require_api_key",
    "AppState",
    "_build_summarizer_provider",
]
