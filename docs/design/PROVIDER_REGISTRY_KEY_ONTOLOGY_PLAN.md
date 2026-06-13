# Provider Registry + Key Ontology Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Progress tracking rule:** after completing each Task in §5, update `.ai/PROJECT_STATE.md` and tick or annotate `docs/design/ROADMAP.md` §10 / §11. Do not leave implementation progress only in chat history.

**Goal:** Complete ROADMAP §10 Provider Registry and §11 Controlled Memory Key Ontology so MemTrace has one deterministic-vs-real-provider boundary and one authoritative memory-key schema for extraction, resolver conflict semantics, policy snapshots, benchmark reproducibility, and future provider families.

**Architecture:** Introduce a small `app.providers` package for non-secret capability metadata, provider registry/factory wiring, deterministic embedding, optional OpenAI-compatible embedding, and a contract-only judge provider. Introduce `app.memory.key_ontology` as the single source of truth for canonical memory keys, aliases, cardinality, default memory type/scope, extraction prompt rendering, and LLM candidate normalization; keep `MemoryRuntime` as the only runtime semantic boundary and keep deterministic benchmark defaults explicitly isolated from real network providers.

**Tech Stack:** Python 3.12, Pydantic v2, FastAPI dependency wiring, SQLAlchemy/PostgreSQL/pgvector via existing repository boundary, `httpx.MockTransport` tests, `uv`, pytest, existing conformance / replay / benchmark suites.

---

## 0. Current-state coordinates

- ROADMAP §10 declares four provider families: existing `LLMExtractionProvider`, new `EmbeddingProvider`, existing `SummarizerProvider`, and future `JudgeProvider`; each needs deterministic fallback, config-gated real implementation, failure degradation, and capability metadata.
- ROADMAP §11 declares a controlled key schema registry for `project.runtime`, `project.package_manager`, `project.test_command`, `project.database`, `tool.command.failed`, `endpoint.current`, `endpoint.deprecated`, and `user.preference.*`; it must remove drift between `writer`, `resolver._SINGLE_VALUED_KEYS`, and `llm_extractor._SYSTEM_PROMPT`.
- `apps/api/app/memory/llm_extractor.py` already has `ExtractionProvider`, `FakeExtractionProvider`, `LLMExtractionProvider`, `ExtractionCandidate`, and `build_results(...)`.
- `apps/api/app/memory/summarizer_provider.py` already has `SummarizerProvider`, `RuleSummarizerProvider`, `LLMSummarizerProvider`, validation, and runtime fallback.
- `apps/api/app/retrieval/similarity.py` still owns deterministic `stable_embedding(...)`; `apps/api/app/runtime/repository.py:35` `ensure_embedding(...)` still calls it synchronously at `Repository.add_memory(...)` time as the direct-seed/backfill boundary.
- `apps/api/app/retrieval/controller.py` now freezes provider snapshots at construction, exposes them through public `provider_snapshot`, and embeds query vectors through the injected embedding provider with deterministic fallback.
- `apps/api/app/retrieval/policy.py` now uses `POLICY_VERSION = "retrieval-policy-v2"`, merges retrieval-relevant provider snapshots (`embedding`, `summarizer`) over deterministic defaults, excludes `judge`, and reflects explicit summarizer overrides.
- `apps/api/app/api/deps.py` now builds providers via `providers/factory.py` and injects the registry into `MemoryRuntime`; provider work remaining after P4 is benchmark deterministic override/conformance in P8, not runtime/retrieval hot-path migration.
- `apps/api/app/memory/resolver.py:39` hard-codes `_SINGLE_VALUED_KEYS`; `apps/api/app/memory/writer.py:127` hard-codes runtime keys; `apps/api/app/memory/llm_extractor.py:92` hard-codes controlled-key prompt text.

## 1. Scope

### Included

1. Provider capability metadata and a `ProviderRegistry` with deterministic snapshots.
2. Deterministic hash embedding provider wrapper plus optional OpenAI-compatible embedding provider.
3. Registry-based FastAPI dependency wiring for extraction, summarizer, embedding, and contract-only judge provider.
4. Runtime/retrieval integration so embedding query/write paths can use a provider while repository-level deterministic fallback remains intact.
5. Retrieval policy snapshot version bump with non-secret provider capability metadata.
6. Key ontology module with canonical specs, aliases, cardinality, free-form policy, prompt rendering, and candidate normalization.
7. Resolver/writer/LLM extraction prompt/build path migrated to ontology.
8. Benchmark deterministic provider override so real provider env vars cannot affect reproducibility.
9. Tests, conformance checks, docs, ROADMAP, and `.ai` project-memory synchronization.

### Excluded

- No production LLM judge behavior in this slice; `JudgeProvider` is interface + registry metadata only.
- No pgvector dimension migration; `embedding_vector` remains 256-dimensional.
- No removal of deterministic `stable_embedding(...)`; it remains the default benchmark path and a direct helper for tests/backfills.
- No storage table for ontology in this slice; ontology is code-defined and versioned in source.
- No Redis/Celery, multi-worker buffer, React dashboard, ES/Neo4j, RBAC/JWT, or hosted governance.
- No automatic git commits during execution unless the user explicitly asks for commits.

## 2. File structure / responsibility map

### New production files

- `apps/api/app/providers/__init__.py` — public exports for provider registry primitives and provider implementations.
- `apps/api/app/providers/base.py` — `ProviderKind`, `ProviderCapabilities`, shared protocol types, and snapshot helpers.
- `apps/api/app/providers/registry.py` — lightweight `ProviderRegistry` core only; no settings/provider implementation imports.
- `apps/api/app/providers/factory.py` — deterministic factory helpers and settings-based registry builder.
- `apps/api/app/providers/embedding.py` — `EmbeddingProvider`, deterministic hash provider, OpenAI-compatible embedding provider, vector validation.
- `apps/api/app/providers/judge.py` — contract-only `JudgeProvider`, no hot-path behavior.
- `apps/api/app/memory/key_ontology.py` — canonical memory key specs, aliases, cardinality, safe free-form validation, prompt rendering, and normalization.

### New test files

- `apps/api/tests/providers/__init__.py`
- `apps/api/tests/providers/test_registry.py`
- `apps/api/tests/providers/test_embedding_provider.py`
- `apps/api/tests/providers/test_judge_provider_contract.py`
- `apps/api/tests/memory/test_key_ontology.py`

### Existing production files to modify

- `apps/api/app/config.py` — embedding provider settings and comments that explain deterministic defaults.
- `apps/api/app/api/deps.py` — registry factory wiring and provider lifecycle shutdown.
- `apps/api/app/runtime/models.py` — expose persisted policy metadata on `AccessInspection` instead of assuming a nested access log field.
- `apps/api/app/runtime/memory_runtime.py` — optional `provider_registry`, embedding preparation before memory persistence, registry compatibility with existing explicit provider args.
- `apps/api/app/retrieval/controller.py` — injected embedding provider for query vectors and provider snapshot for policy snapshots.
- `apps/api/app/retrieval/policy.py` — policy version bump and provider snapshot parameter.
- `apps/api/app/observability/replay.py` — pass the same provider snapshot during policy-drift hash reconstruction.
- `apps/api/app/runtime/repository.py` — keep deterministic `ensure_embedding(...)` fallback; no async provider in repository.
- `apps/api/app/memory/llm_extractor.py` — `free_form` field, ontology-rendered prompt, candidate key normalization before `MemoryWriteResult` conversion.
- `apps/api/app/memory/resolver.py` — derive single-valued semantics from ontology.
- `apps/api/app/memory/writer.py` — use ontology constants for runtime keys.
- `apps/api/app/benchmark/runner.py` — deterministic provider registry for every benchmark runtime.
- `docs/design/ROADMAP.md`, `.ai/PROJECT_STATE.md`, `.ai/REQUIREMENTS.md`, `.ai/IMPLEMENTATION_PLAN.md`, `.ai/PITFALLS.md` — closeout sync.

### Existing tests to modify

- `apps/api/tests/memory/test_llm_extractor.py`
- `apps/api/tests/memory/test_llm_provider.py`
- `apps/api/tests/memory/test_resolver.py`
- `apps/api/tests/memory/test_writer.py`
- `apps/api/tests/retrieval/test_similarity.py`
- `apps/api/tests/retrieval/test_retrieval_trace.py`
- `apps/api/tests/runtime/test_llm_extraction_flow.py`
- `apps/api/tests/runtime/test_memory_runtime_trace.py`
- `apps/api/tests/runtime/test_summarizer_fallback.py`
- `apps/api/tests/benchmark/test_runner.py`
- `apps/api/tests/conformance/test_strategy_conformance.py`
- `apps/api/tests/conformance/test_replay_conformance.py`

## 3. Cross-cutting invariants

1. **Deterministic default:** with no new env vars set, all existing demos, tests, benchmark rows, and reproducibility checks keep deterministic behavior.
2. **No secret snapshots:** provider metadata and policy snapshots must not contain API keys, auth headers, raw request bodies, or raw provider responses.
3. **Benchmark isolation:** benchmark runtimes use deterministic providers even if process env enables real extraction, summarizer, or embedding providers.
4. **Repository fallback:** `Repository.add_memory(...)` remains a deterministic embedding backfill chokepoint for direct test/benchmark seeding.
5. **Provider degradation:** real provider failures degrade to deterministic behavior at runtime call sites, not by storing partial broken metadata.
6. **Ontology is single source:** `writer`, `resolver`, and `llm_extractor` must import ontology constants/functions rather than duplicating key/cardinality/prompt rules.
7. **Free-form explicitness:** unknown LLM candidate keys are dropped unless the provider explicitly marks them as free-form and they pass safe prefix/secret-like key validation.
8. **Policy versioning:** provider metadata changes retrieval policy semantics, so policy snapshot version must bump from v1 to v2.
9. **No import cycles:** `key_ontology.py` may depend on `runtime.models`; `writer.py`, `resolver.py`, and `llm_extractor.py` may depend on `key_ontology.py`; ontology must not import those modules.

## 4. Execution rules

- Use TDD per task: write targeted RED tests, run and confirm failure, implement minimal production changes, run targeted GREEN, then run affected regression.
- Keep changes batch-sized: provider base, embedding, ontology, runtime wiring, benchmark/replay/docs are separate reviewable units.
- Preserve existing public APIs for at least one slice: `MemoryRuntime(..., extraction_provider=..., summarizer_provider=...)` remains accepted while `provider_registry` is introduced.
- Do not commit automatically. If commits are requested by the user during execution, stage only files belonging to the completed task and use the repository's conventional commit style.

---

## 5. Tasks

### Task P1: Provider capability metadata and registry core

**Goal:** Add the smallest provider registry layer with stable, non-secret capability snapshots and deterministic registration semantics. No runtime behavior changes.

**Files:**

- Create: `apps/api/app/providers/__init__.py`
- Create: `apps/api/app/providers/base.py`
- Create: `apps/api/app/providers/registry.py`
- Create: `apps/api/tests/providers/__init__.py`
- Create: `apps/api/tests/providers/test_registry.py`

- [x] **Step 1: Add RED registry tests**

Create `apps/api/tests/providers/test_registry.py`:

