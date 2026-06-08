"""FastAPI application entrypoint.

Run with: uv run uvicorn app.main:app --reload  (from apps/api on PYTHONPATH)
or:       uv run uvicorn app.main:app --app-dir apps/api
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.deps import app_state
from app.api.routes import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    app_state.startup()
    yield
    await app_state.shutdown()


app = FastAPI(title="MemTrace", version="0.1.0", lifespan=lifespan)
app.include_router(router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


__all__ = ["app"]
