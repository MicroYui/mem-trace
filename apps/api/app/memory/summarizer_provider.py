"""Context compaction summarizer providers (C3).

The rolling-history compaction path (C4) needs a provider seam before it starts
touching the retrieval hot path. This module mirrors ``llm_extractor.py``:
deterministic rule implementation by default, optional OpenAI-compatible LLM
implementation, and conservative validation/fallback owned by the runtime.
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional, Protocol, runtime_checkable

import httpx
from pydantic import ConfigDict, Field

from app.memory.llm_extractor import _strip_code_fences
from app.providers.base import ProviderCapabilities, ProviderKind
from app.retrieval.packer import estimate_tokens
from app.runtime.models import CompactionKind, CompactionProvider, ContextBlock, RetainedFact, _Base


class SummarizeRequest(_Base):
    """Input contract for compaction summarization."""

    blocks: list[ContextBlock]
    must_retain_facts: list[RetainedFact] = Field(default_factory=list)
    source_memory_ids: list[str] = Field(default_factory=list)
    source_event_ids: list[str] = Field(default_factory=list)
    source_state_node_ids: list[str] = Field(default_factory=list)
    summary_budget_tokens: int
    run_id: Optional[str] = None
    workspace_id: str
    kind: CompactionKind


class SummarizeResult(_Base):
    """Validated structured summary returned by a provider."""

    model_config = ConfigDict(extra="ignore")

    summary: str
    retained_facts: list[RetainedFact] = Field(default_factory=list)
    omitted_count: int = 0
    source_memory_ids: list[str] = Field(default_factory=list)
    source_event_ids: list[str] = Field(default_factory=list)
    source_state_node_ids: list[str] = Field(default_factory=list)
    pre_tokens: int = 0
    post_tokens: int = 0
    warnings: list[str] = Field(default_factory=list)
    provider: CompactionProvider = CompactionProvider.rule


@runtime_checkable
class SummarizerProvider(Protocol):
    """Compresses context blocks into a structured summary."""

    async def summarize(self, request: SummarizeRequest) -> SummarizeResult: ...


class SummarizerValidationError(ValueError):
    """Raised when an LLM summary violates conservative C3 validation."""


_SYSTEM_PROMPT = """You summarize context-compaction inputs for an AI coding-agent memory runtime.

Return ONLY a JSON object matching this schema:
{
  "summary": "short text",
  "retained_facts": [{"key":"project.runtime","value":"bun","source_memory_id":"mem_..."}],
  "omitted_count": 0,
  "source_memory_ids": ["..."],
  "source_event_ids": ["..."],
  "source_state_node_ids": ["..."],
  "pre_tokens": 0,
  "post_tokens": 0,
  "warnings": []
}

