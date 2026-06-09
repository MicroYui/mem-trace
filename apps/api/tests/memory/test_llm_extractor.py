"""Pure-function tests for the config-gated LLM extraction pipeline (P2).

The extractor turns provider-emitted candidates into ``MemoryWriteResult``
objects under a fixed Pydantic schema. It is storage-agnostic and deterministic,
so these tests call it directly with plain candidates / events. The runtime
facade (covered in tests/runtime/test_llm_extraction_flow.py) owns persistence.
"""
from __future__ import annotations

from app.memory import llm_extractor
from app.memory.llm_extractor import ExtractionCandidate, FakeExtractionProvider
from app.runtime.models import AgentEvent, EventRole, EventType, MemoryScope, MemoryType


def _user_event(content: str) -> AgentEvent:
    return AgentEvent(
        workspace_id="ws", run_id="r", step_id="s", role=EventRole.user,
        event_type=EventType.message, content=content,
    )


async def test_fake_provider_matches_rule_based_output():
    provider = FakeExtractionProvider()
    candidates = await provider.extract(_user_event("这个项目使用 Bun，不用 Node.js"))
    kv = {c.key: c.value for c in candidates}
    assert kv.get("project.runtime") == "bun"
    assert kv.get("project.runtime.excluded") == "nodejs"


def test_build_results_constructs_memory_with_provenance():
    event = _user_event("这个项目使用 Bun")
    candidates = [ExtractionCandidate(key="project.runtime", value="bun")]
    results = llm_extractor.build_results(event, candidates)
    assert len(results) == 1
    mem = results[0].memory
    assert mem.key == "project.runtime"
    assert mem.value == "bun"
    assert mem.memory_type == MemoryType.project
    assert mem.scope == MemoryScope.workspace
    assert mem.source_event_id == event.event_id
    assert mem.source_run_id == event.run_id
    assert mem.summary == "project.runtime=bun"
    # no supersede requested -> no supersede_keys
    assert results[0].supersede_keys == []


def test_build_results_supersede_emits_supersede_keys():
    event = _user_event("不用 Node，用 Bun")
    candidates = [ExtractionCandidate(key="project.runtime", value="bun", supersede=True)]
    results = llm_extractor.build_results(event, candidates)
    assert results[0].supersede_keys == [("project.runtime", MemoryScope.workspace.value)]


def test_build_results_drops_invalid_candidates():
    event = _user_event("anything")
    candidates = [
        {"key": "project.runtime", "value": "bun"},  # valid dict
        {"key": "missing.value"},  # invalid: no value
        {"value": "no.key"},  # invalid: no key
        "garbage",  # invalid type
    ]
    results = llm_extractor.build_results(event, candidates)
    assert len(results) == 1
    assert results[0].memory.value == "bun"


def test_build_results_ignores_extra_fields():
    event = _user_event("anything")
    candidates = [{"key": "project.runtime", "value": "bun", "evil": "rm -rf /"}]
    results = llm_extractor.build_results(event, candidates)
    assert len(results) == 1
    assert not hasattr(results[0].memory, "evil")


def test_build_results_is_deterministically_ordered():
    event = _user_event("anything")
    unordered = [
        ExtractionCandidate(key="project.runtime.excluded", value="nodejs"),
        ExtractionCandidate(key="project.runtime", value="bun"),
    ]
    keys = [r.memory.key for r in llm_extractor.build_results(event, unordered)]
    # sorted by (scope, key, value): project.runtime < project.runtime.excluded
    assert keys == ["project.runtime", "project.runtime.excluded"]