```python
from __future__ import annotations

import pytest

from app.providers.base import ProviderCapabilities, ProviderKind
from app.providers.registry import ProviderRegistry


class _Provider:
    pass


def test_capability_snapshot_is_stable_and_non_secret():
    metadata = {
        "dim": 256,
        "nested": {"dim": 256},
        "api_key": "must-not-render",
        "x_api_key_header": "must-not-render",
        "note": "sk-must-not-render",
    }
    caps = ProviderCapabilities(
        provider_id="embedding.deterministic_hash.v1",
        kind=ProviderKind.embedding,
        deterministic=True,
        requires_network=False,
        endpoint_types=(),
        model=None,
        configured=True,
        fallback_provider_id=None,
        metadata=metadata,
    )
    metadata["dim"] = 999
    metadata["nested"]["dim"] = 999

    snap = caps.snapshot()

    assert snap == {
        "provider_id": "embedding.deterministic_hash.v1",
        "kind": "embedding",
        "deterministic": True,
        "requires_network": False,
        "endpoint_types": [],
        "model": None,
        "configured": True,
        "fallback_provider_id": None,
        "metadata": {"dim": 256, "nested": {"dim": 256}},
    }


def test_registry_registers_and_snapshots_by_provider_kind():
    registry = ProviderRegistry()
    provider = _Provider()
    caps = ProviderCapabilities(
        provider_id="extraction.fake_writer.v1",
        kind=ProviderKind.extraction,
        deterministic=True,
        requires_network=False,
    )

    registry.register(ProviderKind.extraction, provider, caps)

    assert registry.get(ProviderKind.extraction) is provider
    assert registry.capabilities(ProviderKind.extraction) is caps
    assert registry.snapshot() == {"extraction": caps.snapshot()}


def test_registry_rejects_kind_mismatch():
    registry = ProviderRegistry()
    caps = ProviderCapabilities(
        provider_id="summary.rule.v1",
        kind=ProviderKind.summarizer,
        deterministic=True,
        requires_network=False,
    )

    with pytest.raises(ValueError, match="provider capability kind mismatch"):
        registry.register(ProviderKind.embedding, _Provider(), caps)
```

- [x] **Step 2: Run RED test**

Run:

```bash
uv run --extra dev pytest apps/api/tests/providers/test_registry.py -q
```

Expected: fail during import because `app.providers` does not exist.

- [x] **Step 3: Implement provider base types**

Create `apps/api/app/providers/base.py`:

```python
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Protocol, runtime_checkable

_SECRET_METADATA_TERMS = ("api_key", "apikey", "authorization", "bearer", "token", "password", "secret", "credential")
_SECRET_VALUE_TERMS = ("sk-", "bearer ")


class ProviderKind(str, Enum):
    extraction = "extraction"
    embedding = "embedding"
    summarizer = "summarizer"
    judge = "judge"


def _is_secret_metadata_key(key: str) -> bool:
    lowered = key.lower().replace("-", "_")
    return any(term in lowered for term in _SECRET_METADATA_TERMS)


def _is_secret_metadata_value(value: str) -> bool:
    lowered = value.lower()
    return any(term in lowered for term in _SECRET_VALUE_TERMS)


def _safe_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in sorted(metadata.items(), key=lambda item: item[0]):
        if _is_secret_metadata_key(key):
            continue
        if isinstance(value, Mapping):
            safe[key] = _safe_metadata(value)
        elif isinstance(value, str):
            if _is_secret_metadata_value(value):
                continue
            safe[key] = value
        elif isinstance(value, (int, float, bool)) or value is None:
            safe[key] = value
        else:
            text = str(value)
            if _is_secret_metadata_value(text):
                continue
            safe[key] = text
    return safe


def _freeze_metadata(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze_metadata(nested) for key, nested in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_metadata(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    provider_id: str
    kind: ProviderKind
    deterministic: bool
    requires_network: bool
    endpoint_types: tuple[str, ...] = ()
    model: str | None = None
    configured: bool = True
    fallback_provider_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # frozen dataclasses do not freeze mutable dict/list contents; recursively
        # copy/freeze metadata so callers cannot mutate future capability snapshots.
        object.__setattr__(self, "metadata", _freeze_metadata(self.metadata))

    def snapshot(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "kind": self.kind.value,
            "deterministic": self.deterministic,
            "requires_network": self.requires_network,
            "endpoint_types": list(self.endpoint_types),
            "model": self.model,
            "configured": self.configured,
            "fallback_provider_id": self.fallback_provider_id,
            "metadata": _safe_metadata(self.metadata),
        }


@runtime_checkable
class EmbeddingProvider(Protocol):
    capabilities: ProviderCapabilities

    async def embed_text(self, text: str | None) -> list[float]: ...
```

- [x] **Step 4: Implement provider registry**

Create `apps/api/app/providers/registry.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.providers.base import ProviderCapabilities, ProviderKind


@dataclass(slots=True)
class ProviderSlot:
    provider: Any
    capabilities: ProviderCapabilities


class ProviderRegistry:
    def __init__(self) -> None:
        self._slots: dict[ProviderKind, ProviderSlot] = {}

    def register(self, kind: ProviderKind, provider: Any, capabilities: ProviderCapabilities) -> None:
        if capabilities.kind != kind:
            raise ValueError("provider capability kind mismatch")
        self._slots[kind] = ProviderSlot(provider=provider, capabilities=capabilities)

    def get(self, kind: ProviderKind) -> Any | None:
        slot = self._slots.get(kind)
        return slot.provider if slot is not None else None

    def capabilities(self, kind: ProviderKind) -> ProviderCapabilities | None:
        slot = self._slots.get(kind)
        return slot.capabilities if slot is not None else None

    def snapshot(self) -> dict[str, dict[str, Any]]:
        return {
            kind.value: slot.capabilities.snapshot()
            for kind, slot in sorted(self._slots.items(), key=lambda item: item[0].value)
        }
```

- [x] **Step 5: Export public provider symbols**

Create `apps/api/app/providers/__init__.py`:

```python
from app.providers.base import EmbeddingProvider, ProviderCapabilities, ProviderKind
from app.providers.registry import ProviderRegistry

__all__ = [
    "EmbeddingProvider",
    "ProviderCapabilities",
    "ProviderKind",
    "ProviderRegistry",
]
```

- [x] **Step 6: Run GREEN tests**

Run:

```bash
uv run --extra dev pytest apps/api/tests/providers/test_registry.py -q
```

Expected: `3 passed`.

- [x] **Step 7: Run focused compile check**

Run:

```bash
uv run --extra dev python -m compileall -q apps/api/app/providers
```

Expected: command exits successfully.

### Task P2: Embedding providers and OpenAI-compatible vector validation

**Goal:** Add deterministic and real embedding provider implementations while preserving `stable_embedding(...)` as the default deterministic primitive.

**Files:**

- Create: `apps/api/app/providers/embedding.py`
- Test: `apps/api/tests/providers/test_embedding_provider.py`
- Modify: `apps/api/app/providers/__init__.py`
- Modify: `apps/api/tests/retrieval/test_similarity.py`

- [x] **Step 1: Add RED embedding provider tests**

Create `apps/api/tests/providers/test_embedding_provider.py`:

```python
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
```

- [x] **Step 2: Run RED tests**

Run:

```bash
uv run --extra dev pytest apps/api/tests/providers/test_embedding_provider.py -q
```

Expected: fail during import because `app.providers.embedding` does not exist.

- [x] **Step 3: Implement embedding providers**

Create `apps/api/app/providers/embedding.py`:

```python
from __future__ import annotations

from typing import Any

import httpx

from app.providers.base import ProviderCapabilities, ProviderKind
from app.retrieval.similarity import stable_embedding


class DeterministicHashEmbeddingProvider:
    def __init__(self, *, dim: int = 256) -> None:
        self.dim = dim
        self.capabilities = ProviderCapabilities(
            provider_id="embedding.deterministic_hash.v1",
            kind=ProviderKind.embedding,
            deterministic=True,
            requires_network=False,
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
        if self._client is not None:
            resp = await self._client.post(url, json=payload, headers=headers)
        else:
            async with httpx.AsyncClient(timeout=self._timeout_s) as client:
                resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        body = resp.json()
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, list) or not data:
            raise ValueError("embedding response missing data")
        embedding = data[0].get("embedding") if isinstance(data[0], dict) else None
        if not isinstance(embedding, list) or not all(isinstance(v, int | float) for v in embedding):
            raise ValueError("embedding response missing numeric vector")
        vector = [float(v) for v in embedding]
        if len(vector) != self._dimensions:
            raise ValueError(f"embedding dimension mismatch: expected {self._dimensions}, got {len(vector)}")
        return vector


def _host_label(base_url: str) -> str:
    try:
        return httpx.URL(base_url).host or "unknown"
    except Exception:
        return "unknown"
```

- [x] **Step 4: Export embedding providers**

Modify `apps/api/app/providers/__init__.py`:

```python
from app.providers.base import EmbeddingProvider, ProviderCapabilities, ProviderKind
from app.providers.embedding import DeterministicHashEmbeddingProvider, OpenAIEmbeddingProvider
from app.providers.registry import ProviderRegistry

__all__ = [
    "DeterministicHashEmbeddingProvider",
    "EmbeddingProvider",
    "OpenAIEmbeddingProvider",
    "ProviderCapabilities",
    "ProviderKind",
    "ProviderRegistry",
]
```

- [x] **Step 5: Run GREEN tests**

Run:

```bash
uv run --extra dev pytest apps/api/tests/providers/test_embedding_provider.py apps/api/tests/retrieval/test_similarity.py -q
```

Expected: existing similarity tests still pass and new provider tests pass.

### Task P3: Settings-based provider registry factory and FastAPI DI wiring

**Status:** ✅ complete as of 2026-06-13. `providers/factory.py`, settings-based registry construction, FastAPI DI wiring, runtime registry injection, and no-op judge registration in deterministic registry are implemented and verified. Remaining provider work moved to Task P4 embedding write/query migration.

**Goal:** Centralize provider construction in registry/factory helpers while preserving all existing default behavior and default-off LLM paths.

**Files:**

- Modify: `apps/api/app/config.py`
- Create: `apps/api/app/providers/factory.py`
- Modify: `apps/api/app/api/deps.py`
- Modify: `apps/api/tests/providers/test_registry.py`
- Modify: `apps/api/tests/memory/test_summarizer_provider.py`
- Modify: `apps/api/tests/runtime/test_summarizer_fallback.py`

- [x] **Step 1: Add RED tests for default and fallback registry construction**

Append to `apps/api/tests/providers/test_registry.py`:

