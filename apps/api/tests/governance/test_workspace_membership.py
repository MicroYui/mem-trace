"""Workspace membership repository + permission-merge tests (ROADMAP §3.4)."""
from __future__ import annotations

import pytest

from app.governance.permissions import has_workspace_permission, principal_with_membership
from app.runtime.models import (
    Principal,
    WorkspaceMembershipRecord,
    WorkspacePermission,
)
from app.runtime.repository import InMemoryRepository


def _membership(ws, principal_id, role):
    return WorkspaceMembershipRecord(
        workspace_id=ws, principal_id=principal_id, role=role, created_by="owner-key"
    )


@pytest.mark.asyncio
async def test_upsert_get_list_membership_round_trip():
    repo = InMemoryRepository()
    m = await repo.upsert_workspace_membership(_membership("ws", "p1", "writer"))
    got = await repo.get_workspace_membership(workspace_id="ws", principal_id="p1")
    assert got is not None and got.role == "writer"
    listed = await repo.list_workspace_memberships(workspace_id="ws")
    assert [x.membership_id for x in listed] == [m.membership_id]


@pytest.mark.asyncio
async def test_upsert_membership_updates_role_in_place_preserving_identity():
    repo = InMemoryRepository()
    first = await repo.upsert_workspace_membership(_membership("ws", "p1", "reader"))
    second = await repo.upsert_workspace_membership(_membership("ws", "p1", "owner"))
    assert second.membership_id == first.membership_id  # identity preserved
    assert second.created_by == first.created_by
    listed = await repo.list_workspace_memberships(workspace_id="ws")
    assert len(listed) == 1  # not duplicated
    assert listed[0].role == "owner"


@pytest.mark.asyncio
async def test_delete_membership():
    repo = InMemoryRepository()
    m = await repo.upsert_workspace_membership(_membership("ws", "p1", "reader"))
    await repo.delete_workspace_membership(m.membership_id)
    assert await repo.get_workspace_membership(workspace_id="ws", principal_id="p1") is None


# --------------------- permission-merge logic ----------------------- #


def test_membership_grants_permission_not_in_principal():
    # A JWT principal authenticated for no workspace gains writer via membership.
    principal = Principal(principal_id="p1", kind="jwt", workspace_ids=[], roles=[])
    assert not has_workspace_permission(principal, "ws", WorkspacePermission.writer)
    merged = principal_with_membership(principal, "ws", "writer")
    assert has_workspace_permission(merged, "ws", WorkspacePermission.writer)
    assert has_workspace_permission(merged, "ws", WorkspacePermission.reader)  # writer implies reader


def test_no_membership_returns_principal_unchanged():
    principal = Principal(principal_id="p1", kind="api_key", workspace_ids=["ws"], roles=["reader"])
    assert principal_with_membership(principal, "ws", None) is principal
