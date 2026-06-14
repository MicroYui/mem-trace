"""HTTP routes for the MemTrace runtime (P0)."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse

from app.api.dashboard_ui import render_dashboard_html
from app.api.deps import get_quota_service, get_runtime, get_telemetry_service, require_api_key
from app.config import get_settings
from app.governance.admin import require_admin_owner
from app.governance.permissions import require_workspace_permission
from app.governance.quota import QuotaService, QuotaUnit
from app.runtime.memory_runtime import (
    MemoryRuntime,
    RunNotFoundError,
    StepNotFoundError,
    StateTreeError,
)
from app.runtime.models import (
    AccessInspection,
    AgentEvent,
    AgentRun,
    AgentStep,
    CompleteRunRequest,
    CompleteRunResult,
    DashboardTables,
    FinishStepRequest,
    FinishStepResult,
    FlushRequest,
    FlushResult,
    MemoryContext,
    MemoryConflictRecord,
    MemoryItem,
    MemoryVersionRecord,
    ObservabilityReportRequest,
    ObservabilityReportResult,
    ObservabilitySummary,
    ProfileEvent,
    ReplayRetrievalResult,
    RetrievalRequest,
    RollbackRequest,
    RollbackResult,
    RunReplayResult,
    StartRunRequest,
    StartStepRequest,
    StateNode,
    TelemetryExportRequest,
    TelemetryExportResponse,
    WriteEventRequest,
    WriteEventResult,
    Principal,
    WorkspacePermission,
)
from app.telemetry.service import TelemetryService

router = APIRouter(prefix="/v1")


def _authz(principal: Principal, workspace_id: str, permission: WorkspacePermission) -> None:
    require_workspace_permission(principal, workspace_id, permission)


async def _workspace_for_run_or_404(rt: MemoryRuntime, run_id: str) -> str:
    workspace_id = await rt.workspace_for_run(run_id)
    if workspace_id is None:
        raise HTTPException(status_code=404, detail="run not found")
    return workspace_id


async def _workspace_for_run_with_optional_filter_or_404(
    rt: MemoryRuntime,
    run_id: str,
    workspace_id: str | None,
) -> str:
    actual_workspace_id = await _workspace_for_run_or_404(rt, run_id)
    if workspace_id is not None and workspace_id != actual_workspace_id:
        raise HTTPException(status_code=400, detail="workspace mismatch")
    return actual_workspace_id


async def _authz_run_if_required(
    principal: Principal,
    rt: MemoryRuntime,
    run_id: str,
    permission: WorkspacePermission,
) -> None:
    if principal.kind == "anonymous":
        return
    _authz(principal, await _workspace_for_run_or_404(rt, run_id), permission)


async def _workspace_for_step_or_404(rt: MemoryRuntime, step_id: str) -> str:
    workspace_id = await rt.workspace_for_step(step_id)
    if workspace_id is None:
        raise HTTPException(status_code=404, detail="step not found")
    return workspace_id


async def _workspace_for_access_or_404(rt: MemoryRuntime, access_id: str) -> str:
    workspace_id = await rt.workspace_for_access(access_id)
    if workspace_id is None:
        raise HTTPException(status_code=404, detail="access not found")
    return workspace_id


async def _workspace_for_memory_or_404(rt: MemoryRuntime, memory_id: str) -> str:
    workspace_id = await rt.workspace_for_memory(memory_id)
    if workspace_id is None:
        raise HTTPException(status_code=404, detail="memory not found")
    return workspace_id


# --------------------------------------------------------------------------- #
# Runtime write APIs
# --------------------------------------------------------------------------- #
@router.post("/runs", response_model=AgentRun)
async def create_run(
    req: StartRunRequest,
    principal: Principal = Depends(require_api_key),
    rt: MemoryRuntime = Depends(get_runtime),
    quota: QuotaService = Depends(get_quota_service),
) -> AgentRun:
    workspace_id = req.workspace_id or rt.default_workspace_id
    _authz(principal, workspace_id, WorkspacePermission.writer)
    await quota.check(principal, workspace_id, QuotaUnit.write_event)
    return await rt.start_run(req)


@router.post("/steps/start", response_model=AgentStep)
async def start_step(
    req: StartStepRequest,
    principal: Principal = Depends(require_api_key),
    rt: MemoryRuntime = Depends(get_runtime),
    quota: QuotaService = Depends(get_quota_service),
) -> AgentStep:
    try:
        workspace_id = await _workspace_for_run_or_404(rt, req.run_id)
        _authz(principal, workspace_id, WorkspacePermission.writer)
        await quota.check(principal, workspace_id, QuotaUnit.write_event)
        return await rt.start_step(req)
    except (RunNotFoundError, StepNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    except StateTreeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/events", response_model=WriteEventResult)
async def write_event(
    req: WriteEventRequest,
    principal: Principal = Depends(require_api_key),
    rt: MemoryRuntime = Depends(get_runtime),
    quota: QuotaService = Depends(get_quota_service),
) -> WriteEventResult:
    try:
        workspace_id = await _workspace_for_run_or_404(rt, req.run_id)
        _authz(principal, workspace_id, WorkspacePermission.writer)
        await quota.check(principal, workspace_id, QuotaUnit.write_event)
        if req.extraction_mode is not None and req.extraction_mode.value == "async":
            await quota.check(principal, workspace_id, QuotaUnit.async_task_enqueue)
        return await rt.write_event(req)
    except (RunNotFoundError, StepNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/steps/finish", response_model=FinishStepResult)
async def finish_step(
    req: FinishStepRequest,
    principal: Principal = Depends(require_api_key),
    rt: MemoryRuntime = Depends(get_runtime),
    quota: QuotaService = Depends(get_quota_service),
) -> FinishStepResult:
    try:
        workspace_id = await _workspace_for_run_or_404(rt, req.run_id)
        _authz(principal, workspace_id, WorkspacePermission.writer)
        await quota.check(principal, workspace_id, QuotaUnit.write_event)
        return await rt.finish_step(req)
    except (RunNotFoundError, StepNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    except StateTreeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/context/retrieve", response_model=MemoryContext)
async def retrieve_context(
    req: RetrievalRequest,
    principal: Principal = Depends(require_api_key),
    rt: MemoryRuntime = Depends(get_runtime),
    quota: QuotaService = Depends(get_quota_service),
) -> MemoryContext:
    try:
        workspace_id = await _workspace_for_run_or_404(rt, req.run_id)
        if req.workspace_id is not None and req.workspace_id != workspace_id:
            raise HTTPException(status_code=400, detail="workspace mismatch")
        _authz(principal, workspace_id, WorkspacePermission.reader)
        await quota.check(principal, workspace_id, QuotaUnit.retrieve_context)
        return await rt.retrieve_context(req)
    except (RunNotFoundError, StepNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    except StateTreeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/branches/rollback", response_model=RollbackResult)
async def rollback_branch(
    req: RollbackRequest,
    principal: Principal = Depends(require_api_key),
    rt: MemoryRuntime = Depends(get_runtime),
    quota: QuotaService = Depends(get_quota_service),
) -> RollbackResult:
    try:
        workspace_id = await _workspace_for_run_or_404(rt, req.run_id)
        _authz(principal, workspace_id, WorkspacePermission.writer)
        await quota.check(principal, workspace_id, QuotaUnit.write_event)
        return await rt.rollback_branch(req)
    except (RunNotFoundError, StepNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    except StateTreeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/runs/{run_id}/complete", response_model=CompleteRunResult)
async def complete_run(
    run_id: str,
    req: CompleteRunRequest,
    principal: Principal = Depends(require_api_key),
    rt: MemoryRuntime = Depends(get_runtime),
    quota: QuotaService = Depends(get_quota_service),
) -> CompleteRunResult:
    # The path parameter is authoritative for the run id.
    req = req.model_copy(update={"run_id": run_id})
    try:
        workspace_id = await _workspace_for_run_or_404(rt, run_id)
        _authz(principal, workspace_id, WorkspacePermission.writer)
        await quota.check(principal, workspace_id, QuotaUnit.write_event)
        return await rt.complete_run(req)
    except RunNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/sessions/{session_id}/flush", response_model=FlushResult)
async def flush_session(
    session_id: str,
    workspace_id: Optional[str] = Query(default=None),
    principal: Principal = Depends(require_api_key),
    rt: MemoryRuntime = Depends(get_runtime),
    quota: QuotaService = Depends(get_quota_service),
) -> FlushResult:
    """Force extraction of a session's buffered candidates (architecture.md §12.1)."""
    if workspace_id is not None:
        _authz(principal, workspace_id, WorkspacePermission.writer)
        await quota.check(principal, workspace_id, QuotaUnit.write_event)
    elif principal.kind != "anonymous" and "*" not in principal.workspace_ids:
        raise HTTPException(status_code=403, detail="workspace_id required for authorized session flush")
    return await rt.flush_session(session_id, workspace_id=workspace_id)


