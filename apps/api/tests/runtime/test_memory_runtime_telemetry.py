from __future__ import annotations

from app.runtime.memory_runtime import MemoryRuntime
from app.runtime.models import (
    CompleteRunRequest,
    EventRole,
    EventType,
    FinishStepRequest,
    RunStatus,
    RetrievalRequest,
    StartRunRequest,
    StartStepRequest,
    StepStatus,
    WriteEventRequest,
)
from app.runtime.repository import InMemoryRepository
from app.telemetry.exporters import InMemoryTelemetryExporter
from app.telemetry.service import TelemetryService


async def test_runtime_hooks_emit_redacted_spans_after_successful_lifecycle() -> None:
    exporter = InMemoryTelemetryExporter()
    rt = MemoryRuntime(InMemoryRepository(), telemetry_service=TelemetryService(exporter=exporter))

    run = await rt.start_run(StartRunRequest(session_id="s1", task="use Bun for tests", workspace_id="ws1"))
    step = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="implement"))
    result = await rt.write_event(
        WriteEventRequest(
            run_id=run.run_id,
            step_id=step.step_id,
            role=EventRole.user,
            event_type=EventType.message,
            content="raw secret-ish user prompt with password=hunter2 and use bun",
        )
    )
    await rt.finish_step(FinishStepRequest(run_id=run.run_id, step_id=step.step_id, status=StepStatus.completed))
    await rt.complete_run(CompleteRunRequest(run_id=run.run_id, status=RunStatus.completed))
    context = await rt.retrieve_context(RetrievalRequest(run_id=run.run_id, query="what package manager?"))

    spans = exporter.get_finished_spans()
    names = [span.name for span in spans]
    assert "memtrace.run" in names
    assert "memtrace.step" in names
    assert "memtrace.event" in names
    assert "memtrace.retrieve" in names
    rendered = "\n".join(span.model_dump_json() for span in spans)
    assert result.event.event_id in rendered
    assert context.access_id in rendered
    assert "hunter2" not in rendered
    assert "raw secret-ish user prompt" not in rendered
    assert len({span.span_id for span in spans}) == len(spans)


class RaisingExporter:
    def export_spans(self, spans):
        raise RuntimeError("telemetry sink unavailable")


class AccessLookupRaisingRepository(InMemoryRepository):
    async def get_access_log(self, access_id: str):
        raise RuntimeError("telemetry-only access lookup failed")


async def test_runtime_telemetry_failures_do_not_break_hot_path() -> None:
    rt = MemoryRuntime(InMemoryRepository(), telemetry_service=TelemetryService(exporter=RaisingExporter()))
    run = await rt.start_run(StartRunRequest(session_id="s1", task="task", workspace_id="ws1"))
    step = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="work"))
    result = await rt.write_event(
        WriteEventRequest(
            run_id=run.run_id,
            step_id=step.step_id,
            role=EventRole.user,
            event_type=EventType.message,
            content="use bun",
        )
    )
    assert result.event.run_id == run.run_id


async def test_runtime_hooks_fail_open_even_when_service_is_fail_closed() -> None:
    rt = MemoryRuntime(
        InMemoryRepository(),
        telemetry_service=TelemetryService(exporter=RaisingExporter(), fail_open=False),
    )

    run = await rt.start_run(StartRunRequest(session_id="s1", task="task", workspace_id="ws1"))
    step = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="work"))
    result = await rt.write_event(
        WriteEventRequest(
            run_id=run.run_id,
            step_id=step.step_id,
            role=EventRole.user,
            event_type=EventType.message,
            content="use bun",
        )
    )

    assert result.event.run_id == run.run_id


async def test_retrieval_telemetry_projection_failures_do_not_break_retrieve() -> None:
    rt = MemoryRuntime(
        AccessLookupRaisingRepository(),
        telemetry_service=TelemetryService(exporter=InMemoryTelemetryExporter(), fail_open=False),
    )
    run = await rt.start_run(StartRunRequest(session_id="s1", task="task", workspace_id="ws1"))

    context = await rt.retrieve_context(RetrievalRequest(run_id=run.run_id, query="anything"))

    assert context.access_id
    assert context.query == "anything"


async def test_terminal_lifecycle_hooks_export_each_stable_span_id_once() -> None:
    exporter = InMemoryTelemetryExporter()
    rt = MemoryRuntime(InMemoryRepository(), telemetry_service=TelemetryService(exporter=exporter))
    run = await rt.start_run(StartRunRequest(session_id="s1", task="task", workspace_id="ws1"))
    step = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="work"))

    await rt.finish_step(FinishStepRequest(run_id=run.run_id, step_id=step.step_id, status=StepStatus.completed))
    await rt.finish_step(FinishStepRequest(run_id=run.run_id, step_id=step.step_id, status=StepStatus.completed))
    await rt.complete_run(CompleteRunRequest(run_id=run.run_id, status=RunStatus.completed))
    await rt.complete_run(CompleteRunRequest(run_id=run.run_id, status=RunStatus.completed))

    spans = exporter.get_finished_spans()
    step_spans = [span for span in spans if span.name == "memtrace.step"]
    run_spans = [span for span in spans if span.name == "memtrace.run"]
    assert len(step_spans) == 1
    assert len(run_spans) == 1
    assert len({span.span_id for span in step_spans + run_spans}) == 2
