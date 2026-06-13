from __future__ import annotations

from app.providers.base import ProviderCapabilities, ProviderKind
from app.providers.judge import NoopJudgeProvider


async def test_noop_judge_provider_has_capability_metadata_and_no_network():
    provider = NoopJudgeProvider()

    assert provider.capabilities == ProviderCapabilities(
        provider_id="judge.noop.v1",
        kind=ProviderKind.judge,
        deterministic=True,
        requires_network=False,
    )
    assert await provider.judge({"case_id": "case_1"}) == {"decision": "not_configured"}
