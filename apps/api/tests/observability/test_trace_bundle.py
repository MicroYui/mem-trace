from __future__ import annotations

import json

import pytest

from app.runtime.memory_runtime import MemoryRuntime
from app.runtime.models import (
    AgentEvent,
    CompactionKind,
    CompactionProvider,
    ContextCompactionLog,
    EventRole,
    EventType,
    MemoryItem,
    MemoryAccessLog,
    MemoryType,
    RetrievalRequest,
    RetrievalStrategy,
    RetainedNegativeEvidence,
    RiskFlags,
    StartRunRequest,
    StartStepRequest,
    StepStatus,
    FinishStepRequest,
    WriteEventRequest,
)
from app.runtime.repository import InMemoryRepository


@pytest.mark.asyncio
async def test_trace_bundle_export_redacts_secret_event_and_memory_content():
    repo = InMemoryRepository()
    runtime = MemoryRuntime(repo)
    run = await runtime.start_run(StartRunRequest(workspace_id="ws_bundle", session_id="s", task="bundle"))
    step = await runtime.start_step(StartStepRequest(run_id=run.run_id, intent="record secret"))
    await runtime.write_event(
        WriteEventRequest(
            run_id=run.run_id,
            step_id=step.step_id,
            role=EventRole.user,
            event_type=EventType.message,
            content="password is hunter2",
        )
    )
    await repo.add_memory(
        MemoryItem(
            workspace_id="ws_bundle",
            run_id=run.run_id,
            source_state_node_id=step.state_node_id,
            memory_type=MemoryType.episodic,
            content="Use token sk-1234567890abcdef for debugging",
            summary="debug token sk-1234567890abcdef",
            risk_flags=RiskFlags(contains_secret=True),
        )
    )

    bundle = await runtime.export_trace_bundle(run_id=run.run_id, redacted=True)
    payload = json.dumps(bundle.model_dump(mode="json"), ensure_ascii=False)

    assert "hunter2" not in payload
    assert "sk-1234567890abcdef" not in payload
    assert "[REDACTED]" in payload


@pytest.mark.asyncio
async def test_trace_bundle_export_redacts_event_string_payload_fields():
    repo = InMemoryRepository()
    runtime = MemoryRuntime(repo)
    run = await runtime.start_run(StartRunRequest(workspace_id="ws_bundle_fields", session_id="s", task="bundle"))
    step = await runtime.start_step(StartStepRequest(run_id=run.run_id, intent="record secret fields"))
    await repo.append_event(
        AgentEvent(
            workspace_id=run.workspace_id,
            session_id=run.session_id,
            run_id=run.run_id,
            step_id=step.step_id,
            state_node_id=step.state_node_id,
            event_source="sdk token sk-eventsource123456",
            role=EventRole.tool,
            event_type=EventType.tool_result,
            content="ordinary content",
            raw_payload_ref="s3://bucket/password is rawfieldsecret",
            tool_name="deploy password is toolsecret",
            status="failed with token sk-status1234567890",
        )
    )

    bundle = await runtime.export_trace_bundle(run_id=run.run_id, redacted=True)
    payload = json.dumps(bundle.model_dump(mode="json"), ensure_ascii=False)

    assert "sk-eventsource123456" not in payload
    assert "rawfieldsecret" not in payload
    assert "toolsecret" not in payload
    assert "sk-status1234567890" not in payload
    assert "[REDACTED]" in payload


@pytest.mark.asyncio
async def test_trace_bundle_export_redacts_retained_negative_evidence():
    repo = InMemoryRepository()
    runtime = MemoryRuntime(repo)
    run = await runtime.start_run(StartRunRequest(workspace_id="ws_bundle_retained_negative", session_id="s", task="bundle"))
    step = await runtime.start_step(StartStepRequest(run_id=run.run_id, intent="retrieve"))
    access = await repo.add_access_log(
        MemoryAccessLog(
            workspace_id=run.workspace_id,
            run_id=run.run_id,
            step_id=step.step_id,
            query="retain negative evidence",
        )
    )
    await repo.add_compaction_log(
        ContextCompactionLog(
            access_id=access.access_id,
            run_id=run.run_id,
            step_id=step.step_id,
            workspace_id=run.workspace_id,
            kind=CompactionKind.budget_notice,
            provider=CompactionProvider.rule,
            retained_negative_evidence=[
                RetainedNegativeEvidence(
                    source_memory_id="mem_unsafe",
                    source_state_node_id=step.state_node_id,
                    mode="sanitized_risk_notice",
                    risk_kind="destructive",
                    reason="failed_branch_sanitized",
                    safe_text="Do not run rm -rf /prod with password=hunter2 or Authorization: Bearer sk-test123456",
                )
            ],
        )
    )

    bundle = await runtime.export_access_bundle(access.access_id, redacted=True)
    payload = json.dumps(bundle.model_dump(mode="json"), ensure_ascii=False)

    for marker in ("rm -rf", "/prod", "hunter2", "Authorization", "sk-test123456"):
        assert marker not in payload
    assert "destructive operation" in payload


