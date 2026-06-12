from __future__ import annotations

import pytest

import memtrace_sdk.langgraph_adapter as langgraph_adapter
from memtrace_sdk import MemTrace
from memtrace_sdk.types import (
    EventType,
    RetrievalStrategy,
    StartRunRequest,
    StepStatus,
)


def _adapter_class():
    return getattr(langgraph_adapter, "MemTraceLangGraphAdapter")


async def test_before_after_node_traces_through_runtime() -> None:
    client = MemTrace.in_memory(default_workspace_id="ws_langgraph")
    run = await client.start_run(StartRunRequest(session_id="lg-s1", task="run graph"))
    adapter = _adapter_class()(client, run_id=run.run_id)

    step, context = await adapter.before_node(
        "plan", "what should the graph remember?", task_intent="planning"
    )
    write, finish = await adapter.after_node(
        step.step_id,
        content="planned next graph action",
        event_type=EventType.message,
    )
    timeline = await client.get_timeline(run.run_id)
    steps = await client.get_steps(run.run_id)

    assert step.intent == "plan"
    assert context.access_id
    assert write.event.event_source == "langgraph_adapter"
    assert timeline[0].event_source == "langgraph_adapter"
    assert finish.step.status == StepStatus.completed
    assert finish.step in steps
    assert finish.created_memory_ids


async def test_on_error_isolates_failed_branch_from_positive_context() -> None:
    client = MemTrace.in_memory(default_workspace_id="ws_langgraph")
    run = await client.start_run(StartRunRequest(session_id="lg-s2", task="recover from failed node"))
    adapter = _adapter_class()(client, run_id=run.run_id)

    failed_step, _ = await adapter.before_node("test", "run the test command")
    rollback = await adapter.on_error(
        failed_step.step_id,
        error_message="npm test failed; use bun test next time",
    )

    recovery_step, context = await adapter.before_node(
        "recover",
        "recover without repeating npm test",
        strategy=RetrievalStrategy.variant_2,
    )
    steps = await client.get_steps(run.run_id)

    assert failed_step.step_id in rollback.rolled_back_step_ids
    assert any(step.step_id == failed_step.step_id and step.status == StepStatus.rolled_back for step in steps)
    assert recovery_step.step_id != failed_step.step_id

    positive_blocks = [
        block
        for block in context.context_blocks
        if block.type != "avoided_attempts" and block.source != "negative_evidence"
    ]
    assert all("npm test failed" not in block.content for block in positive_blocks)
    for block in context.context_blocks:
        if "npm test failed" in block.content:
            assert block.type == "avoided_attempts"
            assert block.source == "negative_evidence"


async def test_wrap_node_records_success_and_failure_lifecycle() -> None:
    client = MemTrace.in_memory(default_workspace_id="ws_langgraph")
    run = await client.start_run(StartRunRequest(session_id="lg-s3", task="wrap node"))
    adapter = _adapter_class()(client, run_id=run.run_id)

    async def successful_node(state: dict[str, object]) -> dict[str, object]:
        assert "memtrace_context" in state
        return {"answer": "ok"}

    wrapped_success = adapter.wrap_node(successful_node, node_name="success", query="need context")
    assert await wrapped_success({"input": "x"}) == {"answer": "ok"}

    async def failing_node(state: dict[str, object]) -> dict[str, object]:
        raise RuntimeError("boom")

    wrapped_failure = adapter.wrap_node(failing_node, node_name="failure", query="need context")
    with pytest.raises(RuntimeError, match="boom"):
        await wrapped_failure({"input": "x"})

    timeline = await client.get_timeline(run.run_id)
    steps = await client.get_steps(run.run_id)

    assert [event.event_source for event in timeline] == ["langgraph_adapter", "langgraph_adapter"]
    assert any(step.intent == "success" and step.status == StepStatus.completed for step in steps)
    assert any(step.intent == "failure" and step.status == StepStatus.rolled_back for step in steps)
