from __future__ import annotations

from typing import Any, Optional, Protocol, TypeVar

import httpx
from pydantic import BaseModel, TypeAdapter

from app.runtime.memory_runtime import MemoryRuntime, RunNotFoundError, StepNotFoundError, StateTreeError
from app.runtime.repository import InMemoryRepository

from memtrace_sdk.errors import BadRequestError, ForbiddenError, MemTraceError, NotFoundError
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
    WriteEventRequest,
    WriteEventResult,
)

T = TypeVar("T", bound=BaseModel)


class Backend(Protocol):
    """Transport-independent async backend contract for the MemTrace SDK."""

    async def start_run(self, request: StartRunRequest) -> AgentRun: ...

    async def start_step(self, request: StartStepRequest) -> AgentStep: ...

    async def write_event(self, request: WriteEventRequest) -> WriteEventResult: ...

    async def finish_step(self, request: FinishStepRequest) -> FinishStepResult: ...

    async def rollback_branch(self, request: RollbackRequest) -> RollbackResult: ...

    async def complete_run(self, request: CompleteRunRequest) -> CompleteRunResult: ...

    async def retrieve_context(self, request: RetrievalRequest) -> MemoryContext: ...

    async def flush_session(self, session_id: str) -> FlushResult: ...

    async def get_timeline(self, run_id: str) -> list[AgentEvent]: ...

    async def get_state_tree(self, run_id: str) -> list[StateNode]: ...

    async def get_steps(self, run_id: str) -> list[AgentStep]: ...

    async def get_step(self, step_id: str) -> AgentStep: ...

    async def get_profile(self, run_id: str) -> list[ProfileEvent]: ...

    async def list_memories(
        self, *, workspace_id: Optional[str] = None, run_id: Optional[str] = None
    ) -> list[MemoryItem]: ...

    async def inspect_access(self, access_id: str) -> AccessInspection: ...

    async def replay_access(self, access_id: str) -> ReplayRetrievalResult: ...

    async def replay_run(self, run_id: str) -> RunReplayResult: ...

    async def observability_summary(
        self, *, workspace_id: Optional[str] = None, run_id: Optional[str] = None
    ) -> ObservabilitySummary: ...

    async def write_observability_report(
        self, request: ObservabilityReportRequest
    ) -> ObservabilityReportResult: ...

    async def dashboard_tables(self, *, workspace_id: Optional[str] = None) -> DashboardTables: ...

    async def list_memory_versions(self, memory_id: str) -> list[MemoryVersionRecord]: ...

    async def list_memory_conflicts(
        self,
        *,
        workspace_id: str,
        memory_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> list[MemoryConflictRecord]: ...


class InProcessBackend:
    """Backend that calls an existing :class:`MemoryRuntime` directly."""

    def __init__(self, runtime: MemoryRuntime):
        self._runtime = runtime

    @classmethod
    def in_memory(cls, **runtime_kwargs) -> "InProcessBackend":
        """Build a zero-config in-memory runtime for demos/tests/local loops."""

        return cls(MemoryRuntime(InMemoryRepository(), **runtime_kwargs))

    async def start_run(self, request: StartRunRequest) -> AgentRun:
        return await self._runtime.start_run(request)

    async def start_step(self, request: StartStepRequest) -> AgentStep:
        try:
            return await self._runtime.start_step(request)
        except (RunNotFoundError, StepNotFoundError) as exc:
            raise NotFoundError(str(exc)) from exc
        except StateTreeError as exc:
            raise BadRequestError(str(exc)) from exc

    async def write_event(self, request: WriteEventRequest) -> WriteEventResult:
        try:
            return await self._runtime.write_event(request)
        except (RunNotFoundError, StepNotFoundError) as exc:
            raise NotFoundError(str(exc)) from exc

    async def finish_step(self, request: FinishStepRequest) -> FinishStepResult:
        try:
            return await self._runtime.finish_step(request)
        except (RunNotFoundError, StepNotFoundError) as exc:
            raise NotFoundError(str(exc)) from exc
        except StateTreeError as exc:
            raise BadRequestError(str(exc)) from exc

    async def rollback_branch(self, request: RollbackRequest) -> RollbackResult:
        try:
            return await self._runtime.rollback_branch(request)
        except (RunNotFoundError, StepNotFoundError) as exc:
            raise NotFoundError(str(exc)) from exc
        except StateTreeError as exc:
            raise BadRequestError(str(exc)) from exc

    async def complete_run(self, request: CompleteRunRequest) -> CompleteRunResult:
        try:
            return await self._runtime.complete_run(request)
        except (RunNotFoundError, StepNotFoundError) as exc:
            raise NotFoundError(str(exc)) from exc

    async def retrieve_context(self, request: RetrievalRequest) -> MemoryContext:
        try:
            return await self._runtime.retrieve_context(request)
        except (RunNotFoundError, StepNotFoundError) as exc:
            raise NotFoundError(str(exc)) from exc
        except StateTreeError as exc:
            raise BadRequestError(str(exc)) from exc

    async def flush_session(self, session_id: str) -> FlushResult:
        return await self._runtime.flush_session(session_id)

    async def get_timeline(self, run_id: str) -> list[AgentEvent]:
        return await self._runtime.get_timeline(run_id)

    async def get_state_tree(self, run_id: str) -> list[StateNode]:
        return await self._runtime.get_state_tree(run_id)

    async def get_steps(self, run_id: str) -> list[AgentStep]:
        return await self._runtime.get_steps(run_id)

    async def get_step(self, step_id: str) -> AgentStep:
        step = await self._runtime.get_step(step_id)
        if step is None:
            raise NotFoundError(f"step not found: {step_id}")
        return step

    async def get_profile(self, run_id: str) -> list[ProfileEvent]:
        return await self._runtime.get_profile(run_id)

    async def list_memories(
        self, *, workspace_id: Optional[str] = None, run_id: Optional[str] = None
    ) -> list[MemoryItem]:
        return await self._runtime.list_memories(workspace_id=workspace_id, run_id=run_id)

    async def inspect_access(self, access_id: str) -> AccessInspection:
        result = await self._runtime.inspect_access(access_id)
        if result is None:
            raise NotFoundError(f"access not found: {access_id}")
        return result

    async def replay_access(self, access_id: str) -> ReplayRetrievalResult:
        try:
            result = await self._runtime.replay_access(access_id)
        except RunNotFoundError as exc:
            raise NotFoundError(str(exc)) from exc
        if result is None:
            raise NotFoundError(f"access not found: {access_id}")
        return result

    async def replay_run(self, run_id: str) -> RunReplayResult:
        try:
            return await self._runtime.replay_run(run_id)
        except RunNotFoundError as exc:
            raise NotFoundError(str(exc)) from exc

    async def observability_summary(
        self, *, workspace_id: Optional[str] = None, run_id: Optional[str] = None
    ) -> ObservabilitySummary:
        return await self._runtime.observability_summary(workspace_id=workspace_id, run_id=run_id)

    async def write_observability_report(
        self, request: ObservabilityReportRequest
    ) -> ObservabilityReportResult:
        try:
            return await self._runtime.write_observability_report(request)
        except ValueError as exc:
            raise BadRequestError(str(exc)) from exc

    async def dashboard_tables(self, *, workspace_id: Optional[str] = None) -> DashboardTables:
        return await self._runtime.dashboard_tables(workspace_id=workspace_id)

    async def list_memory_versions(self, memory_id: str) -> list[MemoryVersionRecord]:
        result = await self._runtime.list_memory_versions(memory_id)
        if result is None:
            raise NotFoundError(f"memory not found: {memory_id}")
        return result

    async def list_memory_conflicts(
        self,
        *,
        workspace_id: str,
        memory_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> list[MemoryConflictRecord]:
        return await self._runtime.list_memory_conflicts(
            workspace_id=workspace_id,
            memory_id=memory_id,
            status=status,
        )


class HttpBackend:
    """Backend that talks to a MemTrace HTTP ``/v1`` API."""

    def __init__(
        self,
        base_url: str,
        *,
        api_key: Optional[str] = None,
        client: Optional[httpx.AsyncClient] = None,
        timeout: Optional[float | httpx.Timeout] = 30.0,
    ):
        headers = {"Authorization": f"Bearer {api_key}"} if api_key is not None else None
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=base_url.rstrip("/"), headers=headers, timeout=timeout
        )
        if client is not None:
            self._base_url = base_url.rstrip("/")
            self._headers = headers or {}
        else:
            self._base_url = ""
            self._headers = {}

    async def __aenter__(self) -> "HttpBackend":
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _url(self, path: str) -> str:
        if self._base_url:
            return f"{self._base_url}{path}"
        return path

    def _body(self, request: BaseModel) -> dict[str, Any]:
        return request.model_dump(mode="json")

    def _handle_error(self, response: httpx.Response) -> None:
        if response.status_code < 400:
            return
        try:
            detail = response.json().get("detail", response.text)
        except ValueError:
            detail = response.text
        if response.status_code == 404:
            raise NotFoundError(str(detail))
        if response.status_code == 400:
            raise BadRequestError(str(detail))
        if response.status_code in {401, 403}:
            raise ForbiddenError(str(detail))
        raise MemTraceError(f"HTTP {response.status_code}: {detail}")

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        headers = kwargs.pop("headers", None)
        if self._headers:
            headers = {**self._headers, **(headers or {})}
        response = await self._client.request(method, self._url(path), headers=headers, **kwargs)
        self._handle_error(response)
        return response.json()

    async def _get_model(self, path: str, model: type[T]) -> T:
        return model.model_validate(await self._request("GET", path))

    async def _post_model(self, path: str, request: BaseModel, model: type[T]) -> T:
        return model.model_validate(await self._request("POST", path, json=self._body(request)))

    async def _get_list(self, path: str, model: type[T]) -> list[T]:
        return TypeAdapter(list[model]).validate_python(await self._request("GET", path))

    async def start_run(self, request: StartRunRequest) -> AgentRun:
        return await self._post_model("/v1/runs", request, AgentRun)

    async def start_step(self, request: StartStepRequest) -> AgentStep:
        return await self._post_model("/v1/steps/start", request, AgentStep)

    async def write_event(self, request: WriteEventRequest) -> WriteEventResult:
        return await self._post_model("/v1/events", request, WriteEventResult)

    async def finish_step(self, request: FinishStepRequest) -> FinishStepResult:
        return await self._post_model("/v1/steps/finish", request, FinishStepResult)

    async def rollback_branch(self, request: RollbackRequest) -> RollbackResult:
        return await self._post_model("/v1/branches/rollback", request, RollbackResult)

    async def complete_run(self, request: CompleteRunRequest) -> CompleteRunResult:
        return await self._post_model(f"/v1/runs/{request.run_id}/complete", request, CompleteRunResult)

    async def retrieve_context(self, request: RetrievalRequest) -> MemoryContext:
        return await self._post_model("/v1/context/retrieve", request, MemoryContext)

    async def flush_session(self, session_id: str) -> FlushResult:
        return await self._post_model("/v1/sessions/flush", FlushRequest(session_id=session_id), FlushResult)

    async def get_timeline(self, run_id: str) -> list[AgentEvent]:
        return await self._get_list(f"/v1/runs/{run_id}/timeline", AgentEvent)

    async def get_state_tree(self, run_id: str) -> list[StateNode]:
        return await self._get_list(f"/v1/runs/{run_id}/state-tree", StateNode)

    async def get_steps(self, run_id: str) -> list[AgentStep]:
        return await self._get_list(f"/v1/runs/{run_id}/steps", AgentStep)

    async def get_step(self, step_id: str) -> AgentStep:
        return await self._get_model(f"/v1/steps/{step_id}", AgentStep)

    async def get_profile(self, run_id: str) -> list[ProfileEvent]:
        return await self._get_list(f"/v1/runs/{run_id}/profile", ProfileEvent)

    async def list_memories(
        self, *, workspace_id: Optional[str] = None, run_id: Optional[str] = None
    ) -> list[MemoryItem]:
        params = {"workspace_id": workspace_id, "run_id": run_id}
        return TypeAdapter(list[MemoryItem]).validate_python(
            await self._request(
                "GET", "/v1/memories", params={key: value for key, value in params.items() if value is not None}
            )
        )

    async def inspect_access(self, access_id: str) -> AccessInspection:
        return await self._get_model(f"/v1/access/{access_id}", AccessInspection)

    async def replay_access(self, access_id: str) -> ReplayRetrievalResult:
        return await self._get_model(f"/v1/replay/access/{access_id}", ReplayRetrievalResult)

    async def replay_run(self, run_id: str) -> RunReplayResult:
        return await self._get_model(f"/v1/replay/runs/{run_id}", RunReplayResult)

    async def observability_summary(
        self, *, workspace_id: Optional[str] = None, run_id: Optional[str] = None
    ) -> ObservabilitySummary:
        params = {"workspace_id": workspace_id, "run_id": run_id}
        return ObservabilitySummary.model_validate(
            await self._request(
                "GET",
                "/v1/observability/summary",
                params={key: value for key, value in params.items() if value is not None},
            )
        )

    async def write_observability_report(
        self, request: ObservabilityReportRequest
    ) -> ObservabilityReportResult:
        return await self._post_model("/v1/observability/reports", request, ObservabilityReportResult)

    async def dashboard_tables(self, *, workspace_id: Optional[str] = None) -> DashboardTables:
        params = {"workspace_id": workspace_id} if workspace_id is not None else None
        return DashboardTables.model_validate(
            await self._request("GET", "/v1/dashboard/tables", params=params)
        )

    async def list_memory_versions(self, memory_id: str) -> list[MemoryVersionRecord]:
        return await self._get_list(f"/v1/memories/{memory_id}/versions", MemoryVersionRecord)

    async def list_memory_conflicts(
        self,
        *,
        workspace_id: str,
        memory_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> list[MemoryConflictRecord]:
        params = {"workspace_id": workspace_id, "memory_id": memory_id, "status": status}
        return TypeAdapter(list[MemoryConflictRecord]).validate_python(
            await self._request(
                "GET",
                "/v1/memory-conflicts",
                params={key: value for key, value in params.items() if value is not None},
            )
        )
