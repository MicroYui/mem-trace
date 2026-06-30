"""Tests for the real LLMExtractionProvider (OpenAI-compatible, mocked transport).

These exercise the HTTP request/response handling and schema gating without any
real network call: an ``httpx.MockTransport`` returns canned responses. The
runtime-level fallback-on-failure behavior is covered in
tests/runtime/test_llm_extraction_flow.py.
"""
from __future__ import annotations

import json

import httpx
import pytest

from app.memory.llm_extractor import ExtractionCandidate, LLMExtractionProvider
from app.runtime.models import AgentEvent, EventRole, EventType


def _user_event(content: str) -> AgentEvent:
    return AgentEvent(
        workspace_id="ws", run_id="r", step_id="s", role=EventRole.user,
        event_type=EventType.message, content=content,
    )


def _chat_response(candidates) -> httpx.Response:
    """Build an OpenAI-style chat-completion response wrapping `candidates`."""
    content = json.dumps({"candidates": candidates})
    return httpx.Response(
        200,
        json={"choices": [{"message": {"role": "assistant", "content": content}}]},
    )


def _provider(handler) -> LLMExtractionProvider:
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="https://llm.test/v1")
    return LLMExtractionProvider(api_key="sk-test", base_url="https://llm.test/v1", client=client)


async def test_extract_parses_candidate_array():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content)
        return _chat_response(
            [
                {"key": "project.runtime", "value": "bun", "supersede": True},
                {"key": "project.runtime.excluded", "value": "nodejs"},
            ]
        )

    provider = _provider(handler)
    candidates = await provider.extract(_user_event("用 Bun 不用 Node"))

    assert all(isinstance(c, ExtractionCandidate) for c in candidates)
    kv = {c.key: c.value for c in candidates}
    assert kv == {"project.runtime": "bun", "project.runtime.excluded": "nodejs"}
    assert next(c for c in candidates if c.key == "project.runtime").supersede is True
    # request shape
    assert captured["url"] == "https://llm.test/v1/chat/completions"
    assert captured["auth"] == "Bearer sk-test"
    assert captured["body"]["model"] == "gpt-4o-mini"
    # response_format is omitted by default (some endpoints reject it)
    assert "response_format" not in captured["body"]


async def test_response_format_sent_when_enabled():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return _chat_response([{"key": "project.runtime", "value": "bun"}])

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url="https://llm.test/v1")
    provider = LLMExtractionProvider(
        api_key="sk-test", base_url="https://llm.test/v1",
        use_json_response_format=True, client=client,
    )
    await provider.extract(_user_event("用 Bun"))
    assert captured["body"]["response_format"] == {"type": "json_object"}


async def test_extract_strips_markdown_code_fences():
    def handler(request: httpx.Request) -> httpx.Response:
        fenced = '```json\n{"candidates": [{"key": "project.runtime", "value": "bun"}]}\n```'
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": fenced}}]},
        )

    provider = _provider(handler)
    candidates = await provider.extract(_user_event("用 Bun"))
    assert [c.value for c in candidates] == ["bun"]


async def test_extract_drops_invalid_items_but_keeps_valid():
    def handler(request: httpx.Request) -> httpx.Response:
        return _chat_response(
            [
                {"key": "project.runtime", "value": "bun"},
                {"key": "missing.value"},  # invalid: no value
                "garbage",  # invalid type
            ]
        )

    provider = _provider(handler)
    candidates = await provider.extract(_user_event("anything"))
    assert [c.value for c in candidates] == ["bun"]


async def test_extract_ignores_extra_fields():
    def handler(request: httpx.Request) -> httpx.Response:
        return _chat_response([{"key": "project.runtime", "value": "bun", "evil": "rm -rf /"}])

    provider = _provider(handler)
    candidates = await provider.extract(_user_event("anything"))
    assert len(candidates) == 1
    assert not hasattr(candidates[0], "evil")


async def test_extract_preserves_free_form_flag():
    def handler(request: httpx.Request) -> httpx.Response:
        return _chat_response([{"key": "user.preference.editor", "value": "vim", "free_form": True}])

    provider = _provider(handler)
    candidates = await provider.extract(_user_event("prefer vim"))
    assert candidates[0].free_form is True


async def test_extract_empty_content_skips_call():
    called = False

    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        nonlocal called
        called = True
        return _chat_response([])

    provider = _provider(handler)
    assert await provider.extract(_user_event("   ")) == []
    assert called is False


async def test_extract_drops_out_of_range_confidence():
    def handler(request: httpx.Request) -> httpx.Response:
        return _chat_response(
            [
                {"key": "project.runtime", "value": "bun", "confidence": 1.5},  # invalid
                {"key": "project.tool", "value": "ruff", "confidence": 0.7},  # valid
            ]
        )

    provider = _provider(handler)
    candidates = await provider.extract(_user_event("anything"))
    assert [c.value for c in candidates] == ["ruff"]


async def test_extract_raises_on_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    provider = _provider(handler)
    with pytest.raises(httpx.HTTPStatusError):
        await provider.extract(_user_event("anything"))


async def test_extract_raises_on_invalid_json_content():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": "not json"}}]},
        )

    provider = _provider(handler)
    with pytest.raises(json.JSONDecodeError):
        await provider.extract(_user_event("anything"))


async def test_extract_reuses_and_closes_lazy_client(monkeypatch):
    """When no client is injected, the provider must create one lazily, reuse it
    across calls, and close it via aclose()."""
    created: list[httpx.AsyncClient] = []
    real_async_client = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        return _chat_response([])

    def fake_async_client(*args, **kwargs):
        client = real_async_client(transport=httpx.MockTransport(handler))
        created.append(client)
        return client

    monkeypatch.setattr("app.memory.llm_extractor.httpx.AsyncClient", fake_async_client)
    provider = LLMExtractionProvider(api_key="sk-test", base_url="https://llm.test/v1")

    assert provider._client is None
    assert await provider.extract(_user_event("a")) == []
    assert await provider.extract(_user_event("b")) == []
    assert len(created) == 1  # client reused, not recreated per call
    assert provider._client is created[0]

    await provider.aclose()
    assert provider._client is None
