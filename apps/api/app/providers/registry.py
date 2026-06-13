from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.providers.base import ProviderCapabilities, ProviderKind


@dataclass(slots=True)
class ProviderSlot:
    provider: Any
    capabilities: ProviderCapabilities


class ProviderRegistry:
    def __init__(self) -> None:
        self._slots: dict[ProviderKind, ProviderSlot] = {}

    def register(self, kind: ProviderKind, provider: Any, capabilities: ProviderCapabilities) -> None:
        if capabilities.kind != kind:
            raise ValueError("provider capability kind mismatch")
        self._slots[kind] = ProviderSlot(provider=provider, capabilities=capabilities)

    def get(self, kind: ProviderKind) -> Any | None:
        slot = self._slots.get(kind)
        return slot.provider if slot is not None else None

    def capabilities(self, kind: ProviderKind) -> ProviderCapabilities | None:
        slot = self._slots.get(kind)
        return slot.capabilities if slot is not None else None

    def snapshot(self) -> dict[str, dict[str, Any]]:
        return {
            kind.value: slot.capabilities.snapshot()
            for kind, slot in sorted(self._slots.items(), key=lambda item: item[0].value)
        }

