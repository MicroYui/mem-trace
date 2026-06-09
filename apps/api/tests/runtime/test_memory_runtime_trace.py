"""Service-layer tests for the run/step/event/state-tree lifecycle.

These are the foundation invariants from .ai/REQUIREMENTS.md (Tests to Write
First) plus rollback/recovery behavior.
"""
from __future__ import annotations

import pytest

from app.runtime.models import (
    EventRole,
    EventType,
    FinishStepRequest,
    RollbackRequest,
    RunStatus,
    StartRunRequest,
    StartStepRequest,
    StateNodeStatus,
    StateNodeType,
    StepStatus,
    WriteEventRequest,
)


async def _start(runtime):
    return await runtime.start_run(StartRunRequest(session_id="s1", task="t"))


async def test_start_run_creates_running_run_and_active_root_node(runtime):
    run = await _start(runtime)
    assert run.status == RunStatus.running
    nodes = await runtime.get_state_tree(run.run_id)
    assert len(nodes) == 1
    assert nodes[0].node_type == StateNodeType.root
    assert nodes[0].status == StateNodeStatus.active


async def test_start_step_creates_active_step_node_under_root(runtime):
    run = await _start(runtime)
    step = await runtime.start_step(StartStepRequest(run_id=run.run_id, intent="planning"))
    assert step.status == StepStatus.active
    nodes = {n.node_id: n for n in await runtime.get_state_tree(run.run_id)}
    node = nodes[step.state_node_id]
    assert node.node_type == StateNodeType.step
    assert node.status == StateNodeStatus.active
    root = next(n for n in nodes.values() if n.node_type == StateNodeType.root)
    assert node.parent_id == root.node_id
    assert node.depth == 1


async def test_write_event_assigns_monotonic_sequence_numbers_per_run(runtime):
    run = await _start(runtime)
    step = await runtime.start_step(StartStepRequest(run_id=run.run_id, intent="x"))
    seqs = []
    for i in range(3):
        r = await runtime.write_event(
            WriteEventRequest(run_id=run.run_id, step_id=step.step_id, content=f"m{i}")
        )
        seqs.append(r.event.sequence_no)
    assert seqs == [1, 2, 3]
    timeline = await runtime.get_timeline(run.run_id)
    assert [e.sequence_no for e in timeline] == [1, 2, 3]


async def test_sequence_numbers_are_independent_per_run(runtime):
    r1 = await _start(runtime)
    r2 = await _start(runtime)
    s1 = await runtime.start_step(StartStepRequest(run_id=r1.run_id))
    s2 = await runtime.start_step(StartStepRequest(run_id=r2.run_id))
    e1 = await runtime.write_event(WriteEventRequest(run_id=r1.run_id, step_id=s1.step_id, content="a"))
    e2 = await runtime.write_event(WriteEventRequest(run_id=r2.run_id, step_id=s2.step_id, content="b"))
    assert e1.event.sequence_no == 1
    assert e2.event.sequence_no == 1


async def test_write_event_binds_event_to_step_and_state_node(runtime):
    run = await _start(runtime)
    step = await runtime.start_step(StartStepRequest(run_id=run.run_id))
    r = await runtime.write_event(WriteEventRequest(run_id=run.run_id, step_id=step.step_id, content="hi"))
    assert r.event.step_id == step.step_id
    assert r.event.state_node_id == step.state_node_id


async def test_finish_step_success_marks_step_and_state_node_completed(runtime):
    run = await _start(runtime)
    step = await runtime.start_step(StartStepRequest(run_id=run.run_id))
    res = await runtime.finish_step(
        FinishStepRequest(run_id=run.run_id, step_id=step.step_id, status=StepStatus.completed)
    )
    assert res.step.status == StepStatus.completed
    assert res.state_node.status == StateNodeStatus.completed


async def test_finish_step_failed_marks_step_and_state_node_failed(runtime):
    run = await _start(runtime)
    step = await runtime.start_step(StartStepRequest(run_id=run.run_id))
    res = await runtime.finish_step(
        FinishStepRequest(run_id=run.run_id, step_id=step.step_id, status=StepStatus.failed, error_message="boom")
    )
    assert res.step.status == StepStatus.failed
    assert res.state_node.status == StateNodeStatus.failed
    assert res.state_node.failure_reason == "boom"