@router.post("/sessions/flush", response_model=FlushResult)
async def flush_session_by_body(
    req: FlushRequest,
    workspace_id: Optional[str] = Query(default=None),
    principal: Principal = Depends(require_api_key),
    rt: MemoryRuntime = Depends(get_runtime),
    quota: QuotaService = Depends(get_quota_service),
) -> FlushResult:
    """Flush a session id supplied in JSON so arbitrary string ids remain HTTP-safe."""
    if workspace_id is not None:
        _authz(principal, workspace_id, WorkspacePermission.writer)
        await quota.check(principal, workspace_id, QuotaUnit.write_event)
    elif principal.kind != "anonymous" and "*" not in principal.workspace_ids:
        raise HTTPException(status_code=403, detail="workspace_id required for authorized session flush")
    return await rt.flush_session(req.session_id, workspace_id=workspace_id)


# --------------------------------------------------------------------------- #
# Read APIs
# --------------------------------------------------------------------------- #
@router.get("/runs/{run_id}/timeline", response_model=list[AgentEvent])
async def get_timeline(
    run_id: str,
    principal: Principal = Depends(require_api_key),
    rt: MemoryRuntime = Depends(get_runtime),
) -> list[AgentEvent]:
    await _authz_run_if_required(principal, rt, run_id, WorkspacePermission.reader)
    return await rt.get_timeline(run_id)


