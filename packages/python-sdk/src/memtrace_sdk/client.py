from __future__ import annotations

from typing import Optional

import httpx

from app.runtime.memory_runtime import MemoryRuntime

from memtrace_sdk.backends import Backend, HttpBackend, InProcessBackend
from memtrace_sdk.types import (
    AccessInspection,
    AgentEvent,
    AgentRun,
    AgentStep,
    CompleteRunRequest,
    CompleteRunResult,
    DashboardTables,
    FinishStepRequest,
    FinishStepResult,
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
    WriteEventRequest,
    WriteEventResult,
)


class MemTrace:
    """Unified async MemTrace SDK facade over interchangeable backends."""

    def __init__(self, backend: Backend):
        self._backend = backend

    @classmethod
    def in_process(cls, runtime: MemoryRuntime) -> "MemTrace":
        return cls(InProcessBackend(runtime))

    @classmethod
    def in_memory(cls, **runtime_kwargs) -> "MemTrace":
        return cls(InProcessBackend.in_memory(**runtime_kwargs))

    @classmethod
    def http(
        cls,
        base_url: str,
        *,
        api_key: Optional[str] = None,
        client: Optional[httpx.AsyncClient] = None,
    ) -> "MemTrace":
        return cls(HttpBackend(base_url, api_key=api_key, client=client))

    async def __aenter__(self) -> "MemTrace":
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        close = getattr(self._backend, "aclose", None)
        if close is not None:
            await close()

    async def start_run(self, request: StartRunRequest) -> AgentRun:
        return await self._backend.start_run(request)

    async def start_step(self, request: StartStepRequest) -> AgentStep:
        return await self._backend.start_step(request)

    async def write_event(self, request: WriteEventRequest) -> WriteEventResult:
        if request.event_source is None:
            request = request.model_copy(update={"event_source": "sdk"})
        return await self._backend.write_event(request)

    async def finish_step(self, request: FinishStepRequest) -> FinishStepResult:
        return await self._backend.finish_step(request)

    async def rollback_branch(self, request: RollbackRequest) -> RollbackResult:
        return await self._backend.rollback_branch(request)

    async def complete_run(self, request: CompleteRunRequest) -> CompleteRunResult:
        return await self._backend.complete_run(request)

    async def retrieve_context(self, request: RetrievalRequest) -> MemoryContext:
        return await self._backend.retrieve_context(request)

    async def flush_session(self, session_id: str) -> FlushResult:
        return await self._backend.flush_session(session_id)

    async def get_timeline(self, run_id: str) -> list[AgentEvent]:
        return await self._backend.get_timeline(run_id)

    async def get_state_tree(self, run_id: str) -> list[StateNode]:
        return await self._backend.get_state_tree(run_id)

    async def get_steps(self, run_id: str) -> list[AgentStep]:
        return await self._backend.get_steps(run_id)

    async def get_step(self, step_id: str) -> AgentStep:
        return await self._backend.get_step(step_id)

    async def get_profile(self, run_id: str) -> list[ProfileEvent]:
        return await self._backend.get_profile(run_id)

    async def list_memories(
        self, *, workspace_id: Optional[str] = None, run_id: Optional[str] = None
    ) -> list[MemoryItem]:
        return await self._backend.list_memories(workspace_id=workspace_id, run_id=run_id)

    async def inspect_access(self, access_id: str) -> AccessInspection:
        return await self._backend.inspect_access(access_id)

    async def replay_access(self, access_id: str) -> ReplayRetrievalResult:
        return await self._backend.replay_access(access_id)

    async def replay_run(self, run_id: str) -> RunReplayResult:
        return await self._backend.replay_run(run_id)

    async def observability_summary(
        self, *, workspace_id: Optional[str] = None, run_id: Optional[str] = None
    ) -> ObservabilitySummary:
        return await self._backend.observability_summary(workspace_id=workspace_id, run_id=run_id)

    async def write_observability_report(
        self, request: ObservabilityReportRequest
    ) -> ObservabilityReportResult:
        return await self._backend.write_observability_report(request)

    async def dashboard_tables(self, *, workspace_id: Optional[str] = None) -> DashboardTables:
        return await self._backend.dashboard_tables(workspace_id=workspace_id)

    async def list_memory_versions(self, memory_id: str) -> list[MemoryVersionRecord]:
        return await self._backend.list_memory_versions(memory_id)

    async def list_memory_conflicts(
        self,
        *,
        workspace_id: str,
        memory_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> list[MemoryConflictRecord]:
        return await self._backend.list_memory_conflicts(
            workspace_id=workspace_id,
            memory_id=memory_id,
            status=status,
        )
