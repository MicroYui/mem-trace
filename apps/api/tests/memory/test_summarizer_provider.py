"""Tests for Context Compaction C3 summarizer providers."""
from __future__ import annotations

import json

import httpx
import pytest

from app.api.deps import _build_summarizer_provider
from app.config import Settings
from app.memory.summarizer_provider import (
    LLMSummarizerProvider,
    RuleSummarizerProvider,
    SummarizeRequest,
    SummarizeResult,
    SummarizerValidationError,
    _validate_result,
)
from app.runtime.models import CompactionKind, CompactionProvider, ContextBlock, Provenance, RetainedFact


def _fact(key: str = "project.runtime", value: str = "bun") -> RetainedFact:
    return RetainedFact(key=key, value=value, source_memory_id="mem_1")


def _block(content: str, *, block_type: str = "episodic", memory_id: str = "mem_1") -> ContextBlock:
    return ContextBlock(
        type=block_type,
        content=content,
        source="test",
        memory_id=memory_id,
        tokens=max(1, len(content.split())),
    )


def _request(*, budget: int = 24, facts: list[RetainedFact] | None = None) -> SummarizeRequest:
    facts = facts if facts is not None else [_fact(), _fact("project.database", "postgres")]
    return SummarizeRequest(
        blocks=[
            _block("project.runtime=bun and project.database=postgres are required."),
            _block("Low-priority detail can be omitted if budget is tight."),
        ],
        must_retain_facts=facts,
        source_memory_ids=["mem_1", "mem_2"],
        source_event_ids=["evt_1"],
        source_state_node_ids=["node_1"],
        summary_budget_tokens=budget,
        run_id="run_1",
        workspace_id="ws_1",
        kind=CompactionKind.history_summary,
    )


async def test_rule_provider_is_deterministic_retains_required_facts_and_respects_budget():
    provider = RuleSummarizerProvider()
    request = _request(budget=6)

    first = await provider.summarize(request)
    second = await provider.summarize(request)

    assert first == second
    assert first.provider == CompactionProvider.rule
    assert {(f.key, f.value) for f in first.retained_facts} == {
        ("project.database", "postgres"),
        ("project.runtime", "bun"),
    }
    assert "project.runtime=bun" in first.summary
    assert first.post_tokens <= request.summary_budget_tokens
    assert first.omitted_count == 2


async def test_rule_provider_preserves_same_fact_from_distinct_sources():
    provider = RuleSummarizerProvider()
    request = _request(
        facts=[
            RetainedFact(key="project.runtime", value="bun", source_memory_id="mem_1"),
            RetainedFact(key="project.runtime", value="bun", source_memory_id="mem_2"),
        ]
    )

    result = await provider.summarize(request)

    assert [fact.source_memory_id for fact in result.retained_facts] == ["mem_1", "mem_2"]


async def test_rule_provider_handles_mixed_none_and_string_provenance_when_deduping():
    provider = RuleSummarizerProvider()
    request = _request(
        facts=[
            RetainedFact(key="project.runtime", value="bun", source_memory_id="mem_1"),
            RetainedFact(
                key="project.runtime",
                value="bun",
                source_memory_id="mem_1",
                provenance=Provenance(run_id="run_1"),
            ),
            RetainedFact(key="project.runtime", value="bun", source_memory_id=None),
        ]
    )

    result = await provider.summarize(request)

    assert len(result.retained_facts) == 3


async def test_rule_provider_applies_same_source_validation_as_llm_provider():
    provider = RuleSummarizerProvider()
    request = _request(facts=[RetainedFact(key="project.runtime", value="bun", source_memory_id="mem_invented")])
    request = request.model_copy(update={"source_memory_ids": ["mem_1"]})

    with pytest.raises(SummarizerValidationError, match="source_memory_id"):
        await provider.summarize(request)


def test_validate_result_allows_must_retain_fact_provenance_not_present_in_block_provenance():
    fact = RetainedFact(
        key="project.runtime",
        value="bun",
        source_memory_id="mem_1",
        provenance=Provenance(run_id="run_1", step_id="step_1", event_id="evt_1", state_node_id="node_1"),
    )
    request = SummarizeRequest(
        blocks=[],
        must_retain_facts=[fact],
        source_memory_ids=["mem_1"],
        source_event_ids=["evt_1"],
        source_state_node_ids=["node_1"],
        summary_budget_tokens=50,
        run_id="run_1",
        workspace_id="ws",
        kind=CompactionKind.history_summary,
    )
    result = SummarizeResult(
        summary="project.runtime=bun",
        retained_facts=[fact],
        source_memory_ids=["mem_1"],
        source_event_ids=["evt_1"],
        source_state_node_ids=["node_1"],
        pre_tokens=10,
        post_tokens=2,
    )

    assert _validate_result(request, result).retained_facts == [fact]


