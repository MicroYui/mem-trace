"""HTTP routes for the MemTrace runtime (P0)."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_runtime
from app.runtime.memory_runtime import (
    MemoryRuntime,
    RunNotFoundError,
    StepNotFoundError,
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
    MemoryItem,
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
    WriteEventRequest,
    WriteEventResult,
)

router = APIRouter(prefix="/v1")


# --------------------------------------------------------------------------- #
# Runtime write APIs
# --------------------------------------------------------------------------- #
@router.post("/runs", response_model=AgentRun)
async def create_run(req: StartRunRequest, rt: MemoryRuntime = Depends(get_runtime)) -> AgentRun:
    return await rt.start_run(req)


@router.post("/steps/start", response_model=AgentStep)
async def start_step(req: StartStepRequest, rt: MemoryRuntime = Depends(get_runtime)) -> AgentStep:
    try:
        return await rt.start_step(req)
    except (RunNotFoundError, StepNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/events", response_model=WriteEventResult)
async def write_event(req: WriteEventRequest, rt: MemoryRuntime = Depends(get_runtime)) -> WriteEventResult:
    try:
        return await rt.write_event(req)
    except (RunNotFoundError, StepNotFoundError) as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/steps/finish", response_model=FinishStepResult)
async def finish_step(req: FinishStepRequest, rt: MemoryRuntime = Depends(get_runtime)) -> FinishStepResult:
    try:
        return await rt.finish_step(req)
    except StepNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/context/retrieve", response_model=MemoryContext)
async def retrieve_context(req: RetrievalRequest, rt: MemoryRuntime = Depends(get_runtime)) -> MemoryContext:
    try:
        return await rt.retrieve_context(req)
    except RunNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/branches/rollback", response_model=RollbackResult)
async def rollback_branch(req: RollbackRequest, rt: MemoryRuntime = Depends(get_runtime)) -> RollbackResult:
    try:
        return await rt.rollback_branch(req)
    except StepNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/runs/{run_id}/complete", response_model=CompleteRunResult)
async def complete_run(
    run_id: str, req: CompleteRunRequest, rt: MemoryRuntime = Depends(get_runtime)
) -> CompleteRunResult:
    # The path parameter is authoritative for the run id.
    req = req.model_copy(update={"run_id": run_id})
    try:
        return await rt.complete_run(req)
    except RunNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/sessions/{session_id}/flush", response_model=FlushResult)
async def flush_session(session_id: str, rt: MemoryRuntime = Depends(get_runtime)) -> FlushResult:
    """Force extraction of a session's buffered candidates (architecture.md §12.1)."""
    return await rt.flush_session(session_id)


@router.post("/sessions/flush", response_model=FlushResult)
async def flush_session_by_body(req: FlushRequest, rt: MemoryRuntime = Depends(get_runtime)) -> FlushResult:
    """Flush a session id supplied in JSON so arbitrary string ids remain HTTP-safe."""
    return await rt.flush_session(req.session_id)


# --------------------------------------------------------------------------- #
# Read APIs
# --------------------------------------------------------------------------- #
@router.get("/runs/{run_id}/timeline", response_model=list[AgentEvent])
async def get_timeline(run_id: str, rt: MemoryRuntime = Depends(get_runtime)) -> list[AgentEvent]:
    return await rt.get_timeline(run_id)


@router.get("/runs/{run_id}/state-tree", response_model=list[StateNode])
async def get_state_tree(run_id: str, rt: MemoryRuntime = Depends(get_runtime)) -> list[StateNode]:
    return await rt.get_state_tree(run_id)


@router.get("/runs/{run_id}/profile", response_model=list[ProfileEvent])
async def get_profile(run_id: str, rt: MemoryRuntime = Depends(get_runtime)) -> list[ProfileEvent]:
    return await rt.get_profile(run_id)


@router.get("/runs/{run_id}/steps", response_model=list[AgentStep])
async def get_steps(run_id: str, rt: MemoryRuntime = Depends(get_runtime)) -> list[AgentStep]:
    return await rt.get_steps(run_id)


@router.get("/access/{access_id}", response_model=AccessInspection)
async def get_access(access_id: str, rt: MemoryRuntime = Depends(get_runtime)) -> AccessInspection:
    result = await rt.inspect_access(access_id)
    if result is None:
        raise HTTPException(status_code=404, detail="access not found")
    return result


@router.get("/replay/access/{access_id}", response_model=ReplayRetrievalResult)
async def replay_access(access_id: str, rt: MemoryRuntime = Depends(get_runtime)) -> ReplayRetrievalResult:
    access = await rt._repo.get_access_log(access_id)  # noqa: SLF001 - read-through for API error mapping
    if access is None:
        raise HTTPException(status_code=404, detail="access not found")
    if access.run_id is not None and await rt._repo.get_run(access.run_id) is None:  # noqa: SLF001
        raise HTTPException(status_code=404, detail="run not found")
    result = await rt.replay_access(access_id)
    if result is None:
        raise HTTPException(status_code=404, detail="access not found")
    return result


@router.get("/replay/runs/{run_id}", response_model=RunReplayResult)
async def replay_run(run_id: str, rt: MemoryRuntime = Depends(get_runtime)) -> RunReplayResult:
    if await rt._repo.get_run(run_id) is None:  # noqa: SLF001 - read-through for API error mapping
        raise HTTPException(status_code=404, detail="run not found")
    return await rt.replay_run(run_id)


@router.get("/observability/summary", response_model=ObservabilitySummary)
async def observability_summary(
    workspace_id: Optional[str] = Query(default=None),
    run_id: Optional[str] = Query(default=None),
    rt: MemoryRuntime = Depends(get_runtime),
) -> ObservabilitySummary:
    return await rt.observability_summary(workspace_id=workspace_id, run_id=run_id)


@router.post("/observability/reports", response_model=ObservabilityReportResult)
async def write_observability_report(
    req: ObservabilityReportRequest,
    rt: MemoryRuntime = Depends(get_runtime),
) -> ObservabilityReportResult:
    try:
        return await rt.write_observability_report(req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/steps/{step_id}", response_model=AgentStep)
async def get_step(step_id: str, rt: MemoryRuntime = Depends(get_runtime)) -> AgentStep:
    step = await rt._repo.get_step(step_id)  # noqa: SLF001 - read-through for P0
    if step is None:
        raise HTTPException(status_code=404, detail="step not found")
    return step


@router.get("/memories", response_model=list[MemoryItem])
async def list_memories(
    run_id: Optional[str] = Query(default=None),
    workspace_id: Optional[str] = Query(default=None),
    rt: MemoryRuntime = Depends(get_runtime),
) -> list[MemoryItem]:
    return await rt.list_memories(workspace_id=workspace_id, run_id=run_id)


@router.get("/dashboard/tables", response_model=DashboardTables)
async def dashboard_tables(
    workspace_id: Optional[str] = Query(default=None),
    rt: MemoryRuntime = Depends(get_runtime),
) -> DashboardTables:
    return await rt.dashboard_tables(workspace_id=workspace_id)


__all__ = ["router"]
