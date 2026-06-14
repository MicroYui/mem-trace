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
