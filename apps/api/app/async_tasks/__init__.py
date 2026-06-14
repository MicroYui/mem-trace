"""Optional Phase 4 async task infrastructure.

All exports are import-safe in local/dev/test defaults: no Redis, Celery worker,
database engine, or FastAPI app state is initialized at module import time.
"""

from app.async_tasks.contracts import TaskEnvelope, TaskResult

__all__ = ["TaskEnvelope", "TaskResult"]
