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
enabled. Two further deterministic capabilities — ``decide_need_retrieval``
(skip retrieval for trivial/no-signal tasks) and ``rewrite_query`` (expand
structural entity terms into their component words so prose memories still
match) — are exposed here and activated together under the ``full`` mode.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# A run of alphanumerics plus structural separators, anchored on alphanumerics
# at both ends so trailing punctuation (e.g. "project.runtime=bun") is dropped.
_ENTITY_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/:-]*[A-Za-z0-9]")
_SPLIT_RE = re.compile(r"[._/:-]+")
_STRUCTURAL_CHARS = "._/:-"
_MIN_LEN = 3
_MAX_HINTS = 8

# Trivial filler / greeting / pronoun words that carry no retrieval target.
# 1-2 char tokens are already excluded by ``_MIN_LEN``; this set covers the
# longer filler that would otherwise read as a content signal. Intentionally
# conservative — intent-bearing verbs (fix, debug, install, build, test) are
# NOT stopwords, so only genuinely contentless queries skip retrieval.
_STOPWORDS = frozenset(
    {
        "the", "and", "for", "with", "are", "this", "that", "you", "your", "our",
        "ok", "okay", "yes", "yep", "nope", "sure", "thanks", "thank", "please",
        "hey", "hello", "now", "then", "next", "continue", "done", "lets", "let",
        "can", "could", "would", "should", "will", "what", "how", "does", "did",
        "just", "again", "here", "there", "them", "they", "was", "were",
    }
)


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


def _signal_tokens(query: str | None, task_intent: str | None) -> list[str]:
    """Tokens that carry a real retrieval target (entity-like or content word)."""
    text = " ".join(part for part in (query, task_intent) if part)
    out: list[str] = []
    for match in _ENTITY_RE.findall(text):
        token = match.lower()
        if len(token) < _MIN_LEN:
            continue
        if _is_entity_like(token) or token not in _STOPWORDS:
            out.append(token)
    return out


@dataclass(frozen=True)
class NeedRetrievalDecision:
    """Whether a query is worth retrieving for, plus a deterministic reason."""

    should_retrieve: bool
    reason: str


def decide_need_retrieval(
    query: str | None, task_intent: str | None = None
) -> NeedRetrievalDecision:
    """Skip retrieval for trivial tasks with no retrieval signal.

    A query made only of filler / greetings / pronouns (or empty) has no
    concrete target, so retrieving (and force-including project constraints)
    only adds noise. Any entity-like token or content word keeps retrieval on.
    Conservative by design: this is only consulted under the ``full`` planner
    mode, never on the default path.
    """
    if _signal_tokens(query, task_intent):
        return NeedRetrievalDecision(True, "has_retrieval_signal")
    return NeedRetrievalDecision(False, "no_retrieval_signal")


@dataclass(frozen=True)
class QueryRewrite:
    """A query expanded with the component words of its structural entities."""

    text: str
    added_terms: tuple[str, ...]
    reason: str


def rewrite_query(query: str | None, task_intent: str | None = None) -> QueryRewrite:
    """Append component words of structural entity hints to the query.

    The lexical tokenizer keeps ``project.runtime`` as a single token, so a
    dotted-key query never matches prose that spells the words out. Expanding
    the query with the split components (``project``, ``runtime``) lets such
    memories match without changing the original tokens. Deterministic, bounded
    by ``_MAX_HINTS`` hints, and a no-op when the query has no structural terms.
    """
    base = (query or "").strip()
    plan = plan_query(query, task_intent)
    have = {tok for tok in re.split(r"\s+", base.lower()) if tok}
    added: list[str] = []
    seen: set[str] = set()
    for hint in plan.hints:
        for part in _SPLIT_RE.split(hint):
            part = part.strip().lower()
            if len(part) < _MIN_LEN or part in have or part in seen:
                continue
            seen.add(part)
            added.append(part)
    if not added:
        return QueryRewrite(text=base, added_terms=(), reason="no_rewrite")
    return QueryRewrite(
        text=(base + " " + " ".join(added)).strip(),
        added_terms=tuple(added),
        reason="expanded",
    )


def derive_hop_cues(
    contents: list[str], *, exclude: set[str], max_cues: int
) -> tuple[str, ...]:
    """Entity-like cues drawn from candidate contents for the next retrieval hop.

    Multi-hop iterative reconstruction (ROADMAP §4 / draft §5): the contents of
    the current candidates may reference entities (dotted keys, paths, ids) that
    link to *complementary* memories the original query never mentions. This
    returns the new entity cues (not already in ``exclude``), in deterministic
    first-appearance order across the ordered contents, capped at ``max_cues``.
    """
    seen = {token.lower() for token in exclude}
    cues: list[str] = []
    for content in contents:
        if not content:
            continue
        for match in _ENTITY_RE.findall(content):
            token = match.lower()
            if len(token) < _MIN_LEN or not _is_entity_like(token):
                continue
            if token in seen:
                continue
            seen.add(token)
            cues.append(token)
            if len(cues) >= max_cues:
                return tuple(cues)
    return tuple(cues)


__all__ = [
    "QueryPlan",
    "plan_query",
    "hint_boost",
    "NeedRetrievalDecision",
    "decide_need_retrieval",
    "QueryRewrite",
    "rewrite_query",
    "derive_hop_cues",
]