Rules:
1. Do not introduce new facts. Only summarize content present in input blocks.
2. Preserve every must_retain_fact key=value verbatim in retained_facts.
3. Do not include failed, rolled_back, stale, secret, or risky content.
4. If over the summary budget, prioritize project/profile/procedural facts over episodic/tool detail.
5. Echo source ids from the request; do not invent provenance.
Output JSON only, no prose, no markdown fences."""


def _fact_key(fact: RetainedFact) -> tuple[str, str]:
    return (fact.key, fact.value)


def _fact_identity(fact: RetainedFact) -> tuple[str, str, str | None, str | None, str | None, str | None, str | None]:
    provenance = fact.provenance
    return (
        fact.key,
        fact.value,
        fact.source_memory_id,
        provenance.run_id if provenance else None,
        provenance.step_id if provenance else None,
        provenance.event_id if provenance else None,
        provenance.state_node_id if provenance else None,
    )


def _fact_sort_key(fact: RetainedFact) -> tuple[str, str, str, str, str, str, str]:
    return tuple(value or "" for value in _fact_identity(fact))


def _dedupe_facts(facts: list[RetainedFact]) -> list[RetainedFact]:
    out: list[RetainedFact] = []
    seen: set[tuple[str, str, str | None, str | None, str | None, str | None, str | None]] = set()
    for fact in sorted(facts, key=_fact_sort_key):
        identity = _fact_identity(fact)
        if identity in seen:
            continue
        seen.add(identity)
        out.append(fact)
    return out


def _truncate_summary(text: str, max_tokens: int) -> tuple[str, bool]:
    if max_tokens <= 0:
        return "", estimate_tokens(text) > 0
    if estimate_tokens(text) <= max_tokens:
        return text, False
    words = text.split()
    if not words:
        trimmed = text[:max_tokens]
        return trimmed, trimmed != text
    suffix = " … (truncated)"
    keep = min(len(words), max_tokens)
    while keep > 0:
        candidate = " ".join(words[:keep]) + suffix
        if estimate_tokens(candidate) <= max_tokens:
            return candidate, True
        keep -= 1
    return "", True


def _render_rule_summary(facts: list[RetainedFact], *, max_tokens: int) -> tuple[str, list[str]]:
    warnings: list[str] = []
    if facts:
        content = "; ".join(f"{f.key}={f.value}" for f in facts) + "."
    else:
        content = "No structured facts retained."
    summary, truncated = _truncate_summary(content, max_tokens)
    if truncated:
        warnings.append("summary truncated to fit budget")
    return summary, warnings


class RuleSummarizerProvider:
    """Deterministic summarizer used by default and as the fallback path."""

    capabilities = ProviderCapabilities(
        provider_id="summarizer.rule.v1",
        kind=ProviderKind.summarizer,
        deterministic=True,
        requires_network=False,
        metadata={"algorithm": "structured_must_retain_facts"},
    )

    async def summarize(self, request: SummarizeRequest) -> SummarizeResult:
        facts = _dedupe_facts(list(request.must_retain_facts))
        summary, warnings = _render_rule_summary(facts, max_tokens=request.summary_budget_tokens)
        pre_tokens = sum(block.tokens for block in request.blocks)
        if pre_tokens == 0:
            pre_tokens = sum(estimate_tokens(block.content) for block in request.blocks)
        result = SummarizeResult(
            summary=summary,
            retained_facts=facts,
            omitted_count=len(request.blocks),
            source_memory_ids=list(request.source_memory_ids),
            source_event_ids=list(request.source_event_ids),
            source_state_node_ids=list(request.source_state_node_ids),
            pre_tokens=pre_tokens,
            post_tokens=estimate_tokens(summary),
            warnings=warnings,
            provider=CompactionProvider.rule,
        )
        return _validate_result(request, result)


class LLMSummarizerProvider:
    """OpenAI-compatible summarizer provider.

    Any network/HTTP/JSON/schema/validation failure raises. ``MemoryRuntime`` is
    responsible for catching those failures and falling back to the rule path.
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        model: str = "gpt-4o-mini",
        timeout_s: float = 8.0,
        max_tokens: int = 512,
        use_json_response_format: bool = False,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout_s = timeout_s
        self._max_tokens = max_tokens
        self._use_json_response_format = use_json_response_format
        self._client = client
        self.capabilities = ProviderCapabilities(
            provider_id="summarizer.openai_compatible.v1",
            kind=ProviderKind.summarizer,
            deterministic=False,
            requires_network=True,
            endpoint_types=("openai_chat_completions",),
            model=model,
            fallback_provider_id="summarizer.rule.v1",
            metadata={"base_url_host": _host_label(base_url)},
        )

    async def summarize(self, request: SummarizeRequest) -> SummarizeResult:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": _request_payload(request)},
            ],
            "max_tokens": self._max_tokens,
            "temperature": 0,
        }
        if self._use_json_response_format:
            payload["response_format"] = {"type": "json_object"}
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self._base_url}/chat/completions"

        if self._client is not None:
            resp = await self._client.post(url, json=payload, headers=headers)
            result = self._parse_response(resp)
        else:
            async with httpx.AsyncClient(timeout=self._timeout_s) as client:
                resp = await client.post(url, json=payload, headers=headers)
                result = self._parse_response(resp)
        return _validate_result(request, result.model_copy(update={"provider": CompactionProvider.llm}))

    def _parse_response(self, resp: httpx.Response) -> SummarizeResult:
        resp.raise_for_status()
        body = resp.json()
        message = body["choices"][0]["message"]["content"]
        parsed = json.loads(_strip_code_fences(message))
        if not isinstance(parsed, dict):
            raise SummarizerValidationError("summarizer response must be a JSON object")
        return SummarizeResult.model_validate(parsed)


def _request_payload(request: SummarizeRequest) -> str:
    data = {
        "blocks": [
            {
                "type": block.type,
                "content": block.content,
                "source": block.source,
                "memory_id": block.memory_id,
                "tokens": block.tokens,
            }
            for block in request.blocks
        ],
        "must_retain_facts": [fact.model_dump(mode="json") for fact in request.must_retain_facts],
        "source_memory_ids": request.source_memory_ids,
        "source_event_ids": request.source_event_ids,
        "source_state_node_ids": request.source_state_node_ids,
        "summary_budget_tokens": request.summary_budget_tokens,
        "run_id": request.run_id,
        "workspace_id": request.workspace_id,
        "kind": request.kind.value,
    }
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


def _host_label(base_url: str) -> str:
    try:
        return httpx.URL(base_url).host or "unknown"
    except Exception:
        return "unknown"


def _allowed_fact_keys(request: SummarizeRequest) -> set[tuple[str, str]]:
    # C3 deliberately avoids parsing rendered ContextBlock text for allow-list
    # facts. Free-form text can contain negated/stale/risky mentions such as
    # "do not use project.runtime=npm"; only structured facts supplied by the
    # caller are trusted. C4 can extend SummarizeRequest with structured
    # candidate_facts if it needs a wider allow-list.
    return {_fact_key(fact) for fact in request.must_retain_facts}


