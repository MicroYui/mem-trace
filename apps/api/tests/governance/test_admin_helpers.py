from __future__ import annotations

from fastapi import HTTPException

from app.config import Settings
from app.governance.admin import redact_admin_metadata, require_admin_api_enabled, require_admin_owner
from app.runtime.models import Principal, WorkspacePermission


def test_admin_api_disabled_by_default() -> None:
    settings = Settings()

    try:
        require_admin_api_enabled(settings)
    except HTTPException as exc:
        assert exc.status_code == 404
        assert exc.detail == "admin api disabled"
    else:
        raise AssertionError("expected admin api disabled")


def test_admin_requires_owner_role_when_enabled() -> None:
    settings = Settings(admin_api_enabled=True)
    principal = Principal(
        principal_id="reader",
        kind="api_key",
        api_key_id="apikey_reader",
        workspace_ids=["ws_1"],
        roles=[WorkspacePermission.reader.value],
    )

    try:
        require_admin_owner(principal, "ws_1", settings)
    except HTTPException as exc:
        assert exc.status_code == 403
        assert exc.detail == "admin owner permission required"
    else:
        raise AssertionError("expected owner permission failure")


def test_admin_never_allows_anonymous_principal() -> None:
    settings = Settings(admin_api_enabled=True, auth_enabled=False, governance_enabled=False)
    principal = Principal(
        principal_id="anonymous",
        kind="anonymous",
        workspace_ids=["*"],
        roles=[WorkspacePermission.owner.value],
    )

    try:
        require_admin_owner(principal, "ws_1", settings)
    except HTTPException as exc:
        assert exc.status_code == 403
        assert exc.detail == "admin owner permission required"
    else:
        raise AssertionError("expected anonymous admin rejection")


def test_admin_rejects_legacy_global_api_key_principal() -> None:
    settings = Settings(admin_api_enabled=True)
    principal = Principal(
        principal_id="legacy_api_key",
        kind="legacy_api_key",
        workspace_ids=["*"],
        roles=[WorkspacePermission.owner.value],
    )

    try:
        require_admin_owner(principal, "ws_1", settings)
    except HTTPException as exc:
        assert exc.status_code == 403
        assert exc.detail == "admin owner permission required"
    else:
        raise AssertionError("expected legacy admin rejection")


def test_admin_rejects_global_db_api_key_principal() -> None:
    settings = Settings(admin_api_enabled=True)
    principal = Principal(
        principal_id="global_owner",
        kind="api_key",
        api_key_id="apikey_global",
        workspace_ids=["*"],
        roles=[WorkspacePermission.owner.value],
    )

    try:
        require_admin_owner(principal, "ws_1", settings)
    except HTTPException as exc:
        assert exc.status_code == 403
        assert exc.detail == "admin owner permission required"
    else:
        raise AssertionError("expected global api key admin rejection")


def test_admin_rejects_synthetic_api_key_without_persisted_key_id() -> None:
    settings = Settings(admin_api_enabled=True)
    principal = Principal(
        principal_id="owner",
        kind="api_key",
        workspace_ids=["ws_1"],
        roles=[WorkspacePermission.owner.value],
    )

    try:
        require_admin_owner(principal, "ws_1", settings)
    except HTTPException as exc:
        assert exc.status_code == 403
        assert exc.detail == "admin owner permission required"
    else:
        raise AssertionError("expected synthetic api key admin rejection")


def test_admin_owner_is_allowed_when_enabled() -> None:
    settings = Settings(admin_api_enabled=True)
    principal = Principal(
        principal_id="owner",
        kind="api_key",
        api_key_id="apikey_owner",
        workspace_ids=["ws_1"],
        roles=[WorkspacePermission.owner.value],
    )

    require_admin_owner(principal, "ws_1", settings)


def test_redact_admin_metadata_recurses_over_admin_output_surfaces() -> None:
    redacted = redact_admin_metadata(
        {
            "authorization": "Bearer mt_live_admin_secret",
            "raw_payload_ref": "events/raw/1",
            "nested": ["raw_payload_ref=events/raw/1", {"cmd": "rm -rf /prod now"}],
            "safe_count": 2,
        }
    )

    assert redacted["authorization"] != "Bearer mt_live_admin_secret"
    assert redacted["raw_payload_ref"] == "[REDACTED]"
    assert "raw_payload_ref" not in redacted["nested"][0]
    assert "rm -rf" not in redacted["nested"][1]["cmd"]
    assert redacted["safe_count"] == 2
