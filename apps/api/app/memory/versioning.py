"""Memory version snapshot helpers for P4-C.

Version rows are audit/debug metadata. They must never persist raw secrets, so
all writers use ``redacted_memory_snapshot(...)`` rather than dumping the model
directly.
"""
from __future__ import annotations

from typing import Any

from app.memory import secrets
from app.runtime.models import MemoryItem


_VERSIONED_FIELDS = {
    "content",
    "summary",
    "key",
    "value",
    "scope",
    "status",
    "risk_flags",
    "risk_score",
    "sensitivity",
    "memory_type",
    "branch_status",
    "lifecycle_metadata",
    "superseded_by",
}

def _redact_value(value: Any, *, key_hint: str | None = None) -> Any:
    key_is_secret_like = secrets.is_secret_like_key(key_hint)
    if key_is_secret_like and isinstance(value, (str, list, dict)):
        return "[REDACTED]"
    if isinstance(value, str):
        if key_hint == "key" and secrets.is_secret_like_key(value):
            return "[REDACTED]"
        return secrets.redact(value)
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _redact_value(nested, key_hint=str(key)) for key, nested in value.items()}
    return value


def redacted_memory_snapshot(memory: MemoryItem) -> dict[str, Any]:
    """Return a stable, recursively redacted snapshot for version storage."""

    raw = memory.model_dump(mode="json")
    snapshot = _redact_value(raw)
    if secrets.is_secret_like_key(memory.key):
        snapshot["key"] = "[REDACTED]"
        snapshot["value"] = "[REDACTED]"
    snapshot.pop("embedding_vector", None)
    return snapshot


def should_create_memory_version(before: MemoryItem, after: MemoryItem) -> bool:
    """Return true when the memory changed semantically.

    Access-only mutations (``access_count``, ``last_accessed_at``, ``updated_at``)
    are intentionally excluded because P4-B retrieval bumps can be frequent and
    should not create noisy version history.
    """

    before_dump = before.model_dump(mode="json")
    after_dump = after.model_dump(mode="json")
    return any(before_dump.get(field) != after_dump.get(field) for field in _VERSIONED_FIELDS)


__all__ = ["redacted_memory_snapshot", "should_create_memory_version"]
