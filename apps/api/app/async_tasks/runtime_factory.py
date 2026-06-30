"""Worker runtime factory independent from FastAPI app state."""
from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings
from app.providers.base import ProviderKind
from app.providers.factory import build_provider_registry
from app.memory.summarizer_provider import SummarizerProvider
from app.runtime.memory_runtime import MemoryRuntime
from app.runtime.models import ExtractionMode
from app.storage.db import make_engine, make_session_factory
from app.storage.sql_repository import SqlRepository


@dataclass
class WorkerRuntimeHandle:
    runtime: MemoryRuntime
    engine: object | None = None
    provider_registry: object | None = None

    async def aclose(self) -> None:
        # engine.dispose() must always run, even if a provider aclose() raises.
        try:
            if self.provider_registry is not None:
                await self.provider_registry.aclose()
        finally:
            if self.engine is not None:
                await self.engine.dispose()


def build_worker_runtime(settings: Settings) -> WorkerRuntimeHandle:
    """Build a runtime for Celery workers without importing FastAPI app_state."""
    engine = make_engine(settings)
    repo = SqlRepository(make_session_factory(engine))
    registry = build_provider_registry(settings)
    extraction_provider = registry.get(ProviderKind.extraction)
    summarizer_provider = registry.get(ProviderKind.summarizer)
    runtime = MemoryRuntime(
        repo,
        default_workspace_id=settings.default_workspace_id,
        token_budget=settings.retrieval_token_budget,
        extraction_mode=ExtractionMode(settings.extraction_mode),
        extraction_provider=extraction_provider,
        summarizer_provider=summarizer_provider if isinstance(summarizer_provider, SummarizerProvider) else None,
        provider_registry=registry,
    )
    return WorkerRuntimeHandle(runtime=runtime, engine=engine, provider_registry=registry)


__all__ = ["WorkerRuntimeHandle", "build_worker_runtime"]
