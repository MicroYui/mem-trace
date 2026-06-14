from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from app.config import Settings
from app.governance.auth import authenticate_api_key, create_api_key_record, digest_api_key, key_prefix
from app.governance.permissions import require_workspace_permission
from app.runtime.models import Principal, WorkspacePermission
from app.runtime.repository import InMemoryRepository


@pytest.mark.asyncio
async def test_api_key_records_store_prefix_and_digest_never_raw_token() -> None:
    raw = "mt_live_ws1_secret_value"
    record = create_api_key_record(
        raw,
        workspace_id="ws_auth",
        principal_id="user_1",
        roles=[WorkspacePermission.reader.value],
    )

    assert record.key_prefix == key_prefix(raw)
    assert record.key_digest == digest_api_key(raw)
    assert raw not in record.model_dump_json()


@pytest.mark.asyncio
async def test_db_api_key_authenticates_and_updates_last_used() -> None:
    repo = InMemoryRepository()
    raw = "mt_live_ws1_reader_secret"
    record = create_api_key_record(
        raw,
        workspace_id="ws_auth",
        principal_id="user_1",
        roles=[WorkspacePermission.reader.value],
    )
    await repo.add_api_key(record)

    principal = await authenticate_api_key(raw, repo, Settings(auth_enabled=True))

    assert principal == Principal(
        principal_id="user_1",
        kind="api_key",
        workspace_ids=["ws_auth"],
        roles=[WorkspacePermission.reader.value],
        api_key_id=record.api_key_id,
    )
    stored = await repo.get_api_key_by_prefix(record.key_prefix)
    assert stored is not None
    assert stored.last_used_at is not None


@pytest.mark.asyncio
async def test_in_memory_repository_rejects_duplicate_api_key_prefix_like_sql() -> None:
    repo = InMemoryRepository()
    await repo.add_api_key(
        create_api_key_record(
            "mt_live_sameprefix_first_secret",
            workspace_id="ws_auth",
            principal_id="user_1",
            roles=[WorkspacePermission.reader.value],
        )
    )

    duplicate = create_api_key_record(
        "mt_live_sameprefix_second_secret",
        workspace_id="ws_auth",
        principal_id="user_2",
        roles=[WorkspacePermission.reader.value],
    )

    with pytest.raises(ValueError, match="key_prefix"):
        await repo.add_api_key(duplicate)


@pytest.mark.asyncio
async def test_revoked_api_key_fails_closed() -> None:
    repo = InMemoryRepository()
    raw = "mt_live_ws1_revoked_secret"
    record = create_api_key_record(
        raw,
        workspace_id="ws_auth",
        principal_id="user_1",
        roles=[WorkspacePermission.owner.value],
    ).model_copy(update={"revoked_at": datetime.now(timezone.utc)})
    await repo.add_api_key(record)

    with pytest.raises(HTTPException) as exc:
        await authenticate_api_key(raw, repo, Settings(auth_enabled=True))

    assert exc.value.status_code == 403
    assert "revoked" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_legacy_api_key_is_disabled_once_db_keys_exist_by_default() -> None:
    repo = InMemoryRepository()
    await repo.add_api_key(
        create_api_key_record(
            "mt_live_real_secret",
            workspace_id="ws_auth",
            principal_id="user_1",
            roles=[WorkspacePermission.owner.value],
        )
    )

    with pytest.raises(HTTPException) as exc:
        await authenticate_api_key(
            "legacy-secret",
            repo,
            Settings(auth_enabled=True, api_key="legacy-secret", allow_legacy_api_key=False),
        )

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_legacy_api_key_still_works_when_table_empty_or_explicitly_allowed() -> None:
    repo = InMemoryRepository()
    principal = await authenticate_api_key(
        "legacy-secret",
        repo,
        Settings(auth_enabled=True, api_key="legacy-secret"),
    )
    assert principal.kind == "legacy_api_key"
    assert principal.workspace_ids == ["*"]
    assert WorkspacePermission.owner.value in principal.roles

    await repo.add_api_key(
        create_api_key_record(
            "mt_live_real_secret",
            workspace_id="ws_auth",
            principal_id="user_1",
            roles=[WorkspacePermission.reader.value],
        )
    )
    allowed = await authenticate_api_key(
        "legacy-secret",
        repo,
        Settings(auth_enabled=True, api_key="legacy-secret", allow_legacy_api_key=True),
    )
    assert allowed.kind == "legacy_api_key"


def test_workspace_permissions_are_workspace_scoped() -> None:
    principal = Principal(
        principal_id="user_1",
        kind="api_key",
        workspace_ids=["ws_allowed"],
        roles=[WorkspacePermission.reader.value],
        api_key_id="key_1",
    )

    require_workspace_permission(principal, "ws_allowed", WorkspacePermission.reader)
    with pytest.raises(HTTPException) as exc:
        require_workspace_permission(principal, "ws_other", WorkspacePermission.reader)

    assert exc.value.status_code == 403
