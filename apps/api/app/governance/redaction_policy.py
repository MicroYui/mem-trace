"""Governance redaction state machine and raw-payload guard."""
from __future__ import annotations

import hashlib
import hmac
from enum import Enum

from fastapi import HTTPException, status
from pydantic import BaseModel

from app.config import Settings
from app.memory import secrets


class RedactionState(str, Enum):
    none = "none"
    redacted = "redacted"
    digest_only = "digest_only"
    blocked = "blocked"


class RedactionDecision(BaseModel):
    state: RedactionState
    content: str | None = None
    content_digest: str | None = None
    raw_payload_ref: str | None = None
    reason: str | None = None


def _digest(content: str | None, settings: Settings) -> str | None:
    if content is None or not settings.redaction_digest_secret:
        return None
    return hmac.new(
        settings.redaction_digest_secret.encode("utf-8"),
        content.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def decide_redaction_state(content: str | None, settings: Settings) -> RedactionDecision:
    if content is None:
        return RedactionDecision(state=RedactionState.none, content=None)
    contains_secret = secrets.contains_secret(content)
    if not contains_secret:
        return RedactionDecision(state=RedactionState.none, content=content)

    if settings.raw_payload_retention_enabled:
        if not settings.governance_enabled:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="raw payload retention requires governance mode",
            )
        if not settings.raw_payload_store_url or not settings.raw_payload_store_url.startswith("encrypted://"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="raw payload retention requires encrypted raw payload store",
            )

    configured_state = RedactionState(settings.redaction_policy_default_state)
    if configured_state == RedactionState.blocked:
        return RedactionDecision(
            state=RedactionState.blocked,
            content=None,
            content_digest=_digest(content, settings),
            reason="secret content blocked",
        )
    if configured_state == RedactionState.digest_only:
        return RedactionDecision(
            state=RedactionState.digest_only,
            content=None,
            content_digest=_digest(content, settings),
            reason="secret content stored as digest only",
        )
    return RedactionDecision(
        state=RedactionState.redacted,
        content=secrets.redact(content),
        content_digest=_digest(content, settings),
        reason="secret content redacted",
    )
