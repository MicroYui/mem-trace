"""Unified maintenance orchestration over durable run/attempt records."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

from app.governance.admin import redact_admin_metadata
from app.memory import scheduler
from app.runtime.models import (
    MaintenanceOperation,
    MaintenanceRunRecord,
    MaintenanceTaskAttemptRecord,
    SchedulerRunStatus,
    SchedulerTaskStatus,
)
from app.runtime.repository import Repository

OperationHandler = Callable[..., Awaitable[dict[str, Any]]]

OPERATION_HANDLERS: dict[MaintenanceOperation, OperationHandler] = {
    MaintenanceOperation.score_memory: scheduler.score_memory,
    MaintenanceOperation.decay_memory: scheduler.decay_memory,
    MaintenanceOperation.archive_memory: scheduler.archive_memory,
    MaintenanceOperation.quarantine_memory: scheduler.quarantine_memory,
    MaintenanceOperation.conflict_scan: scheduler.conflict_scan,
    MaintenanceOperation.dedup_memory: scheduler.dedup_memory,
    MaintenanceOperation.reindex_memory: scheduler.reindex_memory,
    MaintenanceOperation.summary_refresh: scheduler.summary_refresh,
    MaintenanceOperation.procedural_refresh: scheduler.procedural_refresh,
    MaintenanceOperation.profile_refresh: scheduler.profile_refresh,
}


async def run_workspace_maintenance(
    repo: Repository,
    *,
    workspace_id: str,
    operations: list[MaintenanceOperation | str],
    requested_by: str = "system",
    dry_run: bool = False,
    reason: str | None = None,
) -> MaintenanceRunRecord:
    parsed = _parse_operations(operations)
    validate_operations(parsed)
    now = _now()
    safe_requested_by = redacted_run_text(requested_by)
    safe_reason = None if reason is None else redacted_run_text(reason)
    run = await repo.add_maintenance_run(
        MaintenanceRunRecord(
            workspace_id=workspace_id,
            requested_by=safe_requested_by,
            reason=safe_reason,
            operations=parsed,
            dry_run=dry_run,
            status=SchedulerRunStatus.running,
            started_at=now,
            updated_at=now,
        )
    )

    completed = failed = skipped = 0
    warnings: list[str] = []
    for operation in parsed:
        attempt = await repo.add_maintenance_task_attempt(
            MaintenanceTaskAttemptRecord(
                scheduler_run_id=run.scheduler_run_id,
                workspace_id=workspace_id,
                operation=operation,
                status=SchedulerTaskStatus.running,
                idempotency_key=f"maintenance:{run.scheduler_run_id}:{operation.value}",
                started_at=_now(),
            )
        )
        if dry_run:
            skipped += 1
            attempt = attempt.model_copy(
                update={
                    "status": SchedulerTaskStatus.skipped,
                    "result": {
                        "operation": operation.value,
                        "workspace_id": workspace_id,
                        "reason": "dry_run",
                    },
                    "finished_at": _now(),
                    "updated_at": _now(),
                },
                deep=True,
            )
            await repo.update_maintenance_task_attempt(attempt)
            continue
        try:
            handler = OPERATION_HANDLERS[operation]
            result = await handler(
                repo,
                workspace_id=workspace_id,
                scheduler_run_id=run.scheduler_run_id,
            )
            completed += 1
            attempt = attempt.model_copy(
                update={
                    "status": SchedulerTaskStatus.completed,
                    "result": _redacted_dict(result),
                    "finished_at": _now(),
                    "updated_at": _now(),
                },
                deep=True,
            )
        except Exception as exc:  # noqa: BLE001 - per-operation failure isolation is intentional
            failed += 1
            error_summary = _error_summary(exc)
            warnings.append(f"{operation.value} failed")
            attempt = attempt.model_copy(
                update={
                    "status": SchedulerTaskStatus.failed,
                    "error_summary": error_summary,
                    "finished_at": _now(),
                    "updated_at": _now(),
                },
                deep=True,
            )
        await repo.update_maintenance_task_attempt(attempt)

    finished = _now()
    summary = {
        "operation_count": len(parsed),
        "completed_count": completed,
        "failed_count": failed,
        "skipped_count": skipped,
        "operations": [operation.value for operation in parsed],
    }
    run = run.model_copy(
        update={
            "status": SchedulerRunStatus.failed if failed else SchedulerRunStatus.completed,
            "summary": summary,
            "warnings": warnings,
            "finished_at": finished,
            "updated_at": finished,
        },
        deep=True,
    )
    return await repo.update_maintenance_run(run)


def _parse_operations(operations: list[MaintenanceOperation | str]) -> list[MaintenanceOperation]:
    return [op if isinstance(op, MaintenanceOperation) else MaintenanceOperation(str(op)) for op in operations]


def validate_operations(operations: list[MaintenanceOperation]) -> None:
    """Reject empty, duplicate, or unknown maintenance operations.

    Shared by the orchestrator and the admin route so direct-run and enqueue
    paths reject the same invalid input identically.
    """
    if not operations:
        raise ValueError("maintenance operations must not be empty")
    values = [operation.value for operation in operations]
    if len(values) != len(set(values)):
        raise ValueError("duplicate maintenance operation")
    missing = [operation.value for operation in operations if operation not in OPERATION_HANDLERS]
    if missing:
        raise ValueError(f"unknown maintenance operation: {missing[0]}")


def _redacted_dict(value: dict[str, Any]) -> dict[str, Any]:
    redacted = redact_admin_metadata(value)
    return redacted if isinstance(redacted, dict) else {"result": redacted}


def redacted_run_text(value: object) -> str:
    """Redact and cap run-level free-form admin text (requested_by/reason).

    Shared with the admin route so the enqueue path persists the same redacted
    run-level fields as the direct-run orchestrator.
    """
    return str(redact_admin_metadata(value))[:500]


def _error_summary(exc: Exception) -> str:
    raw = f"{type(exc).__name__}: {exc}"
    return redacted_run_text(raw)


def _now() -> datetime:
    return datetime.now(timezone.utc)


__all__ = [
    "OPERATION_HANDLERS",
    "redacted_run_text",
    "run_workspace_maintenance",
    "validate_operations",
]
