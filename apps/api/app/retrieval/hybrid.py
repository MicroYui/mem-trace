"""Optional hybrid BM25 retrieval backends (ROADMAP §4, default-off).

The default retrieval path blends deterministic lexical overlap with a
deterministic hashed-vector cosine. This module adds an optional third signal —
Okapi BM25 — behind a pluggable backend so an external search engine
(Elasticsearch / OpenSearch) can supply a production-grade lexical ranking
without the runtime depending on it.

Two backends are provided:

- ``InMemoryBM25Backend`` — a real, deterministic Okapi BM25 over the candidate
  memories' content. No network, fully reproducible; can even be enabled in
  benchmarks. This is also the reference implementation the ES backend mirrors.
- ``ElasticsearchBM25Backend`` — lazy-imports ``elasticsearch`` and queries a
  per-workspace index. It degrades to ``available = False`` (so the controller
  ignores it) when the dependency or endpoint is absent, and returns ``{}`` on
  any query error, so the retrieval hot path always falls back cleanly.

Everything here is default-off: ``MEMTRACE_RETRIEVAL_HYBRID_BACKEND=off`` keeps
candidate scoring byte-identical, so benchmark/reproduce and replay snapshots are
unchanged until the backend is explicitly enabled.
"""
from __future__ import annotations

import logging
import math
from typing import Protocol, runtime_checkable

from app.retrieval.similarity import tokenize
from app.runtime.models import MemoryItem

logger = logging.getLogger(__name__)

_BM25_K1 = 1.5
_BM25_B = 0.75


@runtime_checkable
class HybridBackend(Protocol):
    """A backend that scores candidate memories with BM25-style lexical ranking."""

    name: str

    @property
    def available(self) -> bool:
        """Whether the backend can actually serve scores right now."""
        ...

    async def bm25_scores(
        self,
        *,
        query: str | None,
        memories: list[MemoryItem],
        workspace_id: str,
        top_k: int,
    ) -> dict[str, float]:
        """Return ``{memory_id: score}`` in ``[0, 1]`` (normalized), top_k only."""
        ...


def _bm25_scores(
    query: str | None, memories: list[MemoryItem], *, top_k: int, k1: float, b: float
) -> dict[str, float]:
    """Deterministic Okapi BM25 over memory content, normalized to ``[0, 1]``."""
    q_tokens = tokenize(query)
    if not q_tokens or not memories:
        return {}
    docs: list[tuple[str, list[str]]] = [(m.memory_id, tokenize(m.content)) for m in memories]
    n_docs = len(docs)
    total_len = sum(len(toks) for _, toks in docs)
    avgdl = total_len / n_docs if n_docs else 0.0
    if avgdl <= 0.0:
        return {}
    df: dict[str, int] = {}
    for _, toks in docs:
        for term in set(toks):
            df[term] = df.get(term, 0) + 1
    q_set = set(q_tokens)
    raw: dict[str, float] = {}
    for memory_id, toks in docs:
        if not toks:
            continue
        dl = len(toks)
        tf: dict[str, int] = {}
        for term in toks:
            if term in q_set:
                tf[term] = tf.get(term, 0) + 1
        score = 0.0
        for term, freq in tf.items():
            n_term = df.get(term, 0)
            idf = math.log(1 + (n_docs - n_term + 0.5) / (n_term + 0.5))
            denom = freq + k1 * (1 - b + b * dl / avgdl)
            score += idf * (freq * (k1 + 1)) / denom
        if score > 0.0:
            raw[memory_id] = score
    if not raw:
        return {}
    top = max(raw.values())
    ranked = sorted(raw.items(), key=lambda kv: (-kv[1], kv[0]))[:top_k]
    return {memory_id: round(score / top, 6) for memory_id, score in ranked}


class InMemoryBM25Backend:
    """Deterministic Okapi BM25 over the candidate memories. No network."""

    name = "inmemory_bm25"

    def __init__(self, *, k1: float = _BM25_K1, b: float = _BM25_B) -> None:
        self._k1 = k1
        self._b = b

    @property
    def available(self) -> bool:
        return True

    async def bm25_scores(
        self,
        *,
        query: str | None,
        memories: list[MemoryItem],
        workspace_id: str,
        top_k: int,
    ) -> dict[str, float]:
        return _bm25_scores(query, memories, top_k=top_k, k1=self._k1, b=self._b)


