"""Deterministic query planner: entity/keyword hint extraction (ROADMAP §4).

A small, no-external-dependency, no-network Phase 5 micro-slice. Entity-like
query terms — dotted keys (``project.runtime``), paths (``src/app.py``),
namespaced or hyphenated identifiers (``api_key``, ``feature-flag``) — carry
stronger retrieval signal than generic English words, yet plain token-overlap
lexical scoring weights every token equally. The planner surfaces those
structural terms as *hints* so the retrieval controller can give a small,
bounded boost to candidates that actually mention them.

This is deterministic and side-effect free; it never calls a model or the
network. It is wired into the controller behind a default-off setting
(``MEMTRACE_RETRIEVAL_QUERY_PLANNER=off``), so default retrieval, benchmark
reproducibility, and replay snapshots stay byte-identical until explicitly
enabled. The richer "Need-Retrieval Decision" / query rewrite remain deferred.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# A run of alphanumerics plus structural separators, anchored on alphanumerics
# at both ends so trailing punctuation (e.g. "project.runtime=bun") is dropped.
_ENTITY_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/:-]*[A-Za-z0-9]")
_STRUCTURAL_CHARS = "._/:-"
_MIN_LEN = 3
_MAX_HINTS = 8


def _is_entity_like(token: str) -> bool:
    """True when a token looks like a concrete identifier rather than a word.

    A structural separator (dotted key, path, namespaced/hyphenated id) or an
    embedded digit marks the token as entity-like. Generic words such as
    "runtime" or "install" are intentionally excluded — those stay the domain
    of plain lexical overlap.
    """
    return any(ch in token for ch in _STRUCTURAL_CHARS) or any(ch.isdigit() for ch in token)


@dataclass(frozen=True)
class QueryPlan:
    """Result of planning a query: the ordered, deduplicated entity hints."""

    hints: tuple[str, ...]
    reason: str


def plan_query(query: str | None, task_intent: str | None = None) -> QueryPlan:
    """Extract entity-like hints from the query (and optional task intent).

    Hints preserve first-appearance order, are lowercased and deduplicated, and
    are capped at ``_MAX_HINTS`` so the downstream boost stays bounded.
    """
    text = " ".join(part for part in (query, task_intent) if part)
    seen: set[str] = set()
    hints: list[str] = []
    for match in _ENTITY_RE.findall(text):
        token = match.lower()
        if len(token) < _MIN_LEN or not _is_entity_like(token):
            continue
        if token in seen:
            continue
        seen.add(token)
        hints.append(token)
        if len(hints) >= _MAX_HINTS:
            break
    return QueryPlan(hints=tuple(hints), reason="entity_hints" if hints else "no_entity_hints")


def hint_boost(content: str | None, hints: tuple[str, ...], *, weight: float) -> float:
    """Bounded boost in ``[0, weight]`` for content mentioning the hints.

    The boost is ``weight * (matched_hints / total_hints)`` so a candidate that
    mentions every entity hint earns at most ``weight`` and one mentioning none
    earns nothing. Deterministic substring match on lowercased content.
    """
    if not hints or not content or weight <= 0.0:
        return 0.0
    haystack = content.lower()
    matched = sum(1 for hint in hints if hint in haystack)
    if not matched:
        return 0.0
    return round(weight * (matched / len(hints)), 6)


__all__ = ["QueryPlan", "plan_query", "hint_boost"]