async def test_rollback_branch_marks_failed_step_rolled_back(runtime):
    run = await _start(runtime)
    step = await runtime.start_step(StartStepRequest(run_id=run.run_id))
    await runtime.finish_step(
        FinishStepRequest(run_id=run.run_id, step_id=step.step_id, status=StepStatus.failed, error_message="npm")
    )
    rb = await runtime.rollback_branch(RollbackRequest(run_id=run.run_id, step_id=step.step_id, reason="npm"))
    assert step.step_id in rb.rolled_back_step_ids
    nodes = {n.node_id: n for n in await runtime.get_state_tree(run.run_id)}
    node = nodes[step.state_node_id]
    assert node.status == StateNodeStatus.rolled_back
    # failure_reason preserved across rollback
    assert node.failure_reason == "npm"
    assert node.branch_reason.get("rollback_reason") == "npm"


async def test_recovery_step_attaches_to_failed_step_parent_not_failed_node(runtime):
    run = await _start(runtime)
    failed = await runtime.start_step(StartStepRequest(run_id=run.run_id, intent="debug"))
    await runtime.finish_step(
        FinishStepRequest(run_id=run.run_id, step_id=failed.step_id, status=StepStatus.failed, error_message="npm")
    )
    await runtime.rollback_branch(RollbackRequest(run_id=run.run_id, step_id=failed.step_id, reason="npm"))
    recovery = await runtime.start_step(
        StartStepRequest(run_id=run.run_id, intent="debug", recovery_from_step_id=failed.step_id)
    )
    nodes = {n.node_id: n for n in await runtime.get_state_tree(run.run_id)}
    failed_node = nodes[failed.state_node_id]
    recovery_node = nodes[recovery.state_node_id]
    root = next(n for n in nodes.values() if n.node_type == StateNodeType.root)
    # recovery attaches to failed node's PARENT (root), not under the failed node
    assert recovery_node.parent_id == failed_node.parent_id == root.node_id
    assert recovery_node.node_type == StateNodeType.recovery
    assert recovery_node.branch_reason.get("recovery_from_step_id") == failed.step_id


async def test_rollback_flips_related_memory_branch_status(runtime):
    run = await _start(runtime)
    step = await runtime.start_step(StartStepRequest(run_id=run.run_id))
    await runtime.write_event(
        WriteEventRequest(
            run_id=run.run_id, step_id=step.step_id, role=EventRole.tool,
            event_type=EventType.tool_result, status="failed",
            content="Tried running tests with npm test, but it failed because npm was unavailable.",
        )
    )
    await runtime.finish_step(
        FinishStepRequest(run_id=run.run_id, step_id=step.step_id, status=StepStatus.failed, error_message="npm")
    )
    rb = await runtime.rollback_branch(RollbackRequest(run_id=run.run_id, step_id=step.step_id, reason="npm"))
    assert rb.affected_memory_ids
    mems = await runtime.list_memories(run_id=run.run_id)
    tool_ev = [m for m in mems if m.memory_type.value == "tool_evidence"]
    assert tool_ev and all(m.branch_status.value == "rolled_back" for m in tool_ev)


async def test_recovery_raises_when_failed_node_parent_is_dangling(runtime):
    # A structurally inconsistent tree (failed node points at a missing parent)
    # must NOT silently reattach the recovery to root; it raises StateTreeError.
    from app.runtime.memory_runtime import StateTreeError

    run = await _start(runtime)
    failed = await runtime.start_step(StartStepRequest(run_id=run.run_id, intent="debug"))
    await runtime.finish_step(
        FinishStepRequest(run_id=run.run_id, step_id=failed.step_id, status=StepStatus.failed, error_message="boom")
    )
    # Corrupt the tree: point the failed node at a non-existent parent.
    nodes = {n.node_id: n for n in await runtime.get_state_tree(run.run_id)}
    failed_node = nodes[failed.state_node_id]
    failed_node.parent_id = "node_missing"
    await runtime._repo.update_state_node(failed_node)

    with pytest.raises(StateTreeError):
        await runtime.start_step(
            StartStepRequest(run_id=run.run_id, intent="debug", recovery_from_step_id=failed.step_id)
        )
