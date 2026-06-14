from __future__ import annotations

import hashlib

import pytest
from fastapi import HTTPException

from app.config import Settings
from app.governance.redaction_policy import RedactionState, decide_redaction_state


def test_redaction_policy_redacts_secret_content_by_default() -> None:
    decision = decide_redaction_state("token sk-1234567890abcdef", Settings())

    assert decision.state == RedactionState.redacted
    assert decision.content is not None
    assert "sk-1234567890abcdef" not in decision.content
    assert decision.raw_payload_ref is None


def test_redaction_policy_allows_safe_content_without_redaction() -> None:
    decision = decide_redaction_state("use bun for tests", Settings())

    assert decision.state == RedactionState.none
    assert decision.content == "use bun for tests"


def test_raw_secret_retention_requires_configured_encrypted_store() -> None:
    with pytest.raises(HTTPException) as exc:
        decide_redaction_state(
            "password is hunter2",
            Settings(governance_enabled=True, raw_payload_retention_enabled=True, raw_payload_store_url=""),
        )

    assert exc.value.status_code == 400


def test_raw_secret_retention_requires_governance_and_encrypted_store_scheme() -> None:
    with pytest.raises(HTTPException) as disabled:
        decide_redaction_state(
            "password is hunter2",
            Settings(
                governance_enabled=False,
                raw_payload_retention_enabled=True,
                raw_payload_store_url="encrypted://vault/memtrace",
            ),
        )
    assert disabled.value.status_code == 400

    with pytest.raises(HTTPException) as plain_store:
        decide_redaction_state(
            "password is hunter2",
            Settings(
                governance_enabled=True,
                raw_payload_retention_enabled=True,
                raw_payload_store_url="file:///tmp/raw-events",
            ),
        )
    assert plain_store.value.status_code == 400


def test_blocked_redaction_state_stores_no_content() -> None:
    decision = decide_redaction_state(
        "password is hunter2",
        Settings(governance_enabled=True, redaction_policy_default_state="blocked"),
    )

    assert decision.state == RedactionState.blocked
    assert decision.content is None
    assert decision.content_digest is None


def test_secret_digest_requires_operator_secret_and_is_not_raw_sha256() -> None:
    decision = decide_redaction_state(
        "password is hunter2",
        Settings(
            governance_enabled=True,
            redaction_policy_default_state="digest_only",
            redaction_digest_secret="digest-secret",
        ),
    )

    assert decision.content is None
    assert decision.content_digest is not None
    assert decision.content_digest != hashlib.sha256("password is hunter2".encode("utf-8")).hexdigest()