@pytest.mark.asyncio
async def test_trace_bundle_export_defensively_redacts_malformed_retained_negative_evidence():
    repo = InMemoryRepository()
    runtime = MemoryRuntime(repo)
    run = await runtime.start_run(StartRunRequest(workspace_id="ws_bundle_malformed_retained_negative", session_id="s", task="bundle"))
    step = await runtime.start_step(StartStepRequest(run_id=run.run_id, intent="retrieve"))
    access = await repo.add_access_log(
        MemoryAccessLog(
            workspace_id=run.workspace_id,
            run_id=run.run_id,
            step_id=step.step_id,
            query="retain malformed negative evidence",
        )
    )
    await repo.add_compaction_log(
        ContextCompactionLog(
            access_id=access.access_id,
            run_id=run.run_id,
            step_id=step.step_id,
            workspace_id=run.workspace_id,
            kind=CompactionKind.budget_notice,
            provider=CompactionProvider.rule,
            retained_negative_evidence=[
                RetainedNegativeEvidence(
                    source_memory_id="mem_raw_unsafe",
                    source_state_node_id=step.state_node_id,
                    mode="raw_failed_attempt",
                    risk_kind=None,
                    reason="failed_branch_degraded",
                    safe_text="Malformed retained row says rm -rf /prod with password and Authorization: Bearer sk-short",
                ),
                RetainedNegativeEvidence(
                    source_memory_id="mem_unknown_risk",
                    source_state_node_id=step.state_node_id,
                    mode="sanitized_risk_notice",
                    risk_kind="future_destructive_alias",
                    reason="failed_branch_sanitized",
                    safe_text="Unknown risk row says rm -rf /prod with password and Authorization: Bearer sk-short",
                ),
                RetainedNegativeEvidence(
                    source_memory_id="mem_raw_known_risk",
                    source_state_node_id=step.state_node_id,
                    mode="raw_failed_attempt",
                    risk_kind="destructive",
                    reason="failed_branch_degraded",
                    safe_text="Malformed raw retained row says kubectl delete namespace production",
                ),
            ],
        )
    )

    bundle = await runtime.export_access_bundle(access.access_id, redacted=True)
    payload = json.dumps(bundle.model_dump(mode="json"), ensure_ascii=False)

    for marker in ("rm -rf", "/prod", "sk-", "password", "Authorization"):
        assert marker not in payload
    assert "kubectl delete" not in payload
    assert "namespace production" not in payload
    assert "destructive operation" in payload
    assert "unsafe operations" in payload


@pytest.mark.asyncio
async def test_access_trace_bundle_includes_gate_logs_and_referenced_memories_only():
    repo = InMemoryRepository()
    runtime = MemoryRuntime(repo)
    run = await runtime.start_run(StartRunRequest(workspace_id="ws_access_bundle", session_id="s", task="retrieve bun"))
    step = await runtime.start_step(StartStepRequest(run_id=run.run_id, intent="retrieve"))
    referenced = await repo.add_memory(
        MemoryItem(
            workspace_id="ws_access_bundle",
            run_id=run.run_id,
            source_state_node_id=step.state_node_id,
            memory_type=MemoryType.project,
            key="runtime",
            value="Bun",
            content="Project uses Bun for tests",
        )
    )
    unrelated = await repo.add_memory(
        MemoryItem(
            workspace_id="ws_access_bundle",
            run_id=run.run_id,
            source_state_node_id=step.state_node_id,
            memory_type=MemoryType.episodic,
            content="Unrelated Python note",
        )
    )
    unrelated_step = await runtime.start_step(StartStepRequest(run_id=run.run_id, intent="unrelated secret work"))
    unrelated_event = await runtime.write_event(
        WriteEventRequest(
            run_id=run.run_id,
            step_id=unrelated_step.step_id,
            role=EventRole.user,
            event_type=EventType.message,
            content="unrelated note password is swordfish",
        )
    )
    await runtime.finish_step(
        FinishStepRequest(run_id=run.run_id, step_id=unrelated_step.step_id, status=StepStatus.completed)
    )
    ctx = await runtime.retrieve_context(
        RetrievalRequest(
            run_id=run.run_id,
            step_id=step.step_id,
            query="Bun runtime",
            strategy=RetrievalStrategy.variant_2,
            top_k=3,
        )
    )

    bundle = await runtime.export_access_bundle(ctx.access_id, redacted=True)
    memory_ids = {memory.memory_id for memory in bundle.memories}

    assert bundle.access_logs[0].access_id == ctx.access_id
    assert bundle.gate_logs
    assert referenced.memory_id in memory_ids
    assert unrelated.memory_id not in memory_ids
    assert unrelated_step.step_id not in {step.step_id for step in bundle.steps}
    assert unrelated_event.event.event_id not in {event.event_id for event in bundle.events}


