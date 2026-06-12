from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Optional, TypeVar

from memtrace_sdk.client import MemTrace
from memtrace_sdk.types import (
    AgentStep,
    EventType,
    FinishStepRequest,
    FinishStepResult,
    MemoryContext,
    RetrievalRequest,
    RetrievalStrategy,
    RollbackRequest,
    RollbackResult,
    StartStepRequest,
    StepStatus,
    WriteEventRequest,
    WriteEventResult,
)

T = TypeVar("T")


class MemTraceLangGraphAdapter:
    """LangGraph-style lifecycle hooks for tracing node execution with MemTrace.

    The hook methods do not import LangGraph directly. They operate on the SDK
    client and can therefore be used from LangGraph, a custom async loop, or unit
    tests without installing the optional ``memtrace-sdk[langgraph]`` extra.
    """

    def __init__(
        self,
        client: MemTrace,
        *,
        run_id: str,
        workspace_id: Optional[str] = None,
        event_source: str = "langgraph_adapter",
    ):
        self._client = client
        self._run_id = run_id
        self._workspace_id = workspace_id
        self._event_source = event_source

    async def before_node(
        self,
        node_name: str,
        query: str,
        *,
        task_intent: Optional[str] = None,
        strategy: RetrievalStrategy = RetrievalStrategy.variant_2,
    ) -> tuple[AgentStep, MemoryContext]:
        """Start a step for ``node_name`` and retrieve prompt context for it."""

        step = await self._client.start_step(
            StartStepRequest(
                run_id=self._run_id,
                intent=node_name,
                goal=task_intent,
            )
        )
        context = await self._client.retrieve_context(
            RetrievalRequest(
                run_id=self._run_id,
                step_id=step.step_id,
                query=query,
                task_intent=task_intent or node_name,
                workspace_id=self._workspace_id,
                strategy=strategy,
            )
        )
        return step, context

    async def after_node(
        self,
        step_id: str,
        *,
        content: Optional[str],
        event_type: EventType = EventType.message,
        tool_name: Optional[str] = None,
        status: Optional[str] = None,
    ) -> tuple[WriteEventResult, FinishStepResult]:
        """Record a successful node output and finish the step as completed."""

        write = await self._client.write_event(
            WriteEventRequest(
                run_id=self._run_id,
                step_id=step_id,
                event_type=event_type,
                content=content,
                tool_name=tool_name,
                status=status,
                event_source=self._event_source,
            )
        )
        finish = await self._client.finish_step(
            FinishStepRequest(
                run_id=self._run_id,
                step_id=step_id,
                status=StepStatus.completed,
                summary=content,
            )
        )
        return write, finish

    async def on_error(self, step_id: str, *, error_message: str) -> RollbackResult:
        """Record a node failure, mark its step failed, then roll back its branch."""

        await self._client.write_event(
            WriteEventRequest(
                run_id=self._run_id,
                step_id=step_id,
                event_type=EventType.error,
                content=error_message,
                status=StepStatus.failed.value,
                event_source=self._event_source,
            )
        )
        await self._client.finish_step(
            FinishStepRequest(
                run_id=self._run_id,
                step_id=step_id,
                status=StepStatus.failed,
                error_message=error_message,
            )
        )
        return await self._client.rollback_branch(
            RollbackRequest(run_id=self._run_id, step_id=step_id, reason=error_message)
        )

    def wrap_node(
        self,
        fn: Callable[..., Awaitable[T]],
        *,
        node_name: str,
        query: str,
        task_intent: Optional[str] = None,
        strategy: RetrievalStrategy = RetrievalStrategy.variant_2,
    ) -> Callable[..., Awaitable[T]]:
        """Wrap an async node callable with before/after/on_error hooks.

        If the first positional argument is a mutable ``dict`` state, the wrapper
        adds ``memtrace_step`` and ``memtrace_context`` keys before invoking the
        node so the node can inject retrieved context into its prompt.
        """

        async def wrapped(*args: Any, **kwargs: Any) -> T:
            step, context = await self.before_node(
                node_name,
                query,
                task_intent=task_intent,
                strategy=strategy,
            )
            if args and isinstance(args[0], dict):
                args[0]["memtrace_step"] = step
                args[0]["memtrace_context"] = context
            try:
                result = await fn(*args, **kwargs)
            except Exception as exc:
                await self.on_error(step.step_id, error_message=str(exc))
                raise
            await self.after_node(step.step_id, content=_render_node_result(result))
            return result

        return wrapped


def _render_node_result(result: object) -> str:
    if isinstance(result, str):
        return result
    return repr(result)


__all__ = ["MemTraceLangGraphAdapter"]