```python
from app.config import Settings
from app.memory.llm_extractor import FakeExtractionProvider, LLMExtractionProvider
from app.memory.summarizer_provider import RuleSummarizerProvider, LLMSummarizerProvider
from app.providers.base import ProviderKind
from app.providers.embedding import DeterministicHashEmbeddingProvider, OpenAIEmbeddingProvider
from app.providers.factory import build_provider_registry, deterministic_provider_registry


def test_deterministic_provider_registry_uses_only_reproducible_providers():
    registry = deterministic_provider_registry(embedding_dim=256)
    snapshot = registry.snapshot()

    assert isinstance(registry.get(ProviderKind.embedding), DeterministicHashEmbeddingProvider)
    assert isinstance(registry.get(ProviderKind.summarizer), RuleSummarizerProvider)
    assert snapshot["embedding"]["deterministic"] is True
    assert snapshot["summarizer"]["deterministic"] is True
    assert all(not caps["requires_network"] for caps in snapshot.values())


def test_settings_registry_default_is_deterministic_for_embedding_and_summarizer():
    registry = build_provider_registry(Settings())

    assert registry.get(ProviderKind.extraction) is None
    assert isinstance(registry.get(ProviderKind.embedding), DeterministicHashEmbeddingProvider)
    assert isinstance(registry.get(ProviderKind.summarizer), RuleSummarizerProvider)


def test_settings_registry_wires_real_llm_and_embedding_when_enabled_with_keys():
    settings = Settings(
        llm_extraction_enabled=True,
        llm_summarizer_enabled=True,
        llm_api_key="sk-llm",
        embedding_provider="openai",
        embedding_api_key="sk-emb",
        embedding_dimensions=256,
    )
    registry = build_provider_registry(settings)

    assert isinstance(registry.get(ProviderKind.extraction), LLMExtractionProvider)
    assert isinstance(registry.get(ProviderKind.summarizer), LLMSummarizerProvider)
    assert isinstance(registry.get(ProviderKind.embedding), OpenAIEmbeddingProvider)
    assert "sk-" not in str(registry.snapshot())


def test_settings_registry_falls_back_when_enabled_without_keys():
    settings = Settings(
        llm_extraction_enabled=True,
        llm_summarizer_enabled=True,
        llm_api_key="",
        embedding_provider="openai",
        embedding_api_key="",
    )
    registry = build_provider_registry(settings)

    assert isinstance(registry.get(ProviderKind.extraction), FakeExtractionProvider)
    assert isinstance(registry.get(ProviderKind.summarizer), RuleSummarizerProvider)
    assert isinstance(registry.get(ProviderKind.embedding), DeterministicHashEmbeddingProvider)
    assert registry.snapshot()["embedding"]["fallback_provider_id"] == "embedding.deterministic_hash.v1"
```

- [x] **Step 2: Run RED tests**

Run:

```bash
uv run --extra dev pytest apps/api/tests/providers/test_registry.py -q
```

Expected: fail because registry factory helpers and config fields do not exist.

- [x] **Step 3: Add embedding settings**

Modify `apps/api/app/config.py` inside `Settings` near existing embedding settings:

```python
    # Provider Registry embedding settings. The deterministic hash provider is
    # the default benchmark/reproducibility path. Real embedding providers are
    # optional and config-gated, and must match embedding_dim unless a migration
    # explicitly changes the pgvector column dimension.
    embedding_provider: str = "deterministic_hash"
    embedding_api_key: str = ""
    embedding_base_url: str = "https://api.openai.com/v1"
    embedding_model: str = "text-embedding-3-small"
    embedding_timeout_ms: int = 8000
    embedding_dimensions: int = 256
```

- [x] **Step 4: Implement registry factories outside the registry core**

Create `apps/api/app/providers/factory.py`:

```python
import logging

from app.config import Settings
from app.memory.llm_extractor import FakeExtractionProvider, LLMExtractionProvider
from app.memory.summarizer_provider import LLMSummarizerProvider, RuleSummarizerProvider
from app.providers.base import ProviderCapabilities, ProviderKind
from app.providers.embedding import DeterministicHashEmbeddingProvider, OpenAIEmbeddingProvider
from app.providers.registry import ProviderRegistry

logger = logging.getLogger(__name__)


def deterministic_provider_registry(*, embedding_dim: int = 256) -> ProviderRegistry:
    registry = ProviderRegistry()
    embedding = DeterministicHashEmbeddingProvider(dim=embedding_dim)
    registry.register(ProviderKind.embedding, embedding, embedding.capabilities)
    summarizer = RuleSummarizerProvider()
    registry.register(
        ProviderKind.summarizer,
        summarizer,
        ProviderCapabilities(
            provider_id="summarizer.rule.v1",
            kind=ProviderKind.summarizer,
            deterministic=True,
            requires_network=False,
        ),
    )
    return registry


def build_provider_registry(settings: Settings) -> ProviderRegistry:
    registry = deterministic_provider_registry(embedding_dim=settings.embedding_dim)

    if settings.llm_extraction_enabled:
        if settings.llm_api_key:
            extraction = LLMExtractionProvider(
                api_key=settings.llm_api_key,
                base_url=settings.llm_base_url,
                model=settings.llm_model,
                timeout_s=settings.llm_timeout_ms / 1000,
                max_tokens=settings.llm_max_tokens,
                use_json_response_format=settings.llm_use_json_response_format,
            )
            registry.register(
                ProviderKind.extraction,
                extraction,
                ProviderCapabilities(
                    provider_id="extraction.openai_compatible.v1",
                    kind=ProviderKind.extraction,
                    deterministic=False,
                    requires_network=True,
                    endpoint_types=("openai_chat_completions",),
                    model=settings.llm_model,
                ),
            )
        else:
            logger.warning("LLM extraction enabled without API key; using FakeExtractionProvider")
            extraction = FakeExtractionProvider()
            registry.register(
                ProviderKind.extraction,
                extraction,
                ProviderCapabilities(
                    provider_id="extraction.fake_writer.v1",
                    kind=ProviderKind.extraction,
                    deterministic=True,
                    requires_network=False,
                    configured=False,
                    fallback_provider_id=None,
                ),
            )

    if settings.llm_summarizer_enabled and settings.llm_api_key:
        summarizer = LLMSummarizerProvider(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            timeout_s=settings.compaction_timeout_ms / 1000,
            max_tokens=settings.llm_max_tokens,
            use_json_response_format=settings.llm_use_json_response_format,
        )
        registry.register(
            ProviderKind.summarizer,
            summarizer,
            ProviderCapabilities(
                provider_id="summarizer.openai_compatible.v1",
                kind=ProviderKind.summarizer,
                deterministic=False,
                requires_network=True,
                endpoint_types=("openai_chat_completions",),
                model=settings.llm_model,
                fallback_provider_id="summarizer.rule.v1",
            ),
        )
    elif settings.llm_summarizer_enabled:
        logger.warning("LLM summarizer enabled without API key; using RuleSummarizerProvider")

    if settings.embedding_provider == "openai" and settings.embedding_api_key and settings.embedding_dimensions == settings.embedding_dim:
        embedding = OpenAIEmbeddingProvider(
            api_key=settings.embedding_api_key,
            base_url=settings.embedding_base_url,
            model=settings.embedding_model,
            dimensions=settings.embedding_dimensions,
            timeout_s=settings.embedding_timeout_ms / 1000,
        )
        registry.register(ProviderKind.embedding, embedding, embedding.capabilities)
    elif settings.embedding_provider == "openai":
        logger.warning("OpenAI embedding provider unavailable or dimension mismatch; using deterministic hash embedding")
        embedding = DeterministicHashEmbeddingProvider(dim=settings.embedding_dim)
        registry.register(
            ProviderKind.embedding,
            embedding,
            ProviderCapabilities(
                provider_id="embedding.deterministic_hash.v1",
                kind=ProviderKind.embedding,
                deterministic=True,
                requires_network=False,
                configured=False,
                fallback_provider_id="embedding.deterministic_hash.v1",
                metadata={"algorithm": "blake2b_hash_bow", "dim": settings.embedding_dim},
            ),
        )

    return registry
```

- [x] **Step 5: Replace duplicate DI construction with registry factory**

Modify `apps/api/app/api/deps.py`:

```python
from app.providers.base import ProviderKind
from app.providers.factory import build_provider_registry
```

Then in `AppState.startup(...)`, replace manual provider wiring with:

```python
        provider_registry = build_provider_registry(settings)
        provider = provider_registry.get(ProviderKind.extraction)
        summarizer_provider = provider_registry.get(ProviderKind.summarizer)

        self.runtime = MemoryRuntime(
            repo,
            default_workspace_id=settings.default_workspace_id,
            token_budget=settings.retrieval_token_budget,
            extraction_mode=ExtractionMode(settings.extraction_mode),
            extraction_provider=provider,
            summarizer_provider=summarizer_provider,
            provider_registry=provider_registry,
        )
```

Keep `_build_summarizer_provider(...)` only if existing tests import it; if retained, implement it as:

```python
def _build_summarizer_provider(settings: Settings) -> SummarizerProvider:
    provider = build_provider_registry(settings).get(ProviderKind.summarizer)
    assert provider is not None
    return provider
```

- [x] **Step 6: Run GREEN tests and existing provider fallback suites**

Run:

```bash
uv run --extra dev pytest apps/api/tests/providers/test_registry.py apps/api/tests/memory/test_summarizer_provider.py apps/api/tests/runtime/test_summarizer_fallback.py -q
```

Expected: all tests pass; existing summarizer fallback semantics remain unchanged.

### Task P4: Runtime and retrieval provider integration

**Status:** ✅ complete as of 2026-06-13. P4a observability/policy front half is complete (`MemoryRuntime(provider_registry=...)`, `retrieval-policy-v2`, retrieval-relevant provider snapshots, replay hash reconstruction, flat `AccessInspection.policy_*` fields, and `judge` exclusion). P4b embedding hot-path migration is also complete: runtime internal memory writes use `_prepare_embedding(...)` with provider-first / deterministic fallback behavior, retrieval query vectors use `_embed_query(...)` with the same degradation semantics, repository-level `ensure_embedding(...)` remains unchanged as deterministic backfill, replay policy drift uses public `RetrievalController.provider_snapshot` instead of a private helper, provider vectors must be finite 256-dim numeric vectors before reaching storage/search, provider snapshots are frozen, and explicit `summarizer_provider=` overrides are reflected in retrieval policy snapshots.

**Goal:** Use the injected embedding provider for query vectors and memory writes, while retaining repository-level deterministic fallback. Include provider snapshots in retrieval policy v2.

**Files:**

- Modify: `apps/api/app/runtime/memory_runtime.py`
- Modify: `apps/api/app/runtime/models.py`
- Modify: `apps/api/app/retrieval/controller.py`
- Modify: `apps/api/app/retrieval/policy.py`
- Modify: `apps/api/app/observability/replay.py`
- Modify: `apps/api/tests/runtime/test_memory_runtime_trace.py`
- Modify: `apps/api/tests/retrieval/test_retrieval_trace.py`

- [x] **Step 1: Add RED runtime embedding preparation tests**

Append to `apps/api/tests/runtime/test_memory_runtime_trace.py`:

```python
from app.providers.base import ProviderCapabilities, ProviderKind
from app.providers.registry import ProviderRegistry


class _RecordingEmbeddingProvider:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[str | None] = []
        self.fail = fail
        self.capabilities = ProviderCapabilities(
            provider_id="embedding.test_recording.v1",
            kind=ProviderKind.embedding,
            deterministic=True,
            requires_network=False,
            metadata={"dim": 256},
        )

    async def embed_text(self, text: str | None) -> list[float]:
        self.calls.append(text)
        if self.fail:
            raise RuntimeError("embedding failed")
        return [1.0] + [0.0] * 255


def _registry_with_embedding(provider) -> ProviderRegistry:
    registry = ProviderRegistry()
    registry.register(ProviderKind.embedding, provider, provider.capabilities)
    return registry


async def test_runtime_uses_embedding_provider_before_persisting_memory():
    provider = _RecordingEmbeddingProvider()
    runtime = MemoryRuntime(InMemoryRepository(), provider_registry=_registry_with_embedding(provider))
    run = await runtime.start_run(StartRunRequest(workspace_id="ws", session_id="s", task="setup"))
    step = await runtime.start_step(StartStepRequest(run_id=run.run_id, intent="setup"))

    await runtime.write_event(WriteEventRequest(run_id=run.run_id, step_id=step.step_id, role=EventRole.user, event_type=EventType.message, content="用 Bun"))

    memories = await runtime.list_memories(workspace_id="ws")
    assert provider.calls
    assert memories[0].embedding_vector == [1.0] + [0.0] * 255


async def test_runtime_falls_back_to_repository_embedding_when_provider_fails():
    provider = _RecordingEmbeddingProvider(fail=True)
    runtime = MemoryRuntime(InMemoryRepository(), provider_registry=_registry_with_embedding(provider))
    run = await runtime.start_run(StartRunRequest(workspace_id="ws", session_id="s", task="setup"))
    step = await runtime.start_step(StartStepRequest(run_id=run.run_id, intent="setup"))

    await runtime.write_event(WriteEventRequest(run_id=run.run_id, step_id=step.step_id, role=EventRole.user, event_type=EventType.message, content="用 Bun"))

    memories = await runtime.list_memories(workspace_id="ws")
    assert provider.calls
    assert memories[0].embedding_vector is not None
    assert memories[0].embedding_vector != [1.0] + [0.0] * 255
```

