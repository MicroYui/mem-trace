"""Internal telemetry DTOs.

These models are intentionally independent from OpenTelemetry SDK classes so
default test/runtime paths do not import optional telemetry dependencies.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

PrimitiveAttribute = str | bool | int | float
TelemetryAttributeValue = PrimitiveAttribute | list[PrimitiveAttribute]


def _validate_attribute_value(value: object) -> object:
    if isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, list) and all(isinstance(item, (str, bool, int, float)) for item in value):
        return value
    raise ValueError("telemetry attributes must be primitive values or lists of primitives")


class _TelemetryBase(BaseModel):
    model_config = ConfigDict(frozen=True)


class TelemetryEvent(_TelemetryBase):
    name: str
    attributes: dict[str, TelemetryAttributeValue] = Field(default_factory=dict)
    timestamp: datetime | None = None

    @field_validator("attributes")
    @classmethod
    def _attributes_are_otel_safe(cls, value: dict[str, TelemetryAttributeValue]) -> dict[str, TelemetryAttributeValue]:
        for attr_value in value.values():
            _validate_attribute_value(attr_value)
        return value


class TelemetrySpan(_TelemetryBase):
    name: str
    trace_id: str
    span_id: str
    parent_span_id: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    attributes: dict[str, TelemetryAttributeValue] = Field(default_factory=dict)
    events: list[TelemetryEvent] = Field(default_factory=list)
    status: Literal["ok", "error", "unset"] = "unset"

    @field_validator("attributes")
    @classmethod
    def _attributes_are_otel_safe(cls, value: dict[str, TelemetryAttributeValue]) -> dict[str, TelemetryAttributeValue]:
        for attr_value in value.values():
            _validate_attribute_value(attr_value)
        return value


class TelemetryExportResult(_TelemetryBase):
    exported_span_count: int = 0
    dropped_span_count: int = 0
    warnings: list[str] = Field(default_factory=list)


__all__ = [
    "PrimitiveAttribute",
    "TelemetryAttributeValue",
    "TelemetryEvent",
    "TelemetryExportResult",
    "TelemetrySpan",
]