def test_validate_result_requires_exact_top_level_source_id_lists():
    request = _request()
    result = SummarizeResult(
        provider=CompactionProvider.llm,
        summary="project.runtime=bun; project.database=postgres.",
        retained_facts=request.must_retain_facts,
        omitted_count=1,
        source_memory_ids=["mem_2", "mem_1"],
        source_event_ids=["evt_1"],
        source_state_node_ids=["node_1"],
        pre_tokens=8,
        post_tokens=2,
        warnings=[],
    )

    with pytest.raises(SummarizerValidationError, match="source_memory_ids"):
        _validate_result(request, result)


def test_validate_result_rejects_must_retain_fact_source_not_declared_by_request_sources():
    fact = RetainedFact(key="project.runtime", value="bun", source_memory_id="mem_invented")
    request = SummarizeRequest(
        blocks=[],
        must_retain_facts=[fact],
        source_memory_ids=["mem_1"],
        source_event_ids=[],
        source_state_node_ids=[],
        summary_budget_tokens=50,
        run_id="run_1",
        workspace_id="ws",
        kind=CompactionKind.history_summary,
    )
    result = SummarizeResult(
        summary="project.runtime=bun",
        retained_facts=[fact],
        source_memory_ids=["mem_1", "mem_invented"],
        source_event_ids=[],
        source_state_node_ids=[],
        pre_tokens=10,
        post_tokens=2,
    )

    with pytest.raises(SummarizerValidationError, match="source_memory_id"):
        _validate_result(request, result)


def test_validate_result_rejects_invented_summary_fact_with_spaces_around_equals():
    request = _request(facts=[_fact()])
    result = SummarizeResult(
        summary="project.runtime=bun; project.secret = token.",
        retained_facts=[_fact()],
        source_memory_ids=["mem_1", "mem_2"],
        source_event_ids=["evt_1"],
        source_state_node_ids=["node_1"],
        pre_tokens=10,
        post_tokens=5,
    )

    with pytest.raises(SummarizerValidationError, match="invented summary facts"):
        _validate_result(request, result)


def _chat_response(payload: dict) -> httpx.Response:
    return httpx.Response(
        200,
        json={"choices": [{"message": {"role": "assistant", "content": json.dumps(payload)}}]},
    )


def _provider(handler) -> LLMSummarizerProvider:
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="https://llm.test/v1")
    return LLMSummarizerProvider(api_key="sk-test", base_url="https://llm.test/v1", client=client)


async def test_llm_provider_request_shape_auth_and_retained_facts_roundtrip():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content)
        return _chat_response(
            {
                "summary": "project.database=postgres; project.runtime=bun.",
                "retained_facts": [
                    {"key": "project.database", "value": "postgres", "source_memory_id": "mem_1"},
                    {"key": "project.runtime", "value": "bun", "source_memory_id": "mem_1"},
                ],
                "omitted_count": 2,
                "source_memory_ids": ["mem_1", "mem_2"],
                "source_event_ids": ["evt_1"],
                "source_state_node_ids": ["node_1"],
                "pre_tokens": 18,
                "post_tokens": 4,
                "warnings": [],
            }
        )

    result = await _provider(handler).summarize(_request())

    assert captured["url"] == "https://llm.test/v1/chat/completions"
    assert captured["auth"] == "Bearer sk-test"
    assert captured["body"]["model"] == "gpt-4o-mini"
    assert "response_format" not in captured["body"]
    assert result.provider == CompactionProvider.llm
    assert {(f.key, f.value) for f in result.retained_facts} == {
        ("project.database", "postgres"),
        ("project.runtime", "bun"),
    }


async def test_llm_provider_sends_response_format_when_enabled():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return _chat_response(
            {
                "summary": "project.runtime=bun.",
                "retained_facts": [{"key": "project.runtime", "value": "bun", "source_memory_id": "mem_1"}],
                "omitted_count": 1,
                "source_memory_ids": ["mem_1", "mem_2"],
                "source_event_ids": ["evt_1"],
                "source_state_node_ids": ["node_1"],
                "pre_tokens": 18,
                "post_tokens": 2,
                "warnings": [],
            }
        )

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="https://llm.test/v1")
    provider = LLMSummarizerProvider(
        api_key="sk-test",
        base_url="https://llm.test/v1",
        use_json_response_format=True,
        client=client,
    )
    await provider.summarize(_request(facts=[_fact()]))
    assert captured["body"]["response_format"] == {"type": "json_object"}


