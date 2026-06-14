"""Recursive telemetry redaction and attribute budgeting."""
from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from app.memory.secrets import is_secret_like_key, redact
from app.telemetry import semconv
from app.telemetry.models import TelemetryAttributeValue

_REDACTION = "[REDACTED]"
_RAW_PAYLOAD_KEY = "raw_payload_ref"
_RAW_PAYLOAD_MARKER_RE = re.compile(r"(?i)\braw[_-]?payload[_-]?ref\b")
_DESTRUCTIVE_OR_PROD_RE = re.compile(r"(?i)(rm\s+-rf|git\s+push\s+--force|/prod\b|production\s+path)")
_BENIGN_TOKEN_KEYS = {
    "token_budget",
    "token_count",
    "input_tokens",
    "output_tokens",
    "token_input",
    "token_output",
    "actual_tokens",
    "pre_tokens",
    "post_tokens",
}
_RAW_CONTENT_KEYS = {
    "content",
    "context",
    "context_block",
    "context_blocks",
    "failed_attempt",
    "failed_attempt_text",
    "messages",
    "prompt",
    "query",
    "raw_content",
    "raw_context",
    "raw_event_content",
    "raw_failed_attempt",
    "raw_memory_content",
}


def _is_sensitive_key(key: str | None) -> bool:
    if not key:
        return False
    normalized = key.lower().replace("-", "_").split(".")[-1]
    if normalized in _BENIGN_TOKEN_KEYS:
        return False
    return is_secret_like_key(normalized) or normalized == _RAW_PAYLOAD_KEY or normalized in _RAW_CONTENT_KEYS


def _safe_string(value: str, *, max_string_length: int) -> str:
    redacted = redact(value)
    if _RAW_PAYLOAD_MARKER_RE.search(redacted):
        redacted = _REDACTION
    if _DESTRUCTIVE_OR_PROD_RE.search(redacted):
        redacted = _REDACTION
    if len(redacted) > max_string_length:
        return redacted[: max(0, max_string_length - 3)] + "..."
    return redacted


def sanitize_telemetry_value(
    value: Any,
    *,
    key: str | None = None,
    max_string_length: int = semconv.MAX_ATTRIBUTE_STRING_LENGTH,
    max_list_length: int = semconv.MAX_ATTRIBUTE_LIST_LENGTH,
    max_dict_keys: int = semconv.MAX_ATTRIBUTE_DICT_KEYS,
) -> Any:
    """Return a redacted JSON-safe value suitable for later attribute flattening."""
    if _is_sensitive_key(key):
        return _REDACTION
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        return _safe_string(value, max_string_length=max_string_length)
    if isinstance(value, Mapping):
        sanitized: dict[str, Any] = {}
        for raw_key in sorted(str(k) for k in value.keys())[:max_dict_keys]:
            sanitized[raw_key] = sanitize_telemetry_value(
                value.get(raw_key),
                key=raw_key,
                max_string_length=max_string_length,
                max_list_length=max_list_length,
                max_dict_keys=max_dict_keys,
            )
        return sanitized
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [
            sanitize_telemetry_value(
                item,
                max_string_length=max_string_length,
                max_list_length=max_list_length,
                max_dict_keys=max_dict_keys,
            )
            for item in list(value)[:max_list_length]
        ]
    return _safe_string(str(value), max_string_length=max_string_length)


def _cap_serialized(text: str, max_bytes: int) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    return encoded[: max(0, max_bytes - 3)].decode("utf-8", errors="ignore") + "..."


def sanitize_attributes(
    attributes: Mapping[str, Any],
    *,
    max_string_length: int = semconv.MAX_ATTRIBUTE_STRING_LENGTH,
    max_list_length: int = semconv.MAX_ATTRIBUTE_LIST_LENGTH,
    max_dict_keys: int = semconv.MAX_ATTRIBUTE_DICT_KEYS,
    max_serialized_attribute_bytes: int = semconv.MAX_SERIALIZED_ATTRIBUTE_BYTES,
) -> dict[str, TelemetryAttributeValue]:
    """Redact and flatten attributes into primitive/list-of-primitive values.

    Nested dict/list values become capped JSON string attributes named
    ``<key>_json`` because OTel attributes cannot carry arbitrary objects.
    """
    out: dict[str, TelemetryAttributeValue] = {}
    for key, value in attributes.items():
        normalized_key = key.lower().replace("-", "_").split(".")[-1]
        if normalized_key == _RAW_PAYLOAD_KEY:
            continue
        sanitized = sanitize_telemetry_value(
            value,
            key=key,
            max_string_length=max_string_length,
            max_list_length=max_list_length,
            max_dict_keys=max_dict_keys,
        )
        if sanitized is None:
            continue
        if isinstance(sanitized, dict) or (
            isinstance(sanitized, list) and not all(isinstance(item, (str, bool, int, float)) for item in sanitized)
        ):
            json_key = key if key.endswith("_json") else f"{key}_json"
            serialized = json.dumps(sanitized, sort_keys=True, separators=(",", ":"), default=str)
            out[json_key] = _cap_serialized(serialized, max_serialized_attribute_bytes)
        elif isinstance(sanitized, list):
            out[key] = [item for item in sanitized if isinstance(item, (str, bool, int, float))]
        elif isinstance(sanitized, (str, bool, int, float)):
            out[key] = sanitized
        else:
            out[key] = _safe_string(str(sanitized), max_string_length=max_string_length)
    return out


__all__ = ["sanitize_attributes", "sanitize_telemetry_value"]
