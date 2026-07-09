"""FastAPI application entrypoint.

Run with: uv run uvicorn app.main:app --reload  (from apps/api on PYTHONPATH)
or:       uv run uvicorn app.main:app --app-dir apps/api
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from sqlalchemy import text

from app.api.deps import app_state
from app.api.admin_routes import router as admin_router
from app.api.routes import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    app_state.startup()
    yield
    await app_state.shutdown()


app = FastAPI(title="MemTrace", version="0.1.0", lifespan=lifespan)
app.include_router(router)
app.include_router(admin_router)


@app.get("/health")
async def health() -> dict:
    """Liveness: the process is up. Never touches the database (so a DB blip does
    not cause the orchestrator to kill an otherwise-healthy replica)."""
    return {"status": "ok"}


@app.get("/health/ready")
async def readiness(response: Response) -> dict:
    """Readiness: can this replica serve traffic? Verifies the shared Postgres is
    reachable so a load balancer / k8s readinessProbe routes only to replicas that
    can actually answer. Returns 503 when the datastore is unavailable.

    Behind the multi-replica ``docker-compose.scale.yml`` this is the probe the LB
    and orchestrator should gate on (``/health`` is liveness only)."""
    engine = app_state.engine
    if engine is None:
        # No SQL engine bound (e.g. in-memory/test wiring): ready iff a repository
        # is configured — an in-memory repository has no external dependency.
        if app_state.repository is not None:
            return {"status": "ready", "checks": {"database": "in_memory"}}
        response.status_code = 503
        return {"status": "not_ready", "checks": {"database": "unconfigured"}}
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001 - any datastore failure means not-ready, not a crash
        response.status_code = 503
        return {"status": "not_ready", "checks": {"database": "unavailable"}}
    return {"status": "ready", "checks": {"database": "ok"}}


__all__ = ["app"]
