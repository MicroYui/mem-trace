from __future__ import annotations

import math
from typing import Any

import httpx

from app.providers.base import ProviderCapabilities, ProviderKind
from app.retrieval.similarity import stable_embedding


class DeterministicHashEmbeddingProvider:
    def __init__(
        self,
        *,
        dim: int = 256,
        configured: bool = True,
        fallback_provider_id: str | None = None,
    ) -> None:
        self.dim = dim
        self.capabilities = ProviderCapabilities(
            provider_id="embedding.deterministic_hash.v1",
            kind=ProviderKind.embedding,
            deterministic=True,
            requires_network=False,
            configured=configured,
            fallback_provider_id=fallback_provider_id,
            metadata={"algorithm": "blake2b_hash_bow", "dim": dim},
        )

    async def embed_text(self, text: str | None) -> list[float]:
        return stable_embedding(text, self.dim)


class OpenAIEmbeddingProvider:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        dimensions: int,
        timeout_s: float,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._dimensions = dimensions
        self._timeout_s = timeout_s
        self._client = client
        self._owns_client = False
        self.capabilities = ProviderCapabilities(
            provider_id="embedding.openai_compatible.v1",
            kind=ProviderKind.embedding,
            deterministic=False,
            requires_network=True,
            endpoint_types=("openai_embeddings",),
            model=model,
            metadata={"dim": dimensions, "base_url_host": _host_label(base_url)},
        )

    async def embed_text(self, text: str | None) -> list[float]:
        payload: dict[str, Any] = {
            "model": self._model,
            "input": text or "",
            "dimensions": self._dimensions,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self._base_url}/embeddings"
        client = self._client_for_request()
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        body = resp.json()
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, list) or not data:
            raise ValueError("embedding response missing data")
        first = data[0]
        embedding = first.get("embedding") if isinstance(first, dict) else None
        if not isinstance(embedding, list) or not all(isinstance(v, int | float) for v in embedding):
            raise ValueError("embedding response missing numeric vector")
        vector = [float(v) for v in embedding]
        if not all(math.isfinite(v) for v in vector):
            raise ValueError("embedding response must be a finite numeric vector")
        if len(vector) != self._dimensions:
            raise ValueError(f"embedding dimension mismatch: expected {self._dimensions}, got {len(vector)}")
        return vector

    def _client_for_request(self) -> httpx.AsyncClient:
        """Return a reusable client, creating (and owning) one lazily if none was injected."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout_s)
            self._owns_client = True
        return self._client

    async def aclose(self) -> None:
        """Close the client only if this provider created it; never an injected one."""
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None
            self._owns_client = False


def _host_label(base_url: str) -> str:
    try:
        return httpx.URL(base_url).host or "unknown"
    except Exception:
        return "unknown"
