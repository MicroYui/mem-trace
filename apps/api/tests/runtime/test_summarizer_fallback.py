"""Runtime fallback tests for Context Compaction C3 summarization."""
from __future__ import annotations

import asyncio

from app.memory.summarizer_provider import SummarizeRequest, SummarizeResult
from app.runtime.memory_runtime import MemoryRuntime
from app.runtime.models import CompactionProvider, RetainedFact
from app.runtime.repository import InMemoryRepository


class _FailingSummarizer:
    def __init__(self) -> None:
        self.seen: list[SummarizeRequest] = []

    async def summarize(self, request: SummarizeRequest) -> SummarizeResult:
        self.seen.append(request)
        raise RuntimeError("summarizer unavailable")


class _HangingSummarizer:
    def __init__(self) -> None:
        self.seen: list[SummarizeRequest] = []

    async def summarize(self, request: SummarizeRequest) -> SummarizeResult:
        self.seen.append(request)
        await asyncio.sleep(60)
        raise AssertionError("unreachable")


def _request() -> SummarizeRequest:
    return SummarizeRequest(
        blocks=[],
        must_retain_facts=[RetainedFact(key="project.runtime", value="bun")],
        source_memory_ids=["mem_1"],
        source_event_ids=["evt_1"],
        source_state_node_ids=["node_1"],
        summary_budget_tokens=12,
        run_id="run_1",
        workspace_id="ws_1",
        kind="history_summary",
    )


async def test_summarizer_failure_falls_back_to_rule_with_no_info_loss():
    provider = _FailingSummarizer()
    runtime = MemoryRuntime(
        InMemoryRepository(),
        default_workspace_id="ws_test",
        summarizer_provider=provider,
    )

    result = await runtime._summarize(_request(), deadline_ms=100)

    assert provider.seen
    assert result.provider == CompactionProvider.fallback_rule
    assert {(f.key, f.value) for f in result.retained_facts} == {("project.runtime", "bun")}
    assert "project.runtime=bun" in result.summary


async def test_summarizer_timeout_falls_back_to_rule_with_no_info_loss():
    provider = _HangingSummarizer()
    runtime = MemoryRuntime(
        InMemoryRepository(),
        default_workspace_id="ws_test",
        summarizer_provider=provider,
    )

    result = await runtime._summarize(_request(), deadline_ms=1)

    assert provider.seen
    assert result.provider == CompactionProvider.fallback_rule
    assert {(f.key, f.value) for f in result.retained_facts} == {("project.runtime", "bun")}
    assert "summarizer fallback" in "; ".join(result.warnings)
