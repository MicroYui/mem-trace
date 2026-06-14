"""Telemetry service facade for exporters and read-only record projection."""
from __future__ import annotations

import logging

from app.runtime.models import (
    AgentEvent,
    AgentRun,
    AgentStep,
    ContextCompactionLog,
    MemoryAccessLog,
    MemoryGateLog,
    ProfileEvent,
)
from app.telemetry import builder
from app.telemetry.exporters import NoopTelemetryExporter, TelemetryExporter
from app.telemetry.models import TelemetryExportResult, TelemetrySpan


logger = logging.getLogger(__name__)


class TelemetryService:
    """Small fail-open facade around a telemetry exporter."""

    def __init__(self, *, exporter: TelemetryExporter | None = None, fail_open: bool = True, sample_rate: float = 1.0) -> None:
        self.exporter = exporter or NoopTelemetryExporter()
        self.fail_open = fail_open
        self.sample_rate = sample_rate

    def export_spans(self, spans: list[TelemetrySpan]) -> TelemetryExportResult:
        try:
            sampled = [span for span in spans if self._includes_span(span)]
            result = self.exporter.export_spans(sampled)
            dropped_by_sampling = len(spans) - len(sampled)
            if dropped_by_sampling:
                return result.model_copy(
                    update={"dropped_span_count": result.dropped_span_count + dropped_by_sampling},
                    deep=True,
                )
            return result
        except Exception as exc:
            return self._handle_failure(exc, dropped_span_count=len(spans))

    def _includes_span(self, span: TelemetrySpan) -> bool:
        if self.sample_rate >= 1.0:
            return True
        if self.sample_rate <= 0.0:
            return False
        try:
            bucket = int(span.trace_id, 16) / float(16 ** len(span.trace_id))
        except ValueError:
            return True
        return bucket < self.sample_rate

    def _handle_failure(self, exc: Exception, *, dropped_span_count: int = 0) -> TelemetryExportResult:
        if not self.fail_open:
            raise exc
        logger.warning("Telemetry export failed", exc_info=True)
        return TelemetryExportResult(
            exported_span_count=0,
            dropped_span_count=dropped_span_count,
            warnings=["telemetry export failed"],
        )

    def export_run_records(
        self,
        *,
        run: AgentRun,
        steps: list[AgentStep] | None = None,
        events: list[AgentEvent] | None = None,
    ) -> TelemetryExportResult:
        try:
            spans: list[TelemetrySpan] = [builder.build_run_span(run)]
            spans.extend(builder.build_step_span(step, run=run) for step in steps or [])
            spans.extend(builder.build_event_span(event) for event in events or [])
            return self.export_spans(spans)
        except Exception as exc:
            return self._handle_failure(exc)

    def export_step_record(self, *, step: AgentStep, run: AgentRun | None = None) -> TelemetryExportResult:
        try:
            return self.export_spans([builder.build_step_span(step, run=run)])
        except Exception as exc:
            return self._handle_failure(exc)

    def export_event_record(self, *, event: AgentEvent) -> TelemetryExportResult:
        try:
            return self.export_spans([builder.build_event_span(event)])
        except Exception as exc:
            return self._handle_failure(exc)

    def export_retrieval_records(
        self,
        *,
        access: MemoryAccessLog,
        gate_logs: list[MemoryGateLog] | None = None,
        profile_events: list[ProfileEvent] | None = None,
        compaction_logs: list[ContextCompactionLog] | None = None,
    ) -> TelemetryExportResult:
        try:
            retrieval_span = builder.build_retrieval_span(
                access,
                gate_logs=gate_logs,
                profile_events=profile_events,
                compaction_logs=compaction_logs,
            )
            profile_spans = builder.build_profile_phase_spans(profile_events or [], parent_span_id=retrieval_span.span_id)
            return self.export_spans([retrieval_span, *profile_spans])
        except Exception as exc:
            return self._handle_failure(exc)


__all__ = ["TelemetryService"]
