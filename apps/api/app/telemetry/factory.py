"""Settings-driven telemetry exporter factory."""
from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlparse

from app.config import Settings
from app.telemetry.exporters import (
    JsonlTelemetryExporter,
    NoopTelemetryExporter,
    OtlpTelemetryExporter,
    TelemetryExporter,
)
from app.telemetry.service import TelemetryService


@dataclass(frozen=True)
class TelemetryExporterBuildResult:
    exporter: TelemetryExporter
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TelemetryServiceBuildResult:
    service: TelemetryService
    warnings: list[str] = field(default_factory=list)


def build_telemetry_exporter(
    settings: Settings,
    *,
    require_otlp_dependencies: bool = True,
    otlp_dependencies_available: bool | None = None,
) -> TelemetryExporterBuildResult:
    """Build a telemetry exporter from settings.

    The default disabled path always returns noop without touching filesystem,
    optional dependencies, or network endpoints.
    """
    def _degrade(message: str) -> TelemetryExporterBuildResult:
        if settings.telemetry_strict:
            raise ValueError(message)
        return TelemetryExporterBuildResult(exporter=NoopTelemetryExporter(), warnings=[f"{message}; using noop"])

    if not settings.telemetry_enabled:
        return TelemetryExporterBuildResult(exporter=NoopTelemetryExporter())

    exporter_name = settings.telemetry_exporter.strip().lower()
    if exporter_name in {"", "noop", "none", "disabled"}:
        return TelemetryExporterBuildResult(exporter=NoopTelemetryExporter())
    if exporter_name == "jsonl":
        try:
            return TelemetryExporterBuildResult(
                exporter=JsonlTelemetryExporter(
                    path=settings.telemetry_jsonl_path,
                    append=settings.telemetry_jsonl_append,
                )
            )
        except ValueError as exc:
            return _degrade(str(exc))
    if exporter_name == "otlp":
        if not settings.telemetry_otlp_endpoint:
            return _degrade("OTLP telemetry exporter requires MEMTRACE_TELEMETRY_OTLP_ENDPOINT")
        try:
            endpoint = urlparse(settings.telemetry_otlp_endpoint)
        except ValueError:
            return _degrade("Invalid OTLP telemetry endpoint; expected http(s) URL")
        if endpoint.scheme not in {"http", "https"} or not endpoint.netloc:
            return _degrade("Invalid OTLP telemetry endpoint; expected http(s) URL")
        if endpoint.username or endpoint.password:
            return _degrade("OTLP telemetry endpoint must not contain embedded credentials")
        available = OtlpTelemetryExporter.dependencies_available() if otlp_dependencies_available is None else otlp_dependencies_available
        if require_otlp_dependencies and not available:
            return _degrade("OTLP telemetry dependency packages are not installed")
        return TelemetryExporterBuildResult(
            exporter=OtlpTelemetryExporter(endpoint=settings.telemetry_otlp_endpoint, headers=settings.telemetry_headers)
        )

    return _degrade(f"Unknown telemetry exporter '{settings.telemetry_exporter}'")


def build_telemetry_service(
    settings: Settings,
    *,
    require_otlp_dependencies: bool = True,
    otlp_dependencies_available: bool | None = None,
) -> TelemetryServiceBuildResult:
    built = build_telemetry_exporter(
        settings,
        require_otlp_dependencies=require_otlp_dependencies,
        otlp_dependencies_available=otlp_dependencies_available,
    )
    return TelemetryServiceBuildResult(
        service=TelemetryService(
            exporter=built.exporter,
            fail_open=settings.telemetry_fail_open and not settings.telemetry_strict,
            sample_rate=settings.telemetry_sample_rate,
        ),
        warnings=built.warnings,
    )


__all__ = [
    "TelemetryExporterBuildResult",
    "TelemetryServiceBuildResult",
    "build_telemetry_exporter",
    "build_telemetry_service",
]
