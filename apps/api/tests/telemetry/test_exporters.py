from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import pytest

from app.config import Settings
from app.telemetry.factory import build_telemetry_exporter, build_telemetry_service
from app.telemetry.models import TelemetryEvent, TelemetrySpan
from app.telemetry.exporters import (
    InMemoryTelemetryExporter,
    JsonlTelemetryExporter,
    NoopTelemetryExporter,
    OtlpTelemetryExporter,
)


NOW = datetime(2026, 6, 14, 12, 0, tzinfo=timezone.utc)


def _span(span_id: str = "span_1") -> TelemetrySpan:
    return TelemetrySpan(
        name="memtrace.run",
        trace_id="trace_1",
        span_id=span_id,
        start_time=NOW,
        end_time=NOW,
        attributes={
            "memtrace.run_id": "run_1",
            "memtrace.safe": "ok",
            "memtrace.secret": "Bearer sk-1234567890abcdef1234",
        },
    )


def _span_with_secret_event() -> TelemetrySpan:
    return TelemetrySpan(
        name="memtrace.retrieve",
        trace_id="trace_1",
        span_id="span_with_event",
        events=[
            TelemetryEvent(
                name="memtrace.gate",
                attributes={
                    "authorization": "Bearer sk-1234567890abcdef1234",
                    "raw_payload_ref": "vault://raw/event/evt_1",
                    "prompt": "ordinary prompt text should not be exported",
                    "token_budget": 64,
                },
            )
        ],
    )


def test_noop_exporter_drops_spans_without_side_effects():
    result = NoopTelemetryExporter().export_spans([_span()])

    assert result.exported_span_count == 0
    assert result.dropped_span_count == 1
    assert result.warnings == []


def test_in_memory_exporter_collects_sanitized_defensive_snapshots():
    exporter = InMemoryTelemetryExporter()

    result = exporter.export_spans([_span()])

    assert result.exported_span_count == 1
    assert result.dropped_span_count == 0
    snapshot = exporter.get_finished_spans()
    assert len(snapshot) == 1
    assert snapshot[0].attributes["memtrace.secret"] == "[REDACTED]"
    assert "sk-1234567890abcdef1234" not in snapshot[0].model_dump_json()

    snapshot.clear()
    assert len(exporter.get_finished_spans()) == 1
    exporter.clear()
    assert exporter.get_finished_spans() == []


def test_exporters_redact_event_attributes_as_well_as_span_attributes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = "reports/telemetry.jsonl"
    memory_exporter = InMemoryTelemetryExporter()
    jsonl_exporter = JsonlTelemetryExporter(path=path)

    memory_exporter.export_spans([_span_with_secret_event()])
    jsonl_exporter.export_spans([_span_with_secret_event()])

    memory_dump = memory_exporter.get_finished_spans()[0].model_dump_json()
    file_dump = (tmp_path / path).read_text(encoding="utf-8")
    for dumped in (memory_dump, file_dump):
        assert "sk-1234567890abcdef1234" not in dumped
        assert "raw_payload_ref" not in dumped
        assert "vault://raw/event" not in dumped
        assert "ordinary prompt text" not in dumped
        assert "token_budget" in dumped


def test_jsonl_exporter_overwrites_by_default_and_appends_only_when_configured(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = "reports/nested/telemetry.jsonl"

    first = JsonlTelemetryExporter(path=path)
    first_result = first.export_spans([_span("span_1")])
    second = JsonlTelemetryExporter(path=path)
    second_result = second.export_spans([_span("span_2")])

    assert first_result.exported_span_count == 1
    assert second_result.exported_span_count == 1
    lines = (tmp_path / path).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["span_id"] == "span_2"
    assert "sk-1234567890abcdef1234" not in lines[0]

    appending = JsonlTelemetryExporter(path=path, append=True)
    appending.export_spans([_span("span_3")])

    appended_lines = (tmp_path / path).read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["span_id"] for line in appended_lines] == ["span_2", "span_3"]


def test_jsonl_exporter_rejects_unsafe_direct_paths(tmp_path):
    with pytest.raises(ValueError, match="reports"):
        JsonlTelemetryExporter(path=tmp_path / "telemetry.jsonl")
    with pytest.raises(ValueError, match="reports"):
        JsonlTelemetryExporter(path="../telemetry.jsonl")


def test_jsonl_exporter_rechecks_final_file_symlink_before_write(tmp_path, monkeypatch):
    if not hasattr(os, "symlink"):
        pytest.skip("symlink is not available on this platform")
    monkeypatch.chdir(tmp_path)
    reports = tmp_path / "reports"
    reports.mkdir()
    exporter = JsonlTelemetryExporter(path="reports/telemetry.jsonl")
    outside = tmp_path / "outside.jsonl"
    os.symlink(outside, reports / "telemetry.jsonl")

    with pytest.raises(ValueError, match="symlink"):
        exporter.export_spans([_span()])


