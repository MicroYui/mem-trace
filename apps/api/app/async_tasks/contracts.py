"""JSON-safe async task contracts."""
from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.memory.secrets import contains_secret, is_secret_like_key


_REDACTED_PAYLOAD_KEYS = {"redacted_event"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_task_id() -> str:
    return f"task_{uuid.uuid4().hex[:12]}"


def _validate_json_safe(value: Any, *, path: tuple[str, ...] = ()) -> None:
    if value is None or isinstance(value, bool | int | str):
        if isinstance(value, str) and contains_secret(value):
            location = "redacted payload" if path and path[0] in _REDACTED_PAYLOAD_KEYS else "payload"
            raise ValueError(f"raw secret-like value under {location} at {'.'.join(path) or '<root>'}")
        return
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"non-finite numeric value at {'.'.join(path) or '<root>'}")
    if isinstance(value, float):
        return
    if isinstance(value, dict):
        for key, nested in value.items():
            if not isinstance(key, str):
                raise ValueError(f"non-string JSON object key at {'.'.join(path) or '<root>'}")
            if not path or path[0] not in _REDACTED_PAYLOAD_KEYS:
                if is_secret_like_key(str(key)):
                    raise ValueError(f"secret-like payload key is not allowed: {'.'.join((*path, str(key)))}")
            _validate_json_safe(nested, path=(*path, str(key)))
    elif isinstance(value, list):
        for idx, nested in enumerate(value):
            _validate_json_safe(nested, path=(*path, str(idx)))
    else:
        raise ValueError(f"non-JSON payload value at {'.'.join(path) or '<root>'}: {type(value).__name__}")


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TaskEnvelope(_Base):
    """Task request payload persisted or sent to Celery as JSON."""

    task_id: str = Field(default_factory=_new_task_id)
    task_type: str
    workspace_id: str
    dedupe_key: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_now)

    @field_validator("payload")
    @classmethod
    def _payload_is_safe(cls, value: dict[str, Any]) -> dict[str, Any]:
        _validate_json_safe(value)
        return value


class TaskResult(_Base):
    """JSON result returned by eager/worker task wrappers."""

    task_id: str
    task_type: str
    status: Literal["completed", "skipped", "failed"]
    created_memory_ids: list[str] = Field(default_factory=list)
    duplicate: bool = False
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    finished_at: datetime = Field(default_factory=_now)

    @field_validator("error")
    @classmethod
    def _error_is_safe(cls, value: str | None) -> str | None:
        if value is not None and contains_secret(value):
            raise ValueError("task error contains raw secret-like value")
        return value

    @model_validator(mode="after")
    def _metadata_is_safe(self) -> "TaskResult":
        _validate_json_safe(self.metadata)
        return self


__all__ = ["TaskEnvelope", "TaskResult"]
