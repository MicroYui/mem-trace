"""Owner-gated admin routes (default-off) for maintenance governance depth.

Admin APIs are an operator surface. They are unreachable unless
``MEMTRACE_ADMIN_API_ENABLED=true`` and require a real workspace-owner
principal when enabled. Routes live here instead of ``routes.py`` to keep the
runtime/read API module focused.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import (
    get_maintenance_enqueue,
    get_quota_service,
    get_repository,
    require_api_key,
)
from app.async_tasks.contracts import TaskEnvelope
from app.config import Settings, get_settings
from app.governance.admin import (
    generate_api_key,
    redact_admin_metadata,
    require_admin_api_enabled,
    require_admin_owner,
    to_public_api_key,
)
from app.governance.quota import QuotaService, QuotaUnit
from app.memory.lifecycle import transition_memory_status
from app.memory.maintenance import (
    redacted_run_text,
    run_workspace_maintenance,
    validate_operations,
)
from app.runtime.models import (
    AdminActionAuditRecord,
    AdminMemoryStatusRequest,
    CreateApiKeyRequest,
    CreatedApiKeyResponse,
    MaintenanceOperation,
    MaintenanceRunRecord,
    MaintenanceTaskAttemptRecord,
    MemoryConflictRecord,
    MemoryItem,
    MemoryLifecycleAuditRecord,
    MemoryStatus,
    Principal,
    PublicApiKey,
    ResolveMemoryConflictRequest,
    SchedulerRunStatus,
    StartMaintenanceRunRequest,
    UpsertQuotaLimitRequest,
    QuotaLimitRecord,
    WorkspacePermission,
)
from app.runtime.repository import Repository

router = APIRouter(prefix="/v1/admin")


def _resolve_operations(req: StartMaintenanceRunRequest, settings: Settings) -> list[MaintenanceOperation]:
    if req.operations is not None:
        return list(req.operations)
    try:
        return [MaintenanceOperation(name) for name in settings.maintenance_default_operations]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"invalid maintenance default operation: {exc}") from exc


async def _record_admin_audit(
    repo: Repository,
    *,
    workspace_id: str,
    principal_id: str,
    action: str,
    target_type: str,
    target_id: str | None,
    metadata: dict,
) -> None:
    safe_metadata = redact_admin_metadata(metadata)
    await repo.add_admin_action_audit(
        AdminActionAuditRecord(
            workspace_id=workspace_id,
            principal_id=principal_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            metadata=safe_metadata if isinstance(safe_metadata, dict) else {"detail": safe_metadata},
        )
    )


@router.post("/maintenance/runs", response_model=MaintenanceRunRecord)
async def start_maintenance_run(
    req: StartMaintenanceRunRequest,
    principal: Principal = Depends(require_api_key),
    repo: Repository = Depends(get_repository),
    quota: QuotaService = Depends(get_quota_service),
    maintenance_enqueue: Optional[Callable[[TaskEnvelope], Awaitable[str]]] = Depends(get_maintenance_enqueue),
) -> MaintenanceRunRecord:
    settings = get_settings()
    require_admin_owner(principal, req.workspace_id, settings)
    operations = _resolve_operations(req, settings)
    # Validate empty/duplicate/unknown operations before either path so the
    # enqueue path rejects the same invalid input as the direct-run path.
    try:
        validate_operations(operations)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if len(operations) > settings.maintenance_max_operations_per_run:
        raise HTTPException(status_code=400, detail="too many maintenance operations")
    await quota.check(principal, req.workspace_id, QuotaUnit.report_export)

    audit_metadata = {
        "operations": [operation.value for operation in operations],
        "dry_run": req.dry_run,
        "enqueue": req.enqueue,
        "reason": req.reason,
    }

    if req.enqueue:
        if not settings.async_tasks_enabled or maintenance_enqueue is None:
            raise HTTPException(status_code=400, detail="async tasks are not enabled")
        # Redact run-level free-form text the same way the direct-run
        # orchestrator does, so the persisted run record and the task payload
        # never carry raw secrets/destructive markers (redaction also keeps the
        # payload past TaskEnvelope's secret-safety validation).
        requested_by = f"admin:{principal.principal_id}"
        safe_reason = None if req.reason is None else redacted_run_text(req.reason)
        run = await repo.add_maintenance_run(
            MaintenanceRunRecord(
                workspace_id=req.workspace_id,
                requested_by=requested_by,
                reason=safe_reason,
                operations=operations,
                dry_run=req.dry_run,
            )
        )
        envelope = TaskEnvelope(
            task_type="maintenance.memory",
            workspace_id=req.workspace_id,
            dedupe_key=f"admin-maintenance:{run.scheduler_run_id}",
            payload={
                "operations": [operation.value for operation in operations],
                "dry_run": req.dry_run,
                "requested_by": requested_by,
                "reason": safe_reason,
            },
        )
        try:
            await maintenance_enqueue(envelope)
        except Exception as exc:  # noqa: BLE001 - mark the orphan run failed, then surface 503
            run.status = SchedulerRunStatus.failed
            run.finished_at = datetime.now(timezone.utc)
            run.summary = "enqueue failed"
            await repo.update_maintenance_run(run)
            await _record_admin_audit(
                repo,
                workspace_id=req.workspace_id,
                principal_id=principal.principal_id,
                action="enqueue_maintenance_run_failed",
                target_type="maintenance_run",
                target_id=run.scheduler_run_id,
                metadata=audit_metadata,
            )
            raise HTTPException(
                status_code=503, detail="failed to enqueue maintenance run"
            ) from exc
        await _record_admin_audit(
            repo,
            workspace_id=req.workspace_id,
            principal_id=principal.principal_id,
            action="enqueue_maintenance_run",
            target_type="maintenance_run",
            target_id=run.scheduler_run_id,
            metadata=audit_metadata,
        )
        return run

    try:
        run = await run_workspace_maintenance(
            repo,
            workspace_id=req.workspace_id,
            operations=operations,
            requested_by=f"admin:{principal.principal_id}",
            dry_run=req.dry_run,
            reason=req.reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await _record_admin_audit(
        repo,
        workspace_id=req.workspace_id,
        principal_id=principal.principal_id,
        action="start_maintenance_run",
        target_type="maintenance_run",
        target_id=run.scheduler_run_id,
        metadata=audit_metadata,
    )
    return run


@router.get("/maintenance/runs", response_model=list[MaintenanceRunRecord])
async def list_maintenance_runs(
    workspace_id: str = Query(...),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    principal: Principal = Depends(require_api_key),
    repo: Repository = Depends(get_repository),
) -> list[MaintenanceRunRecord]:
    settings = get_settings()
    require_admin_owner(principal, workspace_id, settings)
    return await repo.list_maintenance_runs(workspace_id=workspace_id, limit=limit, offset=offset)


@router.get("/maintenance/runs/{scheduler_run_id}", response_model=MaintenanceRunRecord)
async def get_maintenance_run(
    scheduler_run_id: str,
    principal: Principal = Depends(require_api_key),
    repo: Repository = Depends(get_repository),
) -> MaintenanceRunRecord:
    settings = get_settings()
    require_admin_api_enabled(settings)
    run = await repo.get_maintenance_run(scheduler_run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="maintenance run not found")
    require_admin_owner(principal, run.workspace_id, settings)
    return run


@router.get(
    "/maintenance/runs/{scheduler_run_id}/attempts",
    response_model=list[MaintenanceTaskAttemptRecord],
)
async def list_maintenance_run_attempts(
    scheduler_run_id: str,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    principal: Principal = Depends(require_api_key),
    repo: Repository = Depends(get_repository),
) -> list[MaintenanceTaskAttemptRecord]:
    settings = get_settings()
    require_admin_api_enabled(settings)
    run = await repo.get_maintenance_run(scheduler_run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="maintenance run not found")
    require_admin_owner(principal, run.workspace_id, settings)
    return await repo.list_maintenance_task_attempts(
        scheduler_run_id=scheduler_run_id, limit=limit, offset=offset
    )


@router.get("/lifecycle-audits", response_model=list[MemoryLifecycleAuditRecord])
async def list_lifecycle_audits(
    workspace_id: str = Query(...),
    memory_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    principal: Principal = Depends(require_api_key),
    repo: Repository = Depends(get_repository),
) -> list[MemoryLifecycleAuditRecord]:
    settings = get_settings()
    require_admin_owner(principal, workspace_id, settings)
    return await repo.list_lifecycle_audits(
        workspace_id=workspace_id, memory_id=memory_id, limit=limit, offset=offset
    )


# --------------------------------------------------------------------------- #
# API key administration (Task 6)
# --------------------------------------------------------------------------- #
_ALLOWED_API_KEY_ROLES = {
    WorkspacePermission.owner,
    WorkspacePermission.writer,
    WorkspacePermission.reader,
    WorkspacePermission.report_reader,
}


@router.post("/api-keys", response_model=CreatedApiKeyResponse)
async def create_api_key(
    req: CreateApiKeyRequest,
    principal: Principal = Depends(require_api_key),
    repo: Repository = Depends(get_repository),
) -> CreatedApiKeyResponse:
    settings = get_settings()
    require_admin_owner(principal, req.workspace_id, settings)
    if req.workspace_id == "*":
        raise HTTPException(status_code=400, detail="wildcard workspace api keys are not allowed")
    if not req.principal_id:
        raise HTTPException(status_code=400, detail="principal_id required")
    if not req.roles:
        raise HTTPException(status_code=400, detail="roles must not be empty")
    if any(role not in _ALLOWED_API_KEY_ROLES for role in req.roles):
        raise HTTPException(status_code=400, detail="invalid workspace role")
    record, raw = generate_api_key(
        workspace_id=req.workspace_id,
        principal_id=req.principal_id,
        roles=req.roles,
        salt=settings.api_key_digest_salt,
    )
    stored = await repo.add_api_key(record)
    await _record_admin_audit(
        repo,
        workspace_id=req.workspace_id,
        principal_id=principal.principal_id,
        action="create_api_key",
        target_type="api_key",
        target_id=stored.api_key_id,
        metadata={"principal_id": req.principal_id, "roles": [role.value for role in req.roles]},
    )
    return CreatedApiKeyResponse(api_key=to_public_api_key(stored), raw_api_key=raw)


@router.get("/api-keys", response_model=list[PublicApiKey])
async def list_api_keys(
    workspace_id: str = Query(...),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    principal: Principal = Depends(require_api_key),
    repo: Repository = Depends(get_repository),
) -> list[PublicApiKey]:
    settings = get_settings()
    require_admin_owner(principal, workspace_id, settings)
    records = await repo.list_api_keys(workspace_id=workspace_id, limit=limit, offset=offset)
    return [to_public_api_key(record) for record in records]


@router.post("/api-keys/{api_key_id}/revoke", response_model=PublicApiKey)
async def revoke_api_key(
    api_key_id: str,
    principal: Principal = Depends(require_api_key),
    repo: Repository = Depends(get_repository),
) -> PublicApiKey:
    settings = get_settings()
    require_admin_api_enabled(settings)
    record = await repo.get_api_key(api_key_id)
    if record is None:
        raise HTTPException(status_code=404, detail="api key not found")
    require_admin_owner(principal, record.workspace_id, settings)
    revoked = await repo.revoke_api_key(api_key_id, revoked_at=datetime.now(timezone.utc))
    if revoked is None:
        raise HTTPException(status_code=404, detail="api key not found")
    await _record_admin_audit(
        repo,
        workspace_id=record.workspace_id,
        principal_id=principal.principal_id,
        action="revoke_api_key",
        target_type="api_key",
        target_id=api_key_id,
        metadata={"principal_id": record.principal_id},
    )
    return to_public_api_key(revoked)


# --------------------------------------------------------------------------- #
# Quota override administration (Task 7)
# --------------------------------------------------------------------------- #
@router.get("/quota-limits", response_model=list[QuotaLimitRecord])
async def list_quota_limits(
    workspace_id: str = Query(...),
    principal_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    principal: Principal = Depends(require_api_key),
    repo: Repository = Depends(get_repository),
) -> list[QuotaLimitRecord]:
    settings = get_settings()
    require_admin_owner(principal, workspace_id, settings)
    return await repo.list_quota_limits(
        workspace_id=workspace_id, principal_id=principal_id, limit=limit, offset=offset
    )


@router.put("/quota-limits", response_model=QuotaLimitRecord)
async def upsert_quota_limit(
    req: UpsertQuotaLimitRequest,
    principal: Principal = Depends(require_api_key),
    repo: Repository = Depends(get_repository),
) -> QuotaLimitRecord:
    settings = get_settings()
    require_admin_owner(principal, req.workspace_id, settings)
    if req.limit < 0:
        raise HTTPException(status_code=400, detail="limit must be >= 0")
    if req.window_seconds < 1:
        raise HTTPException(status_code=400, detail="window_seconds must be >= 1")
    # Always hand a fresh record to upsert_quota_limit; the repository merges by
    # (workspace_id, principal_id, unit) identity and preserves the existing id
    # plus creation audit. Selecting a "base" here by (workspace, principal)
    # alone could wrongly reuse a different unit's row and break identity.
    record = QuotaLimitRecord(
        workspace_id=req.workspace_id,
        principal_id=req.principal_id,
        unit=req.unit,
        limit=req.limit,
        window_seconds=req.window_seconds,
        created_by=f"admin:{principal.principal_id}",
    )
    stored = await repo.upsert_quota_limit(record)
    await _record_admin_audit(
        repo,
        workspace_id=req.workspace_id,
        principal_id=principal.principal_id,
        action="upsert_quota_limit",
        target_type="quota_limit",
        target_id=stored.quota_limit_id,
        metadata={
            "unit": str(req.unit),
            "limit": req.limit,
            "window_seconds": req.window_seconds,
            "target_principal_id": req.principal_id,
        },
    )
    return stored


@router.delete("/quota-limits/{quota_limit_id}", status_code=204)
async def delete_quota_limit(
    quota_limit_id: str,
    workspace_id: str = Query(...),
    principal: Principal = Depends(require_api_key),
    repo: Repository = Depends(get_repository),
) -> None:
    settings = get_settings()
    require_admin_owner(principal, workspace_id, settings)
    target = await repo.get_quota_limit(quota_limit_id)
    if target is None or target.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="quota limit not found")
    await repo.delete_quota_limit(quota_limit_id)
    await _record_admin_audit(
        repo,
        workspace_id=workspace_id,
        principal_id=principal.principal_id,
        action="delete_quota_limit",
        target_type="quota_limit",
        target_id=quota_limit_id,
        metadata={"unit": str(target.unit)},
    )


# --------------------------------------------------------------------------- #
# Manual lifecycle + conflict resolution administration (Task 8)
# --------------------------------------------------------------------------- #
@router.post("/memories/{memory_id}/status", response_model=MemoryItem)
async def admin_set_memory_status(
    memory_id: str,
    req: AdminMemoryStatusRequest,
    principal: Principal = Depends(require_api_key),
    repo: Repository = Depends(get_repository),
) -> MemoryItem:
    settings = get_settings()
    require_admin_api_enabled(settings)
    memory = await repo.get_memory(memory_id)
    if memory is None:
        raise HTTPException(status_code=404, detail="memory not found")
    require_admin_owner(principal, memory.workspace_id, settings)
    try:
        updated, audit = transition_memory_status(
            memory,
            req.to_status,
            reason=req.reason,
            actor=f"admin:{principal.principal_id}",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    stored, _ = await repo.transition_memory_with_audit(updated, audit)
    await _record_admin_audit(
        repo,
        workspace_id=memory.workspace_id,
        principal_id=principal.principal_id,
        action="set_memory_status",
        target_type="memory",
        target_id=memory_id,
        metadata={"to_status": req.to_status.value, "reason": req.reason},
    )
    return stored


@router.post("/memory-conflicts/{conflict_id}/resolve", response_model=MemoryConflictRecord)
async def admin_resolve_memory_conflict(
    conflict_id: str,
    req: ResolveMemoryConflictRequest,
    principal: Principal = Depends(require_api_key),
    repo: Repository = Depends(get_repository),
) -> MemoryConflictRecord:
    settings = get_settings()
    require_admin_api_enabled(settings)
    conflict = await repo.get_memory_conflict(conflict_id)
    if conflict is None:
        raise HTTPException(status_code=404, detail="memory conflict not found")
    require_admin_owner(principal, conflict.workspace_id, settings)
    # Only open conflicts may be adjudicated. Re-resolving a resolved conflict
    # could flip resolved_false_positive -> choose_winner and supersede memories
    # the first decision chose to keep, with no rollback.
    if conflict.status != "open":
        raise HTTPException(status_code=409, detail="memory conflict already resolved")

    if req.action == "mark_false_positive":
        resolved = conflict.model_copy(
            update={"status": "resolved_false_positive", "resolved_at": datetime.now(timezone.utc)}
        )
        stored = await repo.update_memory_conflict(resolved)
        await _record_admin_audit(
            repo,
            workspace_id=conflict.workspace_id,
            principal_id=principal.principal_id,
            action="resolve_conflict_false_positive",
            target_type="memory_conflict",
            target_id=conflict_id,
            metadata={"reason": req.reason},
        )
        return stored

    # choose_winner
    if not req.winner_memory_id:
        raise HTTPException(status_code=400, detail="winner_memory_id required for choose_winner")
    if req.winner_memory_id not in conflict.memory_ids:
        raise HTTPException(status_code=400, detail="winner_memory_id must belong to the conflict")
    winner = await repo.get_memory(req.winner_memory_id)
    if winner is None or winner.workspace_id != conflict.workspace_id:
        raise HTTPException(status_code=400, detail="winner_memory_id must resolve to the conflict workspace")

    # Pre-validate every loser transition before persisting any, so a mid-loop
    # failure cannot leave some losers superseded while the conflict stays open.
    # (transition_memory_with_audit is per-memory; this minimizes the partial
    # state window without claiming cross-memory atomicity.)
    planned: list[tuple[MemoryItem, MemoryLifecycleAuditRecord]] = []
    for loser_id in conflict.memory_ids:
        if loser_id == req.winner_memory_id:
            continue
        loser = await repo.get_memory(loser_id)
        if loser is None or loser.status == MemoryStatus.superseded:
            continue
        try:
            updated, audit = transition_memory_status(
                loser,
                MemoryStatus.superseded,
                reason=req.reason,
                actor=f"admin:{principal.principal_id}",
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        updated = updated.model_copy(update={"superseded_by": req.winner_memory_id})
        planned.append((updated, audit))

    for updated, audit in planned:
        await repo.transition_memory_with_audit(updated, audit)

    resolved = conflict.model_copy(
        update={"status": "resolved_choose_winner", "resolved_at": datetime.now(timezone.utc)}
    )
    stored = await repo.update_memory_conflict(resolved)
    await _record_admin_audit(
        repo,
        workspace_id=conflict.workspace_id,
        principal_id=principal.principal_id,
        action="resolve_conflict_choose_winner",
        target_type="memory_conflict",
        target_id=conflict_id,
        metadata={"winner_memory_id": req.winner_memory_id, "reason": req.reason},
    )
    return stored


__all__ = ["router"]