async def test_llm_provider_strips_markdown_code_fences():
    def handler(request: httpx.Request) -> httpx.Response:
        fenced = """```json
{"summary":"project.runtime=bun.","retained_facts":[{"key":"project.runtime","value":"bun","source_memory_id":"mem_1"}],"omitted_count":1,"source_memory_ids":["mem_1","mem_2"],"source_event_ids":["evt_1"],"source_state_node_ids":["node_1"],"pre_tokens":8,"post_tokens":2,"warnings":[]}
```"""
        return httpx.Response(200, json={"choices": [{"message": {"content": fenced}}]})

    result = await _provider(handler).summarize(_request(facts=[_fact()]))
    assert result.summary == "project.runtime=bun."


async def test_llm_provider_raises_on_http_error_bad_json_and_missing_fields():
    def http_error(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    with pytest.raises(httpx.HTTPStatusError):
        await _provider(http_error).summarize(_request())

    def bad_json(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]})

    with pytest.raises(json.JSONDecodeError):
        await _provider(bad_json).summarize(_request())

    def missing_fields(request: httpx.Request) -> httpx.Response:
        return _chat_response({"summary": "missing required fields"})

    with pytest.raises(Exception):
        await _provider(missing_fields).summarize(_request())


async def test_llm_provider_rejects_invented_retained_fact():
    def handler(request: httpx.Request) -> httpx.Response:
        return _chat_response(
            {
                "summary": "project.runtime=bun; project.secret=token; api_key=sk-1234567890123456.",
                "retained_facts": [
                    {"key": "project.runtime", "value": "bun"},
                    {"key": "project.secret", "value": "token"},
                ],
                "omitted_count": 1,
                "source_memory_ids": ["mem_1", "mem_2"],
                "source_event_ids": ["evt_1"],
                "source_state_node_ids": ["node_1"],
                "pre_tokens": 8,
                "post_tokens": 4,
                "warnings": [],
            }
        )

    with pytest.raises(SummarizerValidationError):
        await _provider(handler).summarize(_request(facts=[_fact()]))


async def test_llm_provider_rejects_unretained_key_value_fact_in_summary():
    def handler(request: httpx.Request) -> httpx.Response:
        return _chat_response(
            {
                "summary": "project.runtime=bun; project.secret=token; api_key=sk-1234567890123456.",
                "retained_facts": [{"key": "project.runtime", "value": "bun", "source_memory_id": "mem_1"}],
                "omitted_count": 1,
                "source_memory_ids": ["mem_1", "mem_2"],
                "source_event_ids": ["evt_1"],
                "source_state_node_ids": ["node_1"],
                "pre_tokens": 8,
                "post_tokens": 4,
                "warnings": [],
            }
        )

    with pytest.raises(SummarizerValidationError):
        await _provider(handler).summarize(_request(facts=[_fact()]))


async def test_llm_provider_rejects_missing_must_retain_fact():
    def handler(request: httpx.Request) -> httpx.Response:
        return _chat_response(
            {
                "summary": "project.runtime=bun.",
                "retained_facts": [{"key": "project.runtime", "value": "bun", "source_memory_id": "mem_1"}],
                "omitted_count": 1,
                "source_memory_ids": ["mem_1", "mem_2"],
                "source_event_ids": ["evt_1"],
                "source_state_node_ids": ["node_1"],
                "pre_tokens": 8,
                "post_tokens": 2,
                "warnings": [],
            }
        )

    with pytest.raises(SummarizerValidationError):
        await _provider(handler).summarize(_request())


async def test_llm_provider_recomputes_post_tokens_before_budget_check():
    long_summary = " ".join(["project.runtime=bun"] * 20)

    def handler(request: httpx.Request) -> httpx.Response:
        return _chat_response(
            {
                "summary": long_summary,
                "retained_facts": [{"key": "project.runtime", "value": "bun", "source_memory_id": "mem_1"}],
                "omitted_count": 1,
                "source_memory_ids": ["mem_1", "mem_2"],
                "source_event_ids": ["evt_1"],
                "source_state_node_ids": ["node_1"],
                "pre_tokens": 40,
                "post_tokens": 1,
                "warnings": [],
            }
        )

    request = _request(budget=4, facts=[_fact()])
    result = await _provider(handler).summarize(request)

    assert result.summary != long_summary
    assert result.post_tokens <= request.summary_budget_tokens
    assert "summary truncated to fit budget" in result.warnings