- [x] **Step 2: Add RED policy snapshot provider test**

Append to `apps/api/tests/retrieval/test_retrieval_trace.py`:

```python
from app.providers.base import ProviderCapabilities, ProviderKind
from app.providers.factory import deterministic_provider_registry
from app.runtime.memory_runtime import MemoryRuntime
from app.runtime.repository import InMemoryRepository


async def test_policy_snapshot_includes_provider_capabilities(runtime):
    run = await runtime.start_run(StartRunRequest(workspace_id="ws_test", session_id="s", task="setup"))
    step = await runtime.start_step(StartStepRequest(run_id=run.run_id, intent="setup"))
    await runtime.write_event(WriteEventRequest(run_id=run.run_id, step_id=step.step_id, role=EventRole.user, event_type=EventType.message, content="用 Bun"))

    ctx = await runtime.retrieve_context(RetrievalRequest(run_id=run.run_id, query="bun", strategy=RetrievalStrategy.variant_2))
    inspection = await runtime.inspect_access(ctx.access_id)

    assert inspection.policy_version == "retrieval-policy-v2"
    providers = inspection.policy_snapshot["providers"]
    assert providers["embedding"]["provider_id"] == "embedding.deterministic_hash.v1"
    assert providers["embedding"]["deterministic"] is True
    assert "judge" not in providers
    assert "api_key" not in str(providers)


class _CustomSummarizerForSnapshot:
    capabilities = ProviderCapabilities(
        provider_id="summarizer.custom_test.v1",
        kind=ProviderKind.summarizer,
        deterministic=True,
        requires_network=False,
    )


async def test_policy_snapshot_reflects_explicit_summarizer_override():
    registry = deterministic_provider_registry(embedding_dim=256)
    runtime = MemoryRuntime(
        InMemoryRepository(),
        provider_registry=registry,
        summarizer_provider=_CustomSummarizerForSnapshot(),
    )
    run = await runtime.start_run(StartRunRequest(workspace_id="ws_override", session_id="s", task="setup"))
    step = await runtime.start_step(StartStepRequest(run_id=run.run_id, intent="setup"))
    await runtime.write_event(WriteEventRequest(run_id=run.run_id, step_id=step.step_id, role=EventRole.user, event_type=EventType.message, content="用 Bun"))

    ctx = await runtime.retrieve_context(RetrievalRequest(run_id=run.run_id, query="bun", strategy=RetrievalStrategy.variant_2))
    inspection = await runtime.inspect_access(ctx.access_id)

    providers = inspection.policy_snapshot["providers"]
    assert providers["summarizer"]["provider_id"] == "summarizer.custom_test.v1"
    assert "judge" not in providers
```

- [x] **Step 3: Run RED tests**

Run:

```bash
uv run --extra dev pytest apps/api/tests/runtime/test_memory_runtime_trace.py -k "embedding_provider" -q
uv run --extra dev pytest apps/api/tests/retrieval/test_retrieval_trace.py -k "provider_capabilities" -q
```

Expected: fail because `MemoryRuntime` does not accept `provider_registry` and policy snapshot does not include provider metadata.

- [x] **Step 4: Update retrieval policy snapshot**

Modify `apps/api/app/retrieval/policy.py`:

```python
POLICY_VERSION = "retrieval-policy-v2"
```

Change `build_policy_snapshot(...)` signature:

```python
def build_policy_snapshot(
    request: RetrievalRequest,
    *,
    gate_config: GateConfig,
    effective_token_budget: int,
    vector_enabled: bool,
    vector_weight: float,
    compaction_notice_reserve_tokens: int,
    provider_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
```

Replace providers block:

```python
        "providers": provider_snapshot or {},
```

- [x] **Step 4b: Surface persisted policy metadata in access inspection**

Modify `apps/api/app/runtime/models.py` in `AccessInspection`:

```python
    policy_version: str | None = None
    policy_hash: str | None = None
    policy_snapshot: dict[str, Any] = Field(default_factory=dict)
```

Modify `MemoryRuntime.inspect_access(...)` return in `apps/api/app/runtime/memory_runtime.py`:

```python
            policy_version=access.policy_version,
            policy_hash=access.policy_hash,
            policy_snapshot=access.policy_snapshot,
```

- [x] **Step 5: Inject provider snapshot and embedding provider into RetrievalController**

Modify `apps/api/app/retrieval/controller.py` imports:

```python
from app.providers.embedding import DeterministicHashEmbeddingProvider
from app.providers.base import EmbeddingProvider
```

Change constructor:

```python
    def __init__(
        self,
        repo: Repository,
        *,
        default_token_budget: int = 512,
        embedding_provider: EmbeddingProvider | None = None,
        provider_snapshot: dict[str, Any] | None = None,
    ):
        self._repo = repo
        self._default_budget = default_token_budget
        settings = get_settings()
        self._use_vector = settings.retrieval_use_vector
        self._vector_weight = settings.retrieval_vector_weight
        self._embed_dim = settings.embedding_dim
        self._embedding_provider = embedding_provider or DeterministicHashEmbeddingProvider(dim=self._embed_dim)
        self._provider_snapshot = provider_snapshot or {"embedding": self._embedding_provider.capabilities.snapshot()}
        self._timeout_ms = settings.retrieval_timeout_ms
        self._compaction_notice_reserve_tokens = settings.compaction_notice_reserve_tokens
```

Add a read-only snapshot property to `RetrievalController`:

```python
    @property
    def provider_snapshot(self) -> dict[str, Any]:
        return copy.deepcopy(self._provider_snapshot)
```

Add `import copy` if not already present. Update `_attach_policy_snapshot(...)` call:

```python
            provider_snapshot=self._provider_snapshot,
```

Also update replay policy-drift reconstruction in `apps/api/app/observability/replay.py::_policy_drift(...)` so replay hashes the same provider metadata that retrieval persisted:

```python
            provider_snapshot=self._retrieval.provider_snapshot,
```

In `_select_candidates(...)`, replace query vector creation with provider fallback:

```python
        q_vec: list[float] | None = None
        if self._use_vector:
            try:
                q_vec = await self._embedding_provider.embed_text(query)
            except Exception:
                q_vec = stable_embedding(query, self._embed_dim)
```

- [x] **Step 6: Add provider registry support to MemoryRuntime**

Modify `apps/api/app/runtime/memory_runtime.py` imports:

```python
from app.providers.base import ProviderKind, EmbeddingProvider
from app.providers.embedding import DeterministicHashEmbeddingProvider
from app.providers.factory import deterministic_provider_registry
from app.providers.registry import ProviderRegistry
from app.runtime.models import EmbeddingStatus
```

Change constructor signature:

```python
        provider_registry: ProviderRegistry | None = None,
```

Initialize registry and providers before retrieval controller:

```python
        self._provider_registry = provider_registry or deterministic_provider_registry(embedding_dim=settings.embedding_dim)
        registry_extraction = self._provider_registry.get(ProviderKind.extraction)
        registry_summarizer = self._provider_registry.get(ProviderKind.summarizer)
        registry_embedding = self._provider_registry.get(ProviderKind.embedding)
        self._embedding_provider: EmbeddingProvider = registry_embedding or DeterministicHashEmbeddingProvider(dim=settings.embedding_dim)
        self._extraction_provider = extraction_provider if extraction_provider is not None else registry_extraction
        self._summarizer_provider = summarizer_provider or registry_summarizer or RuleSummarizerProvider()
        provider_snapshot = _retrieval_provider_snapshot(
            self._provider_registry,
            embedding_provider=self._embedding_provider,
            summarizer_provider=self._summarizer_provider,
        )
        self._retrieval = RetrievalController(
            repo,
            default_token_budget=token_budget,
            embedding_provider=self._embedding_provider,
            provider_snapshot=provider_snapshot,
        )
```

Add helper functions near the constructor. This keeps retrieval policy hashes limited to retrieval-relevant providers and makes explicit provider overrides visible in observability:

```python
def _provider_capability_snapshot(provider: object) -> dict[str, Any] | None:
    capabilities = getattr(provider, "capabilities", None)
    if capabilities is None:
        return None
    snapshot = getattr(capabilities, "snapshot", None)
    if callable(snapshot):
        return snapshot()
    return None


def _retrieval_provider_snapshot(
    registry: ProviderRegistry,
    *,
    embedding_provider: object,
    summarizer_provider: object,
) -> dict[str, dict[str, Any]]:
    base = {
        key: value
        for key, value in registry.snapshot().items()
        if key in {ProviderKind.embedding.value, ProviderKind.summarizer.value}
    }
    embedding_snapshot = _provider_capability_snapshot(embedding_provider)
    if embedding_snapshot is not None:
        base[ProviderKind.embedding.value] = embedding_snapshot
    summarizer_snapshot = _provider_capability_snapshot(summarizer_provider)
    if summarizer_snapshot is not None:
        base[ProviderKind.summarizer.value] = summarizer_snapshot
    return base
```

Add helper near `_apply_write_rules(...)`:

```python
    async def _prepare_embedding(self, memory: MemoryItem) -> MemoryItem:
        if memory.embedding_vector is not None or not memory.content:
            return memory
        try:
            memory.embedding_vector = await self._embedding_provider.embed_text(memory.content)
            memory.embedding_status = EmbeddingStatus.embedded
        except Exception:
            logger.warning("Embedding provider failed; repository deterministic fallback will be used", exc_info=True)
        return memory
```

Use before each `add_memory(...)` hot/cold path:

```python
        mem = await self._prepare_embedding(mem)
        await self._repo.add_memory(mem)
```

and in `_resolve_and_persist(...)`:

```python
        if result.add is not None:
            result.add = await self._prepare_embedding(result.add)
            await self._repo.add_memory(result.add)
```

If direct assignment to `result.add` is awkward because `ResolveResult` is a dataclass, use a local variable:

```python
        if result.add is not None:
            to_add = await self._prepare_embedding(result.add)
            await self._repo.add_memory(to_add)
            return to_add.memory_id
```

- [x] **Step 7: Run GREEN tests**

Run:

```bash
uv run --extra dev pytest apps/api/tests/runtime/test_memory_runtime_trace.py -k "embedding_provider" -q
uv run --extra dev pytest apps/api/tests/retrieval/test_retrieval_trace.py -k "provider_capabilities or policy" -q
```

Expected: targeted tests pass.

- [x] **Step 8: Run affected retrieval/runtime suite**

