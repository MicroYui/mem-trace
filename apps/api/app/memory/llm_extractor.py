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

import json
from typing import Any, Optional, Protocol, runtime_checkable

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

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
    confidence: float = Field(default=0.9, ge=0.0, le=1.0)


@runtime_checkable
class ExtractionProvider(Protocol):
    """Turns a single user-message event into structured memory candidates."""

    async def extract(self, event: AgentEvent) -> list[ExtractionCandidate]: ...


class FakeExtractionProvider:
    """Deterministic provider used for tests + as a default wiring placeholder.

    It reuses the deterministic ``writer`` rules so its output is identical to the
    rule-based path (fixed key/value), but routes through the schema -> result
    conversion so the full LLM pipeline skeleton is exercised. Used as a fallback
    when LLM extraction is enabled but no API key is configured.
    """

    async def extract(self, event: AgentEvent) -> list[ExtractionCandidate]:
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


_SYSTEM_PROMPT = """You extract durable memory facts from a single user message in an AI coding-agent session.

Return ONLY a JSON object with a single key "candidates" whose value is a JSON array.
Each array item is an object with exactly these fields:
- "key": a stable dotted identifier, e.g. "project.runtime", "project.runtime.excluded".
- "value": the extracted value, e.g. "bun", "npm".
- "memory_type": one of "project", "episodic", "procedural", "working_state". Default "project".
- "scope": one of "workspace", "session", "run", "global". Default "workspace".
- "supersede": true if this fact explicitly corrects/replaces a previous preference, else false.
- "confidence": a float in [0,1].

Rules:
- Extract only durable preferences, project constraints, and explicit corrections.
- Do NOT invent facts. If the message contains nothing durable, return {"candidates": []}.
- Output JSON only, no prose, no markdown fences."""


class LLMExtractionProvider:
    """Real extraction provider backed by an OpenAI-compatible chat API.

    Calls ``{base_url}/chat/completions`` with a fixed system prompt that
    constrains the model to the :class:`ExtractionCandidate` schema. Any failure
    (network, timeout, non-2xx, invalid JSON) raises; the runtime catches it and
    degrades to the deterministic rule writer so no memory is lost.
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        model: str = "gpt-4o-mini",
        timeout_s: float = 8.0,
        max_tokens: int = 512,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout_s = timeout_s
        self._max_tokens = max_tokens
        self._client = client

    async def extract(self, event: AgentEvent) -> list[ExtractionCandidate]:
        content = (event.content or "").strip()
        if not content:
            return []
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": content},
            ],
            "max_tokens": self._max_tokens,
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self._base_url}/chat/completions"

        if self._client is not None:
            resp = await self._client.post(url, json=payload, headers=headers)
            data = self._parse_response(resp)
        else:
            async with httpx.AsyncClient(timeout=self._timeout_s) as client:
                resp = await client.post(url, json=payload, headers=headers)
                data = self._parse_response(resp)
        return data

    def _parse_response(self, resp: httpx.Response) -> list[ExtractionCandidate]:
        resp.raise_for_status()
        body = resp.json()
        message = body["choices"][0]["message"]["content"]
        parsed = json.loads(message)
        raw_candidates = _extract_candidate_list(parsed)
        # Drop individually-invalid items here (a noisy item must not fail the
        # whole batch). build_results re-validates as the schema gate of record.
        candidates: list[ExtractionCandidate] = []
        for raw in raw_candidates:
            validated = _validate(raw)
            if validated is not None:
                candidates.append(validated)
        return candidates


def _extract_candidate_list(parsed: Any) -> list[Any]:
    """Pull the candidate array out of a model response.

    Accepts either a bare JSON array or an object with a ``candidates`` array
    (the shape the system prompt asks for).
    """
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        candidates = parsed.get("candidates")
        if isinstance(candidates, list):
            return candidates
    return []


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
    "LLMExtractionProvider",
    "build_results",
]