async def test_llm_provider_rejects_invented_source_ids_and_fact_provenance():
    def invented_top_level_sources(request: httpx.Request) -> httpx.Response:
        return _chat_response(
            {
                "summary": "project.runtime=bun.",
                "retained_facts": [{"key": "project.runtime", "value": "bun", "source_memory_id": "mem_1"}],
                "omitted_count": 1,
                "source_memory_ids": ["mem_other"],
                "source_event_ids": ["evt_1"],
                "source_state_node_ids": ["node_1"],
                "pre_tokens": 8,
                "post_tokens": 2,
                "warnings": [],
            }
        )

    with pytest.raises(SummarizerValidationError):
        await _provider(invented_top_level_sources).summarize(_request(facts=[_fact()]))

    def invented_fact_source(request: httpx.Request) -> httpx.Response:
        return _chat_response(
            {
                "summary": "project.runtime=bun.",
                "retained_facts": [{"key": "project.runtime", "value": "bun", "source_memory_id": "mem_other"}],
                "omitted_count": 1,
                "source_memory_ids": ["mem_1"],
                "source_event_ids": ["evt_1"],
                "source_state_node_ids": ["node_1"],
                "pre_tokens": 8,
                "post_tokens": 2,
                "warnings": [],
            }
        )

    with pytest.raises(SummarizerValidationError):
        await _provider(invented_fact_source).summarize(_request(facts=[_fact()]))


async def test_llm_provider_rejects_missing_top_level_source_ids():
    def handler(request: httpx.Request) -> httpx.Response:
        return _chat_response(
            {
                "summary": "project.runtime=bun.",
                "retained_facts": [{"key": "project.runtime", "value": "bun", "source_memory_id": "mem_1"}],
                "omitted_count": 1,
                "source_memory_ids": [],
                "source_event_ids": [],
                "source_state_node_ids": [],
                "pre_tokens": 8,
                "post_tokens": 2,
                "warnings": [],
            }
        )

    with pytest.raises(SummarizerValidationError):
        await _provider(handler).summarize(_request(facts=[_fact()]))


async def test_llm_provider_rejects_retained_fact_bound_to_wrong_allowed_source():
    def handler(request: httpx.Request) -> httpx.Response:
        return _chat_response(
            {
                "summary": "project.runtime=bun; project.database=postgres.",
                "retained_facts": [
                    {"key": "project.runtime", "value": "bun", "source_memory_id": "mem_db"},
                    {"key": "project.database", "value": "postgres", "source_memory_id": "mem_db"},
                ],
                "omitted_count": 2,
                "source_memory_ids": ["mem_runtime", "mem_db"],
                "source_event_ids": ["evt_runtime", "evt_db"],
                "source_state_node_ids": ["node_runtime", "node_db"],
                "pre_tokens": 16,
                "post_tokens": 4,
                "warnings": [],
            }
        )

    request = _request(
        facts=[
            RetainedFact(key="project.runtime", value="bun", source_memory_id="mem_runtime"),
            RetainedFact(key="project.database", value="postgres", source_memory_id="mem_db"),
        ]
    )
    request.source_memory_ids = ["mem_runtime", "mem_db"]
    request.source_event_ids = ["evt_runtime", "evt_db"]
    request.source_state_node_ids = ["node_runtime", "node_db"]
    with pytest.raises(SummarizerValidationError):
        await _provider(handler).summarize(request)


async def test_llm_provider_rejects_missing_required_fact_identity_with_same_key_value():
    def handler(request: httpx.Request) -> httpx.Response:
        return _chat_response(
            {
                "summary": "project.runtime=bun.",
                "retained_facts": [{"key": "project.runtime", "value": "bun", "source_memory_id": "mem_2"}],
                "omitted_count": 1,
                "source_memory_ids": ["mem_1", "mem_2"],
                "source_event_ids": ["evt_1"],
                "source_state_node_ids": ["node_1"],
                "pre_tokens": 12,
                "post_tokens": 2,
                "warnings": [],
            }
        )

    request = _request(
        facts=[
            RetainedFact(key="project.runtime", value="bun", source_memory_id="mem_1"),
            RetainedFact(key="project.runtime", value="bun", source_memory_id="mem_2"),
        ]
    )
    request.source_memory_ids = ["mem_1", "mem_2"]
    with pytest.raises(SummarizerValidationError):
        await _provider(handler).summarize(request)