def test_factory_defaults_to_noop_when_telemetry_disabled():
    built = build_telemetry_exporter(Settings())

    assert isinstance(built.exporter, NoopTelemetryExporter)
    assert built.warnings == []


def test_factory_builds_jsonl_exporter_when_enabled(tmp_path):
    path = "reports/test-telemetry.jsonl"
    built = build_telemetry_exporter(
        Settings(
            telemetry_enabled=True,
            telemetry_exporter="jsonl",
            telemetry_jsonl_path=path,
            telemetry_jsonl_append=True,
        )
    )

    assert isinstance(built.exporter, JsonlTelemetryExporter)
    assert built.warnings == []


def test_factory_rejects_jsonl_paths_outside_reports():
    parent_escape = build_telemetry_exporter(
        Settings(telemetry_enabled=True, telemetry_exporter="jsonl", telemetry_jsonl_path="../telemetry.jsonl")
    )
    absolute_path = build_telemetry_exporter(
        Settings(telemetry_enabled=True, telemetry_exporter="jsonl", telemetry_jsonl_path="/tmp/telemetry.jsonl")
    )

    assert isinstance(parent_escape.exporter, NoopTelemetryExporter)
    assert isinstance(absolute_path.exporter, NoopTelemetryExporter)
    assert any("reports" in warning.lower() for warning in parent_escape.warnings)
    assert any("reports" in warning.lower() for warning in absolute_path.warnings)


def test_factory_rejects_jsonl_symlink_escape(tmp_path, monkeypatch):
    if not hasattr(os, "symlink"):
        pytest.skip("symlink is not available on this platform")
    outside = tmp_path / "outside"
    outside.mkdir()
    os.symlink(outside, tmp_path / "reports")
    monkeypatch.chdir(tmp_path)

    built = build_telemetry_exporter(
        Settings(telemetry_enabled=True, telemetry_exporter="jsonl", telemetry_jsonl_path="reports/telemetry.jsonl")
    )

    assert isinstance(built.exporter, NoopTelemetryExporter)
    assert any("symlink" in warning.lower() or "reports" in warning.lower() for warning in built.warnings)


def test_factory_rejects_jsonl_final_file_symlink_escape(tmp_path, monkeypatch):
    if not hasattr(os, "symlink"):
        pytest.skip("symlink is not available on this platform")
    outside = tmp_path / "outside"
    outside.mkdir()
    reports = tmp_path / "reports"
    reports.mkdir()
    os.symlink(outside / "telemetry.jsonl", reports / "telemetry.jsonl")
    monkeypatch.chdir(tmp_path)

    built = build_telemetry_exporter(
        Settings(telemetry_enabled=True, telemetry_exporter="jsonl", telemetry_jsonl_path="reports/telemetry.jsonl")
    )

    assert isinstance(built.exporter, NoopTelemetryExporter)
    assert any("symlink" in warning.lower() or "reports" in warning.lower() for warning in built.warnings)


def test_factory_degrades_otlp_to_noop_without_endpoint_or_dependencies():
    missing_endpoint = build_telemetry_exporter(Settings(telemetry_enabled=True, telemetry_exporter="otlp"))

    assert isinstance(missing_endpoint.exporter, NoopTelemetryExporter)
    assert any("endpoint" in warning.lower() for warning in missing_endpoint.warnings)

    missing_dependency = build_telemetry_exporter(
        Settings(
            telemetry_enabled=True,
            telemetry_exporter="otlp",
            telemetry_otlp_endpoint="http://localhost:4318/v1/traces",
        ),
        require_otlp_dependencies=True,
        otlp_dependencies_available=False,
    )
    assert isinstance(missing_dependency.exporter, NoopTelemetryExporter)
    assert any("dependency" in warning.lower() for warning in missing_dependency.warnings)


def test_factory_rejects_otlp_endpoint_with_invalid_scheme_or_embedded_credentials():
    invalid_scheme = build_telemetry_exporter(
        Settings(
            telemetry_enabled=True,
            telemetry_exporter="otlp",
            telemetry_otlp_endpoint="ftp://localhost:4318/v1/traces",
        ),
        otlp_dependencies_available=True,
    )
    embedded_credentials = build_telemetry_exporter(
        Settings(
            telemetry_enabled=True,
            telemetry_exporter="otlp",
            telemetry_otlp_endpoint="https://user:pass@example.test/v1/traces",
        ),
        otlp_dependencies_available=True,
    )

    assert isinstance(invalid_scheme.exporter, NoopTelemetryExporter)
    assert isinstance(embedded_credentials.exporter, NoopTelemetryExporter)
    assert any("invalid" in warning.lower() for warning in invalid_scheme.warnings)
    assert any("credentials" in warning.lower() for warning in embedded_credentials.warnings)


def test_factory_malformed_otlp_endpoint_degrades_to_noop_with_warning():
    built = build_telemetry_exporter(
        Settings(
            telemetry_enabled=True,
            telemetry_exporter="otlp",
            telemetry_otlp_endpoint="http://[::1",
        ),
        otlp_dependencies_available=True,
    )

    assert isinstance(built.exporter, NoopTelemetryExporter)
    assert any("invalid" in warning.lower() for warning in built.warnings)


