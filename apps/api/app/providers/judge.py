from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from app.providers.base import ProviderCapabilities, ProviderKind


@runtime_checkable
class JudgeProvider(Protocol):
    capabilities: ProviderCapabilities

    async def judge(self, payload: dict[str, Any]) -> dict[str, Any]: ...


class NoopJudgeProvider:
    def __init__(self) -> None:
        self.capabilities = ProviderCapabilities(
            provider_id="judge.noop.v1",
            kind=ProviderKind.judge,
            deterministic=True,
            requires_network=False,
        )

    async def judge(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {"decision": "not_configured"}
