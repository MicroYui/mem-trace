"""Deterministic similarity for retrieval.

No external embedding provider, so demo and benchmark results stay fully
reproducible. Two complementary signals are provided:

- ``lexical_similarity``: token Jaccard / query-coverage overlap in [0, 1].
- ``stable_embedding`` + ``cosine_similarity``: a deterministic hashed
  bag-of-words vector for pgvector KNN. The hash uses blake2b (not Python's
  built-in ``hash``) so vectors are stable across processes and can be persisted
  to the pgvector column and queried later.

The retrieval controller blends the two into one relevance score.
"""
from __future__ import annotations

import hashlib
import math
import re

_TOKEN_RE = re.compile(r"[A-Za-z0-9_.\-]+|[\u4e00-\u9fff]")

_STOP = {
    "the", "a", "an", "to", "of", "is", "are", "this", "that", "it", "and", "or",
    "如何", "怎么", "请", "了", "的", "吗", "我", "你",
}


def tokenize(text: str | None) -> list[str]:
    if not text:
        return []
    return [t.lower() for t in _TOKEN_RE.findall(text) if t.lower() not in _STOP]


def lexical_similarity(query: str | None, content: str | None) -> float:
    """Weighted token overlap in [0, 1].

    Combines Jaccard with query-coverage so that a candidate containing all
    query tokens scores high even if it is long.
    """
    q = set(tokenize(query))
    c = set(tokenize(content))
    if not q or not c:
        return 0.0
    inter = q & c
    if not inter:
        return 0.0
    jaccard = len(inter) / len(q | c)
    coverage = len(inter) / len(q)
    return round(0.4 * jaccard + 0.6 * coverage, 6)


def _stable_bucket(token: str, dim: int) -> int:
    """Map a token to a vector bucket with a process-stable hash."""
    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") % dim


def stable_embedding(text: str | None, dim: int = 256) -> list[float]:
    """Deterministic, process-stable hashed bag-of-words vector, L2-normalized.

    Unlike Python's built-in ``hash`` (salted per process), blake2b gives the
    same vector across runs, so embeddings can be persisted to pgvector and
    queried by later processes.
    """
    vec = [0.0] * dim
    for tok in tokenize(text):
        vec[_stable_bucket(tok, dim)] += 1.0
    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0:
        vec = [v / norm for v in vec]
    return vec


def cosine_similarity(a: list[float] | None, b: list[float] | None) -> float:
    """Cosine similarity of two vectors in [0, 1] for normalized inputs."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    return round(max(0.0, dot), 6)


__all__ = [
    "tokenize",
    "lexical_similarity",
    "stable_embedding",
    "cosine_similarity",
]