Run:

```bash
uv run --extra dev pytest apps/api/tests/runtime/test_memory_runtime_trace.py apps/api/tests/retrieval/test_retrieval_trace.py apps/api/tests/retrieval/test_retrieval_flow.py apps/api/tests/observability/test_replay.py -q
```

Expected: affected suite passes; replay tests may need expected policy version updated to `retrieval-policy-v2` while preserving `policy_snapshot_missing` behavior for old rows.

Observed P4b verification (2026-06-13): targeted RED `uv run --extra dev pytest apps/api/tests/runtime/test_memory_runtime_trace.py apps/api/tests/retrieval/test_retrieval_trace.py apps/api/tests/observability/test_replay.py -k "embedding or query_vector or provider_snapshot_property" -q` -> **6 failed** for the missing behavior; targeted GREEN same command -> **6 passed, 49 deselected**. Review-hardening RED/GREEN covered wrong-dimension provider fallback, frozen provider snapshot, non-finite provider vectors, and explicit summarizer override reflection. Final affected provider/runtime/retrieval/replay suite `uv run --extra dev pytest apps/api/tests/providers/test_embedding_provider.py apps/api/tests/runtime/test_memory_runtime_trace.py apps/api/tests/retrieval/test_retrieval_trace.py apps/api/tests/observability/test_replay.py -q` -> **66 passed**; compile + full regression `uv run --extra dev python -m compileall -q apps/api/app && uv run --extra dev pytest -q` -> **423 passed, 1 skipped**; deterministic benchmark/reproducibility `uv run python -m app.benchmark.runner --output-dir reports && bash scripts/reproduce.sh` -> `acceptance.passed=true (12/12 checks true)`.

### Task P5: Controlled Memory Key Ontology core

**Goal:** Add one source of truth for canonical keys, aliases, cardinality, default memory type/scope, safe free-form handling, and stable prompt rendering.

**Files:**

- Create: `apps/api/app/memory/key_ontology.py`
- Create: `apps/api/tests/memory/test_key_ontology.py`

- [x] **Step 1: Add RED ontology tests**

Create `apps/api/tests/memory/test_key_ontology.py`:

```python
from __future__ import annotations

from app.memory.key_ontology import (
    PROJECT_PACKAGE_MANAGER,
    PROJECT_RUNTIME,
    PROJECT_RUNTIME_EXCLUDED,
    MemoryKeyCardinality,
    is_single_valued_key,
    normalize_memory_key,
    render_llm_extraction_key_prompt,
)


def test_package_manager_is_distinct_canonical_key_from_runtime():
    normalized = normalize_memory_key("project.package_manager")
    assert normalized.key == PROJECT_PACKAGE_MANAGER
    assert normalized.changed is False
    assert normalized.free_form is False
    assert normalized.spec is not None


def test_runtime_alias_normalizes_to_canonical_runtime_key():
    normalized = normalize_memory_key("project.js_runtime")
    assert normalized.key == PROJECT_RUNTIME
    assert normalized.changed is True
    assert normalized.free_form is False
    assert normalized.spec is not None


def test_runtime_cardinality_and_excluded_cardinality():
    assert is_single_valued_key(PROJECT_RUNTIME) is True
    assert is_single_valued_key(PROJECT_PACKAGE_MANAGER) is True
    assert is_single_valued_key("project.package_manager") is True
    excluded = normalize_memory_key(PROJECT_RUNTIME_EXCLUDED)
    assert excluded.spec is not None
    assert excluded.spec.cardinality == MemoryKeyCardinality.multi
    assert is_single_valued_key(PROJECT_RUNTIME_EXCLUDED) is False


def test_unknown_key_without_free_form_is_rejected():
    normalized = normalize_memory_key("project.unknown_concept")
    assert normalized.spec is None
    assert normalized.free_form is False
    assert normalized.warning == "unknown memory key requires free_form=true"


def test_safe_free_form_key_is_allowed_under_known_prefix():
    normalized = normalize_memory_key("user.preference.editor", free_form=True)
    assert normalized.key == "user.preference.editor"
    assert normalized.spec is not None
    assert normalized.spec.key == "user.preference.*"
    assert normalized.spec.memory_type.value == "project"
    assert normalized.spec.scope.value == "workspace"
    assert normalized.free_form is True
    assert normalized.warning is None


def test_secret_like_free_form_key_is_rejected():
    normalized = normalize_memory_key("project.api_key", free_form=True)
    assert normalized.spec is None
    assert normalized.free_form is False
    assert normalized.warning == "unsafe free-form memory key"


def test_free_form_wildcard_key_is_rejected():
    normalized = normalize_memory_key("project.*", free_form=True)
    assert normalized.spec is None
    assert normalized.free_form is False
    assert normalized.warning == "unsafe free-form memory key"


def test_prompt_rendering_is_stable_and_uses_canonical_keys():
    prompt = render_llm_extraction_key_prompt()
    assert '"project.runtime"' in prompt
    assert '"project.package_manager"' in prompt
    assert prompt.index('"project.runtime"') < prompt.index('"project.runtime.excluded"')
    assert "user.preference.*" in prompt
    assert '"tool.command.failed"' not in prompt
```

- [x] **Step 2: Run RED tests**

Run:

```bash
uv run --extra dev pytest apps/api/tests/memory/test_key_ontology.py -q
```

Expected: fail because `app.memory.key_ontology` does not exist.

- [x] **Step 3: Implement ontology module**

Create `apps/api/app/memory/key_ontology.py`:

```python
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from app.runtime.models import MemoryScope, MemoryType


PROJECT_RUNTIME = "project.runtime"
PROJECT_RUNTIME_EXCLUDED = "project.runtime.excluded"
PROJECT_PACKAGE_MANAGER = "project.package_manager"


class MemoryKeyCardinality(str, Enum):
    single = "single"
    multi = "multi"


@dataclass(frozen=True, slots=True)
class MemoryKeySpec:
    key: str
    memory_type: MemoryType
    scope: MemoryScope
    cardinality: MemoryKeyCardinality
    description: str
    aliases: tuple[str, ...] = ()
    excluded_key: str | None = None
    prompt_examples: tuple[str, ...] = ()
    allow_free_form_children: bool = False
    llm_extractable: bool = True


@dataclass(frozen=True, slots=True)
class MemoryKeyNormalization:
    key: str
    spec: MemoryKeySpec | None
    free_form: bool
    changed: bool
    warning: str | None = None


KEY_SPECS: tuple[MemoryKeySpec, ...] = (
    MemoryKeySpec(
        key=PROJECT_RUNTIME,
        memory_type=MemoryType.project,
        scope=MemoryScope.workspace,
        cardinality=MemoryKeyCardinality.single,
        description="JavaScript/runtime choice such as bun/node/deno",
        aliases=("project.js_runtime", "project.node_runtime"),
        excluded_key=PROJECT_RUNTIME_EXCLUDED,
        prompt_examples=("bun", "node", "deno"),
    ),
    MemoryKeySpec(
        key=PROJECT_RUNTIME_EXCLUDED,
        memory_type=MemoryType.project,
        scope=MemoryScope.workspace,
        cardinality=MemoryKeyCardinality.multi,
        description="Umbrella execution-tool exclusions for the current MVP, including runtimes and package managers the project should not use; split package-manager exclusions later only if product semantics require it",
        prompt_examples=("npm", "node", "deno"),
    ),
    MemoryKeySpec(
        key=PROJECT_PACKAGE_MANAGER,
        memory_type=MemoryType.project,
        scope=MemoryScope.workspace,
        cardinality=MemoryKeyCardinality.single,
        description="JavaScript package manager choice",
        aliases=("project.pkg_manager",),
        prompt_examples=("npm", "pnpm", "yarn", "bun"),
    ),
    MemoryKeySpec(
        key="project.language",
        memory_type=MemoryType.project,
        scope=MemoryScope.workspace,
        cardinality=MemoryKeyCardinality.single,
        description="Primary programming language",
        aliases=("project.lang",),
        excluded_key="project.language.excluded",
        prompt_examples=("python", "go", "typescript"),
    ),
    MemoryKeySpec(
        key="project.language.excluded",
        memory_type=MemoryType.project,
        scope=MemoryScope.workspace,
        cardinality=MemoryKeyCardinality.multi,
        description="Programming languages the project should not use",
    ),
    MemoryKeySpec(
        key="project.database",
        memory_type=MemoryType.project,
        scope=MemoryScope.workspace,
        cardinality=MemoryKeyCardinality.single,
        description="Primary database",
        excluded_key="project.database.excluded",
        prompt_examples=("postgres", "mysql", "sqlite"),
    ),
    MemoryKeySpec(
        key="project.database.excluded",
        memory_type=MemoryType.project,
        scope=MemoryScope.workspace,
        cardinality=MemoryKeyCardinality.multi,
        description="Databases the project should not use",
    ),
    MemoryKeySpec(
        key="project.test_framework",
        memory_type=MemoryType.project,
        scope=MemoryScope.workspace,
        cardinality=MemoryKeyCardinality.single,
        description="Preferred test framework",
        prompt_examples=("pytest", "vitest", "jest"),
    ),
    MemoryKeySpec(
        key="project.test_command",
        memory_type=MemoryType.project,
        scope=MemoryScope.workspace,
        cardinality=MemoryKeyCardinality.single,
        description="Preferred test command",
        prompt_examples=("uv run pytest -q", "bun test"),
    ),
    MemoryKeySpec(
        key="project.formatting",
        memory_type=MemoryType.project,
        scope=MemoryScope.workspace,
        cardinality=MemoryKeyCardinality.single,
        description="Formatting or linting tool",
        prompt_examples=("ruff", "prettier", "black"),
    ),
    MemoryKeySpec(
        key="tool.command.failed",
        memory_type=MemoryType.tool_evidence,
        scope=MemoryScope.workspace,
        cardinality=MemoryKeyCardinality.multi,
        description="Failed tool command evidence; run-local identity is carried by MemoryItem.run_id/source ids because MemoryScope has no run enum",
        llm_extractable=False,
    ),
    MemoryKeySpec(
        key="endpoint.current",
        memory_type=MemoryType.project,
        scope=MemoryScope.workspace,
        cardinality=MemoryKeyCardinality.single,
        description="Current endpoint for a capability",
    ),
    MemoryKeySpec(
        key="endpoint.deprecated",
        memory_type=MemoryType.project,
        scope=MemoryScope.workspace,
        cardinality=MemoryKeyCardinality.multi,
        description="Deprecated endpoint marker",
    ),
    MemoryKeySpec(
        key="user.preference.*",
        memory_type=MemoryType.project,
        scope=MemoryScope.workspace,
        cardinality=MemoryKeyCardinality.multi,
        description="Explicit user preference namespace for safe free-form child keys",
        allow_free_form_children=True,
    ),
)

_BY_KEY = {spec.key: spec for spec in KEY_SPECS if not spec.key.endswith(".*")}
_ALIASES = {alias: spec.key for spec in KEY_SPECS for alias in spec.aliases}
_WILDCARD_SPECS = tuple(spec for spec in KEY_SPECS if spec.allow_free_form_children and spec.key.endswith(".*"))
_WILDCARD_PREFIXES = tuple(spec.key[:-1] for spec in KEY_SPECS if spec.allow_free_form_children and spec.key.endswith("*"))
_SAFE_FREE_FORM_PREFIXES = ("project.", "user.preference.", "endpoint.")
_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_][a-z0-9_\-]*)+$")
_SECRET_KEY_TERMS = ("api_key", "apikey", "password", "passwd", "token", "secret", "private_key", "credential")


def canonical_key_specs() -> tuple[MemoryKeySpec, ...]:
    return KEY_SPECS


def normalize_memory_key(key: str, *, free_form: bool = False) -> MemoryKeyNormalization:
    cleaned = (key or "").strip().lower()
    canonical = _ALIASES.get(cleaned, cleaned)
    spec = _BY_KEY.get(canonical)
    if spec is not None:
        return MemoryKeyNormalization(key=spec.key, spec=spec, free_form=False, changed=spec.key != key)
    if not free_form:
        return MemoryKeyNormalization(key=canonical, spec=None, free_form=False, changed=canonical != key, warning="unknown memory key requires free_form=true")
    if not _is_safe_free_form_key(canonical):
        return MemoryKeyNormalization(key=canonical, spec=None, free_form=False, changed=canonical != key, warning="unsafe free-form memory key")
    return MemoryKeyNormalization(key=canonical, spec=_wildcard_spec_for(canonical), free_form=True, changed=canonical != key)


def _wildcard_spec_for(key: str) -> MemoryKeySpec | None:
    for spec in _WILDCARD_SPECS:
        if key.startswith(spec.key[:-1]):
            return spec
    return None


def canonical_memory_key(key: str | None) -> str | None:
    if key is None:
        return None
    return normalize_memory_key(key, free_form=True).key


def same_memory_key_identity(left: str | None, right: str | None) -> bool:
    return canonical_memory_key(left) == canonical_memory_key(right)


def is_single_valued_key(key: str | None) -> bool:
    if not key:
        return False
    normalized = normalize_memory_key(key, free_form=False)
    return normalized.spec is not None and normalized.spec.cardinality == MemoryKeyCardinality.single


def render_llm_extraction_key_prompt() -> str:
    lines: list[str] = []
    for spec in sorted((item for item in KEY_SPECS if item.llm_extractable), key=lambda item: item.key):
        aliases = f" aliases: {', '.join(spec.aliases)}." if spec.aliases else ""
        examples = f" examples: {', '.join(spec.prompt_examples)}." if spec.prompt_examples else ""
        excluded = f" excluded key: {spec.excluded_key}." if spec.excluded_key else ""
        lines.append(
            f'- "{spec.key}" ({spec.cardinality.value}, {spec.memory_type.value}, {spec.scope.value}): '
            f"{spec.description}.{aliases}{excluded}{examples}"
        )
    lines.append('- Unknown durable concepts require "free_form": true and must use a safe dotted key under project.*, endpoint.*, or user.preference.*.')
    return "\n".join(lines)


def _is_safe_free_form_key(key: str) -> bool:
    if not _KEY_RE.match(key):
        return False
    if any(term in key for term in _SECRET_KEY_TERMS):
        return False
    return key.startswith(_SAFE_FREE_FORM_PREFIXES) or key.startswith(_WILDCARD_PREFIXES)
```