async def test_llm_provider_rejects_invented_provenance_run_or_step_id():
    def invented_run_id(request: httpx.Request) -> httpx.Response:
        return _chat_response(
            {
                "summary": "project.runtime=bun.",
                "retained_facts": [
                    {
                        "key": "project.runtime",
                        "value": "bun",
                        "source_memory_id": "mem_1",
                        "provenance": {"run_id": "run_other", "event_id": "evt_1", "state_node_id": "node_1"},
                    }
                ],
                "omitted_count": 1,
                "source_memory_ids": ["mem_1"],
                "source_event_ids": ["evt_1"],
                "source_state_node_ids": ["node_1"],
                "pre_tokens": 8,
                "post_tokens": 2,
                "warnings": [],
            }
        )

    with pytest.raises(SummarizerValidationError):
        await _provider(invented_run_id).summarize(_request(facts=[_fact()]))

    def invented_step_id(request: httpx.Request) -> httpx.Response:
        return _chat_response(
            {
                "summary": "project.runtime=bun.",
                "retained_facts": [
                    {
                        "key": "project.runtime",
                        "value": "bun",
                        "source_memory_id": "mem_1",
                        "provenance": {"run_id": "run_1", "step_id": "step_other", "event_id": "evt_1"},
                    }
                ],
                "omitted_count": 1,
                "source_memory_ids": ["mem_1"],
                "source_event_ids": ["evt_1"],
                "source_state_node_ids": ["node_1"],
                "pre_tokens": 8,
                "post_tokens": 2,
                "warnings": [],
            }
        )

    request = _request(facts=[_fact()])
    request.blocks[0].provenance = Provenance(run_id="run_1", step_id="step_1", event_id="evt_1")
    with pytest.raises(SummarizerValidationError):
        await _provider(invented_step_id).summarize(request)


async def test_llm_provider_does_not_allow_negated_key_value_from_free_text():
    def handler(request: httpx.Request) -> httpx.Response:
        return _chat_response(
            {
                "summary": "project.runtime=npm.",
                "retained_facts": [{"key": "project.runtime", "value": "npm"}],
                "omitted_count": 1,
                "source_memory_ids": ["mem_1"],
                "source_event_ids": ["evt_1"],
                "source_state_node_ids": ["node_1"],
                "pre_tokens": 8,
                "post_tokens": 2,
                "warnings": [],
            }
        )

    request = SummarizeRequest(
        blocks=[_block("do not use project.runtime=npm")],
        must_retain_facts=[],
        source_memory_ids=["mem_1"],
        source_event_ids=["evt_1"],
        source_state_node_ids=["node_1"],
        summary_budget_tokens=12,
        workspace_id="ws_1",
        kind=CompactionKind.history_summary,
    )
    with pytest.raises(SummarizerValidationError):
        await _provider(handler).summarize(request)


def test_dependency_wiring_uses_rule_by_default_and_llm_when_enabled_with_key():
    default_provider = _build_summarizer_provider(Settings())
    assert isinstance(default_provider, RuleSummarizerProvider)

    no_key_provider = _build_summarizer_provider(Settings(llm_summarizer_enabled=True, llm_api_key=""))
    assert isinstance(no_key_provider, RuleSummarizerProvider)

    llm_provider = _build_summarizer_provider(
        Settings(llm_summarizer_enabled=True, llm_api_key="sk-test", llm_base_url="https://llm.test/v1")
    )
    assert isinstance(llm_provider, LLMSummarizerProvider)


def _valid_summary_payload() -> dict:
    return {
        "summary": "project.database=postgres; project.runtime=bun.",
        "retained_facts": [
            {"key": "project.database", "value": "postgres", "source_memory_id": "mem_1"},
            {"key": "project.runtime", "value": "bun", "source_memory_id": "mem_1"},
        ],
        "omitted_count": 2,
        "source_memory_ids": ["mem_1", "mem_2"],
        "source_event_ids": ["evt_1"],
        "source_state_node_ids": ["node_1"],
        "pre_tokens": 18,
        "post_tokens": 4,
        "warnings": [],
    }


async def test_llm_summarizer_provider_reuses_and_closes_lazy_client(monkeypatch):
    """When no client is injected, the provider must create one lazily, reuse it
    across calls, and close it via aclose()."""
    created: list[httpx.AsyncClient] = []
    real_async_client = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        return _chat_response(_valid_summary_payload())

    def fake_async_client(*args, **kwargs):
        client = real_async_client(transport=httpx.MockTransport(handler))
        created.append(client)
        return client

    monkeypatch.setattr("app.memory.summarizer_provider.httpx.AsyncClient", fake_async_client)
    provider = LLMSummarizerProvider(api_key="sk-test", base_url="https://llm.test/v1")

    assert provider._client is None
    first = await provider.summarize(_request())
    second = await provider.summarize(_request())
    assert first.provider == CompactionProvider.llm
    assert second.provider == CompactionProvider.llm
    assert len(created) == 1  # client reused, not recreated per call
    assert provider._client is created[0]

    await provider.aclose()
    assert provider._client is None
