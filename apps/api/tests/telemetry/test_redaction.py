from __future__ import annotations

import json

from app.telemetry.redaction import sanitize_attributes, sanitize_telemetry_value


def test_sanitize_telemetry_value_redacts_secret_keys_and_values_but_preserves_budget_fields():
    payload = {
        "authorization": "Bearer sk-1234567890abcdef1234",
        "api_key": "plain-token",
        "token": "session-secret",
        "client_secret": "client-secret-value",
        "secret_key": "secret-key-value",
        "id_token": "id-token-value",
        "session_token": "session-token-value",
        "password": "hunter2",
        "token_budget": 128,
        "nested": [
            {"raw_payload_ref": "vault://raw/event/1"},
            "run rm -rf /prod now",
            "normal text",
        ],
    }

    sanitized = sanitize_telemetry_value(payload)

    assert sanitized["authorization"] == "[REDACTED]"
    assert sanitized["api_key"] == "[REDACTED]"
    assert sanitized["token"] == "[REDACTED]"
    assert sanitized["client_secret"] == "[REDACTED]"
    assert sanitized["secret_key"] == "[REDACTED]"
    assert sanitized["id_token"] == "[REDACTED]"
    assert sanitized["session_token"] == "[REDACTED]"
    assert sanitized["password"] == "[REDACTED]"
    assert sanitized["token_budget"] == 128
    assert sanitized["nested"][0]["raw_payload_ref"] == "[REDACTED]"
    assert sanitized["nested"][1] == "[REDACTED]"
    assert sanitized["nested"][2] == "normal text"


def test_sanitize_telemetry_value_caps_nested_structures_deterministically():
    payload = {
        "z": "last",
        "a": "x" * 40,
        "b": [1, 2, 3, 4, 5],
        "c": {"d": "kept", "e": "also-kept", "f": "dropped"},
    }

    sanitized = sanitize_telemetry_value(
        payload,
        max_string_length=12,
        max_list_length=3,
        max_dict_keys=3,
    )

    assert list(sanitized) == ["a", "b", "c"]
    assert sanitized["a"] == "xxxxxxxxx..."
    assert sanitized["b"] == [1, 2, 3]
    assert sanitized["c"] == {"d": "kept", "e": "also-kept", "f": "dropped"}


def test_sanitize_attributes_serializes_nested_values_as_capped_json_strings():
    attrs = sanitize_attributes(
        {
            "memtrace.policy.snapshot": {"provider": {"authorization": "Bearer sk-1234567890abcdef1234"}},
            "memtrace.context.token_budget": 64,
        },
        max_serialized_attribute_bytes=160,
    )

    assert attrs["memtrace.context.token_budget"] == 64
    snapshot_json = attrs["memtrace.policy.snapshot_json"]
    assert isinstance(snapshot_json, str)
    decoded = json.loads(snapshot_json)
    assert decoded["provider"]["authorization"] == "[REDACTED]"
    assert "sk-1234567890abcdef1234" not in snapshot_json


def test_sanitize_attributes_redacts_raw_payload_ref_markers_in_string_values_and_omits_none():
    attrs = sanitize_attributes(
        {
            "memtrace.event.debug": "raw_payload_ref=vault://raw/event/evt_1",
            "memtrace.optional": None,
        }
    )

    dumped = json.dumps(attrs, sort_keys=True)
    assert attrs["memtrace.event.debug"] == "[REDACTED]"
    assert "raw_payload_ref" not in dumped
    assert "vault://raw/event" not in dumped
    assert "memtrace.optional" not in attrs


def test_sanitize_attributes_redacts_raw_content_like_metadata_keys_but_preserves_token_metrics():
    attrs = sanitize_attributes(
        {
            "raw_context": "ordinary non-secret context block text should not be exported",
            "prompt": "ordinary prompt text should not be exported",
            "content": "ordinary event content should not be exported",
            "query": "ordinary user query should not be exported",
            "memtrace.event.token_input": 5,
            "memtrace.event.token_output": 0,
        }
    )

    dumped = json.dumps(attrs, sort_keys=True)
    assert attrs["raw_context"] == "[REDACTED]"
    assert attrs["prompt"] == "[REDACTED]"
    assert attrs["content"] == "[REDACTED]"
    assert attrs["query"] == "[REDACTED]"
    assert attrs["memtrace.event.token_input"] == 5
    assert attrs["memtrace.event.token_output"] == 0
    assert "ordinary non-secret context block text" not in dumped
    assert "ordinary prompt text" not in dumped
    assert "ordinary event content" not in dumped
    assert "ordinary user query" not in dumped