- [x] **Step 4: Run GREEN ontology tests**

Run:

```bash
uv run --extra dev pytest apps/api/tests/memory/test_key_ontology.py -q
```

Expected: ontology tests pass.

Observed P5 verification (2026-06-13): RED `uv run --extra dev pytest apps/api/tests/memory/test_key_ontology.py -q` failed with `ModuleNotFoundError: No module named 'app.memory.key_ontology'`; GREEN after implementation -> **8 passed**.

### Task P6: Migrate writer and resolver to ontology

**Goal:** Remove duplicated key constants/cardinality from deterministic writer and resolver, while preserving existing write and conflict behavior.

**Files:**

- Modify: `apps/api/app/memory/writer.py`
- Modify: `apps/api/app/memory/resolver.py`
- Modify: `apps/api/app/runtime/memory_runtime.py`
- Modify: `apps/api/tests/memory/test_writer.py`
- Modify: `apps/api/tests/memory/test_resolver.py`
- Modify: `apps/api/tests/runtime/test_memory_runtime_trace.py`

- [x] **Step 1: Add RED resolver and writer assertions**

Append to `apps/api/tests/memory/test_resolver.py`:

```python
def test_alias_key_conflict_uses_ontology_single_valued_semantics():
    existing = _mem("npm", key="project.pkg_manager", trust=0.6, mid="mem_npm")
    incoming = _mem("pnpm", key="project.package_manager", trust=0.9, mid="mem_pnpm")

    result = resolver.resolve(incoming, [existing])

    assert result.add is incoming
    old = next(u for u in result.updates if u.memory_id == "mem_npm")
    assert old.status == MemoryStatus.superseded
    assert old.superseded_by == "mem_pnpm"


def test_endpoint_current_is_single_valued_but_deprecated_is_multi_valued():
    existing = _mem("/v1/old", key="endpoint.current", trust=0.6, mid="mem_old")
    incoming = _mem("/v1/new", key="endpoint.current", trust=0.9, mid="mem_new")
    result = resolver.resolve(incoming, [existing])
    assert next(u for u in result.updates if u.memory_id == "mem_old").status == MemoryStatus.superseded

    deprecated = _mem("/v1/old", key="endpoint.deprecated", mid="mem_deprecated")
    incoming_deprecated = _mem("/v0/older", key="endpoint.deprecated", mid="mem_deprecated_2")
    result = resolver.resolve(incoming_deprecated, [deprecated])
    assert result.add is incoming_deprecated
    assert result.updates == []
```

Append to `apps/api/tests/memory/test_writer.py`:

```python
from app.memory.key_ontology import PROJECT_RUNTIME, PROJECT_RUNTIME_EXCLUDED


def test_writer_uses_ontology_runtime_keys():
    results = writer.write_from_user_message(_user_event("这个项目使用 Bun，不用 Node.js"))
    keys = {r.memory.key: r.memory.value for r in results}
    assert keys[PROJECT_RUNTIME] == "bun"
    assert keys[PROJECT_RUNTIME_EXCLUDED] == "nodejs"
```

Append to `apps/api/tests/runtime/test_memory_runtime_trace.py`:

```python
async def test_runtime_same_identity_actives_match_historical_alias_keys():
    repo = InMemoryRepository()
    runtime = MemoryRuntime(repo)
    run = await runtime.start_run(StartRunRequest(workspace_id="ws", session_id="s", task="setup"))
    step = await runtime.start_step(StartStepRequest(run_id=run.run_id, intent="setup"))
    await repo.add_memory(
        MemoryItem(
            workspace_id="ws",
            session_id="s",
            run_id=run.run_id,
            memory_type=MemoryType.project,
            key="project.pkg_manager",
            value="npm",
            scope=MemoryScope.workspace,
            content="project.package_manager=npm",
            branch_status=BranchStatus.completed,
            trust_score=0.6,
        )
    )

    await runtime._resolve_and_persist(  # noqa: SLF001 - locks runtime identity behavior
        "ws",
        MemoryItem(
            workspace_id="ws",
            session_id="s",
            run_id=run.run_id,
            memory_type=MemoryType.project,
            key="project.package_manager",
            value="pnpm",
            scope=MemoryScope.workspace,
            content="project.package_manager=pnpm",
            branch_status=BranchStatus.completed,
            trust_score=0.9,
        ),
    )

    memories = await runtime.list_memories(workspace_id="ws")
    old = next(mem for mem in memories if mem.key == "project.pkg_manager")
    assert old.status == MemoryStatus.superseded
```

- [x] **Step 2: Run RED tests**

Run:

```bash
uv run --extra dev pytest apps/api/tests/memory/test_resolver.py apps/api/tests/memory/test_writer.py -q
```

Expected: resolver tests may pass for existing `_SINGLE_VALUED_KEYS` only partly; if they pass, continue because production duplication still must be removed.

- [x] **Step 3: Modify resolver to derive cardinality from ontology**

Modify `apps/api/app/memory/resolver.py` imports:

```python
from app.memory.key_ontology import is_single_valued_key
```

Remove `_SINGLE_VALUED_KEYS` and replace:

```python
    if is_single_valued_key(incoming.key) and diff:
```

- [x] **Step 4: Modify writer to use ontology constants**

Modify `apps/api/app/runtime/memory_runtime.py` imports:

```python
from app.memory.key_ontology import canonical_memory_key, same_memory_key_identity
```

Update `_same_identity_actives(...)` so existing active rows written with known aliases still participate in dedup/conflict resolution after incoming keys canonicalize:

```python
                and same_memory_key_identity(mem.key, incoming.key)
                and mem.scope.value == incoming.scope.value
```

Update `_supersede_keys(...)` to canonicalize requested key identities before comparing:

```python
        wanted = {(canonical_memory_key(key), scope) for key, scope in keys}
```

and compare with:

```python
            if (canonical_memory_key(mem.key), mem.scope.value) in wanted:
```

Modify `apps/api/app/memory/writer.py` imports:

```python
from app.memory.key_ontology import PROJECT_RUNTIME, PROJECT_RUNTIME_EXCLUDED
```

Replace hard-coded runtime keys:

```python
        mem = _project_memory(event, key=PROJECT_RUNTIME, value=new_rt, content=content)
        results.append(MemoryWriteResult(mem, supersede_keys=[(PROJECT_RUNTIME, MemoryScope.workspace.value)]))
```

```python
                        _project_memory(event, key=PROJECT_RUNTIME, value=rt, content=content)
```

```python
                            key=PROJECT_RUNTIME_EXCLUDED,
```

```python
    excluded = {r.memory.value for r in results if r.memory.key == PROJECT_RUNTIME_EXCLUDED}
```

```python
            if not (r.memory.key == PROJECT_RUNTIME and r.memory.value in excluded)
```

- [x] **Step 5: Run GREEN tests**

Run:

```bash
uv run --extra dev pytest apps/api/tests/memory/test_resolver.py apps/api/tests/memory/test_writer.py apps/api/tests/memory/test_key_ontology.py -q
uv run --extra dev pytest apps/api/tests/runtime/test_memory_runtime_trace.py -k "historical_alias" -q
```

Expected: memory ontology/writer/resolver tests pass, and the runtime alias identity regression passes before waiting for the broader P10 runtime suite.

Observed P6 verification (2026-06-13): targeted RED `uv run --extra dev pytest apps/api/tests/memory/test_resolver.py apps/api/tests/memory/test_writer.py apps/api/tests/runtime/test_memory_runtime_trace.py -k "alias_key_conflict or endpoint_current or ontology_runtime_keys or historical_alias" -q` -> **2 failed / 2 passed** for missing endpoint cardinality and runtime alias identity; targeted GREEN with ontology/writer/resolver/runtime tests -> **12 passed, 48 deselected**.

### Task P7: LLM extraction ontology normalization and prompt rendering

**Goal:** Enforce controlled key schema at the LLM extraction boundary: aliases canonicalize, unknown non-free-form keys drop, safe explicit free-form keys pass, and system prompt is rendered from ontology.

**Files:**

- Modify: `apps/api/app/memory/llm_extractor.py`
- Modify: `apps/api/tests/memory/test_llm_extractor.py`
- Modify: `apps/api/tests/memory/test_llm_provider.py`

- [x] **Step 1: Add RED extractor tests**

Append to `apps/api/tests/memory/test_llm_extractor.py`:

```python
from app.memory.llm_extractor import ExtractionCandidate, build_results, _SYSTEM_PROMPT


def test_build_results_normalizes_alias_key_to_canonical_package_manager(user_event):
    results = build_results(user_event("use pnpm"), [ExtractionCandidate(key="project.pkg_manager", value="pnpm")])
    assert len(results) == 1
    assert results[0].memory.key == "project.package_manager"
    assert results[0].memory.value == "pnpm"


def test_build_results_uses_ontology_type_and_scope_for_controlled_key(user_event):
    results = build_results(
        user_event("current endpoint is /v2/users"),
        [ExtractionCandidate(key="endpoint.current", value="/v2/users", memory_type="episodic", scope="session")],
    )
    assert len(results) == 1
    assert results[0].memory.memory_type.value == "project"
    assert results[0].memory.scope.value == "workspace"


def test_build_results_drops_unknown_non_free_form_key(user_event):
    results = build_results(user_event("remember custom"), [ExtractionCandidate(key="project.unknown_concept", value="x")])
    assert results == []


def test_build_results_allows_safe_explicit_free_form_key(user_event):
    results = build_results(
        user_event("prefer vim"),
        [ExtractionCandidate(key="user.preference.editor", value="vim", free_form=True, memory_type="episodic", scope="session")],
    )
    assert len(results) == 1
    assert results[0].memory.key == "user.preference.editor"
    assert results[0].memory.value == "vim"
    assert results[0].memory.memory_type.value == "project"
    assert results[0].memory.scope.value == "workspace"


def test_build_results_rejects_secret_like_free_form_key(user_event):
    results = build_results(
        user_event("secret"),
        [ExtractionCandidate(key="project.api_key", value="abc", free_form=True)],
    )
    assert results == []


def test_system_prompt_contains_ontology_rendered_controlled_keys():
    assert '"project.runtime"' in _SYSTEM_PROMPT
    assert '"endpoint.current"' in _SYSTEM_PROMPT
    assert "free_form" in _SYSTEM_PROMPT
```

If `test_llm_extractor.py` does not have `user_event`, add:

```python
def user_event(content: str) -> AgentEvent:
    return AgentEvent(workspace_id="ws", run_id="r", step_id="s", role=EventRole.user, event_type=EventType.message, content=content)
```

- [x] **Step 2: Run RED tests**

Run:

```bash
uv run --extra dev pytest apps/api/tests/memory/test_llm_extractor.py -q
```

Expected: tests fail because `free_form` does not exist and unknown keys are currently accepted.

- [x] **Step 3: Add `free_form` to ExtractionCandidate and render prompt from ontology**

Modify `apps/api/app/memory/llm_extractor.py` imports:

```python
from app.memory.key_ontology import normalize_memory_key, render_llm_extraction_key_prompt
```

Update `ExtractionCandidate`:

```python
    free_form: bool = False
```

Replace controlled key section in `_SYSTEM_PROMPT` with ontology rendering:

```python
_SYSTEM_PROMPT = f"""You extract durable memory facts from a single user message in an AI coding-agent session.

Return ONLY a JSON object with a single key "candidates" whose value is a JSON array.
Each array item is an object with exactly these fields:
- "key": a stable dotted identifier (see the controlled key rules below).
- "value": the extracted value, lowercased and normalized, e.g. "bun", "npm", "postgres".
- "memory_type": one of "project", "episodic", "procedural", "working_state". Default "project".
- "scope": one of "workspace", "session", "user". Default "workspace".
- "supersede": true if this fact explicitly corrects/replaces a previous preference, else false.
- "confidence": a float in [0,1].
- "free_form": true only when no controlled key matches and the key is a safe durable dotted key.

Controlled keys:
{render_llm_extraction_key_prompt()}

Rules:
- Extract only durable preferences, project constraints, and explicit corrections.
- When the user switches to a different choice for the same concept, emit the controlled key with the new value and set "supersede": true so the old value is retired.
- Do NOT invent facts. If the message contains nothing durable, return {{"candidates": []}}.
- Output JSON only, no prose, no markdown fences."""
```

- [x] **Step 4: Normalize keys in `build_results(...)`**

Inside `build_results(...)`, replace the validated-list construction with explicit normalization:

```python
    validated: list[ExtractionCandidate] = []
    for raw in candidates:
        candidate = _validate(raw)
        if candidate is None:
            continue
        normalized = normalize_memory_key(candidate.key, free_form=candidate.free_form)
        if normalized.spec is None and not normalized.free_form:
            continue
        updates = {"key": normalized.key, "free_form": normalized.free_form}
        if normalized.spec is not None:
            updates["memory_type"] = normalized.spec.memory_type
            updates["scope"] = normalized.spec.scope
        validated.append(candidate.model_copy(update=updates))
    validated.sort(key=_sort_key)
```

When constructing `MemoryItem`, use `candidate.key` after normalization and preserve existing risk flag / content behavior.

- [x] **Step 5: Update LLM provider tests for free_form schema tolerance**

Modify `apps/api/tests/memory/test_llm_provider.py` expected request/prompt assertions only if they compare exact prompt text. Add a mocked provider response with `free_form=True`:

```python
async def test_extract_preserves_free_form_flag():
    def handler(request: httpx.Request) -> httpx.Response:
        return _chat_response([{"key": "user.preference.editor", "value": "vim", "free_form": True}])

    provider = _provider(handler)
    candidates = await provider.extract(_user_event("prefer vim"))
    assert candidates[0].free_form is True
```

- [x] **Step 6: Run GREEN extractor tests**

Run:

```bash
uv run --extra dev pytest apps/api/tests/memory/test_llm_extractor.py apps/api/tests/memory/test_llm_provider.py apps/api/tests/runtime/test_llm_extraction_flow.py -q
```

Expected: extraction tests pass; runtime fallback behavior unchanged.

Observed P7 verification (2026-06-13): RED `uv run --extra dev pytest apps/api/tests/memory/test_llm_extractor.py -q` -> **6 failed / 6 passed** for missing alias normalization, ontology default overrides, unknown/free-form filtering, and ontology-rendered prompt; GREEN `uv run --extra dev pytest apps/api/tests/memory/test_llm_extractor.py apps/api/tests/memory/test_llm_provider.py apps/api/tests/runtime/test_llm_extraction_flow.py -q` -> **28 passed**. Initial affected P5-P7 memory/runtime suite -> **116 passed**. Post-review hardening RED `uv run --extra dev pytest apps/api/tests/memory/test_writer.py apps/api/tests/memory/test_resolver.py apps/api/tests/memory/test_llm_extractor.py apps/api/tests/runtime/test_memory_runtime_trace.py -k "package_manager or canonical_key or project_free_form" -q` -> **5 failed / 1 passed** for package-manager/runtime split, same-value alias canonical survivor, and arbitrary safe free-form defaults; GREEN after fixes -> **6 passed, 63 deselected**. Final affected memory/runtime suite -> **121 passed**.

### Task P8: Benchmark deterministic registry and provider conformance

**Goal:** Guarantee benchmark/reproducibility never use network providers, and provider metadata is visible in access policy snapshots.

**Files:**

- Modify: `apps/api/app/benchmark/runner.py`
- Modify: `apps/api/tests/benchmark/test_runner.py`
- Modify: `apps/api/tests/conformance/test_strategy_conformance.py`
- Modify: `apps/api/tests/conformance/test_replay_conformance.py`

- [x] **Step 1: Add RED benchmark deterministic provider test**

Append to `apps/api/tests/benchmark/test_runner.py`:

```python
async def test_run_case_uses_deterministic_provider_registry_even_when_real_providers_are_configured(monkeypatch):
    monkeypatch.setenv("MEMTRACE_LLM_EXTRACTION_ENABLED", "true")
    monkeypatch.setenv("MEMTRACE_LLM_API_KEY", "sk-test")
    monkeypatch.setenv("MEMTRACE_EMBEDDING_PROVIDER", "openai")
    monkeypatch.setenv("MEMTRACE_EMBEDDING_API_KEY", "sk-embedding")

    repo = InMemoryRepository()
    await _run_case(CASES[0], "ws_benchmark_provider", repo=repo)
    accesses = await repo.list_access_logs(workspace_id="ws_benchmark_provider")

    assert accesses
    for access in accesses:
        providers = access.policy_snapshot["providers"]
        assert providers["embedding"]["deterministic"] is True
        assert providers["embedding"]["requires_network"] is False
        assert providers["summarizer"]["deterministic"] is True
```

- [x] **Step 2: Run RED benchmark test**

Run:

```bash
uv run --extra dev pytest apps/api/tests/benchmark/test_runner.py -k "deterministic_provider_registry" -q
```

Expected: fail before provider snapshots exist; after Task P4 it may already pass through `MemoryRuntime`'s deterministic default. Still apply Step 3 so benchmark isolation is explicit at the call site and never depends on settings-based registry construction.

- [x] **Step 3: Wire deterministic registry in benchmark runner**

Modify `apps/api/app/benchmark/runner.py` imports:

```python
from app.providers.factory import deterministic_provider_registry
```

Change `_run_case(...)` runtime construction:

```python
    runtime = MemoryRuntime(
        repo,
        default_workspace_id=workspace_id,
        provider_registry=deterministic_provider_registry(),
    )
```

- [x] **Step 4: Add conformance assertion for non-secret provider snapshot**

Append to `apps/api/tests/conformance/test_strategy_conformance.py` or `test_replay_conformance.py`:

```python
async def test_access_policy_provider_snapshot_is_non_secret(runtime):
    run = await runtime.start_run(StartRunRequest(workspace_id="ws_test", session_id="s", task="setup"))
    step = await runtime.start_step(StartStepRequest(run_id=run.run_id, intent="setup"))
    await runtime.write_event(WriteEventRequest(run_id=run.run_id, step_id=step.step_id, role=EventRole.user, event_type=EventType.message, content="用 Bun"))
    ctx = await runtime.retrieve_context(RetrievalRequest(run_id=run.run_id, query="bun", strategy=RetrievalStrategy.variant_2))
    inspection = await runtime.inspect_access(ctx.access_id)

    snapshot_text = str(inspection.policy_snapshot["providers"])
    assert "api_key" not in snapshot_text
    assert "sk-" not in snapshot_text
    assert inspection.policy_snapshot["providers"]["embedding"]["provider_id"]
    assert "judge" not in inspection.policy_snapshot["providers"]
```

- [x] **Step 5: Run GREEN benchmark/conformance tests**

Run:

```bash
uv run --extra dev pytest apps/api/tests/benchmark/test_runner.py -k "deterministic_provider_registry" -q
uv run --extra dev pytest apps/api/tests/conformance -q
```

Expected: provider-specific benchmark test and conformance suite pass.

Observed P8 verification (2026-06-13): RED `uv run --extra dev pytest apps/api/tests/benchmark/test_runner.py -k "provider" -q` -> **1 failed / 1 passed / 22 deselected** because `_run_case(...)` constructed `MemoryRuntime` without an explicit `provider_registry`. GREEN after wiring `deterministic_provider_registry()` into benchmark runtime construction -> **2 passed, 22 deselected**. Affected provider/benchmark/replay suite `uv run --extra dev pytest apps/api/tests/benchmark/test_runner.py apps/api/tests/providers apps/api/tests/retrieval/test_retrieval_trace.py apps/api/tests/observability/test_replay.py -q` -> **70 passed**; compile of affected modules passed. Added conformance coverage for non-secret, retrieval-relevant provider snapshots -> `apps/api/tests/conformance/test_strategy_conformance.py -q` **13 passed**.

