"""Deterministic lexical similarity for P0 retrieval.

No external embedding provider. We use token Jaccard / overlap so demo and
benchmark results are fully reproducible. A simple hashed bag-of-words vector is
also exposed for parity with the pgvector column (embedding is optional in P0).
"""
from __future__ import annotations

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


def hashed_embedding(text: str | None, dim: int = 256) -> list[float]:
    """Deterministic hashed bag-of-words vector, L2-normalized."""
    vec = [0.0] * dim
    for tok in tokenize(text):
        vec[hash(tok) % dim] += 1.0
    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0:
        vec = [v / norm for v in vec]
    return vec


__all__ = ["tokenize", "lexical_similarity", "hashed_embedding"]