class ElasticsearchBM25Backend:
    """Optional Elasticsearch/OpenSearch BM25 backend (lazy import, degrade-safe).

    Indexes the candidate corpus into a per-workspace index (idempotent upsert by
    ``memory_id``) then runs a filtered ``match`` query, returning the normalized
    ``_score`` per hit. Any missing dependency / endpoint / query error degrades
    to ``available = False`` or an empty result, so retrieval never breaks. A
    client may be injected for tests.
    """

    name = "elasticsearch_bm25"

    def __init__(
        self,
        *,
        url: str,
        index_prefix: str = "memtrace",
        client: object | None = None,
    ) -> None:
        self._url = url
        self._index_prefix = index_prefix
        self._client = client
        self._available = client is not None
        if client is None and url:
            try:  # lazy: the dependency is an optional extra
                from elasticsearch import Elasticsearch  # type: ignore
            except ModuleNotFoundError:
                logger.warning(
                    "MEMTRACE_RETRIEVAL_HYBRID_BACKEND=elasticsearch requires the "
                    "'search' extra (pip install '.[search]'); hybrid scoring disabled."
                )
                self._available = False
            else:
                try:
                    self._client = Elasticsearch(url)
                    self._available = True
                except Exception:  # noqa: BLE001 - construction must never break startup
                    logger.warning("Failed to construct Elasticsearch client; hybrid scoring disabled.")
                    self._available = False

    @property
    def available(self) -> bool:
        return self._available

    def _index_name(self, workspace_id: str) -> str:
        # Index names are lowercased and must avoid reserved characters.
        safe_ws = "".join(ch if ch.isalnum() else "_" for ch in workspace_id.lower())
        return f"{self._index_prefix}-{safe_ws}"

    async def bm25_scores(
        self,
        *,
        query: str | None,
        memories: list[MemoryItem],
        workspace_id: str,
        top_k: int,
    ) -> dict[str, float]:
        if not self._available or self._client is None or not query:
            return {}
        index = self._index_name(workspace_id)
        try:
            for mem in memories:
                self._client.index(  # type: ignore[attr-defined]
                    index=index,
                    id=mem.memory_id,
                    document={"workspace_id": mem.workspace_id, "content": mem.content},
                )
            self._client.indices.refresh(index=index)  # type: ignore[attr-defined]
            resp = self._client.search(  # type: ignore[attr-defined]
                index=index,
                query={
                    "bool": {
                        "must": [{"match": {"content": query}}],
                        "filter": [{"term": {"workspace_id": workspace_id}}],
                    }
                },
                size=top_k,
            )
            hits = resp["hits"]["hits"]
        except Exception:  # noqa: BLE001 - retrieval must degrade, never raise
            logger.warning("Elasticsearch hybrid scoring failed; degrading to lexical/vector.")
            return {}
        if not hits:
            return {}
        top = max((hit["_score"] or 0.0) for hit in hits) or 1.0
        return {hit["_id"]: round((hit["_score"] or 0.0) / top, 6) for hit in hits}


def build_hybrid_backend(settings) -> HybridBackend | None:
    """Construct the configured hybrid backend, or ``None`` when default-off."""
    mode = (getattr(settings, "retrieval_hybrid_backend", "off") or "off").lower()
    if mode == "off":
        return None
    if mode == "inmemory":
        return InMemoryBM25Backend()
    if mode in ("elasticsearch", "opensearch"):
        return ElasticsearchBM25Backend(
            url=getattr(settings, "es_url", "") or "",
            index_prefix=getattr(settings, "es_index_prefix", "memtrace") or "memtrace",
        )
    return None


__all__ = [
    "HybridBackend",
    "InMemoryBM25Backend",
    "ElasticsearchBM25Backend",
    "build_hybrid_backend",
]
