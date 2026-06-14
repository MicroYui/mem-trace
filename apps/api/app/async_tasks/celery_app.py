"""Celery app factory for optional async workers."""
from __future__ import annotations

from celery import Celery
from kombu import Queue

from app.async_tasks.tasks import process_event_extraction, process_memory_maintenance
from app.config import Settings, get_settings


def make_celery_app(settings: Settings) -> Celery:
    """Create a Celery app without import-time network side effects."""
    app = Celery("memtrace", broker=settings.celery_broker_url, backend=settings.celery_result_backend)
    app.conf.update(
        task_always_eager=settings.celery_task_always_eager,
        task_eager_propagates=True,
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        result_backend=settings.celery_result_backend,
        task_default_queue=settings.memory_queue_name,
        task_queues=(
            Queue(settings.memory_queue_name),
            Queue(settings.maintenance_queue_name),
            Queue(settings.eval_queue_name),
        ),
    )
    app.task(name="memory.extract_event", queue=settings.memory_queue_name)(process_event_extraction)
    app.task(name="maintenance.memory", queue=settings.maintenance_queue_name)(process_memory_maintenance)
    return app


def create_celery_app() -> Celery:
    """Celery CLI factory using environment-backed settings."""
    return make_celery_app(get_settings())


celery_app = create_celery_app()


__all__ = ["celery_app", "create_celery_app", "make_celery_app"]
