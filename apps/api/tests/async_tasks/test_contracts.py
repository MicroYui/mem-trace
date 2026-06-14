from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.async_tasks.contracts import TaskEnvelope, TaskResult


def test_task_envelope_serializes_required_fields_as_json():
    envelope = TaskEnvelope(
        task_type="memory.extract_event",
        workspace_id="ws1",
        dedupe_key="extract:event_1",
        payload={"event_id": "event_1", "redacted_event": {"content": "[REDACTED]"}},
    )

    payload = envelope.model_dump(mode="json")

    assert set(payload) == {"task_id", "task_type", "workspace_id", "dedupe_key", "payload", "created_at"}
    assert payload["task_id"].startswith("task_")
    assert payload["task_type"] == "memory.extract_event"
    assert payload["workspace_id"] == "ws1"
    assert payload["dedupe_key"] == "extract:event_1"
    assert payload["payload"] == {"event_id": "event_1", "redacted_event": {"content": "[REDACTED]"}}
    assert isinstance(payload["created_at"], str)


@pytest.mark.parametrize(
    "secret_key",
    ["api_key", "api-key", "authorization", "password", "passwd", "secret", "token", "credential", "access-key", "private-key"],
)
def test_task_envelope_rejects_secret_like_payload_keys(secret_key: str):
    with pytest.raises(ValidationError):
        TaskEnvelope(
            task_type="memory.extract_event",
            workspace_id="ws1",
            dedupe_key="extract:event_1",
            payload={secret_key: "sk-raw-secret"},
        )


def test_task_envelope_allows_secret_words_under_redacted_event_only():
    envelope = TaskEnvelope(
        task_type="memory.extract_event",
        workspace_id="ws1",
        dedupe_key="extract:event_1",
        payload={"redacted_event": {"api_key": "[REDACTED]", "authorization": "[REDACTED]"}},
    )

    assert envelope.payload["redacted_event"]["api_key"] == "[REDACTED]"


def test_task_envelope_rejects_raw_secret_under_redacted_event():
    with pytest.raises(ValidationError):
        TaskEnvelope(
            task_type="memory.extract_event",
            workspace_id="ws1",
            dedupe_key="extract:event_1",
            payload={"redacted_event": {"api_key": "sk-raw-secret password=hunter2"}},
        )


def test_task_envelope_rejects_raw_secret_payload_values_even_with_safe_key():
    with pytest.raises(ValidationError):
        TaskEnvelope(
            task_type="memory.extract_event",
            workspace_id="ws1",
            dedupe_key="extract:event_1",
            payload={"content": "password=hunter2"},
        )


def test_task_envelope_rejects_non_json_payload_types():
    with pytest.raises(ValidationError):
        TaskEnvelope(
            task_type="memory.extract_event",
            workspace_id="ws1",
            dedupe_key="extract:event_1",
            payload={"bad": object()},
        )


def test_task_envelope_rejects_non_finite_numeric_payload_values():
    with pytest.raises(ValidationError):
        TaskEnvelope(
            task_type="memory.extract_event",
            workspace_id="ws1",
            dedupe_key="extract:event_1",
            payload={"score": math.inf},
        )


def test_task_result_rejects_non_finite_metadata_values():
    with pytest.raises(ValidationError):
        TaskResult(task_id="task_1", task_type="memory.extract_event", status="completed", metadata={"latency": math.nan})


def test_task_result_rejects_raw_secret_error_text():
    with pytest.raises(ValidationError):
        TaskResult(
            task_id="task_1",
            task_type="memory.extract_event",
            status="failed",
            error="authorization: bearer abcdefghijklmnop",
        )


def test_async_settings_defaults_are_disabled_and_eager_safe():
    settings = Settings()

    assert settings.async_tasks_enabled is False
    assert settings.celery_task_always_eager is True
    assert settings.redis_url == "redis://localhost:6379/0"
    assert settings.memory_queue_name == "memtrace.memory"
    assert settings.maintenance_queue_name == "memtrace.maintenance"
    assert settings.eval_queue_name == "memtrace.eval"
    assert settings.async_task_default_ttl_seconds == 3600
