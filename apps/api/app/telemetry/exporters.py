"""Telemetry exporter sinks.

The exporters consume already-redacted internal ``TelemetrySpan`` DTOs. They do
not import optional OpenTelemetry packages unless an OTLP export call is made.
"""
from __future__ import annotations

import contextvars
import json
import os
from datetime import datetime
from pathlib import Path
from pathlib import PurePosixPath
from types import TracebackType
from typing import Protocol

from app.telemetry.models import TelemetryEvent, TelemetryExportResult, TelemetrySpan
from app.telemetry.redaction import sanitize_attributes


_OTEL_ID_HINT: contextvars.ContextVar[tuple[int, int] | None] = contextvars.ContextVar("memtrace_otel_id_hint", default=None)


class TelemetryExporter(Protocol):
    """Protocol implemented by all telemetry sinks."""

    def export_spans(self, spans: list[TelemetrySpan]) -> TelemetryExportResult:
        """Export spans and return a small deterministic result."""


def _sanitize_event(event: TelemetryEvent) -> TelemetryEvent:
    return event.model_copy(update={"attributes": sanitize_attributes(event.attributes)}, deep=True)


def _sanitize_span(span: TelemetrySpan) -> TelemetrySpan:
    return span.model_copy(
        update={
            "attributes": sanitize_attributes(span.attributes),
            "events": [_sanitize_event(event) for event in span.events],
        },
        deep=True,
    )


class NoopTelemetryExporter:
    """Default exporter: drops spans without side effects."""

    def export_spans(self, spans: list[TelemetrySpan]) -> TelemetryExportResult:
        return TelemetryExportResult(exported_span_count=0, dropped_span_count=len(spans), warnings=[])


class InMemoryTelemetryExporter:
    """Deterministic test exporter that stores sanitized span snapshots."""

    def __init__(self) -> None:
        self._spans: list[TelemetrySpan] = []

    def export_spans(self, spans: list[TelemetrySpan]) -> TelemetryExportResult:
        sanitized = [_sanitize_span(span) for span in spans]
        self._spans.extend(sanitized)
        return TelemetryExportResult(exported_span_count=len(sanitized), dropped_span_count=0, warnings=[])

    def get_finished_spans(self) -> list[TelemetrySpan]:
        return [span.model_copy(deep=True) for span in self._spans]

    def clear(self) -> None:
        self._spans.clear()