@router.get("/runs/{run_id}/state-tree", response_model=list[StateNode])
async def get_state_tree(
    run_id: str,
    principal: Principal = Depends(require_api_key),
    rt: MemoryRuntime = Depends(get_runtime),
) -> list[StateNode]:
    await _authz_run_if_required(principal, rt, run_id, WorkspacePermission.reader)
    return await rt.get_state_tree(run_id)


@router.get("/runs/{run_id}/profile", response_model=list[ProfileEvent])
async def get_profile(
    run_id: str,
    principal: Principal = Depends(require_api_key),
    rt: MemoryRuntime = Depends(get_runtime),
) -> list[ProfileEvent]:
    await _authz_run_if_required(principal, rt, run_id, WorkspacePermission.reader)
    return await rt.get_profile(run_id)


@router.get("/runs/{run_id}/steps", response_model=list[AgentStep])
async def get_steps(
    run_id: str,
    principal: Principal = Depends(require_api_key),
    rt: MemoryRuntime = Depends(get_runtime),
) -> list[AgentStep]:
    await _authz_run_if_required(principal, rt, run_id, WorkspacePermission.reader)
    return await rt.get_steps(run_id)


@router.get("/access/{access_id}", response_model=AccessInspection)
async def get_access(
    access_id: str,
    principal: Principal = Depends(require_api_key),
    rt: MemoryRuntime = Depends(get_runtime),
) -> AccessInspection:
    _authz(principal, await _workspace_for_access_or_404(rt, access_id), WorkspacePermission.reader)
    result = await rt.inspect_access(access_id)
    if result is None:
        raise HTTPException(status_code=404, detail="access not found")
    return result


