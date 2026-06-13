from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Protocol, runtime_checkable

_SECRET_METADATA_TERMS = (
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "token",
    "password",
    "secret",
    "credential",
)
_SECRET_VALUE_TERMS = (
    "sk-",
    "bearer ",
    "api_key",
    "apikey",
    "authorization",
    "token",
    "password",
    "passwd",
    "secret",
    "credential",
    "private_key",
)


class ProviderKind(str, Enum):
    extraction = "extraction"
    embedding = "embedding"
    summarizer = "summarizer"
    judge = "judge"


def _is_secret_metadata_key(key: str) -> bool:
    lowered = key.lower().replace("-", "_")
    return any(term in lowered for term in _SECRET_METADATA_TERMS)


def _is_secret_metadata_value(value: str) -> bool:
    lowered = value.lower()
    return any(term in lowered for term in _SECRET_VALUE_TERMS)


def _safe_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in sorted(metadata.items(), key=lambda item: str(item[0])):
        key_text = str(key)
        if _is_secret_metadata_key(key_text):
            continue
        if isinstance(value, Mapping):
            safe[key_text] = _safe_metadata(value)
        elif isinstance(value, str):
            if _is_secret_metadata_value(value):
                continue
            safe[key_text] = value
        elif isinstance(value, (int, float, bool)) or value is None:
            safe[key_text] = value
        else:
            text = str(value)
            if _is_secret_metadata_value(text):
                continue
            safe[key_text] = text
    return safe


def _safe_optional_string(value: str | None) -> str | None:
    if value is None or _is_secret_metadata_value(value):
        return None
    return value


def _safe_string_list(values: tuple[str, ...]) -> list[str]:
    return [value for value in values if not _is_secret_metadata_value(value)]


def _freeze_metadata(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze_metadata(nested) for key, nested in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_metadata(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    provider_id: str
    kind: ProviderKind
    deterministic: bool
    requires_network: bool
    endpoint_types: tuple[str, ...] = ()
    model: str | None = None
    configured: bool = True
    fallback_provider_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", _freeze_metadata(self.metadata))

    def snapshot(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "kind": self.kind.value,
            "deterministic": self.deterministic,
            "requires_network": self.requires_network,
            "endpoint_types": _safe_string_list(self.endpoint_types),
            "model": _safe_optional_string(self.model),
            "configured": self.configured,
            "fallback_provider_id": _safe_optional_string(self.fallback_provider_id),
            "metadata": _safe_metadata(self.metadata),
        }


@runtime_checkable
class EmbeddingProvider(Protocol):
    capabilities: ProviderCapabilities

    async def embed_text(self, text: str | None) -> list[float]: ...
