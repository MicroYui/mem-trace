"""Workspace-scoped permission checks."""
from __future__ import annotations

from fastapi import HTTPException, status

from app.runtime.models import Principal, WorkspacePermission


_ROLE_GRANTS: dict[str, set[WorkspacePermission]] = {
    WorkspacePermission.owner.value: {
        WorkspacePermission.owner,
        WorkspacePermission.writer,
        WorkspacePermission.reader,
        WorkspacePermission.report_reader,
    },
    WorkspacePermission.writer.value: {WorkspacePermission.writer, WorkspacePermission.reader},
    WorkspacePermission.reader.value: {WorkspacePermission.reader},
    WorkspacePermission.report_reader.value: {WorkspacePermission.report_reader},
}


def has_workspace_permission(principal: Principal, workspace_id: str, permission: WorkspacePermission) -> bool:
    if "*" not in principal.workspace_ids and workspace_id not in principal.workspace_ids:
        return False
    granted: set[WorkspacePermission] = set()
    for role in principal.roles:
        granted.update(_ROLE_GRANTS.get(role, set()))
    return permission in granted


def require_workspace_permission(principal: Principal, workspace_id: str, permission: WorkspacePermission) -> None:
    if not has_workspace_permission(principal, workspace_id, permission):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="workspace permission denied")


def principal_with_membership(
    principal: Principal, workspace_id: str, membership_role: str | None
) -> Principal:
    """Augment a principal with a workspace-membership role (ROADMAP §3.4).

    Returns a principal whose ``workspace_ids`` include ``workspace_id`` and whose
    ``roles`` include the membership role, so ``has_workspace_permission`` grants
    access via membership even when the principal's own key/token did not list
    that workspace. A ``None`` role (no membership) returns the principal as-is.
    """
    if not membership_role:
        return principal
    workspace_ids = list(principal.workspace_ids)
    if "*" not in workspace_ids and workspace_id not in workspace_ids:
        workspace_ids.append(workspace_id)
    roles = list(principal.roles)
    if membership_role not in roles:
        roles.append(membership_role)
    return principal.model_copy(update={"workspace_ids": workspace_ids, "roles": roles})