@router.get("/replay/access/{access_id}", response_model=ReplayRetrievalResult)
async def replay_access(
    access_id: str,
    principal: Principal = Depends(require_api_key),
    rt: MemoryRuntime = Depends(get_runtime),
    quota: QuotaService = Depends(get_quota_service),
) -> ReplayRetrievalResult:
    try:
        workspace_id = await _workspace_for_access_or_404(rt, access_id)
        _authz(principal, workspace_id, WorkspacePermission.report_reader)
        await quota.check(principal, workspace_id, QuotaUnit.replay)
        result = await rt.replay_access(access_id)
    except RunNotFoundError:
        raise HTTPException(status_code=404, detail="run not found")
    if result is None:
        raise HTTPException(status_code=404, detail="access not found")
    return result


@router.get("/replay/runs/{run_id}", response_model=RunReplayResult)
async def replay_run(
    run_id: str,
    principal: Principal = Depends(require_api_key),
    rt: MemoryRuntime = Depends(get_runtime),
    quota: QuotaService = Depends(get_quota_service),
) -> RunReplayResult:
    try:
        workspace_id = await _workspace_for_run_or_404(rt, run_id)
        _authz(principal, workspace_id, WorkspacePermission.report_reader)
        await quota.check(principal, workspace_id, QuotaUnit.replay)
        return await rt.replay_run(run_id)
    except RunNotFoundError:
        raise HTTPException(status_code=404, detail="run not found")


@router.get("/observability/summary", response_model=ObservabilitySummary)
async def observability_summary(
    workspace_id: Optional[str] = Query(default=None),
    run_id: Optional[str] = Query(default=None),
    principal: Principal = Depends(require_api_key),
    rt: MemoryRuntime = Depends(get_runtime),
) -> ObservabilitySummary:
    if run_id is not None and principal.kind != "anonymous":
        workspace_id = await _workspace_for_run_with_optional_filter_or_404(rt, run_id, workspace_id)
    if workspace_id is not None:
        _authz(principal, workspace_id, WorkspacePermission.report_reader)
    elif principal.kind != "anonymous" and "*" not in principal.workspace_ids:
        raise HTTPException(status_code=403, detail="workspace_id required")
    return await rt.observability_summary(workspace_id=workspace_id, run_id=run_id)


@router.post("/observability/reports", response_model=ObservabilityReportResult)
async def write_observability_report(
    req: ObservabilityReportRequest,
    principal: Principal = Depends(require_api_key),
    rt: MemoryRuntime = Depends(get_runtime),
    quota: QuotaService = Depends(get_quota_service),
) -> ObservabilityReportResult:
    try:
        workspace_id = req.workspace_id
        if req.run_id is not None and principal.kind != "anonymous":
            workspace_id = await _workspace_for_run_with_optional_filter_or_404(rt, req.run_id, req.workspace_id)
        if workspace_id is not None:
            _authz(principal, workspace_id, WorkspacePermission.report_reader)
            await quota.check(principal, workspace_id, QuotaUnit.report_export)
        elif principal.kind != "anonymous" and "*" not in principal.workspace_ids:
            raise HTTPException(status_code=403, detail="workspace_id required")
        return await rt.write_observability_report(req.model_copy(update={"workspace_id": workspace_id}))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/telemetry/export/runs/{run_id}", response_model=TelemetryExportResponse)
async def export_run_telemetry(
    run_id: str,
    req: TelemetryExportRequest,
    principal: Principal = Depends(require_api_key),
    rt: MemoryRuntime = Depends(get_runtime),
    telemetry: TelemetryService = Depends(get_telemetry_service),
    quota: QuotaService = Depends(get_quota_service),
) -> TelemetryExportResponse:
    workspace_id = await _workspace_for_run_or_404(rt, run_id)
    _authz(principal, workspace_id, WorkspacePermission.report_reader)
    await quota.check(principal, workspace_id, QuotaUnit.report_export)
    run = await rt.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    steps = await rt.get_steps(run_id) if req.include_steps else []
    events = await rt.get_timeline(run_id) if req.include_events else []
    result = telemetry.export_run_records(run=run, steps=steps, events=events)
    return TelemetryExportResponse(
        exported_span_count=result.exported_span_count,
        dropped_span_count=result.dropped_span_count,
        warnings=result.warnings,
    )