class JsonlTelemetryExporter:
    """Local no-network JSONL exporter for smoke/debug output."""

    def __init__(self, *, path: str | Path, append: bool = False) -> None:
        self.path = self._validate_safe_path(path)
        self.append = append
        self._has_written = False

    @staticmethod
    def _validate_safe_path(path: str | Path) -> Path:
        raw = str(path)
        posix_path = PurePosixPath(raw)
        if posix_path.is_absolute() or ".." in posix_path.parts or not posix_path.parts or posix_path.parts[0] != "reports":
            raise ValueError("Telemetry JSONL path must be a relative path under reports/")
        candidate = Path(raw)
        current = Path()
        for part in candidate.parts:
            current = current / part
            if current.is_symlink():
                raise ValueError("Telemetry JSONL path must not traverse symlinks under reports/")
        return candidate

    def _prepare_safe_output_path(self) -> None:
        # Re-check before every write so a path validated at construction cannot
        # later be swapped to a symlink escape. This keeps the direct exporter as
        # strict as the settings factory.
        self._validate_safe_path(self.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        current = Path()
        for part in self.path.parts:
            current = current / part
            if current.is_symlink():
                raise ValueError("Telemetry JSONL path must not traverse symlinks under reports/")

    def export_spans(self, spans: list[TelemetrySpan]) -> TelemetryExportResult:
        self._prepare_safe_output_path()
        mode = "a" if self.append or self._has_written else "w"
        sanitized = [_sanitize_span(span) for span in spans]
        opener = None
        if hasattr(os, "O_NOFOLLOW"):
            opener = lambda file, flags: os.open(file, flags | os.O_NOFOLLOW)  # noqa: E731
        with open(self.path, mode, encoding="utf-8", opener=opener) as handle:
            for span in sanitized:
                payload = span.model_dump(mode="json", exclude_none=True)
                handle.write(json.dumps(payload, sort_keys=True, separators=(",", ":")))
                handle.write("\n")
        self._has_written = True
        return TelemetryExportResult(exported_span_count=len(sanitized), dropped_span_count=0, warnings=[])


class OtlpTelemetryExporter:
    """Optional OTLP exporter placeholder with lazy dependency validation.

    Segment 2 constructs this object only when the endpoint and dependencies are
    available. Actual SDK span conversion is intentionally minimal here and can
    be expanded in Segment 3 without changing the service/factory contract.
    """

    def __init__(self, *, endpoint: str, headers: dict[str, str] | None = None) -> None:
        self.endpoint = endpoint
        self.headers = dict(headers or {})
        self._provider = None
        self._tracer = None

    @staticmethod
    def dependencies_available() -> bool:
        try:
            import opentelemetry.exporter.otlp.proto.http.trace_exporter  # noqa: F401
            import opentelemetry.sdk.trace  # noqa: F401
        except ModuleNotFoundError:
            return False
        return True

    @staticmethod
    def _to_ns(value: datetime | None) -> int | None:
        if value is None:
            return None
        return int(value.timestamp() * 1_000_000_000)

    def _ensure_tracer(self):
        if not self.dependencies_available():
            raise ModuleNotFoundError("opentelemetry telemetry dependencies are not installed")

        if self._tracer is None:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor
            from opentelemetry.sdk.trace.id_generator import IdGenerator, RandomIdGenerator

            class MemTraceIdGenerator(IdGenerator):
                def __init__(self) -> None:
                    self._fallback = RandomIdGenerator()

                def generate_span_id(self) -> int:
                    hint = _OTEL_ID_HINT.get()
                    return hint[1] if hint is not None else self._fallback.generate_span_id()

                def generate_trace_id(self) -> int:
                    hint = _OTEL_ID_HINT.get()
                    return hint[0] if hint is not None else self._fallback.generate_trace_id()

            self._provider = TracerProvider(
                resource=Resource.create({"service.name": "memtrace"}),
                id_generator=MemTraceIdGenerator(),
            )
            self._provider.add_span_processor(
                BatchSpanProcessor(OTLPSpanExporter(endpoint=self.endpoint, headers=self.headers or None))
            )
            self._tracer = self._provider.get_tracer("memtrace.telemetry")
        return self._tracer

    def _otel_parent_context(self, span: TelemetrySpan):
        if not span.parent_span_id:
            return None
        try:
            trace_id = int(span.trace_id, 16)
            parent_span_id = int(span.parent_span_id, 16)
        except ValueError:
            return None
        from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags, set_span_in_context

        return set_span_in_context(
            NonRecordingSpan(
                SpanContext(
                    trace_id=trace_id,
                    span_id=parent_span_id,
                    is_remote=False,
                    trace_flags=TraceFlags(TraceFlags.SAMPLED),
                )
            )
        )

    def export_spans(self, spans: list[TelemetrySpan]) -> TelemetryExportResult:
        try:
            tracer = self._ensure_tracer()
        except ModuleNotFoundError:
            return TelemetryExportResult(
                exported_span_count=0,
                dropped_span_count=len(spans),
                warnings=["OTLP telemetry dependencies are not installed; dropped spans"],
            )

        try:
            from opentelemetry.trace import Status, StatusCode
        except ModuleNotFoundError:
            Status = None
            StatusCode = None

        for span in [_sanitize_span(item) for item in spans]:
            try:
                id_hint = (int(span.trace_id, 16), int(span.span_id, 16))
            except ValueError:
                id_hint = None
            token = _OTEL_ID_HINT.set(id_hint)
            try:
                span_cm = tracer.start_as_current_span(
                    span.name,
                    attributes=dict(span.attributes),
                    start_time=self._to_ns(span.start_time),
                    end_on_exit=False,
                    context=self._otel_parent_context(span),
                )
                otel_span = span_cm.__enter__()
            finally:
                _OTEL_ID_HINT.reset(token)
            try:
                if span.status == "ok" and Status is not None and StatusCode is not None:
                    otel_span.set_status(Status(StatusCode.OK))
                elif span.status == "error" and Status is not None and StatusCode is not None:
                    otel_span.set_status(Status(StatusCode.ERROR))
                for event in span.events:
                    otel_span.add_event(event.name, attributes=dict(event.attributes), timestamp=self._to_ns(event.timestamp))
            except BaseException as exc:
                span_cm.__exit__(type(exc), exc, exc.__traceback__)
                raise
            span_cm.__exit__(None, None, None)
            otel_span.end(end_time=self._to_ns(span.end_time))
        return TelemetryExportResult(exported_span_count=len(spans), dropped_span_count=0, warnings=[])

    def shutdown(self) -> None:
        if self._provider is not None:
            self._provider.shutdown()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.shutdown()


__all__ = [
    "InMemoryTelemetryExporter",
    "JsonlTelemetryExporter",
    "NoopTelemetryExporter",
    "OtlpTelemetryExporter",
    "TelemetryExporter",
]
