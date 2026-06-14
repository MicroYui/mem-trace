"""Admin governance helpers.

Admin APIs are intentionally default-off and owner-gated. This module keeps
that policy small and reusable before the route layer is introduced.
"""
from __future__ import annotations

import re
import secrets
from typing import Any

from fastapi import HTTPException, status

from app.config import Settings
from app.governance.auth import create_api_key_record
from app.governance.permissions import has_workspace_permission
from app.memory.secrets import is_secret_like_key, redact
from app.runtime.models import ApiKeyRecord, Principal, PublicApiKey, WorkspacePermission

_REDACTION = "[REDACTED]"
_RAW_PAYLOAD_MARKER_RE = re.compile(r"(?i)\braw[_-]?payload[_-]?ref\b")
_DESTRUCTIVE_OR_PROD_RE = re.compile(r"(?i)(rm\s+-rf|git\s+push\s+--force|/prod\b|production\s+path)")
_SECRET_HEADER_OR_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(authorization|api[_-]?key|access[_-]?token|id[_-]?token|client[_-]?secret|secret[_-]?key|password|passwd)\b\s*[:=]"
)


def require_admin_api_enabled(settings: Settings) -> None:
    if not settings.admin_api_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="admin api disabled")


def require_admin_owner(principal: Principal, workspace_id: str, settings: Settings) -> None:
    require_admin_api_enabled(settings)
    if principal.kind != "api_key" or principal.api_key_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin owner permission required")
    if "*" in principal.workspace_ids or workspace_id not in principal.workspace_ids:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin owner permission required")
    if not has_workspace_permission(principal, workspace_id, WorkspacePermission.owner):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin owner permission required")


def _redact_admin_string(value: str) -> str:
    redacted = redact(value)
    if _SECRET_HEADER_OR_ASSIGNMENT_RE.search(redacted):
        return _REDACTION
    if _RAW_PAYLOAD_MARKER_RE.search(redacted):
        return _REDACTION
    if _DESTRUCTIVE_OR_PROD_RE.search(redacted):
        return _REDACTION
    return redacted


def redact_admin_metadata(value: object) -> object:
    """Recursively redact admin/scheduler egress and audit metadata."""

    if isinstance(value, str):
        return _redact_admin_string(value)
    if isinstance(value, list):
        return [redact_admin_metadata(v) for v in value]
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            key = str(raw_key)
            out[key] = (
                _REDACTION
                if is_secret_like_key(key) or _RAW_PAYLOAD_MARKER_RE.search(key)
                else redact_admin_metadata(raw_value)
            )
        return out
    return value


_API_KEY_PREFIX = "mtk_"


def generate_api_key(
    *,
    workspace_id: str,
    principal_id: str,
    roles: list[WorkspacePermission],
    salt: str = "",
) -> tuple[ApiKeyRecord, str]:
    """Mint a new raw API key plus its persistable record.

    The raw key is returned only here; persistence stores prefix + digest. The
    caller is responsible for persisting the record and returning the raw key at
    most once in the create response.
    """
    raw = f"{_API_KEY_PREFIX}{secrets.token_urlsafe(32)}"
    record = create_api_key_record(
        raw,
        workspace_id=workspace_id,
        principal_id=principal_id,
        roles=[role.value for role in roles],
        salt=salt,
    )
    return record, raw


def to_public_api_key(record: ApiKeyRecord) -> PublicApiKey:
    """Project an ApiKeyRecord to its public, digest-free DTO."""
    return PublicApiKey(
        api_key_id=record.api_key_id,
        workspace_id=record.workspace_id,
        principal_id=record.principal_id,
        key_prefix=record.key_prefix,
        roles=list(record.roles),
        created_at=record.created_at,
        last_used_at=record.last_used_at,
        revoked_at=record.revoked_at,
    )


__all__ = [
    "generate_api_key",
    "redact_admin_metadata",
    "require_admin_api_enabled",
    "require_admin_owner",
    "to_public_api_key",
]