@router.get("/steps/{step_id}", response_model=AgentStep)
async def get_step(
    step_id: str,
    principal: Principal = Depends(require_api_key),
    rt: MemoryRuntime = Depends(get_runtime),
) -> AgentStep:
    _authz(principal, await _workspace_for_step_or_404(rt, step_id), WorkspacePermission.reader)
    step = await rt.get_step(step_id)
    if step is None:
        raise HTTPException(status_code=404, detail="step not found")
    return step


@router.get("/memories", response_model=list[MemoryItem])
async def list_memories(
    run_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    principal: Principal = Depends(require_api_key),
    rt: MemoryRuntime = Depends(get_runtime),
) -> list[MemoryItem]:
    if run_id is not None and principal.kind != "anonymous":
        workspace_id = await _workspace_for_run_with_optional_filter_or_404(rt, run_id, workspace_id)
    if workspace_id is not None:
        _authz(principal, workspace_id, WorkspacePermission.reader)
    elif principal.kind != "anonymous" and "*" not in principal.workspace_ids:
        raise HTTPException(status_code=403, detail="workspace_id required")
    return await rt.list_memories(workspace_id=workspace_id, run_id=run_id)


@router.get("/memories/{memory_id}/versions", response_model=list[MemoryVersionRecord])
async def list_memory_versions(
    memory_id: str,
    principal: Principal = Depends(require_api_key),
    rt: MemoryRuntime = Depends(get_runtime),
) -> list[MemoryVersionRecord]:
    _authz(principal, await _workspace_for_memory_or_404(rt, memory_id), WorkspacePermission.reader)
    versions = await rt.list_memory_versions(memory_id)
    if versions is None:
        raise HTTPException(status_code=404, detail="memory not found")
    return versions


@router.get("/memory-conflicts", response_model=list[MemoryConflictRecord])
async def list_memory_conflicts(
    workspace_id: str = Query(...),
    memory_id: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    principal: Principal = Depends(require_api_key),
    rt: MemoryRuntime = Depends(get_runtime),
) -> list[MemoryConflictRecord]:
    _authz(principal, workspace_id, WorkspacePermission.reader)
    return await rt.list_memory_conflicts(
        workspace_id=workspace_id,
        memory_id=memory_id,
        status=status,
    )


@router.get("/dashboard/tables", response_model=DashboardTables)
async def dashboard_tables(
    workspace_id: Optional[str] = Query(default=None),
    principal: Principal = Depends(require_api_key),
    rt: MemoryRuntime = Depends(get_runtime),
) -> DashboardTables:
    if workspace_id is not None:
        _authz(principal, workspace_id, WorkspacePermission.report_reader)
    elif principal.kind != "anonymous" and "*" not in principal.workspace_ids:
        raise HTTPException(status_code=403, detail="workspace_id required")
    # Owner-only maintenance/admin governance tables are gated behind the same
    # default-off owner policy as the /v1/admin routes; report-reader and
    # anonymous dashboard callers never see admin audit/maintenance/quota rows.
    include_admin = False
    if workspace_id is not None:
        try:
            require_admin_owner(principal, workspace_id, get_settings())
            include_admin = True
        except HTTPException:
            include_admin = False
    return await rt.dashboard_tables(workspace_id=workspace_id, include_admin=include_admin)


@router.get("/dashboard/ui", response_class=HTMLResponse, include_in_schema=False)
async def dashboard_ui() -> HTMLResponse:
    """Serve the self-contained read-only Dashboard UI.

    The page itself is a static shell with no embedded data; it calls the
    authenticated read-only APIs (``/v1/dashboard/tables`` and
    ``/v1/observability/summary``) from the browser. Auth, when enabled, is still
    enforced on those data endpoints, so serving the shell unauthenticated does
    not expose any workspace data.
    """
    return HTMLResponse(content=render_dashboard_html())


__all__ = ["router"]
