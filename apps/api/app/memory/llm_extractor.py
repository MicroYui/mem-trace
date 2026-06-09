"""LLM extraction pipeline (P2, config-gated).

An optional, *opt-in* alternative to the rule-based ``writer.write_from_user_message``
path. When a provider is injected into ``MemoryRuntime`` (driven by
``Settings.llm_extraction_enabled``), user-message events are turned into memory
candidates by an :class:`ExtractionProvider` instead of the regex writer.

Design (mirrors writer/resolver/summarizer):
- Pure + storage-agnostic: the provider returns validated candidates; this module
  turns them into ``MemoryWriteResult`` objects; the runtime facade persists them
  (so the resolver still owns dedup/conflict/lineage).
- Deterministic by default: the only shipped provider is
  :class:`FakeExtractionProvider`, which wraps the deterministic writer rules so
  demo/benchmark stay reproducible. A real LLM client is a future wiring point.
- Hardened (architecture.md §11.4): provider output is validated against a fixed
  Pydantic schema; invalid candidates are dropped; results are sorted by a stable
  total order so extraction never introduces ordering jitter.

Secrets never reach here: ``MemoryRuntime.write_event`` redacts + skips the whole
extraction branch for secret events before any extractor is consulted.
"""
from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, ValidationError

from app.memory.writer import MemoryWriteResult, detect_risk_flags, write_from_user_message
from app.runtime.models import (
    AgentEvent,
    BranchStatus,
    MemoryItem,
    MemoryScope,
    MemoryType,
)


class ExtractionCandidate(BaseModel):
    """Fixed JSON schema a provider must emit (architecture.md §11.4).

    Extra/unknown fields are ignored so a noisy LLM response can't smuggle
    arbitrary attributes onto the memory.
    """

    model_config = ConfigDict(extra="ignore")

    key: str
    value: str
    memory_type: MemoryType = MemoryType.project
    scope: MemoryScope = MemoryScope.workspace
    supersede: bool = False
    confidence: float = 0.9


@runtime_checkable
class ExtractionProvider(Protocol):
    """Turns a single user-message event into structured memory candidates."""

    def extract(self, event: AgentEvent) -> list[ExtractionCandidate]: ...


class FakeExtractionProvider:
    """Deterministic provider used for tests + as a default wiring placeholder.

    It reuses the deterministic ``writer`` rules so its output is identical to the
    rule-based path (fixed key/value), but routes through the schema -> result
    conversion so the full LLM pipeline skeleton is exercised. Swap this for a real
    LLM client later without touching the runtime.
    """

    def extract(self, event: AgentEvent) -> list[ExtractionCandidate]:
        candidates: list[ExtractionCandidate] = []
        for result in write_from_user_message(event):
            mem = result.memory
            if mem.key is None or mem.value is None:
                continue
            candidates.append(
                ExtractionCandidate(
                    key=mem.key,
                    value=mem.value,
                    memory_type=mem.memory_type,
                    scope=mem.scope,
                    supersede=bool(result.supersede_keys),
                    confidence=mem.confidence,
                )
            )
        return candidates


def _validate(raw: object) -> Optional[ExtractionCandidate]:
    if isinstance(raw, ExtractionCandidate):
        return raw
    try:
        if isinstance(raw, dict):
            return ExtractionCandidate.model_validate(raw)
    except ValidationError:
        return None
    return None


def _sort_key(c: ExtractionCandidate) -> tuple:
    # Stable total order so extraction never introduces ordering jitter.
    return (c.scope.value, c.key, c.value)


def build_results(event: AgentEvent, candidates: list[object]) -> list[MemoryWriteResult]:
    """Convert validated candidates into ``MemoryWriteResult`` objects.

    Invalid candidates are dropped. The result list is deterministically ordered.
    ``supersede=True`` retires same-(key, scope) actives, matching the explicit
    correction semantics in ``writer.write_from_user_message``.
    """
    validated = [c for c in (_validate(raw) for raw in candidates) if c is not None]
    validated.sort(key=_sort_key)

    results: list[MemoryWriteResult] = []
    for c in validated:
        mem = MemoryItem(
            workspace_id=event.workspace_id,
            session_id=event.session_id,
            run_id=event.run_id,
            memory_type=c.memory_type,
            key=c.key,
            value=c.value,
            scope=c.scope,
            content=(event.content or "").strip(),
            summary=f"{c.key}={c.value}",
            source_event_id=event.event_id,
            source_run_id=event.run_id,
            source_state_node_id=event.state_node_id,
            branch_status=BranchStatus.completed,
            confidence=c.confidence,
            importance=0.8,
            trust_score=0.8,
            risk_flags=detect_risk_flags(event.content),
        )
        supersede_keys = [(c.key, c.scope.value)] if c.supersede else []
        results.append(MemoryWriteResult(mem, supersede_keys=supersede_keys))
    return results


__all__ = [
    "ExtractionCandidate",
    "ExtractionProvider",
    "FakeExtractionProvider",
    "build_results",
]
