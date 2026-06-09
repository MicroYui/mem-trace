"""Runtime integration tests for the config-gated LLM extraction pipeline (P2).

Exercises the opt-in ``extraction_provider`` path: when a provider is injected,
user-message events are turned into memories by the provider (via
``llm_extractor.build_results``) instead of the rule-based writer, then flow
through the same supersede + resolver persistence. With no provider the default
rule-based path is unchanged. Secret events never reach the extractor, and the
provider path also works under buffered/idle flush.
"""
from __future__ import annotations

from app.memory.llm_extractor import ExtractionCandidate, FakeExtractionProvider
from app.runtime.memory_runtime import MemoryRuntime
from app.runtime.models import (
    EventRole,
    EventType,
    ExtractionMode,
    MemoryStatus,
    MemoryType,
    StartRunRequest,
    StartStepRequest,
    WriteEventRequest,
)
from app.runtime.repository import InMemoryRepository


class _RecordingProvider:
    """Deterministic provider that records the events it was asked to extract."""

    def __init__(self, candidates: list[ExtractionCandidate]):
        self._candidates = candidates
        self.seen: list[str] = []

    async def extract(self, event):
        self.seen.append(event.content or "")
        return list(self._candidates)


class _FailingProvider:
    """Provider that always raises, to exercise the rule-writer fallback."""

    def __init__(self) -> None:
        self.seen: list[str] = []

    async def extract(self, event):
        self.seen.append(event.content or "")
        raise RuntimeError("LLM unavailable")


def _runtime(provider=None, *, mode=ExtractionMode.sync) -> MemoryRuntime:
    return MemoryRuntime(
        InMemoryRepository(),
        default_workspace_id="ws_test",
        extraction_mode=mode,
        extraction_provider=provider,
    )


def _ev(run_id, step_id, content):
    return WriteEventRequest(
        run_id=run_id, step_id=step_id, role=EventRole.user,
        event_type=EventType.message, content=content,
    )


async def _start(rt):
    run = await rt.start_run(StartRunRequest(session_id="s", task="t"))
    step = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="planning"))
    return run, step


async def _project_memories(rt, ws="ws_test"):
    return [
        m for m in await rt.list_memories(workspace_id=ws)
        if m.memory_type == MemoryType.project and m.key == "project.runtime"
    ]


async def test_provider_path_persists_via_resolver():
    provider = _RecordingProvider([ExtractionCandidate(key="project.runtime", value="bun")])
    rt = _runtime(provider)
    run, step = await _start(rt)
    res = await rt.write_event(_ev(run.run_id, step.step_id, "let's set things up"))
    assert res.created_memory_ids
    mems = await _project_memories(rt)
    assert len(mems) == 1 and mems[0].value == "bun"
    # provider was actually consulted with the event content
    assert provider.seen == ["let's set things up"]


async def test_no_provider_uses_rule_based_writer():
    rt = _runtime(provider=None)
    run, step = await _start(rt)
    await rt.write_event(_ev(run.run_id, step.step_id, "这个项目使用 Bun"))
    mems = await _project_memories(rt)
    assert len(mems) == 1 and mems[0].value == "bun"


async def test_provider_dedup_through_resolver():
    provider = _RecordingProvider([ExtractionCandidate(key="project.runtime", value="bun")])
    rt = _runtime(provider)
    run, step = await _start(rt)
    await rt.write_event(_ev(run.run_id, step.step_id, "first"))
    await rt.write_event(_ev(run.run_id, step.step_id, "second"))
    actives = [m for m in await _project_memories(rt) if m.status == MemoryStatus.active]
    assert len(actives) == 1  # resolver deduped the same value


async def test_secret_event_skips_provider():
    provider = _RecordingProvider([ExtractionCandidate(key="project.runtime", value="bun")])
    rt = _runtime(provider)
    run, step = await _start(rt)
    res = await rt.write_event(
        _ev(run.run_id, step.step_id, "api_key=sk-ABCDEFGHIJKLMNOP1234")
    )
    assert res.created_memory_ids == []
    assert provider.seen == []  # extractor never consulted for secret events
    assert await _project_memories(rt) == []


async def test_provider_path_works_under_buffered_flush():
    provider = _RecordingProvider([ExtractionCandidate(key="project.runtime", value="bun")])
    rt = _runtime(provider, mode=ExtractionMode.buffered)
    run, step = await _start(rt)
    res = await rt.write_event(_ev(run.run_id, step.step_id, "deferred"))
    assert res.buffered is True
    assert provider.seen == []  # deferred until flush
    assert await _project_memories(rt) == []
    flushed = await rt.flush_session("s")
    assert flushed.created_memory_ids
    assert provider.seen == ["deferred"]
    mems = await _project_memories(rt)
    assert len(mems) == 1 and mems[0].value == "bun"


async def test_provider_failure_falls_back_to_rule_writer():
    provider = _FailingProvider()
    rt = _runtime(provider)
    run, step = await _start(rt)
    # The provider is consulted but raises; the runtime degrades to the rule
    # writer, which extracts the Bun constraint from the message content.
    res = await rt.write_event(_ev(run.run_id, step.step_id, "这个项目使用 Bun"))
    assert provider.seen == ["这个项目使用 Bun"]
    assert res.created_memory_ids  # no memory lost on LLM failure
    mems = await _project_memories(rt)
    assert len(mems) == 1 and mems[0].value == "bun"
