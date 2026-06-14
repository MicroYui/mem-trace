"""API-key authentication primitives.

Raw API keys are accepted only at the request boundary. Persistence stores a
short lookup prefix and a SHA-256 digest; comparisons use constant-time digest
checks and error messages never echo supplied tokens.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from secrets import compare_digest

from fastapi import HTTPException, status

from app.config import Settings
from app.runtime.models import ApiKeyRecord, Principal, WorkspacePermission
from app.runtime.repository import Repository


def key_prefix(raw: str, *, length: int = 12) -> str:
    return raw[:length]


def digest_api_key(raw: str, *, salt: str = "") -> str:
    material = f"{salt}:{raw}" if salt else raw
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def create_api_key_record(
    raw: str,
    *,
    workspace_id: str,
    principal_id: str,
    roles: list[str],
    salt: str = "",
) -> ApiKeyRecord:
    return ApiKeyRecord(
        workspace_id=workspace_id,
        principal_id=principal_id,
        key_prefix=key_prefix(raw),
        key_digest=digest_api_key(raw, salt=salt),
        roles=list(roles),
    )


def legacy_principal() -> Principal:
    return Principal(
        principal_id="legacy_api_key",
        kind="legacy_api_key",
        workspace_ids=["*"],
        roles=[WorkspacePermission.owner.value],
    )


def anonymous_principal() -> Principal:
    return Principal(
        principal_id="anonymous",
        kind="anonymous",
        workspace_ids=["*"],
        roles=[WorkspacePermission.owner.value],
    )


async def authenticate_api_key(raw: str, repo: Repository, settings: Settings) -> Principal:
    stored_keys = await repo.list_api_keys()
    expected_legacy = settings.api_key
    legacy_allowed = not stored_keys or settings.allow_legacy_api_key
    if expected_legacy and legacy_allowed:
        if compare_digest(raw.encode("utf-8"), expected_legacy.encode("utf-8")):
            return legacy_principal()

    record = await repo.get_api_key_by_prefix(key_prefix(raw))
    supplied_digest = digest_api_key(raw, salt=settings.api_key_digest_salt)
    if record is None or not compare_digest(supplied_digest, record.key_digest):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid api key")
    if record.revoked_at is not None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="api key revoked")
    used_at = datetime.now(timezone.utc)
    await repo.mark_api_key_used(record.api_key_id, used_at=used_at)
    return Principal(
        principal_id=record.principal_id,
        kind="api_key",
        workspace_ids=[record.workspace_id],
        roles=list(record.roles),
        api_key_id=record.api_key_id,
    )