### Task P9: JudgeProvider contract only

**Goal:** Represent ROADMAP §10's `JudgeProvider` family in the registry without adding LLM judge behavior or changing deterministic evaluator semantics.

**Files:**

- Create: `apps/api/app/providers/judge.py`
- Modify: `apps/api/app/providers/factory.py`
- Modify: `apps/api/app/providers/__init__.py`
- Create: `apps/api/tests/providers/test_judge_provider_contract.py`
- Modify: `apps/api/tests/providers/test_registry.py`

- [x] **Step 1: Add RED contract test**

Create `apps/api/tests/providers/test_judge_provider_contract.py`:

```python
from __future__ import annotations

from app.providers.base import ProviderCapabilities, ProviderKind
from app.providers.judge import NoopJudgeProvider


async def test_noop_judge_provider_has_capability_metadata_and_no_network():
    provider = NoopJudgeProvider()

    assert provider.capabilities == ProviderCapabilities(
        provider_id="judge.noop.v1",
        kind=ProviderKind.judge,
        deterministic=True,
        requires_network=False,
    )
    assert await provider.judge({"case_id": "case_1"}) == {"decision": "not_configured"}
```

- [x] **Step 2: Run RED test**

Run:

```bash
uv run --extra dev pytest apps/api/tests/providers/test_judge_provider_contract.py -q
```

Expected: fail because `app.providers.judge` does not exist.

- [x] **Step 3: Implement no-op judge provider**

Create `apps/api/app/providers/judge.py`:

```python
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from app.providers.base import ProviderCapabilities, ProviderKind


@runtime_checkable
class JudgeProvider(Protocol):
    capabilities: ProviderCapabilities

    async def judge(self, payload: dict[str, Any]) -> dict[str, Any]: ...


class NoopJudgeProvider:
    def __init__(self) -> None:
        self.capabilities = ProviderCapabilities(
            provider_id="judge.noop.v1",
            kind=ProviderKind.judge,
            deterministic=True,
            requires_network=False,
        )

    async def judge(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {"decision": "not_configured"}
```

- [x] **Step 4: Export judge provider contract**

Modify `apps/api/app/providers/__init__.py`:

```python
from app.providers.judge import JudgeProvider, NoopJudgeProvider
```

Add both names to `__all__`.

- [x] **Step 4b: Register no-op judge in deterministic registry** — completed after Task P3 factory creation; `deterministic_provider_registry(...)` now registers `NoopJudgeProvider`.

Modify `apps/api/app/providers/factory.py` imports:

```python
from app.providers.judge import NoopJudgeProvider
```

In `deterministic_provider_registry(...)`, after registering the rule summarizer, add:

```python
    judge = NoopJudgeProvider()
    registry.register(ProviderKind.judge, judge, judge.capabilities)
```

Append to `apps/api/tests/providers/test_registry.py`:

```python
from app.providers.judge import NoopJudgeProvider


def test_deterministic_registry_includes_noop_judge_family():
    registry = deterministic_provider_registry(embedding_dim=256)
    snapshot = registry.snapshot()

    assert isinstance(registry.get(ProviderKind.judge), NoopJudgeProvider)
    assert snapshot["judge"]["provider_id"] == "judge.noop.v1"
    assert snapshot["judge"]["requires_network"] is False
```

- [x] **Step 5: Run GREEN test**

Run:

```bash
uv run --extra dev pytest apps/api/tests/providers/test_judge_provider_contract.py apps/api/tests/providers/test_registry.py -q
```

Expected: contract and registry-family tests pass.

### Task P10: Full affected regression and docs/project-memory closeout

**Goal:** Verify provider/ontology changes end-to-end, mark ROADMAP §10/§11 complete for this slice, and sync `.ai` project memory.

**Files:**

- Modify: `docs/design/ROADMAP.md`
- Modify: `.ai/PROJECT_STATE.md`
- Modify: `.ai/REQUIREMENTS.md`
- Modify: `.ai/IMPLEMENTATION_PLAN.md`
- Modify: `.ai/PITFALLS.md`
- Optionally modify: `AGENTS.md` only if current-priority wording changes after this slice finishes.

- [x] **Step 1: Run provider/ontology affected suite**

Run:

```bash
uv run --extra dev pytest apps/api/tests/providers apps/api/tests/memory/test_key_ontology.py apps/api/tests/memory/test_llm_extractor.py apps/api/tests/memory/test_llm_provider.py apps/api/tests/memory/test_resolver.py apps/api/tests/memory/test_writer.py -q
```

Expected: provider and memory ontology suites pass.

- [x] **Step 2: Run retrieval/runtime/replay affected suite**

Run:

```bash
uv run --extra dev pytest apps/api/tests/runtime/test_memory_runtime_trace.py apps/api/tests/runtime/test_llm_extraction_flow.py apps/api/tests/runtime/test_summarizer_fallback.py apps/api/tests/retrieval/test_similarity.py apps/api/tests/retrieval/test_retrieval_trace.py apps/api/tests/retrieval/test_retrieval_flow.py apps/api/tests/observability/test_replay.py -q
```

Expected: runtime/retrieval/replay tests pass with policy version `retrieval-policy-v2` expectations updated.

- [x] **Step 3: Run benchmark/conformance/reproducibility guard tests**

Run:

```bash
uv run --extra dev pytest apps/api/tests/benchmark/test_runner.py apps/api/tests/conformance apps/api/tests/integration/test_reproducibility.py -q
```

Expected: benchmark rows and reproducibility guard still pass; real provider env monkeypatch test proves deterministic benchmark override.

- [x] **Step 4: Run compile and full regression**

Run:

```bash
uv run --extra dev python -m compileall -q apps/api/app packages/python-sdk/src examples
uv run --extra dev pytest -q
```

Expected: compile succeeds and full pytest suite passes.

- [x] **Step 5: Run deterministic benchmark and reproduce script**

Run:

```bash
uv run python -m app.benchmark.runner --output-dir reports
bash scripts/reproduce.sh
```

Expected: benchmark writes reports and reproduce script prints `acceptance.passed=true (12/12 checks true)` unless a future benchmark task intentionally changes acceptance count in the same implementation branch.

- [x] **Step 6: Update ROADMAP §10 and §11**

In `docs/design/ROADMAP.md`:

- Mark Provider abstraction family complete for extraction/summarizer/embedding and contract-only judge.
- Mark capability metadata complete and note benchmark deterministic override.
- Mark key ontology table complete and note code-defined source registry.
- Mark extraction-side validation/normalization complete.
- Mark ontology-as-single-truth complete for writer/resolver/LLM prompt.
- Leave real LLM judge behavior, storage-backed ontology administration, and any larger governance under their existing deferred roadmap sections.

- [x] **Step 7: Update `.ai` project memory**

In `.ai/PROJECT_STATE.md`, add a new “Implemented (ROADMAP §10/§11 Provider Registry + Key Ontology)” section with:

- Date.
- Files changed.
- Provider registry behavior.
- Key ontology behavior.
- Verification command outputs.
- Next recommended action.

In `.ai/REQUIREMENTS.md` and `.ai/IMPLEMENTATION_PLAN.md`, update current selected target away from §10/§11 after implementation completes.

In `.ai/PITFALLS.md`, add provider/ontology traps:

- capability metadata must stay non-secret;
- benchmark must force deterministic providers;
- ontology prompt/resolver/writer must stay derived from one registry;
- repository deterministic embedding fallback must remain for direct seeded memories.

- [x] **Step 8: Inspect git diff before handoff**

Run:

```bash
git status --short
git diff -- docs/design/ROADMAP.md .ai/PROJECT_STATE.md .ai/REQUIREMENTS.md .ai/IMPLEMENTATION_PLAN.md .ai/PITFALLS.md
```

Expected: source/test/doc changes are intentional; generated `reports/` artifacts remain ignored.

---

## 6. Acceptance criteria

- Default local runtime still works with no provider-related env vars.
- `ProviderRegistry.snapshot()` is stable and contains no secrets.
- Access policy snapshots use `retrieval-policy-v2` and include provider capability snapshots.
- OpenAI-compatible embedding provider validates endpoint shape and vector dimension, and failure degrades to deterministic embeddings at runtime write/query call sites.
- `Repository.add_memory(...)` still backfills deterministic embeddings for direct seeded memories.
- Benchmark runner uses deterministic provider registry even when real-provider env vars are configured.
- `writer`, `resolver`, and `llm_extractor` no longer duplicate runtime-key/cardinality/prompt rules.
- LLM candidate aliases canonicalize; unknown non-free-form keys drop; safe explicit free-form keys pass; secret-like free-form keys drop.
- Full regression passes; benchmark and reproduce script keep `acceptance.passed=true`.

## 7. Risk checklist

- **API key leakage risk:** search provider snapshots and policy snapshots for `sk-`, `api_key`, `authorization`, `token`, `password`, and `secret` after implementation.
- **pgvector dimension risk:** real embedding provider results must be validated against the fixed 256-dimensional pgvector column; this plan does not change the column dimension. Wrong-dimension provider results must fall back to deterministic `stable_embedding(..., 256)` rather than reaching repository/SQL writes or vector search.
- **benchmark nondeterminism risk:** benchmark runtime construction must not call `build_provider_registry(get_settings())`.
- **import-cycle risk:** `providers.registry` must not import provider implementations or settings; `providers.factory` owns settings-based wiring; `providers.base` must stay dependency-light; `key_ontology` must not import writer/resolver/extractor.
- **historical alias risk:** runtime identity lookup and resolver must treat known aliases such as `project.pkg_manager` as the same single-valued concept even before all old rows are canonicalized.
- **policy snapshot relevance risk:** retrieval access policy snapshots must include only retrieval-relevant providers (`embedding`, `summarizer`) and must reflect actual explicit provider overrides; registry-only families such as `judge` must not change retrieval policy hashes.
- **policy drift risk:** replay tests should expect policy drift only through policy snapshot hash/version, not through candidate/context data drift.
- **settings-derived provider dimension risk:** settings-based provider construction must remain pinned to the fixed `EMBED_DIM=256` storage/search contract unless a separate pgvector migration lands; do not let `MEMTRACE_EMBEDDING_DIM` create non-256 provider snapshots/vectors that hot paths immediately reject.
- **dual-use correction token risk:** correction rules must use old-key context for dual-use tokens such as `bun`; `npm -> bun` is a package-manager correction and must supersede `project.package_manager`, while `Node.js -> Bun` remains a runtime correction.

## 8. Implementation status

Implementation complete through P10 (2026-06-13). Completed: P1/P2/P9 provider-only infrastructure, P3 settings-based factory/DI/runtime registry injection, P4 runtime/retrieval/replay provider integration, P5 key ontology core, P6 writer/resolver/runtime ontology migration, P7 LLM extraction ontology normalization, P8 benchmark deterministic registry + provider conformance, and P10 full regression/reproducibility/project-memory closeout. Final review hardening fixed settings-derived embedding providers to the fixed 256-dim pgvector contract, package-manager correction semantics (`npm -> bun`), ontology schema coverage, and summarizer provider factory wiring. Final verification: affected provider/ontology/runtime/retrieval/replay/benchmark/conformance suite **322 passed**; compile passed; deterministic benchmark passed; `bash scripts/reproduce.sh` printed `acceptance.passed=true (12/12 checks true)`; full `uv run --extra dev pytest -q` -> **460 passed, 1 skipped**.
