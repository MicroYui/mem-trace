"""FastAPI dependency wiring.

A single shared engine/session factory + SqlRepository + MemoryRuntime are
created at startup and injected into routes.
"""
from __future__ import annotations

from typing import Optional

from app.config import get_settings
from app.memory.llm_extractor import ExtractionProvider, FakeExtractionProvider
from app.runtime.memory_runtime import MemoryRuntime
from app.runtime.models import ExtractionMode
from app.storage.db import make_engine, make_session_factory
from app.storage.sql_repository import SqlRepository


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
        # deterministic. The shipped provider is a deterministic placeholder;
        # swap in a real LLM client here when one is added.
        provider: Optional[ExtractionProvider] = (
            FakeExtractionProvider() if settings.llm_extraction_enabled else None
        )
        self.runtime = MemoryRuntime(
            repo,
            default_workspace_id=settings.default_workspace_id,
            token_budget=settings.retrieval_token_budget,
            extraction_mode=ExtractionMode(settings.extraction_mode),
            extraction_provider=provider,
        )

    async def shutdown(self) -> None:
        if self.engine is not None:
            await self.engine.dispose()


app_state = AppState()


def get_runtime() -> MemoryRuntime:
    assert app_state.runtime is not None, "runtime not initialized"
    return app_state.runtime


__all__ = ["app_state", "get_runtime", "AppState"]