def _validate_source_ids(request: SummarizeRequest, result: SummarizeResult) -> None:
    allowed_memory_ids = set(request.source_memory_ids)
    allowed_event_ids = set(request.source_event_ids)
    allowed_state_node_ids = set(request.source_state_node_ids)
    allowed_run_ids = {request.run_id} if request.run_id is not None else set()
    allowed_step_ids: set[str] = set()
    for fact in request.must_retain_facts:
        if fact.source_memory_id is not None and fact.source_memory_id not in allowed_memory_ids:
            raise SummarizerValidationError(
                "summarizer request has retained fact source_memory_id outside source_memory_ids"
            )
        if fact.provenance is None:
            continue
        if fact.provenance.run_id is not None:
            allowed_run_ids.add(fact.provenance.run_id)
        if fact.provenance.step_id is not None:
            allowed_step_ids.add(fact.provenance.step_id)
        if fact.provenance.event_id is not None:
            allowed_event_ids.add(fact.provenance.event_id)
        if fact.provenance.state_node_id is not None:
            allowed_state_node_ids.add(fact.provenance.state_node_id)
    for block in request.blocks:
        if block.provenance is None:
            continue
        if block.provenance.run_id is not None:
            allowed_run_ids.add(block.provenance.run_id)
        if block.provenance.step_id is not None:
            allowed_step_ids.add(block.provenance.step_id)

    if result.source_memory_ids != request.source_memory_ids:
        raise SummarizerValidationError("summarizer did not preserve source_memory_ids")
    if result.source_event_ids != request.source_event_ids:
        raise SummarizerValidationError("summarizer did not preserve source_event_ids")
    if result.source_state_node_ids != request.source_state_node_ids:
        raise SummarizerValidationError("summarizer did not preserve source_state_node_ids")

    for fact in result.retained_facts:
        if fact.source_memory_id is not None and fact.source_memory_id not in allowed_memory_ids:
            raise SummarizerValidationError("summarizer invented retained fact source_memory_id")
        if fact.provenance is None:
            continue
        if fact.provenance.run_id is not None and fact.provenance.run_id not in allowed_run_ids:
            raise SummarizerValidationError("summarizer invented retained fact run_id")
        if fact.provenance.step_id is not None and fact.provenance.step_id not in allowed_step_ids:
            raise SummarizerValidationError("summarizer invented retained fact step_id")
        if fact.provenance.event_id is not None and fact.provenance.event_id not in allowed_event_ids:
            raise SummarizerValidationError("summarizer invented retained fact event_id")
        if fact.provenance.state_node_id is not None and fact.provenance.state_node_id not in allowed_state_node_ids:
            raise SummarizerValidationError("summarizer invented retained fact state_node_id")


_SUMMARY_FACT_PATTERN = re.compile(r"\b([A-Za-z][\w.-]*)\s*=\s*([^\s;,`]+)")


def _summary_fact_keys(summary: str) -> set[tuple[str, str]]:
    facts: set[tuple[str, str]] = set()
    for match in _SUMMARY_FACT_PATTERN.finditer(summary):
        value = match.group(2).strip(".。!！?？)]}>")
        facts.add((match.group(1), value))
    return facts


def _validate_result(request: SummarizeRequest, result: SummarizeResult) -> SummarizeResult:
    allowed = _allowed_fact_keys(request)
    required = {_fact_key(fact) for fact in request.must_retain_facts}
    actual = {_fact_key(fact) for fact in result.retained_facts}
    allowed_identities = {_fact_identity(fact) for fact in request.must_retain_facts}

    invented = actual - allowed
    if invented:
        raise SummarizerValidationError(f"summarizer invented retained facts: {sorted(invented)}")
    missing = required - actual
    if missing:
        raise SummarizerValidationError(f"summarizer dropped required facts: {sorted(missing)}")
    actual_identities = {_fact_identity(fact) for fact in result.retained_facts}
    missing_identities = allowed_identities - actual_identities
    if missing_identities:
        raise SummarizerValidationError("summarizer dropped required retained fact provenance")
    identity_drift = actual_identities - allowed_identities
    if identity_drift:
        raise SummarizerValidationError("summarizer changed retained fact provenance")

    summary_invented = _summary_fact_keys(result.summary) - allowed
    if summary_invented:
        raise SummarizerValidationError(f"summarizer invented summary facts: {sorted(summary_invented)}")

    _validate_source_ids(request, result)

    actual_post_tokens = estimate_tokens(result.summary)
    if actual_post_tokens > request.summary_budget_tokens:
        summary, truncated = _truncate_summary(result.summary, request.summary_budget_tokens)
        warnings = list(result.warnings)
        if truncated:
            warnings.append("summary truncated to fit budget")
        result = result.model_copy(update={"summary": summary, "post_tokens": estimate_tokens(summary), "warnings": warnings})
    elif result.post_tokens != actual_post_tokens:
        result = result.model_copy(update={"post_tokens": actual_post_tokens})
    return result


__all__ = [
    "LLMSummarizerProvider",
    "RuleSummarizerProvider",
    "SummarizeRequest",
    "SummarizeResult",
    "SummarizerProvider",
    "SummarizerValidationError",
]
