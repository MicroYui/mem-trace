from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.runtime.models import AgentEvent, AgentRun, AgentStep, EventRole, EventType, RunStatus, StepStatus
from app.telemetry.exporters import InMemoryTelemetryExporter
from app.telemetry.models import TelemetryExportResult, TelemetrySpan
from app.telemetry.service import TelemetryService


NOW = datetime(2026, 6, 14, 12, 0, tzinfo=timezone.utc)


class FailingExporter:
    def export_spans(self, spans: list[TelemetrySpan]) -> TelemetryExportResult:
        raise RuntimeError("network down")


def _span() -> TelemetrySpan:
    return TelemetrySpan(name="memtrace.run", trace_id="trace_1", span_id="span_1")


def test_service_exports_spans_through_configured_exporter():
    exporter = InMemoryTelemetryExporter()
    service = TelemetryService(exporter=exporter)

    result = service.export_spans([_span()])

    assert result.exported_span_count == 1
    assert result.dropped_span_count == 0
    assert [span.span_id for span in exporter.get_finished_spans()] == ["span_1"]


def test_service_fail_open_converts_exporter_errors_to_warnings():
    service = TelemetryService(exporter=FailingExporter(), fail_open=True)

    result = service.export_spans([_span()])

    assert result.exported_span_count == 0
    assert result.dropped_span_count == 1
    assert result.warnings == ["telemetry export failed"]


def test_service_fail_closed_raises_exporter_errors_when_explicitly_configured():
    service = TelemetryService(exporter=FailingExporter(), fail_open=False)

    with pytest.raises(RuntimeError, match="network down"):
        service.export_spans([_span()])


def test_service_fail_open_covers_record_projection_errors(monkeypatch):
    service = TelemetryService(exporter=InMemoryTelemetryExporter(), fail_open=True)

    def boom(run):
        raise RuntimeError("builder drift")

    monkeypatch.setattr("app.telemetry.builder.build_run_span", boom)
    run = AgentRun(run_id="run_1", workspace_id="ws_1", session_id="sess_1", status=RunStatus.completed)

    result = service.export_run_records(run=run)

    assert result.exported_span_count == 0
    assert result.dropped_span_count == 0
    assert result.warnings == ["telemetry export failed"]


def test_service_public_warnings_do_not_include_exception_payloads():
    class PayloadLeakingExporter:
        def export_spans(self, spans: list[TelemetrySpan]) -> TelemetryExportResult:
            raise RuntimeError('{"span_id":"span_1","attributes":{"prompt":"raw prompt"}}')

    service = TelemetryService(exporter=PayloadLeakingExporter(), fail_open=True)

    result = service.export_spans([_span()])

    rendered = "\n".join(result.warnings)
    assert result.warnings == ["telemetry export failed"]
    assert "span_1" not in rendered
    assert "raw prompt" not in rendered


def test_service_applies_deterministic_sample_rate():
    exporter = InMemoryTelemetryExporter()
    service = TelemetryService(exporter=exporter, sample_rate=0.0)

    result = service.export_spans([_span()])

    assert result.exported_span_count == 0
    assert result.dropped_span_count == 1
    assert exporter.get_finished_spans() == []


def test_service_builds_and_exports_run_step_event_records_without_raw_content():
    exporter = InMemoryTelemetryExporter()
    service = TelemetryService(exporter=exporter)
    run = AgentRun(
        run_id="run_1",
        workspace_id="ws_1",
        session_id="sess_1",
        task="Do not leak this task body",
        status=RunStatus.completed,
        started_at=NOW,
        finished_at=NOW,
    )
    step = AgentStep(
        step_id="step_1",
        workspace_id="ws_1",
        run_id="run_1",
        intent="implement",
        status=StepStatus.completed,
        started_at=NOW,
        finished_at=NOW,
    )
    event = AgentEvent(
        event_id="evt_1",
        workspace_id="ws_1",
        session_id="sess_1",
        run_id="run_1",
        step_id="step_1",
        sequence_no=1,
        role=EventRole.user,
        event_type=EventType.message,
        content="ordinary prompt with token=secret-value and raw_payload_ref=vault://evt",
        created_at=NOW,
    )

    result = service.export_run_records(run=run, steps=[step], events=[event])

    assert result.exported_span_count == 3
    dumped = "\n".join(span.model_dump_json() for span in exporter.get_finished_spans())
    assert "token=secret-value" not in dumped
    assert "raw_payload_ref" not in dumped
    assert [span.name for span in exporter.get_finished_spans()] == ["memtrace.run", "memtrace.step", "memtrace.event"]