@pytest.mark.asyncio
async def test_access_trace_bundle_ignores_foreign_step_on_malformed_access_log():
    repo = InMemoryRepository()
    runtime = MemoryRuntime(repo)
    run_a = await runtime.start_run(StartRunRequest(workspace_id="ws_bundle_malformed", session_id="a", task="run a"))
    run_b = await runtime.start_run(StartRunRequest(workspace_id="ws_bundle_malformed", session_id="b", task="run b"))
    step_b = await runtime.start_step(StartStepRequest(run_id=run_b.run_id, intent="foreign secret step"))
    access = await repo.add_access_log(
        MemoryAccessLog(
            workspace_id=run_a.workspace_id,
            run_id=run_a.run_id,
            step_id=step_b.step_id,
            query="malformed historical row",
        )
    )

    bundle = await runtime.export_access_bundle(access.access_id, redacted=True)

    assert bundle.runs == [run_a]
    assert bundle.steps == []


@pytest.mark.asyncio
async def test_run_trace_bundle_includes_gate_referenced_memory_from_prior_run():
    repo = InMemoryRepository()
    runtime = MemoryRuntime(repo)
    seed_run = await runtime.start_run(
        StartRunRequest(workspace_id="ws_run_bundle_cross", session_id="s1", task="record project runtime")
    )
    seed_step = await runtime.start_step(StartStepRequest(run_id=seed_run.run_id, intent="record runtime"))
    cross_run_memory = await repo.add_memory(
        MemoryItem(
            workspace_id="ws_run_bundle_cross",
            run_id=seed_run.run_id,
            source_state_node_id=seed_step.state_node_id,
            memory_type=MemoryType.project,
            key="runtime",
            value="Bun",
            content="Project uses Bun for tests",
        )
    )

    retrieve_run = await runtime.start_run(
        StartRunRequest(workspace_id="ws_run_bundle_cross", session_id="s2", task="retrieve project runtime")
    )
    retrieve_step = await runtime.start_step(StartStepRequest(run_id=retrieve_run.run_id, intent="retrieve runtime"))
    await runtime.retrieve_context(
        RetrievalRequest(
            run_id=retrieve_run.run_id,
            step_id=retrieve_step.step_id,
            query="Bun runtime",
            strategy=RetrievalStrategy.variant_2,
            top_k=3,
        )
    )

    bundle = await runtime.export_trace_bundle(run_id=retrieve_run.run_id, redacted=True)
    gate_memory_ids = {gate.memory_id for gate in bundle.gate_logs}
    bundle_memory_ids = {memory.memory_id for memory in bundle.memories}

    assert cross_run_memory.memory_id in gate_memory_ids
    assert gate_memory_ids <= bundle_memory_ids


@pytest.mark.asyncio
async def test_trace_bundle_validation_reports_counts_without_writing():
    runtime = MemoryRuntime(InMemoryRepository())
    run = await runtime.start_run(StartRunRequest(workspace_id="ws_bundle_validate", session_id="s", task="validate"))

    bundle = await runtime.export_trace_bundle(run_id=run.run_id, redacted=True)
    validation = runtime.validate_trace_bundle(bundle.model_dump(mode="json"))

    assert validation.valid is True
    assert validation.schema_version == "trace-bundle-v1"
    assert validation.counts["runs"] == 1
    assert validation.counts["events"] == 0
    assert validation.errors == []


def test_trace_bundle_validation_rejects_unknown_schema_version():
    runtime = MemoryRuntime(InMemoryRepository())

    validation = runtime.validate_trace_bundle({"schema_version": "trace-bundle-v999"})

    assert validation.valid is False
    assert validation.errors