def test_factory_allows_otlp_exporter_when_endpoint_and_dependencies_are_available():
    built = build_telemetry_exporter(
        Settings(
            telemetry_enabled=True,
            telemetry_exporter="otlp",
            telemetry_otlp_endpoint="http://localhost:4318/v1/traces",
            telemetry_headers={"x-otlp-routing": "local"},
        ),
        require_otlp_dependencies=True,
        otlp_dependencies_available=True,
    )

    assert isinstance(built.exporter, OtlpTelemetryExporter)
    assert built.exporter.headers == {"x-otlp-routing": "local"}
    assert built.warnings == []


def test_factory_strict_mode_raises_instead_of_degrading():
    with pytest.raises(ValueError, match="OTLP telemetry dependency"):
        build_telemetry_exporter(
            Settings(
                telemetry_enabled=True,
                telemetry_exporter="otlp",
                telemetry_otlp_endpoint="http://localhost:4318/v1/traces",
                telemetry_strict=True,
            ),
            require_otlp_dependencies=True,
            otlp_dependencies_available=False,
        )


def test_settings_reject_invalid_telemetry_sample_rate():
    with pytest.raises(ValueError, match="telemetry_sample_rate"):
        Settings(telemetry_sample_rate=1.5)


def test_otlp_exporter_redacts_span_and_event_attributes_before_sdk_conversion(monkeypatch):
    captured: dict[str, object] = {}

    class FakeOtelSpan:
        def set_status(self, status):
            captured["status"] = status

        def add_event(self, name, attributes=None, timestamp=None):
            captured["event_name"] = name
            captured["event_attributes"] = attributes

        def end(self, end_time=None):
            captured["ended"] = True

    class FakeSpanContext:
        def __enter__(self):
            return FakeOtelSpan()

        def __exit__(self, exc_type, exc, traceback):
            return None

    class FakeTracer:
        def start_as_current_span(self, name, attributes=None, start_time=None, end_on_exit=False, context=None):
            captured["span_name"] = name
            captured["span_attributes"] = attributes
            captured["context"] = context
            return FakeSpanContext()

    exporter = OtlpTelemetryExporter(endpoint="http://localhost:4318/v1/traces")
    monkeypatch.setattr(exporter, "_ensure_tracer", lambda: FakeTracer())

    result = exporter.export_spans([_span_with_secret_event()])

    assert result.exported_span_count == 1
    dumped = json.dumps(captured, default=str)
    assert "sk-1234567890abcdef1234" not in dumped
    assert "raw_payload_ref" not in dumped
    assert "ordinary prompt text" not in dumped
    assert captured["event_attributes"]["token_budget"] == 64


def test_otlp_exporter_uses_internal_trace_and_parent_context(monkeypatch):
    captured_contexts: list[object] = []

    class FakeOtelSpan:
        def set_status(self, status):
            return None

        def add_event(self, name, attributes=None, timestamp=None):
            return None

        def end(self, end_time=None):
            return None

    class FakeSpanContext:
        def __enter__(self):
            return FakeOtelSpan()

        def __exit__(self, exc_type, exc, traceback):
            return None

    class FakeTracer:
        def start_as_current_span(self, name, attributes=None, start_time=None, end_on_exit=False, context=None):
            captured_contexts.append(context)
            return FakeSpanContext()

    run_span = TelemetrySpan(name="memtrace.run", trace_id="0" * 31 + "1", span_id="0" * 15 + "1")
    step_span = TelemetrySpan(
        name="memtrace.step",
        trace_id=run_span.trace_id,
        span_id="0" * 15 + "2",
        parent_span_id=run_span.span_id,
    )
    exporter = OtlpTelemetryExporter(endpoint="http://localhost:4318/v1/traces")
    monkeypatch.setattr(exporter, "_ensure_tracer", lambda: FakeTracer())
    monkeypatch.setattr(exporter, "_otel_parent_context", lambda span: f"parent:{span.parent_span_id}" if span.parent_span_id else None)

    result = exporter.export_spans([run_span, step_span])

    assert result.exported_span_count == 2
    assert captured_contexts == [None, f"parent:{run_span.span_id}"]


def test_factory_unknown_exporter_degrades_to_noop_with_warning():
    built = build_telemetry_exporter(Settings(telemetry_enabled=True, telemetry_exporter="bogus"))

    assert isinstance(built.exporter, NoopTelemetryExporter)
    assert any("unknown" in warning.lower() for warning in built.warnings)


def test_factory_builds_service_with_settings_fail_open_flag():
    built = build_telemetry_service(Settings(telemetry_fail_open=False))

    assert isinstance(built.service.exporter, NoopTelemetryExporter)
    assert built.service.fail_open is False
    assert built.warnings == []
