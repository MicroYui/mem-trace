from __future__ import annotations

import json

import httpx
import pytest

from app.providers.base import ProviderKind
from app.providers.embedding import DeterministicHashEmbeddingProvider, OpenAIEmbeddingProvider
from app.retrieval.similarity import stable_embedding


async def test_deterministic_hash_embedding_provider_matches_stable_embedding():
    provider = DeterministicHashEmbeddingProvider(dim=256)

    assert await provider.embed_text("run bun test") == stable_embedding("run bun test", 256)
    assert provider.capabilities.kind == ProviderKind.embedding
    assert provider.capabilities.deterministic is True
    assert provider.capabilities.requires_network is False
    assert provider.capabilities.snapshot()["metadata"] == {"algorithm": "blake2b_hash_bow", "dim": 256}


async def test_openai_embedding_provider_request_shape_and_vector():
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"data": [{"embedding": [0.6, 0.8]}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://emb.test/v1")
    provider = OpenAIEmbeddingProvider(
        api_key="sk-test",
        base_url="https://emb.test/v1",
        model="text-embedding-test",
        dimensions=2,
        timeout_s=8.0,
        client=client,
    )

    assert await provider.embed_text("bun test") == [0.6, 0.8]
    assert captured["url"] == "https://emb.test/v1/embeddings"
    assert captured["auth"] == "Bearer sk-test"
    assert captured["body"] == {"model": "text-embedding-test", "input": "bun test", "dimensions": 2}
    snap = provider.capabilities.snapshot()
    assert snap["provider_id"] == "embedding.openai_compatible.v1"
    assert snap["requires_network"] is True
    assert "api_key" not in str(snap)
    assert "sk-test" not in str(snap)

    await client.aclose()


async def test_openai_embedding_provider_rejects_dimension_mismatch():
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"data": [{"embedding": [1.0]}]})),
        base_url="https://emb.test/v1",
    )
    provider = OpenAIEmbeddingProvider(
        api_key="sk-test",
        base_url="https://emb.test/v1",
        model="text-embedding-test",
        dimensions=2,
        timeout_s=8.0,
        client=client,
    )

    with pytest.raises(ValueError, match="embedding dimension mismatch"):
        await provider.embed_text("bun test")

    await client.aclose()


async def test_openai_embedding_provider_rejects_non_finite_values():
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                content=b'{"data":[{"embedding":[NaN,0.8]}]}',
                headers={"Content-Type": "application/json"},
            )
        ),
        base_url="https://emb.test/v1",
    )
    provider = OpenAIEmbeddingProvider(
        api_key="sk-test",
        base_url="https://emb.test/v1",
        model="text-embedding-test",
        dimensions=2,
        timeout_s=8.0,
        client=client,
    )

    with pytest.raises(ValueError, match="finite numeric vector"):
        await provider.embed_text("bun test")

    await client.aclose()


async def test_openai_embedding_provider_raises_on_http_error():
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(500, json={"error": "boom"})),
        base_url="https://emb.test/v1",
    )
    provider = OpenAIEmbeddingProvider(
        api_key="sk-test",
        base_url="https://emb.test/v1",
        model="text-embedding-test",
        dimensions=2,
        timeout_s=8.0,
        client=client,
    )

    with pytest.raises(httpx.HTTPStatusError):
        await provider.embed_text("bun test")

    await client.aclose()


async def test_openai_embedding_provider_reuses_and_closes_lazy_client(monkeypatch):
    """When no client is injected, the provider must create one lazily, reuse it
    across calls, and close it via aclose()."""
    created: list[httpx.AsyncClient] = []
    real_async_client = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"embedding": [0.6, 0.8]}]})

    def fake_async_client(*args, **kwargs):
        client = real_async_client(transport=httpx.MockTransport(handler))
        created.append(client)
        return client

    monkeypatch.setattr("app.providers.embedding.httpx.AsyncClient", fake_async_client)
    provider = OpenAIEmbeddingProvider(
        api_key="sk-test",
        base_url="https://emb.test/v1",
        model="text-embedding-test",
        dimensions=2,
        timeout_s=8.0,
    )

    assert provider._client is None
    assert await provider.embed_text("a") == [0.6, 0.8]
    assert await provider.embed_text("b") == [0.6, 0.8]
    assert len(created) == 1  # client reused, not recreated per call
    assert provider._client is created[0]

    await provider.aclose()
    assert provider._client is None


async def test_openai_embedding_provider_aclose_leaves_injected_client_open():
    """aclose() must only close a client the provider created itself, never an
    injected one."""
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"data": [{"embedding": [0.6, 0.8]}]})),
        base_url="https://emb.test/v1",
    )
    provider = OpenAIEmbeddingProvider(
        api_key="sk-test",
        base_url="https://emb.test/v1",
        model="text-embedding-test",
        dimensions=2,
        timeout_s=8.0,
        client=client,
    )

    await provider.embed_text("a")
    await provider.aclose()
    assert client.is_closed is False  # injected client is not owned
    assert await provider.embed_text("b") == [0.6, 0.8]

    await client.aclose()
