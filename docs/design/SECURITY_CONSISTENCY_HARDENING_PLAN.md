# Security & Consistency Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete ROADMAP §13 security and consistency hardening so MemTrace's existing trace-first, replayable runtime guarantees hold under unsafe memory, backend adapters, concurrency, timeout, replay, schema drift, and future provider/ontology/scheduler extensions.

**Architecture:** Keep the public `MemoryRuntime` facade as the single semantic boundary. Harden the existing retrieval/gate/packer/replay/storage paths instead of adding alternate code paths; then freeze those invariants into a conformance suite and policy snapshot so future §10 Provider Registry, §11 Key Ontology, and §3.2 Reflection/Forgetting work cannot bypass lifecycle, gate, redaction, replay, or backend-equivalence contracts.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.0 async, Alembic, PostgreSQL/pgvector, `uv`, pytest, httpx ASGITransport, existing `memtrace-sdk` package.

***

## 0. Evaluation Summary

This plan expands ROADMAP §13 and §1.1 into executable implementation tasks. The source findings are already catalogued in `docs/design/ROADMAP.md:32` and `docs/design/ROADMAP.md:255`; this file is the implementation-grade plan for that backlog.

### Source high-risk gaps verified in code at plan creation

Status update (2026-06-13): H1-H18 are complete and post-review hardened. The first three findings below are closed by packer-level positive redaction, `variant_1` gate convergence plus non-bypassable quarantine/secret/destructive/tool-sensitive safety floors, and default-off lightweight API auth; review hardening also covers retained-fact key redaction and non-ASCII invalid-token handling. H4-H6 close backend isomorphism, atomic event append, and timeout persistence; H13 closes state-tree boundary corruption. H7-H10 close deterministic gate/replay ordering, ORM/migration compaction-index drift, retrieval policy snapshot/drift classification, and the initial conformance suite. H11/H12/H14 close token-budget precision, structured summarizer provenance validation with exact top-level source preservation, and whole-memory benchmark fairness snapshots with created/missing-memory guards. H15-H18 close migration compatibility policy, redacted trace bundle export/validation, deterministic dogfood harnesses, and docs/project-memory closeout.

1. **\[Closed by H1] Positive context packing lacks defense-in-depth redaction.** `pack_context(...)` constructed positive blocks directly from `mem.content` / `mem.summary`; H1 now applies `redact()` before prompt context rendering.
2. **\[Closed by H2]** **`variant_1`** **over-disables the gate, and quarantine is not yet non-bypassable.** H2 keeps hard/risk policy enabled for `variant_1` and rejects quarantined memory before strategy-specific toggles.
3. **\[Closed by H3] API key support is currently transport decoration.** H3 adds default-off `/v1` auth dependency using Bearer or `X-API-Key` when enabled.
4. **SQL sequence allocation is not atomic with insertion.** `next_sequence_no(...)` commits after `SELECT max+1` in `apps/api/app/storage/sql_repository.py:449`, while `add_event(...)` inserts in a later transaction in `apps/api/app/storage/sql_repository.py:460`.
5. **Retrieval timeout paths diverge.** `retrieve(...)` returns an unpersisted `access_id` on timeout in `apps/api/app/retrieval/controller.py:119`; `retrieve_with_prelude(...)` persists a minimal access in `apps/api/app/retrieval/controller.py:142`.
6. **Backend error semantics still differ.** Route-level replay existence checks read `rt._repo` in `apps/api/app/api/routes.py:150`, while in-process `replay_access(...)` delegates directly from `packages/python-sdk/src/memtrace_sdk/backends.py:178`.
7. **Gate logs and replay order need deterministic tie-breaks.** SQL orders gate logs only by `created_at` in `apps/api/app/storage/sql_repository.py:581`; in-memory preserves append order in `apps/api/app/runtime/repository.py:301`.
8. **ORM metadata and Alembic migration drift.** ORM declares a single-column workspace index in `apps/api/app/storage/orm.py:222`, but migration `0005_context_compaction` creates `(workspace_id, created_at)` in `migrations/versions/0005_context_compaction.py:43`.
9. **Token budgeting reuses retrieval tokenization.** `estimate_tokens(...)` calls the stopword-pruning retrieval tokenizer in `apps/api/app/retrieval/packer.py:32`, which is unsuitable for budget closure and CJK truncation.
10. **Summarizer provenance validation is too narrow.** `_validate_source_ids(...)` does not seed allowed ids from `must_retain_facts` provenance in `apps/api/app/memory/summarizer_provider.py:271`.
11. **State-tree edge cases are under-specified.** `apply_finish(...)` ignores `StepStatus.rolled_back` in `apps/api/app/runtime/state_tree.py:91`, and `finish_step(...)` can return a ghost `StateNode` when the persisted node is missing in `apps/api/app/runtime/memory_runtime.py:312`.
12. **Benchmark fairness snapshot is too narrow.** The runner currently restores `access_count` only; future reflection scheduler fields would silently affect later strategies.
13. **Replay does not persist retrieval policy contracts.** `MemoryAccessLog` records strategy and top-k/budget but not gate config, packer config, lifecycle filter version, provider determinism, or policy hash.

### Recommended implementation order

1. **Batch A1 — Safety-floor closure:** H1 positive redaction + H2 `variant_1` gate contract. This establishes the non-bypassable rule that benchmark strategies may relax relevance/state/branch semantics but cannot bypass workspace/lifecycle/redaction/safety invariants.
2. **Batch A2 — Lightweight auth:** H3 default-off API token gate.
3. **Batch B1 — Runtime error/state boundaries:** H4 backend error isomorphism + H13 state-machine boundary hardening.
4. **Batch B2 — Atomic event append:** H5 repository protocol + SQL sequence uniqueness/concurrency.
5. **Batch B3 — Timeout semantics:** H6 unified timeout persistence, implemented independently because timeout cancellation semantics are subtle.
6. **Batch C — Determinism/schema alignment (§13.2 medium):** H7 gate ordering + H8 ORM/migration index alignment.
7. **Batch D1 — Policy snapshot:** H9 access-level retrieval policy snapshot and policy-drift classification.
8. **Batch D2 — Conformance suite:** H10 layered runtime invariant tests after policy drift exists.
9. **Batch E1 — Benchmark fairness:** H14 whole-memory benchmark snapshot before token/precision changes perturb benchmark numbers.
10. **Batch E2 — Precision/robustness:** H11 independent token estimation + H12 summarizer provenance.
11. **Batch F — Remaining runtime hardening (§13.4):** H15 migration compatibility policy, H16 redacted trace bundle export/validation, H17 dogfood harness.
12. **Batch G — Documentation/project-memory sync:** H18 closeout.

### Scope intentionally excluded from this plan

- Full RBAC/JWT/workspace membership/quota/admin governance; that remains ROADMAP §3.4. H3 implements only ADR-016's lightweight token gate.
- Redis/Celery, Redis locks, async task queues, and multi-worker candidate-buffer redesign.
- Real Reflection/Forgetting scheduler; H14 only hardens benchmark fairness before that future work.
- Provider Registry (§10), Controlled Memory Key Ontology (§11), ES/Neo4j, LoCoMo/MemoryArena, React dashboard.
- Any hosted/public deployment assumptions beyond local default-off auth.

***

## 1. File Structure / Responsibility Map

### Existing files to modify

- `apps/api/app/retrieval/packer.py` — positive redaction, independent token estimator, CJK-safe truncation, protected negative evidence priority.
- `apps/api/app/retrieval/gate.py` — strategy contract for `variant_1`, risk/hard policy invariants.
- `apps/api/app/retrieval/controller.py` — timeout behavior, atomic persistence boundary, policy snapshot creation, deterministic accepted ordering.
- `apps/api/app/retrieval/policy.py` — new focused module for `RetrievalPolicySnapshot` helpers if H9 would otherwise bloat `controller.py`.
- `apps/api/app/memory/secrets.py` — reused redaction API; extend only if tests uncover missing pattern during H1.
- `apps/api/app/memory/summarizer_provider.py` — provenance allow-set fix.
- `apps/api/app/runtime/models.py` — auth-free domain DTOs plus policy snapshot model and `MemoryAccessLog` schema additions.
- `apps/api/app/runtime/repository.py` — Repository protocol updates, InMemory atomic event append, deterministic gate-log ordering, benchmark snapshot helpers if kept repository-local.
- `apps/api/app/runtime/state_tree.py` — explicit rolled\_back finish mapping.
- `apps/api/app/runtime/memory_runtime.py` — event append wiring, `StateTreeError` boundary, replay existence downshift, state-node ghost-node removal.
- `apps/api/app/api/deps.py` — lightweight auth dependency.
- `apps/api/app/api/routes.py` — router-level auth dependency and exception mapping cleanup.
- `apps/api/app/config.py` — default-off auth settings.
- `apps/api/app/storage/orm.py` — sequence unique index, access-log policy fields, compaction index alignment.
- `apps/api/app/storage/sql_repository.py` — atomic event insert, deterministic gate-log order.
- `apps/api/app/observability/replay.py` — policy drift classification and deterministic tie-breaks.
- `apps/api/app/observability/reports.py` — trace bundle reuse and redacted export guardrails.
- `apps/api/app/benchmark/runner.py` — whole-memory benchmark snapshot/restore.
- `packages/python-sdk/src/memtrace_sdk/backends.py` — in-process error mapping for `StateTreeError` and replay existence semantics.
- `packages/python-sdk/src/memtrace_sdk/cli.py` — trace-bundle command and auth smoke coverage if H16 includes CLI.
- `docs/design/ROADMAP.md` — tick/annotate completed §13 tasks after implementation.
- `.ai/PROJECT_STATE.md`, `.ai/REQUIREMENTS.md`, `.ai/IMPLEMENTATION_PLAN.md`, `.ai/PITFALLS.md` — update after meaningful implementation batches.

### New files to create only when their batch starts

- `migrations/versions/0006_security_consistency_hardening.py` — event sequence unique index and/or access-log policy snapshot fields if H5/H9 are implemented in one migration. If H5 and H9 are separated, create one migration per merged batch.
- `apps/api/tests/api/test_auth.py` — auth dependency tests.
- `apps/api/tests/conformance/test_strategy_conformance.py` — strategy invariants.
- `apps/api/tests/conformance/test_backend_conformance.py` — backend equivalence harness, importing existing SDK helpers when possible.
- `apps/api/tests/conformance/test_replay_conformance.py` — replay side-effect and policy/data drift invariants.
- `apps/api/tests/observability/test_trace_bundle.py` — redacted export/schema-validation tests if H16 lands.
- `examples/dogfood/` — only if H17 needs separate scripts instead of extending existing examples.

***

## 2. Execution Rules

- Use TDD for every task: write failing targeted tests first, run them and capture expected failure, then implement minimal production changes, then run targeted and affected regression suites.
- Keep one semantic change per commit when the user asks for commits. Do not commit automatically unless explicitly requested.
- Preserve deterministic benchmark defaults. Any real-model/network/provider path must stay config-gated and excluded from deterministic benchmark runs.
- Keep auth default-off so existing local development, benchmark, and examples continue to work without secrets.
- Do not broaden the product. These tasks harden existing promises; they do not add new RAG, UI, multi-tenant governance, or distributed infrastructure.

***

## 3. Tasks

### Task H1: Positive Context Redaction Defense-in-Depth

**Goal:** Every positive context block must be safe even when a benchmark strategy disables gate hard/risk policy or a future import path seeds unsafe memory.

**Files:**

- Modify: `apps/api/app/retrieval/packer.py:15-34`, `apps/api/app/retrieval/packer.py:280-313`, `apps/api/app/retrieval/packer.py:346-429`
- Possibly modify: `apps/api/app/memory/secrets.py`
- Test: `apps/api/tests/retrieval/test_retrieval_flow.py`
- Test: `apps/api/tests/retrieval/test_packer_negative.py`
- Test: `apps/api/tests/benchmark/test_runner.py`
- [x] **Step 1: Add failing retrieval-flow tests for positive redaction**

Add tests that seed unsafe memory directly so they bypass writer-side redaction and prove packer defense-in-depth. Include all strategies that historically loosen policy.

Also cover every positive-context construction path that can render text outside the writer: `MemoryItem.value` rendered through project constraints / compacted retained facts, `summary`-only and `content`-only project memory, `prelude_blocks`, `history_summary`/compaction retained facts, and `active_node.goal` / `active_node.summary`. The acceptance distinction is intentional: a strategy may still return a redacted `[REDACTED]` block, but no raw secret value may appear in any `ContextBlock.content`.

```python
@pytest.mark.asyncio
async def test_positive_context_redacts_secret_even_when_gate_policies_are_disabled():
    repo = InMemoryRepository()
    runtime = MemoryRuntime(repo)
    run = await runtime.start_run(StartRunRequest(workspace_id="ws_redact", session_id="s", task="debug auth"))
    step = await runtime.start_step(StartStepRequest(run_id=run.run_id, name="debug"))
    await repo.add_memory(
        MemoryItem(
            workspace_id="ws_redact",
            run_id=run.run_id,
            source_state_node_id=step.state_node_id,
            memory_type=MemoryType.episodic,
            content="Use token sk-1234567890abcdef when calling the API",
            sensitivity=Sensitivity.internal,
            risk_flags=RiskFlags(contains_secret=True),
        )
    )

    for strategy in (RetrievalStrategy.baseline_1, RetrievalStrategy.long_context, RetrievalStrategy.variant_1):
        ctx = await runtime.retrieve_context(
            RetrievalRequest(run_id=run.run_id, query="token api", strategy=strategy, top_k=5)
        )
        rendered = "\n".join(block.content for block in ctx.context_blocks)
        assert "sk-1234567890abcdef" not in rendered
        assert "[REDACTED]" in rendered
```

Also add a project-memory test for the `mem.summary or mem.content` branch:

```python
@pytest.mark.asyncio
async def test_project_memory_summary_is_redacted_before_packing():
    repo = InMemoryRepository()
    runtime = MemoryRuntime(repo)
    run = await runtime.start_run(StartRunRequest(workspace_id="ws_project_secret", session_id="s", task="inspect"))
    await repo.add_memory(
        MemoryItem(
            workspace_id="ws_project_secret",
            run_id=run.run_id,
            memory_type=MemoryType.project,
            key="project.database",
            value="postgres",
            summary="Database password is hunter2 for local postgres",
            content="Database password is hunter2 for local postgres",
            risk_flags=RiskFlags(contains_secret=True),
        )
    )
    ctx = await runtime.retrieve_context(
        RetrievalRequest(run_id=run.run_id, query="database password", strategy=RetrievalStrategy.long_context, top_k=5)
    )
    rendered = "\n".join(block.content for block in ctx.context_blocks)
    assert "hunter2" not in rendered
    assert "[REDACTED]" in rendered
```

`apps/api/app/memory/secrets.py` already supports natural-language `password is <value>` for password/passwd, so `Database password is hunter2` is a valid H1 fixture. For token/API-key natural-language fixtures such as `token is <value>`, first extend `secrets.py` with a bounded pattern (for example `(?i)\b(password|passwd|token|api[_-]?key|secret)\s+(is|=|:)\s+\S+`) and add a focused `secrets.redact(...)` test; otherwise use an already-supported deterministic marker such as `sk-1234567890abcdef` or `password=hunter2`.

- [x] **Step 2: Run targeted tests and verify failure**

Run:

```bash
uv run --extra dev pytest apps/api/tests/retrieval/test_retrieval_flow.py::test_positive_context_redacts_secret_even_when_gate_policies_are_disabled apps/api/tests/retrieval/test_retrieval_flow.py::test_project_memory_summary_is_redacted_before_packing -q
```

Expected: both tests fail because raw secret text appears in positive blocks.

- [x] **Step 3: Implement packer-level redaction helper**

Modify `apps/api/app/retrieval/packer.py` to import and use `redact` centrally.

```python
from app.memory.secrets import redact
```

Add helper near `_copy_block(...)`:

```python
def _safe_content(text: str | None) -> str:
    """Apply final defense-in-depth redaction before prompt context packing."""
    return redact(text or "")


def _safe_block(block: ContextBlock) -> ContextBlock:
    safe = _safe_content(block.content)
    if safe == block.content and block.tokens == estimate_tokens(safe):
        return block
    return block.model_copy(update={"content": safe, "tokens": estimate_tokens(safe)})
```

Apply `_safe_content(...)` to all constructed positive blocks, including active state, active path, project constraints, and memory-derived blocks. For prelude blocks and negative evidence blocks, apply `_safe_block(...)` as a final belt-and-suspenders pass before sorting:

```python
if prelude_blocks:
    blocks.extend(_safe_block(block) for block in prelude_blocks)

content = _safe_content(active_node.goal or active_node.summary or f"Current {active_node.node_type.value} step.")

content = _safe_content((mem.summary or mem.content) if mem.memory_type == MemoryType.project else mem.content)

if negative_evidence:
    blocks.extend(_safe_block(build_negative_evidence_block(ev)) for ev in negative_evidence)
```

For `build_project_constraint_block(...)`, redact the rendered sentence before creating the block:

```python
content = _safe_content(content)
```

For retained facts and compacted constraints, redact rendered values without mutating source `MemoryItem` objects:

```python
content = "Compacted: " + "; ".join(f"{f.key}={_safe_content(f.value)}" for f in facts) + "."
```

If a future test proves `RetainedFact.value` itself needs safe persisted representation, add a separate structured-field redaction decision; H1's required invariant is prompt-context safety.

- [x] **Step 4: Verify targeted tests pass**

Run the same targeted command. Expected: both tests pass.

- [x] **Step 5: Run affected suites**

Run:

```bash
uv run --extra dev pytest apps/api/tests/retrieval/test_packer_negative.py apps/api/tests/retrieval/test_retrieval_flow.py -q
uv run --extra dev pytest apps/api/tests/benchmark/test_runner.py -q
```

Expected: all pass. If token counts change, update only deterministic expected values that explicitly assert redacted-token counts; do not loosen security assertions.

**Acceptance:** No raw secret seeded through positive memory appears in any `ContextBlock.content` for `baseline_1`, `long_context`, or `variant_1`.

**Status (2026-06-13):** Complete. Positive context now applies packer-level `redact()` through `_safe_content(...)` / `_safe_block(...)` for active state/path, prelude blocks, project constraints, memory-derived blocks, retained compacted constraints, and negative-evidence belt-and-suspenders rendering. Retained compacted facts redact both keys and values before entering `PackResult.retained_constraints`, pending compaction logs, or profile metadata, so observability/replay surfaces match prompt safety even if secret-like material appears in a key before §11 ontology exists. Post-review H2 safety-floor tightening means memories explicitly marked `secret` / `contains_secret` / destructive / tool-sensitive are now rejected even for `baseline_1` and `long_context`; packer redaction remains the final defense for unflagged or future bypass paths. Targeted RED/GREEN tests were added in `apps/api/tests/retrieval/test_retrieval_flow.py` and `test_packer_negative.py`; affected retrieval/benchmark suites and full regression passed.

***

### Task H2: `variant_1` Gate Contract Convergence

**Goal:** Preserve `variant_1` as state-aware failed-branch downweighting while keeping hard/risk policy defense against secrets, quarantined memory, destructive commands, and tool-sensitive content. Quarantined, secret/contains-secret, destructive-command, and tool-sensitive memory are non-bypassable safety states: they may remain retrievable as candidates for audit/gate logging, but no strategy may render them into positive context.

**Files:**

- Modify: `apps/api/app/retrieval/gate.py:51-77`
- Test: `apps/api/tests/retrieval/test_gate.py`
- Test: `apps/api/tests/retrieval/test_retrieval_flow.py`
- Docs update later: `docs/design/ROADMAP.md:259`, `README.md` strategy description if it still implies full policy disabled.
- [x] **Step 1: Add failing gate-contract tests**

Add explicit checks:

```python
def test_variant_1_keeps_hard_and_risk_policy_while_allowing_failed_branch_downweight():
    cfg = GateConfig.for_strategy(RetrievalStrategy.variant_1)
    assert cfg.enable_state_match is True
    assert cfg.allow_failed_branch is True
    assert cfg.allow_rolled_back is True
    assert cfg.enable_hard_policy is True
    assert cfg.enable_risk_policy is True
    assert cfg.enable_failure_learning is False


def test_variant_1_rejects_secret_memory():
    mem = make_memory(
        branch_status=BranchStatus.completed,
        sensitivity=Sensitivity.secret,
        risk_flags=RiskFlags(contains_secret=True),
    )
    out = evaluate(
        mem,
        workspace_id=mem.workspace_id,
        relevance=1.0,
        state_match=1.0,
        config=GateConfig.for_strategy(RetrievalStrategy.variant_1),
    )
    assert out.decision == GateDecisionType.reject
    assert out.reject_reason == "secret"


def test_variant_1_rejects_destructive_and_tool_sensitive_memory():
    for flags, reason in [
        (RiskFlags(destructive_command=True), "destructive_command"),
        (RiskFlags(tool_sensitive=True), "tool_sensitive"),
    ]:
        mem = make_memory(risk_flags=flags)
        out = evaluate(
            mem,
            workspace_id=mem.workspace_id,
            relevance=1.0,
            state_match=1.0,
            config=GateConfig.for_strategy(RetrievalStrategy.variant_1),
        )
        assert out.decision == GateDecisionType.reject
        assert out.reject_reason == reason


def test_quarantined_memory_is_rejected_for_every_strategy_even_when_hard_policy_is_disabled():
    for strategy in RetrievalStrategy:
        cfg = GateConfig.for_strategy(strategy)
        mem = make_memory(status=MemoryStatus.quarantined)
        out = evaluate(
            mem,
            workspace_id=mem.workspace_id,
            relevance=1.0,
            state_match=1.0,
            config=cfg,
        )
        assert out.decision == GateDecisionType.reject
        assert out.reject_reason == "invalid_status"
```

If existing test factories are named differently, adapt calls to the local `test_gate.py` helpers rather than introducing duplicate factories.

- [x] **Step 2: Run targeted tests and verify failure**

Run:

```bash
uv run --extra dev pytest apps/api/tests/retrieval/test_gate.py -k "variant_1" -q
```

Expected: new contract/rejection tests fail because `variant_1` currently disables hard/risk policy.

- [x] **Step 3: Add mandatory quarantine safety and change** **`GateConfig.for_strategy`**

In `evaluate(...)`, keep quarantined auditable as a candidate but reject it before strategy-specific hard/risk toggles:

```python
# Mandatory safety floor: quarantine is never prompt-injectable, even in
# ablation strategies that disable parts of the hard/risk gate.
if memory.status == MemoryStatus.quarantined:
    return _reject(memory, GateLayer.hard_policy, "invalid_status", relevance, state_match, freshness, trust, risk)
```

Do not move `quarantined` out of `_RETRIEVABLE_STATUSES`; preserving candidate/gate logs is useful for audit. Do not apply this mandatory floor to all `MemoryStatus.deleted` paths in the gate as a substitute for candidate filtering; deleted/superseded/archived/dormant should continue to be excluded before gate by the lifecycle candidate filter.

Replace the `variant_1` branch in `apps/api/app/retrieval/gate.py:62` with:

```python
if strategy == RetrievalStrategy.variant_1:
    return cls(
        enable_hard_policy=True,
        enable_risk_policy=True,
        enable_state_match=True,
        allow_failed_branch=True,
        allow_rolled_back=True,
        enable_failure_learning=False,
    )
```

Do not change failed-branch downweight logic in `evaluate(...)`; it should still multiply `final_score` by `failed_branch_penalty` when `allow_failed_branch` or `allow_rolled_back` is true.

- [x] **Step 4: Update strategy docs/tests/report wording that assumed disabled policy**

Adjust exact wording in tests/docstrings/README/ROADMAP/benchmark-report prose from “variant\_1 disables hard/risk policy” to “variant\_1 relaxes failed/rolled\_back branch rejection but keeps hard/risk safety policy.” After H1+H2 the six-strategy ladder should be described as:

```text
All runtime strategies share non-bypassable workspace/lifecycle/quarantine/redaction safety invariants.
baseline_0: no memory.
long_context / baseline_1: ablation baselines that may relax gate relevance/risk semantics, but raw secrets are still redacted before prompt context.
variant_1: state-aware ranking plus non-bypassable safety floor; only failed/rolled_back branch hard rejection is relaxed for ablation.
variant_2: full gate + failure learning.
variant_3: variant_2 + deterministic reflection-lite rerank.
```

This is a security correction to the benchmark semantics: safety invariants are not a tunable strategy feature.

- [x] **Step 5: Verify affected suites**

Run:

```bash
uv run --extra dev pytest apps/api/tests/retrieval/test_gate.py apps/api/tests/retrieval/test_retrieval_flow.py apps/api/tests/runtime/test_models_strategy.py -q
```

Expected: all pass. If benchmark metrics move, document the change in ROADMAP closeout as a security correction, not a benchmark regression.

**Acceptance:** `variant_1` still admits/downweights safe failed/rolled\_back memory, but rejects secret, quarantined, destructive, and tool-sensitive memory; quarantined, secret/contains-secret, destructive, and tool-sensitive memory never reach positive context for any strategy while still producing auditable gate decisions; failure-learning sanitized reasons still win for unsafe failed/rolled\_back branches; strategy documentation no longer implies that any non-`baseline_0` path may bypass workspace/lifecycle/quarantine/secret/tool/redaction safety invariants.

**Status (2026-06-13):** Complete. `variant_1` now keeps hard/risk policy enabled while only relaxing failed/rolled\_back branch rejection, and `evaluate(...)` applies mandatory quarantine plus secret/destructive/tool-sensitive rejection floors for every strategy while preserving failure-learning sanitized reject reasons. Gate contract tests cover secret/destructive/tool-sensitive/quarantine behavior for `variant_1` and ablation baselines; affected retrieval/runtime suites and full regression passed.

***

### Task H3: Lightweight Default-Off API Authentication

**Goal:** Remove security theater by making existing SDK/CLI bearer-token support meaningful when enabled, while preserving zero-auth local/dev/benchmark defaults.

**Files:**

- Modify: `apps/api/app/config.py`
- Modify: `apps/api/app/api/deps.py`
- Modify: `apps/api/app/api/routes.py:44`
- Test: `apps/api/tests/api/test_auth.py`
- Test: `packages/python-sdk/tests/test_http_backend.py`
- Test: `packages/python-sdk/tests/test_cli.py`
- [x] **Step 1: Add failing API auth tests**

Create `apps/api/tests/api/test_auth.py` with dependency override or monkeypatch for settings. `get_settings()` is `@lru_cache` in `apps/api/app/config.py`, so cache clearing is mandatory for every env-mutating auth test:

```python
@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
```

```python
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_auth_disabled_keeps_health_and_v1_routes_open(monkeypatch):
    monkeypatch.setenv("MEMTRACE_AUTH_ENABLED", "false")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/v1/runs", json={"workspace_id": "ws", "session_id": "s", "task": "t"})
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_auth_enabled_requires_bearer_token(monkeypatch):
    monkeypatch.setenv("MEMTRACE_AUTH_ENABLED", "true")
    monkeypatch.setenv("MEMTRACE_API_KEY", "dev-secret")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        missing = await client.post("/v1/runs", json={"workspace_id": "ws", "session_id": "s"})
        wrong = await client.post(
            "/v1/runs",
            json={"workspace_id": "ws", "session_id": "s"},
            headers={"Authorization": "Bearer wrong"},
        )
        ok = await client.post(
            "/v1/runs",
            json={"workspace_id": "ws", "session_id": "s"},
            headers={"Authorization": "Bearer dev-secret"},
        )
        x_api_key_ok = await client.post(
            "/v1/runs",
            json={"workspace_id": "ws", "session_id": "s"},
            headers={"X-API-Key": "dev-secret"},
        )
    assert missing.status_code == 401
    assert wrong.status_code == 403
    assert ok.status_code == 200
    assert x_api_key_ok.status_code == 200
```

Use the repository's existing settings pattern and clear the cache both before and after each test to avoid ASGITransport flakiness across default-off/default-on cases.

- [x] **Step 2: Run tests and verify failure**

Run:

```bash
uv run --extra dev pytest apps/api/tests/api/test_auth.py -q
```

Expected: auth-enabled tests fail because no dependency checks headers.

- [x] **Step 3: Add settings**

In `apps/api/app/config.py`, add default-off settings:

```python
auth_enabled: bool = False
api_key: str | None = None
```

Keep environment variable names consistent with current settings prefix. If the settings model uses `env_prefix="MEMTRACE_"`, the variables above map to `MEMTRACE_AUTH_ENABLED` and `MEMTRACE_API_KEY`.

- [x] **Step 4: Add auth dependency**

In `apps/api/app/api/deps.py`, add:

```python
from secrets import compare_digest

from fastapi import Header, HTTPException, status


async def require_api_key(
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
) -> None:
    settings = get_settings()
    if not settings.auth_enabled:
        return
    expected = settings.api_key
    if not expected:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="auth enabled but api key is not configured")
    supplied = None
    if authorization and authorization.lower().startswith("bearer "):
        supplied = authorization.split(" ", 1)[1]
    elif x_api_key:
        supplied = x_api_key
    if not supplied:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing api key")
    if not compare_digest(supplied.encode("utf-8"), expected.encode("utf-8")):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid api key")
```

- [x] **Step 5: Protect the** **`/v1`** **router**

In `apps/api/app/api/routes.py`, change router construction to:

```python
from app.api.deps import get_runtime, require_api_key

router = APIRouter(prefix="/v1", dependencies=[Depends(require_api_key)])
```

Do not protect `/health` if it is outside this router.

- [x] **Step 6: Verify SDK/CLI token path**

Add one ASGITransport SDK test proving `MemTrace.http(..., api_key="dev-secret")` reaches a token-protected route. Add one CLI test proving `--api-key dev-secret` sets the header for HTTP mode.

- [x] **Step 7: Run affected suites**

Run:

```bash
uv run --extra dev pytest apps/api/tests/api/ -q
uv run --package memtrace-sdk --extra dev pytest packages/python-sdk/tests/test_http_backend.py packages/python-sdk/tests/test_cli.py -q
```

**Acceptance:** Auth is off by default; when enabled, missing tokens produce 401, wrong tokens produce 403, Bearer and `X-API-Key` headers work, and SDK/CLI bearer tokens work.

**Status (2026-06-13):** Complete. `MEMTRACE_AUTH_ENABLED=false` remains default; when enabled with `MEMTRACE_API_KEY`, `/v1` routes require Bearer or `X-API-Key` while `/health` stays open. Token comparison is byte-based so non-ASCII invalid credentials fail closed with 403 instead of surfacing `TypeError`. API, SDK ASGITransport, and CLI `--api-key` tests cover the token path; affected API/SDK suites and full regression passed.

***

### Task H4: Backend Error Isomorphism for StateTree and Replay

**Goal:** In-process SDK, HTTP SDK, and direct runtime should expose equivalent client-correctable errors for state-tree misuse and replay references.

**Status (2026-06-13):** Complete. `StateTreeError` now maps to HTTP 400 / SDK `BadRequestError` for in-process and HTTP backends; replay missing-run existence checks live in `MemoryRuntime` and map to 404 / SDK `NotFoundError` without route/backend private repo reads.

**Files:**

- Modify: `apps/api/app/runtime/memory_runtime.py:152-193`, `apps/api/app/runtime/memory_runtime.py:808-814`
- Modify: `apps/api/app/api/routes.py:55-92`, `apps/api/app/api/routes.py:150-167`
- Modify: `packages/python-sdk/src/memtrace_sdk/backends.py:8-11`, `packages/python-sdk/src/memtrace_sdk/backends.py:107-187`
- Test: `packages/python-sdk/tests/test_backend_isomorphism.py`
- Test: `apps/api/tests/api/test_observability.py`
- [x] **Step 1: Add failing backend-isomorphism tests**

Extend existing backend isomorphism tests with two cases:

Use a corrupt-state fixture that actually triggers `StateTreeError` rather than `RunNotFoundError` / `StepNotFoundError`. For the current runtime, the deterministic path is a recovery step whose failed node exists but points to a missing parent:

```python
@pytest.mark.asyncio
async def test_state_tree_error_maps_to_bad_request_for_in_process_and_http(shared_runtime_backends):
    runtime, in_process, http = shared_runtime_backends
    run = await runtime.start_run(StartRunRequest(workspace_id="ws_state", session_id="s", task="t"))
    bad_failed_node = StateNode(
        workspace_id="ws_state",
        run_id=run.run_id,
        parent_id="missing_parent",
        status=StateNodeStatus.failed,
        failure_reason="boom",
    )
    await runtime._repo.add_state_node(bad_failed_node)  # noqa: SLF001 - corrupt-state fixture
    failed_step = AgentStep(
        workspace_id="ws_state",
        run_id=run.run_id,
        state_node_id=bad_failed_node.node_id,
        status=StepStatus.failed,
    )
    await runtime._repo.add_step(failed_step)  # noqa: SLF001 - corrupt-state fixture

    request = StartStepRequest(run_id=run.run_id, name="recovery", recovery_from_step_id=failed_step.step_id)
    for backend in (in_process, http):
        with pytest.raises(BadRequestError):
            await backend.start_step(request)
```

H13 should additionally cover `finish_step(...)` with a step pointing at a missing state node, then rely on this H4 mapping so HTTP and in-process SDK expose it as 400 / `BadRequestError`.

For replay missing-run semantics:

```python
@pytest.mark.asyncio
async def test_replay_access_missing_run_is_not_found_for_in_process_and_http(shared_runtime_backends):
    runtime, in_process, http = shared_runtime_backends
    access = MemoryAccessLog(workspace_id="ws", run_id="run_missing", query="q")
    await runtime._repo.add_access_log(access)  # noqa: SLF001 - test fixture seeds inconsistent data
    for backend in (in_process, http):
        with pytest.raises(NotFoundError):
            await backend.replay_access(access.access_id)
```

- [x] **Step 2: Verify tests fail**

Run:

```bash
uv run --package memtrace-sdk --extra dev pytest packages/python-sdk/tests/test_backend_isomorphism.py -q
```

Expected: in-process/HTTP errors differ.

- [x] **Step 3: Map** **`StateTreeError`** **at route and SDK boundaries**

Import `StateTreeError` in `routes.py` and return 400:

```python
from app.runtime.state_tree import StateTreeError

except StateTreeError as e:
    raise HTTPException(status_code=400, detail=str(e))
```

Add the same mapping to `InProcessBackend`:

```python
from app.runtime.state_tree import StateTreeError

...
except StateTreeError as exc:
    raise BadRequestError(str(exc)) from exc
```

- [x] **Step 4: Move replay existence checks into runtime**

In `MemoryRuntime.replay_access(...)`, add:

```python
access = await self._repo.get_access_log(access_id)
if access is None:
    return None
if access.run_id is not None and await self._repo.get_run(access.run_id) is None:
    raise RunNotFoundError(access.run_id)
return await RetrievalReplayService(self._repo, self._retrieval).replay_access(access_id)
```

In HTTP route, remove direct `rt._repo` reads and catch `RunNotFoundError` as 404. In `InProcessBackend.replay_access(...)`, catch `RunNotFoundError` and raise `NotFoundError`.

- [x] **Step 5: Run affected tests**

Run:

```bash
uv run --package memtrace-sdk --extra dev pytest packages/python-sdk/tests/test_backend_isomorphism.py packages/python-sdk/tests/test_http_backend.py -q
uv run --extra dev pytest apps/api/tests/api/test_observability.py -q
```

**Acceptance:** State-tree misuse maps to client-correctable `BadRequestError`/HTTP 400; missing replay run maps to `NotFoundError`/HTTP 404 in both backends.

***

### Task H5: Atomic Event Sequence Allocation and Insert

**Goal:** Guarantee per-run event `sequence_no` uniqueness and monotonicity under concurrent SQL writers.

**Status (2026-06-13):** Complete. Runtime event writes now go through repository-level `append_event(...)`; in-memory assigns sequence and insert atomically; SQL allocates and inserts in one transaction under a namespaced advisory lock with bounded `IntegrityError` retry. ORM now uses the same `uq_event_run_seq` constraint name as `0001_initial`; `0006_security_consistency_hardening` remains as the hardening revision boundary without creating a duplicate same-column unique constraint.

**Files:**

- Modify: `apps/api/app/runtime/repository.py:67-70`, `apps/api/app/runtime/repository.py:194-202`
- Modify: `apps/api/app/runtime/memory_runtime.py:218-255`
- Modify: `apps/api/app/storage/sql_repository.py:449-464`
- Modify: `apps/api/app/storage/orm.py` event table indexes
- Add migration: `migrations/versions/0006_security_consistency_hardening.py` or split migration
- Test: `apps/api/tests/runtime/test_memory_runtime_trace.py`
- Test: `apps/api/tests/storage/test_migrations.py`
- [x] **Step 1: Add failing concurrency/protocol tests**

Add an in-memory concurrency test first; it will pass today for InMemory but protects the new protocol:

```python
@pytest.mark.asyncio
async def test_concurrent_write_events_get_gap_free_run_local_sequence_numbers():
    runtime = MemoryRuntime(InMemoryRepository())
    run = await runtime.start_run(StartRunRequest(workspace_id="ws_seq", session_id="s", task="seq"))
    step = await runtime.start_step(StartStepRequest(run_id=run.run_id, name="step"))

    async def write(i: int):
        return await runtime.write_event(
            WriteEventRequest(step_id=step.step_id, role=EventRole.user, type=EventType.message, content=f"event {i}")
        )

    await asyncio.gather(*(write(i) for i in range(50)))
    events = await runtime.get_timeline(run.run_id)
    assert [event.sequence_no for event in events] == list(range(1, 51))
```

Add migration metadata test asserting a unique constraint/index over `(run_id, sequence_no)`.

Add an env-gated SQL integration test that runs only when `MEMTRACE_TEST_DATABASE_URL` is set and otherwise skips explicitly. The test database must be migrated to Alembic head before running the concurrency assertions; either run `alembic upgrade head` in the fixture or assert/skip with a clear message when the schema is not at head. It should start one SQL-backed run/step and perform 50 concurrent `write_event(...)` calls against `SqlRepository`, then assert the stored timeline has exactly `1..50` sequence numbers. This is the only test that can prove the advisory-lock/unique-index path under the real backend; the in-memory test protects the shared protocol only.

- [x] **Step 2: Run tests and note SQL-schema failure**

Run:

```bash
uv run --extra dev pytest apps/api/tests/runtime/test_memory_runtime_trace.py apps/api/tests/storage/test_migrations.py -q
```

Expected: migration/schema assertion fails until unique index is added.

- [x] **Step 3: Add atomic repository method**

Update `Repository` protocol:

```python
async def append_event(self, event: AgentEvent) -> AgentEvent: ...
```

Keep `next_sequence_no(...)` and `add_event(...)` temporarily if tests or older code still call them, but route runtime writes through `append_event(...)`.

In InMemory:

```python
async def append_event(self, event: AgentEvent) -> AgentEvent:
    self._seq_counters[event.run_id] = self._seq_counters.get(event.run_id, 0) + 1
    stored = event.model_copy(update={"sequence_no": self._seq_counters[event.run_id]})
    self._events[stored.event_id] = stored.model_copy(deep=True)
    return stored.model_copy(deep=True)
```

- [x] **Step 4: Use atomic append in** **`write_event`**

In `MemoryRuntime.write_event(...)`, construct `AgentEvent` with a temporary `sequence_no=0`, then call:

```python
event = await self._repo.append_event(event)
```

Remove the preceding call to `next_sequence_no(...)` from runtime's hot path.

- [x] **Step 5: Implement SQL atomic transaction**

In `SqlRepository.append_event(...)`, use a namespaced advisory lock plus bounded unique-conflict retry (`from sqlalchemy.exc import IntegrityError`). Historical duplicate rows should still make the migration fail loudly; runtime concurrent conflicts should be retried because event append is a hot path.

```python
async def append_event(self, event: AgentEvent) -> AgentEvent:
    last_error = None
    for _attempt in range(3):
        try:
            async with self._sf() as s:
                async with s.begin():
                    await s.execute(
                        text("SELECT pg_advisory_xact_lock(hashtext('memtrace_event_seq'), hashtext(:run_id))"),
                        {"run_id": event.run_id},
                    )
                    cur = (await s.execute(
                        select(func.coalesce(func.max(orm.EventORM.sequence_no), 0)).where(orm.EventORM.run_id == event.run_id)
                    )).scalar_one()
                    stored = event.model_copy(update={"sequence_no": int(cur) + 1})
                    s.add(_event_to_orm(stored))
                return stored
        except IntegrityError as exc:
            last_error = exc
    assert last_error is not None
    raise last_error
```

Do not commit between allocation and insert.

- [x] **Step 6: Add unique index migration**

Add a migration operation:

```python
op.create_index("ux_events_run_sequence_no", "agent_events", ["run_id", "sequence_no"], unique=True)
```

Use the actual event table name from `orm.py`. Downgrade drops the index.

- [x] **Step 7: Verify affected suites**

Run:

```bash
uv run --extra dev pytest apps/api/tests/runtime/test_memory_runtime_trace.py apps/api/tests/storage/test_migrations.py -q
uv run --extra dev pytest apps/api/tests/runtime/ apps/api/tests/api/ -q
```

**Acceptance:** Runtime no longer allocates sequence in a transaction separate from insert; schema has `(run_id, sequence_no)` uniqueness; the SQL path uses a namespaced advisory transaction lock and bounded retry for unique conflicts; real SQL concurrency is covered when `MEMTRACE_TEST_DATABASE_URL` is available.

***

### Task H6: Unified Retrieval Timeout Persistence

**Goal:** Timeout responses must have inspectable access records, consistent prelude/non-prelude behavior, and no partial trace/access split-brain.

**Status (2026-06-13):** Complete. Both `retrieve(...)` and `retrieve_with_prelude(...)` persist the same minimal timeout access shape, and timeout now wraps trace construction only; successful trace persistence and access-count mutation run after trace success outside the timeout window, with regression coverage for slow persistence after fast trace success.

**Files:**

- Modify: `apps/api/app/retrieval/controller.py:114-197`, `apps/api/app/retrieval/controller.py:420-475`
- Test: `apps/api/tests/retrieval/test_retrieval_flow.py`
- Test: `apps/api/tests/retrieval/test_retrieval_trace.py`
- Test: `apps/api/tests/observability/test_replay.py`
- [x] **Step 1: Add failing tests**

Add tests for both timeout paths:

```python
@pytest.mark.asyncio
async def test_timeout_context_has_persisted_inspectable_access_log(monkeypatch):
    repo = InMemoryRepository()
    controller = RetrievalController(repo)
    controller._timeout_ms = 1

    async def slow_trace(*args, **kwargs):
        await asyncio.sleep(1)

    monkeypatch.setattr(controller, "trace", slow_trace)
    ctx = await controller.retrieve(
        RetrievalRequest(run_id="run_timeout", query="q", strategy=RetrievalStrategy.baseline_1),
        workspace_id="ws_timeout",
    )
    access = await repo.get_access_log(ctx.access_id)
    assert access is not None
    assert access.query == "q"
    assert access.workspace_id == "ws_timeout"
    assert "timed out" in "\n".join(ctx.warnings)
```

Add the same assertion for `retrieve_with_prelude(...)`, verifying both branches persist the same fields.

- [x] **Step 2: Run targeted tests and verify failure**

Run:

```bash
uv run --extra dev pytest apps/api/tests/retrieval/test_retrieval_flow.py -k "timeout" -q
```

Expected: non-prelude timeout has no persisted access log.

- [x] **Step 3: Add timeout access helper**

In `RetrievalController`, add:

```python
def _timeout_access(self, request: RetrievalRequest, *, workspace_id: str) -> MemoryAccessLog:
    return MemoryAccessLog(
        workspace_id=workspace_id,
        run_id=request.run_id,
        step_id=request.step_id,
        query=request.query,
        task_intent=request.task_intent,
        retrieval_strategy=request.strategy,
        token_budget=request.token_budget or self._default_budget,
        top_k=request.top_k,
        latency_ms=self._timeout_ms or 0,
    )
```

Use it in both timeout branches and call `await self._repo.add_access_log(access)`. After H9, this helper must also attach a policy snapshot/hash so timeout accesses are replay/inspect compatible with successful accesses.

- [x] **Step 4: Refactor timeout to wrap trace construction only**

Do not use `asyncio.wait_for(_retrieve_impl(...))`, because `_retrieve_impl(...)` currently includes trace construction, access/gate/profile persistence, and access-count mutation. If timeout fires during persistence, a caller could receive a timeout response while a shielded or partially completed successful trace writes in the background.

Instead split successful retrieval into explicit phases:

```python
async def _persist_trace_and_mutations(self, trace: RetrievalPipelineTrace) -> None:
    await self._persist_trace(trace)
    await self._bump_access_counts(trace.accepted_memories)


async def retrieve(...):
    try:
        trace = await asyncio.wait_for(
            self.trace(request, workspace_id=workspace_id, prelude_blocks=prelude_blocks, ...),
            timeout=self._timeout_ms / 1000.0,
        )
    except asyncio.TimeoutError:
        access = self._timeout_access(request, workspace_id=workspace_id)
        await self._repo.add_access_log(access)
        return self._timeout_context(access, prelude_warnings=prelude_warnings)

    await self._persist_trace_and_mutations(trace)
    return self._context_from_trace(trace)
```

The same helper should be used by both `retrieve(...)` and `retrieve_with_prelude(...)` so prelude/non-prelude timeout rows have the same persistence semantics. The successful path runs persistence **outside** the timeout window and without `asyncio.shield`:

```python
await self._persist_trace_and_mutations(trace)
return self._context_from_trace(trace)
```

This keeps semantics clear: if trace construction does not complete before the timeout, only a minimal timeout access is persisted; if trace construction completes, the access is treated as a successful retrieval and must be fully persisted. Profile failures remain non-fatal because `_persist_trace(...)` already catches profile exceptions in `apps/api/app/retrieval/controller.py:441`.

- [x] **Step 5: Verify affected suites**

Run:

```bash
uv run --extra dev pytest apps/api/tests/retrieval/test_retrieval_flow.py apps/api/tests/retrieval/test_retrieval_trace.py apps/api/tests/observability/test_replay.py -q
```

**Acceptance:** Every timeout response references a persisted access log; timeout only applies to trace construction; successful trace persistence and access-count mutation run after trace success and cannot be confused with a timeout response or produce a duplicate minimal/full access split.

***

### Task H7: Deterministic Gate Logs and Replay Tie-Breaks

**Goal:** SQL, InMemory, hot-path context, and replay original-view reconstruction must use deterministic order when timestamps or scores tie.

**Files:**

- Modify: `apps/api/app/storage/sql_repository.py:581-587`
- Modify: `apps/api/app/runtime/repository.py:297-302`
- Modify: `apps/api/app/retrieval/controller.py:294-302`
- Modify: `apps/api/app/observability/replay.py`
- Test: `apps/api/tests/observability/test_replay.py`
- Test: `apps/api/tests/retrieval/test_retrieval_flow.py`
- [x] **Step 1: Add failing deterministic-order tests**

Create two gate logs with same `created_at` and equal `final_score`, then assert order by `gate_id` / `memory_id`.

```python
@pytest.mark.asyncio
async def test_gate_logs_are_sorted_by_created_at_then_gate_id():
    repo = InMemoryRepository()
    access = MemoryAccessLog(workspace_id="ws", query="q")
    await repo.add_access_log(access)
    same_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    await repo.add_gate_log(MemoryGateLog(gate_id="gate_b", access_id=access.access_id, memory_id="mem_b", created_at=same_time))
    await repo.add_gate_log(MemoryGateLog(gate_id="gate_a", access_id=access.access_id, memory_id="mem_a", created_at=same_time))
    rows = await repo.list_gate_logs(access.access_id)
    assert [row.gate_id for row in rows] == ["gate_a", "gate_b"]
```

- [x] **Step 2: Run targeted test and verify failure**

Run:

```bash
uv run --extra dev pytest apps/api/tests/observability/test_replay.py -k "gate_logs_are_sorted" -q
```

Expected: in-memory returns append order.

- [x] **Step 3: Sort InMemory and SQL gate logs**

In InMemory:

```python
async def list_gate_logs(self, access_id: str) -> list[MemoryGateLog]:
    rows = [g for g in self._gate_logs if g.access_id == access_id]
    rows.sort(key=lambda g: (g.created_at, g.gate_id))
    return [g.model_copy(deep=True) for g in rows]
```

In SQL:

```python
.order_by(orm.GateLogORM.created_at, orm.GateLogORM.gate_id)
```

- [x] **Step 4: Add deterministic accepted-outcome tie-breaks**

In controller hot path:

```python
accepted_outcomes.sort(key=lambda o: (-o.final_score, o.memory.memory_id))
```

Use the same accepted-context tie-break in replay when reconstructing accepted ordering from persisted gate logs. Keep this distinct from the gate-log row-order tie-break: `list_gate_logs(...)` should order persisted rows by `(created_at, gate_id)` for deterministic log iteration, while accepted-memory/context reconstruction should order accepted decisions by `(-final_score, memory_id)` so replay matches the hot path.

- [x] **Step 5: Verify replay suites**

Run:

```bash
uv run --extra dev pytest apps/api/tests/observability/test_replay.py apps/api/tests/retrieval/test_retrieval_flow.py -q
```

**Acceptance:** Equal timestamps/scores never produce backend-specific or run-to-run context order drift.

***

### Task H8: ORM and Migration Index Alignment

**Goal:** `create_all` metadata and Alembic migration schema describe the same `context_compaction_logs` indexes.

**Files:**

- Modify: `apps/api/app/storage/orm.py:222-241`
- Test: `apps/api/tests/storage/test_migrations.py`
- [x] **Step 1: Add failing metadata test**

Add:

```python
def test_context_compaction_log_orm_indexes_match_migration_names():
    indexes = {index.name: tuple(column.name for column in index.columns) for index in orm.ContextCompactionORM.__table__.indexes}
    assert indexes["ix_context_compaction_logs_access_id"] == ("access_id",)
    assert indexes["ix_context_compaction_logs_run_id"] == ("run_id",)
    assert indexes["ix_context_compaction_logs_workspace_created"] == ("workspace_id", "created_at")
    assert "ix_context_compaction_logs_workspace_id" not in indexes
```

- [x] **Step 2: Run test and verify failure**

Run:

```bash
uv run --extra dev pytest apps/api/tests/storage/test_migrations.py -q
```

Expected: ORM currently exposes a single-column workspace index instead of the compound index.

- [x] **Step 3: Align ORM metadata**

Use explicit `Index` entries:

```python
from sqlalchemy import Index


class ContextCompactionORM(Base):
    __tablename__ = "context_compaction_logs"
    __table_args__ = (
        Index("ix_context_compaction_logs_workspace_created", "workspace_id", "created_at"),
    )
    access_id: Mapped[str] = mapped_column(String, index=True)
    run_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    workspace_id: Mapped[str] = mapped_column(String)
```

Keep existing migration unchanged because it already creates the intended compound index.

- [x] **Step 4: Verify storage tests**

Run:

```bash
uv run --extra dev pytest apps/api/tests/storage/test_migrations.py -q
```

**Acceptance:** ORM metadata index names/columns match migration `0005_context_compaction`.

***

### Task H9: Retrieval Policy Snapshot and Policy Drift Classification

**Goal:** Persist enough retrieval policy data per access to distinguish memory/data drift from policy/code/config drift during replay and benchmark comparisons.

**Files:**

- Add: `apps/api/app/retrieval/policy.py`
- Modify: `apps/api/app/runtime/models.py` `MemoryAccessLog`
- Modify: `apps/api/app/storage/orm.py` access-log table
- Modify: `apps/api/app/storage/sql_repository.py` access log conversion helpers
- Modify: `apps/api/app/runtime/repository.py` InMemory copy only if model field addition requires no logic
- Modify: `apps/api/app/retrieval/controller.py:199-237`
- Modify: `apps/api/app/observability/replay.py`
- Add migration: `migrations/versions/0007_retrieval_policy_snapshot.py` if not combined with H5
- Test: `apps/api/tests/retrieval/test_retrieval_trace.py`
- Test: `apps/api/tests/observability/test_replay.py`
- Test: `apps/api/tests/storage/test_migrations.py`
- [x] **Step 1: Add failing persistence and replay tests**

```python
@pytest.mark.asyncio
async def test_access_log_persists_retrieval_policy_snapshot():
    repo = InMemoryRepository()
    runtime = MemoryRuntime(repo)
    run = await runtime.start_run(StartRunRequest(workspace_id="ws_policy", session_id="s", task="policy"))
    ctx = await runtime.retrieve_context(
        RetrievalRequest(run_id=run.run_id, query="q", strategy=RetrievalStrategy.variant_2, token_budget=123, top_k=4)
    )
    access = await repo.get_access_log(ctx.access_id)
    assert access.policy_snapshot is not None
    assert access.policy_snapshot["strategy"] == "variant_2"
    assert access.policy_snapshot["token_budget"] == 123
    assert access.policy_hash
```

For replay drift:

```python
@pytest.mark.asyncio
async def test_replay_reports_policy_drift_when_persisted_policy_hash_differs():
    ...
    access.policy_hash = "sha256:not-current"
    await repo.add_access_log(access)
    replay = await runtime.replay_access(access.access_id)
    assert any(diff.kind == "policy_drift" for diff in replay.diffs)
```

Use the actual replay diff DTO fields. If current diff model uses string categories, use that exact field name.

Add timeout coverage after H6:

```python
@pytest.mark.asyncio
async def test_timeout_access_log_persists_policy_snapshot(monkeypatch):
    ...
    ctx = await controller.retrieve(RetrievalRequest(...), workspace_id="ws_policy_timeout")
    access = await repo.get_access_log(ctx.access_id)
    assert access.policy_snapshot["strategy"] == request.strategy.value
    assert access.policy_hash
```

- [x] **Step 2: Run targeted tests and verify failure**

Run:

```bash
uv run --extra dev pytest apps/api/tests/retrieval/test_retrieval_trace.py apps/api/tests/observability/test_replay.py -k "policy" -q
```

Expected: `policy_snapshot` / `policy_hash` fields do not exist.

- [x] **Step 3: Add model fields**

In `MemoryAccessLog`:

```python
policy_version: str = "retrieval-policy-v1"
policy_hash: Optional[str] = None
policy_snapshot: dict[str, Any] = Field(default_factory=dict)
```

Use JSON-compatible primitives only.

- [x] **Step 4: Add snapshot builder**

Create `apps/api/app/retrieval/policy.py`:

```python
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import Any

from app.retrieval.gate import GateConfig
from app.runtime.models import RetrievalRequest, RetrievalStrategy

POLICY_VERSION = "retrieval-policy-v1"
LIFECYCLE_FILTER_VERSION = "retrievable-statuses-v1"


def build_policy_snapshot(
    request: RetrievalRequest,
    *,
    gate_config: GateConfig,
    effective_token_budget: int,
    vector_enabled: bool,
    vector_weight: float,
    compaction_notice_reserve_tokens: int,
) -> dict[str, Any]:
    snapshot = {
        "policy_version": POLICY_VERSION,
        "strategy": request.strategy.value,
        "top_k": request.top_k,
        "token_budget": effective_token_budget,
        "gate_config": asdict(gate_config),
        "retrieval": {
            "vector_enabled": vector_enabled,
            "vector_weight": vector_weight if vector_enabled else 0.0,
            "include_all": request.strategy == RetrievalStrategy.long_context,
            "lifecycle_filter_version": LIFECYCLE_FILTER_VERSION,
        },
        "packer": {
            "compaction_notice_reserve_tokens": compaction_notice_reserve_tokens,
            "negative_evidence_max_blocks": 3,
        },
        "providers": {
            "embedding": "deterministic_hash_default",
            "summarizer": "persisted_or_config_gated",
        },
    }
    return snapshot


def policy_hash(snapshot: dict[str, Any]) -> str:
    payload = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()
```

- [x] **Step 5: Persist snapshot in successful and timeout access logs**

In `RetrievalController.trace(...)`, build `config = GateConfig.for_strategy(...)` before the `baseline_0` early return so **all** strategy accesses, including `baseline_0`, receive a snapshot. Then set:

```python
snapshot = build_policy_snapshot(...)
access.policy_snapshot = snapshot
access.policy_version = snapshot["policy_version"]
access.policy_hash = policy_hash(snapshot)
```

If long-context later expands `budget`, recompute snapshot/hash after updating `access.token_budget`.

Use the same builder from H6's `_timeout_access(...)` helper so timeout access rows do not become a policy-snapshot blind spot. Timeout snapshots should use the effective requested/default budget and the same `GateConfig.for_strategy(...)` contract, even though candidate selection never completed.

- [x] **Step 6: Add ORM/migration support**

Add JSONB/text fields to `AccessLogORM`:

```python
policy_version: Mapped[str | None] = mapped_column(String, nullable=True)
policy_hash: Mapped[str | None] = mapped_column(String, nullable=True)
policy_snapshot: Mapped[dict] = mapped_column(JSONB, default=dict)
```

Migration should add nullable/default-compatible fields so old access logs remain readable.

- [x] **Step 7: Classify missing policy separately from policy drift in replay**

When replay reconstructs the current policy snapshot, compare hash:

```python
if not access.policy_hash:
    warnings.append("policy_snapshot_missing")
elif access.policy_hash != current_hash:
    diffs.append(ReplayDiff(kind="policy_drift", severity="warning", ...))
```

Do not suppress data drift; report policy drift separately. Old pre-H9 access rows and deliberately minimal historical fixtures should produce `policy_snapshot_missing` warnings, not `policy_drift` and not a critical replay failure.

- [x] **Step 8: Verify affected suites**

Run:

```bash
uv run --extra dev pytest apps/api/tests/retrieval/test_retrieval_trace.py apps/api/tests/observability/test_replay.py apps/api/tests/storage/test_migrations.py -q
```

**Acceptance:** Every new successful or timeout access has a stable policy hash/snapshot; old missing-policy accesses are reported as `policy_snapshot_missing`; replay distinguishes policy drift from candidate/context data drift.

***

### Task H10: Runtime Invariant and Conformance Suite

**Goal:** Turn scattered safety/equivalence assumptions into reusable tests that every future retrieval path, backend, adapter, provider, scheduler, and import/export feature must satisfy.

**Files:**

- Add: `apps/api/tests/conformance/__init__.py`
- Add: `apps/api/tests/conformance/test_strategy_conformance.py`
- Add: `apps/api/tests/conformance/test_backend_conformance.py`
- Add: `apps/api/tests/conformance/test_replay_conformance.py`
- Modify existing helpers only if reuse avoids duplication.
- [x] **Step 1: Add layered strategy conformance tests**

Keep conformance assertions layered so stable red lines do not get confused with intentional strategy differences.

**Non-bypassable invariants for every strategy:** workspace isolation; lifecycle-invalid states never become candidates/context; quarantined memory may be candidate/audited but never positive context; raw secret text never appears in context/report/bundle; replay has no side effects. A strategy may return a redacted `[REDACTED]` block after H1, but no raw secret marker may appear.

**Strategy-specific invariants:** `baseline_0` returns no memory context; `long_context` includes all eligible workspace/lifecycle-valid memories; `baseline_1` remains relevance/top-k oriented but still cannot leak raw secrets; `variant_1` relaxes failed/rolled\_back branch rejection while keeping the safety floor; `variant_2`/`variant_3` apply full gate + failure learning, with `variant_3` adding reflection-lite rerank only.

Create fixtures that seed active, superseded, archived, dormant, deleted, quarantined, secret, failed, rolled\_back, workspace-mismatch, destructive, and tool-sensitive memories. Assert non-bypassable lifecycle/workspace behavior separately from strategy-specific branch/gate behavior:

```python
@pytest.mark.parametrize("strategy", list(RetrievalStrategy))
@pytest.mark.asyncio
async def test_all_strategies_apply_workspace_and_lifecycle_candidate_filter(strategy):
    ...
    ctx = await runtime.retrieve_context(RetrievalRequest(run_id=run.run_id, query="marker", strategy=strategy, top_k=20))
    rendered = "\n".join(block.content for block in ctx.context_blocks)
    assert "OTHER_WORKSPACE_MARKER" not in rendered
    assert "SUPERSEDED_MARKER" not in rendered
    assert "ARCHIVED_MARKER" not in rendered
    assert "DORMANT_MARKER" not in rendered
    assert "DELETED_MARKER" not in rendered
```

For `baseline_0`, assert context is empty and still no leaks. For `long_context`, assert it includes only retrievable workspace memory. For secret fixtures, assert raw marker absence across all strategies; only strategies with active hard-policy rejection should additionally assert the entire secret block is absent.

- [x] **Step 2: Add backend conformance tests**

Use existing ASGITransport shared-runtime pattern from `packages/python-sdk/tests/test_backend_isomorphism.py` and assert:

Backend invariants should focus on transport equivalence rather than strategy policy: in-memory / HTTP / SQL response shape equivalence, client-correctable error mapping, cross-backend read/write visibility, and sequence number monotonicity.

```python
@pytest.mark.asyncio
async def test_in_process_and_http_cross_read_write_runtime_contract(shared_backends):
    in_process, http = shared_backends
    run = await in_process.start_run(StartRunRequest(workspace_id="ws_conf", session_id="s", task="contract"))
    step = await http.start_step(StartStepRequest(run_id=run.run_id, name="step"))
    await in_process.write_event(WriteEventRequest(step_id=step.step_id, role=EventRole.user, type=EventType.message, content="use bun"))
    timeline = await http.get_timeline(run.run_id)
    assert [event.sequence_no for event in timeline] == [1]
```

- [x] **Step 3: Add replay conformance tests**

Assert replay has no side effects:

```python
before_accesses = await repo.list_access_logs(workspace_id="ws")
before_memories = await repo.list_memories(workspace_id="ws")
await runtime.replay_access(access_id)
after_accesses = await repo.list_access_logs(workspace_id="ws")
after_memories = await repo.list_memories(workspace_id="ws")
assert [a.access_id for a in after_accesses] == [a.access_id for a in before_accesses]
assert [(m.memory_id, m.access_count) for m in after_memories] == [(m.memory_id, m.access_count) for m in before_memories]
```

- [x] **Step 4: Run conformance suite and fix only real defects**

Run:

```bash
uv run --extra dev pytest apps/api/tests/conformance/ -q
```

Expected after H1-H9: pass. If a test reveals an unplanned defect, fix it in the relevant module and record the pitfall.

- [x] **Step 5: Run broader safety/equivalence suites**

Run:

```bash
uv run --extra dev pytest apps/api/tests/retrieval/ apps/api/tests/observability/test_replay.py packages/python-sdk/tests/test_backend_isomorphism.py -q
```

**Acceptance:** New `apps/api/tests/conformance/` captures strategy, backend, and replay invariants without needing future maintainers to rediscover scattered safety assumptions.

***

### Task H11: Independent Token Estimation and CJK-Safe Truncation

**Goal:** Budget estimates must not undercount stopwords or fail to truncate no-space CJK text.

**Batch note:** Keep H11 as its own semantic change within Batch E2. It can perturb compaction triggers, `actual_tokens`, `avg_memory_token_overhead`, long-context token-bloat metrics, and tight-budget fixtures such as `case_12_reflection_retention`; verify benchmark acceptance and update deterministic numeric snapshots only with explicit justification.

**Files:**

- Modify: `apps/api/app/retrieval/packer.py:32-34`, `apps/api/app/retrieval/packer.py:106-125`
- Test: `apps/api/tests/retrieval/test_packer_negative.py` or new `apps/api/tests/retrieval/test_packer_tokens.py`
- Test: `apps/api/tests/runtime/test_context_compaction.py`
- Test: `apps/api/tests/benchmark/test_runner.py`
- [x] **Step 1: Add failing token/truncation tests**

```python
def test_estimate_tokens_counts_stopwords_and_cjk_characters():
    assert estimate_tokens("the and of to in") >= 5
    assert estimate_tokens("这是一个没有空格的中文句子") >= 8


def test_truncate_text_handles_cjk_without_exceeding_budget():
    text = "这是一个没有空格的中文句子用于测试截断行为"
    truncated = _truncate_text(text, 6)
    assert estimate_tokens(truncated) <= 6
    assert truncated
    assert len(truncated) < len(text)
```

- [x] **Step 2: Run tests and verify failure**

Run:

```bash
uv run --extra dev pytest apps/api/tests/retrieval/test_packer_tokens.py -q
```

Expected: stopwords undercount and/or CJK truncation exceeds budget.

- [x] **Step 3: Replace estimator**

In `packer.py`, add regex-based deterministic estimator:

```python
_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]+|[^\sA-Za-z0-9_]", re.UNICODE)


def estimate_tokens(text: str | None) -> int:
    if not text:
        return 0
    return max(1, len(_TOKEN_PATTERN.findall(text)))
```

Do not import `tokenize` from retrieval similarity for budgeting.

- [x] **Step 4: Make truncation budget-closed**

Update `_truncate_text(...)` so both whitespace and CJK paths re-check budget:

```python
def _truncate_text(text: str, max_tokens: int, *, suffix: str = " …") -> str:
    if max_tokens <= 0:
        return ""
    if estimate_tokens(text) <= max_tokens:
        return text
    units = text.split() if " " in text else list(text)
    suffix_units = estimate_tokens(suffix)
    if max_tokens <= suffix_units + 1:
        suffix = ""
        suffix_units = 0
    keep = max(1, min(len(units), max_tokens - suffix_units))
    while keep > 0:
        head = " ".join(units[:keep]) if " " in text else "".join(units[:keep])
        candidate = head + suffix
        if estimate_tokens(candidate) <= max_tokens:
            return candidate
        keep -= 1
    trimmed_suffix = suffix
    while trimmed_suffix and estimate_tokens(trimmed_suffix) > max_tokens:
        trimmed_suffix = trimmed_suffix[:-1]
    return trimmed_suffix
```

- [x] **Step 5: Verify affected suites**

Run:

```bash
uv run --extra dev pytest apps/api/tests/retrieval/ apps/api/tests/runtime/test_context_compaction.py apps/api/tests/benchmark/test_runner.py -q
```

**Acceptance:** Token budgeting is deterministic, stopword-preserving, CJK-aware, and truncation never exceeds the requested estimate.

**Status (2026-06-13):** Complete. `retrieval/packer.py` now uses an independent regex token-budget estimator that preserves stopwords, treats no-space CJK characters as budget units, keeps structured `key=value` facts compact enough for compaction retention, and truncates whitespace, CJK, ASCII, and mixed text with a final budget check. `retrieval/policy.py` records `TOKEN_ESTIMATOR_VERSION = "regex-stopword-cjk-v1"` in access policy snapshots so replay can classify future budget-policy drift. `case_9_over_budget_compaction` was retuned from 18 to 24 tokens to preserve the same semantic acceptance under the more precise estimator.

***

### Task H12: Summarizer LLM Provenance Validation Fix

**Goal:** Allow legitimate retained facts whose provenance comes from structured `must_retain_facts` while still rejecting invented facts and source ids.

**Files:**

- Modify: `apps/api/app/memory/summarizer_provider.py:262-304`
- Test: `apps/api/tests/memory/test_summarizer_provider.py`
- Test: `apps/api/tests/runtime/test_summarizer_fallback.py`
- [x] **Step 1: Add failing validation tests**

```python
def test_validate_result_allows_must_retain_fact_provenance_not_present_in_block_provenance():
    fact = RetainedFact(
        key="project.runtime",
        value="bun",
        source_memory_id="mem_1",
        provenance=Provenance(run_id="run_1", step_id="step_1", event_id="evt_1", state_node_id="node_1"),
    )
    request = SummarizeRequest(
        blocks=[],
        must_retain_facts=[fact],
        source_memory_ids=["mem_1"],
        source_event_ids=["evt_1"],
        source_state_node_ids=["node_1"],
        summary_budget_tokens=50,
        run_id="run_1",
        workspace_id="ws",
    )
    result = SummarizeResult(
        summary="project.runtime=bun",
        retained_facts=[fact],
        source_memory_ids=["mem_1"],
        source_event_ids=["evt_1"],
        source_state_node_ids=["node_1"],
        pre_tokens=10,
        post_tokens=2,
    )
    assert _validate_result(request, result).retained_facts == [fact]
```

Keep negative tests for invented source ids.

- [x] **Step 2: Run targeted tests and verify failure**

Run:

```bash
uv run --extra dev pytest apps/api/tests/memory/test_summarizer_provider.py -q
```

Expected: legitimate fact provenance can be rejected.

- [x] **Step 3: Seed allow-set from** **`must_retain_facts`** **provenance**

In `_validate_source_ids(...)`, after initializing allowed sets:

```python
for fact in request.must_retain_facts:
    if fact.source_memory_id is not None and fact.source_memory_id not in allowed_memory_ids:
        raise SummarizerValidationError("summarizer request has retained fact source_memory_id outside source_memory_ids")
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
```

Keep exact preservation checks for `result.source_*_ids` against request top-level source lists. `must_retain_facts` may seed provenance ids, but fact-local `source_memory_id` must already be present in `request.source_memory_ids`; otherwise the request/result pair is invalid rather than a reason to widen the memory allow-set.

- [x] **Step 4: Verify tests**

Run:

```bash
uv run --extra dev pytest apps/api/tests/memory/test_summarizer_provider.py apps/api/tests/runtime/test_summarizer_fallback.py -q
```

**Acceptance:** Valid structured provenance passes; invented fact/source/provenance still fails.

**Status (2026-06-13):** Complete. `_validate_source_ids(...)` now seeds allowed run/step/event/state-node ids from structured `must_retain_facts` provenance before checking returned retained facts, while fact-local `source_memory_id` must already be declared in `request.source_memory_ids` and top-level `source_*_ids` still must exactly preserve the request source lists. Invented source ids, changed fact provenance, and spaced invented summary facts such as `project.secret = token` remain rejected. Both LLM and rule fallback providers pass through `_validate_result(...)`.

***

### Task H13: State-Machine Boundary Hardening

**Goal:** State-tree transitions should never silently leave rolled\_back nodes active, return ghost nodes, or misreport rollback degeneracy.

**Status (2026-06-13):** Complete. `apply_finish(...)` maps `StepStatus.rolled_back` to `StateNodeStatus.rolled_back`; `finish_step(...)` and `rollback_branch(...)` now raise `StateTreeError` for missing referenced state nodes, including corrupt steps with `state_node_id=None`, instead of returning ghost or degenerate state. Post-review tests lock that these validations happen before step-status writes or buffered flush side effects.

**Files:**

- Modify: `apps/api/app/runtime/state_tree.py:91-100`
- Modify: `apps/api/app/runtime/memory_runtime.py:280-377`
- Test: `apps/api/tests/runtime/test_state_tree.py`
- Test: `apps/api/tests/runtime/test_memory_runtime_trace.py`
- Test: `packages/python-sdk/tests/test_backend_isomorphism.py`
- [x] **Step 1: Add failing tests**

```python
def test_apply_finish_maps_rolled_back_step_to_rolled_back_node():
    node = make_node(status=StateNodeStatus.active)
    state_tree.apply_finish(node, StepStatus.rolled_back)
    assert node.status == StateNodeStatus.rolled_back


@pytest.mark.asyncio
async def test_finish_step_missing_state_node_raises_state_tree_error():
    repo = InMemoryRepository()
    runtime = MemoryRuntime(repo)
    step = AgentStep(workspace_id="ws", run_id="run", state_node_id="missing_node")
    await repo.add_step(step)
    with pytest.raises(StateTreeError):
        await runtime.finish_step(FinishStepRequest(step_id=step.step_id, status=StepStatus.completed))
```

- [x] **Step 2: Run targeted tests and verify failure**

Run:

```bash
uv run --extra dev pytest apps/api/tests/runtime/test_state_tree.py apps/api/tests/runtime/test_memory_runtime_trace.py -k "rolled_back or missing_state_node" -q
```

Expected: rolled\_back mapping missing and ghost node behavior occurs.

- [x] **Step 3: Update pure state transition**

In `apply_finish(...)`:

```python
elif step_status in (StepStatus.cancelled, StepStatus.rolled_back):
    node.status = StateNodeStatus.rolled_back
```

- [x] **Step 4: Replace ghost-node return with explicit error**

In `MemoryRuntime.finish_step(...)`, if `step.state_node_id` is missing or points to no node, raise `StateTreeError` before status writes or flush side effects:

```python
if not step.state_node_id or node is None:
    raise StateTreeError(f"state node not found for step: {step.step_id}")
```

Return `state_node=node` only when it is real. H4 should already map this to HTTP 400 / SDK `BadRequestError`.

- [x] **Step 5: Clarify rollback missing-node behavior**

Choose strict behavior for corrupted state:

```python
if not step.state_node_id or target_node is None:
    raise StateTreeError(f"state node not found for rollback step: {step.step_id}")
```

If preserving the old degenerate step-only rollback is required for compatibility, return a result with a metadata warning and accurately document that no node was rolled. Prefer strict error because ROADMAP §13.3 calls out ghost/inconsistent state.

- [x] **Step 6: Verify affected suites**

Run:

```bash
uv run --extra dev pytest apps/api/tests/runtime/test_state_tree.py apps/api/tests/runtime/test_memory_runtime_trace.py packages/python-sdk/tests/test_backend_isomorphism.py -q
```

**Acceptance:** rolled\_back finish maps to rolled\_back state; missing state-node corruption is explicit, side-effect-free, and backend-equivalent.

***

### Task H14: Whole-Memory Benchmark Snapshot and Restore

**Goal:** Benchmark strategy comparisons must stay fair when retrieval or future reflection code mutates fields beyond `access_count`.

**Files:**

- Modify: `apps/api/app/benchmark/runner.py`
- Test: `apps/api/tests/benchmark/test_runner.py`
- [x] **Step 1: Add failing drift-detection tests**

```python
@pytest.mark.asyncio
async def test_workspace_memory_snapshot_restores_all_mutable_retrieval_fields():
    repo = InMemoryRepository()
    mem = MemoryItem(workspace_id="ws_snap", memory_type=MemoryType.episodic, content="marker", access_count=1, trust_score=0.7, freshness_score=0.8)
    await repo.add_memory(mem)
    snapshot = await _snapshot_workspace_memories(repo, "ws_snap")
    mem.access_count = 9
    mem.trust_score = 0.1
    mem.freshness_score = 0.2
    mem.last_accessed_at = datetime.now(timezone.utc)
    await repo.update_memory(mem)
    await _restore_workspace_memories(repo, "ws_snap", snapshot)
    restored = await repo.get_memory(mem.memory_id)
    assert restored.access_count == 1
    assert restored.trust_score == 0.7
    assert restored.freshness_score == 0.8
    assert restored.last_accessed_at is None
```

Add a side-effect pollution guard: after taking a snapshot, insert a new memory in the same workspace to simulate a future scheduler/retrieval-side write, then assert restore fails loudly (preferred) rather than silently letting the next strategy see extra memory. The repository protocol does not currently expose `delete_memory`, so benchmark comparison should treat `current_ids - snapshot_ids` as an invariant violation.

```python
@pytest.mark.asyncio
async def test_workspace_memory_restore_rejects_new_memories_created_after_snapshot():
    repo = InMemoryRepository()
    await repo.add_memory(MemoryItem(workspace_id="ws_snap", memory_type=MemoryType.episodic, content="original"))
    snapshot = await _snapshot_workspace_memories(repo, "ws_snap")
    await repo.add_memory(MemoryItem(workspace_id="ws_snap", memory_type=MemoryType.episodic, content="polluting new memory"))
    with pytest.raises(RuntimeError, match="created during benchmark retrieval"):
        await _restore_workspace_memories(repo, "ws_snap", snapshot)
```

- [x] **Step 2: Run tests and verify failure**

Run:

```bash
uv run --extra dev pytest apps/api/tests/benchmark/test_runner.py -k "snapshot" -q
```

Expected: helper does not exist or only restores `access_count`.

- [x] **Step 3: Replace access-count-only snapshot helpers**

In `benchmark/runner.py`, implement:

```python
async def _snapshot_workspace_memories(repo: Repository, workspace_id: str) -> dict[str, MemoryItem]:
    return {m.memory_id: m.model_copy(deep=True) for m in await repo.list_memories(workspace_id=workspace_id)}


async def _restore_workspace_memories(repo: Repository, workspace_id: str, snapshot: dict[str, MemoryItem]) -> None:
    current = {m.memory_id: m for m in await repo.list_memories(workspace_id=workspace_id)}
    created = sorted(set(current) - set(snapshot))
    if created:
        raise RuntimeError(f"memories created during benchmark retrieval: {created}")
    missing = sorted(set(snapshot) - set(current))
    if missing:
        raise RuntimeError(f"memories missing from benchmark workspace snapshot: {missing}")
    for original in snapshot.values():
        await repo.update_memory(original.model_copy(deep=True))
```

Keep stable case seeding unchanged. This restores existing seeded memories and fails if retrieval/strategy code creates new memories during comparison; benchmark should not have write-side effects during strategy retrieval.

- [x] **Step 4: Update** **`_run_case(...)`** **orchestration**

Take the snapshot immediately after `case.seed(...)`, then restore before every strategy.

- [x] **Step 5: Verify benchmark suite and reproducibility**

Run:

```bash
uv run --extra dev pytest apps/api/tests/benchmark/test_runner.py -q
uv run python -m app.benchmark.runner --output-dir reports
```

Expected: benchmark acceptance remains all true.

**Acceptance:** Benchmark fairness no longer assumes retrieval mutates only `access_count`; restore also detects any memory created after the snapshot and fails the benchmark rather than contaminating later strategies.

**Status (2026-06-13):** Complete. Benchmark strategy setup now snapshots full workspace `MemoryItem` rows after seeding, restores them before each strategy, and fails loudly if any strategy/retrieval-side path creates new memories in the benchmark workspace after the snapshot or removes/moves a snapshot memory out of the workspace.

***

### Task H15: Schema Compatibility and Migration Policy

**Goal:** Make migration compatibility explicit before adding provider registry, key ontology, scheduler, or policy snapshot schema changes.

**Files:**

- Modify: `apps/api/tests/storage/test_migrations.py`
- Possibly add: `apps/api/tests/storage/fixtures/` for fixture metadata or JSON rows
- Docs update: `docs/design/ROADMAP.md:285`
- [x] **Step 1: Add migration policy tests**

Add tests that verify every new migration file satisfies:

```python
def test_migrations_declare_revision_down_revision_and_downgrade_policy():
    for path in migration_files():
        text = path.read_text()
        assert "revision =" in text
        assert "down_revision =" in text
        assert "def upgrade()" in text
        assert "def downgrade()" in text
```

For schema additions with non-null fields, require server defaults or backfill statements without hardcoding a specific migration number (H5/H9 may be split or combined):

```python
def test_new_non_nullable_columns_have_defaults_or_backfill():
    for path in migration_files():
        text = path.read_text()
        if "op.add_column" in text and "nullable=False" in text:
            assert "server_default" in text or "op.execute" in text
```

- [x] **Step 2: Add optional PostgreSQL upgrade test guard**

If the repo already has DB test settings, add an integration test marked with `pytest.mark.postgres` that runs `alembic upgrade head` against a disposable database. If not configured, keep this as a skipped test with an explicit skip reason when `MEMTRACE_TEST_DATABASE_URL` is absent:

```python
pytest.skip("MEMTRACE_TEST_DATABASE_URL not set; migration declaration tests still run")
```

- [x] **Step 3: Run storage tests**

Run:

```bash
uv run --extra dev pytest apps/api/tests/storage/test_migrations.py -q
```

**Acceptance:** Future schema work has machine-checked defaults/backfill/downgrade declarations, with optional real upgrade coverage when PostgreSQL is available.

**Status (2026-06-13):** Complete. Migration tests now iterate all Alembic version files, accept typed revision declarations, require revision/down-revision/upgrade/downgrade declarations, enforce defaults/backfills for newly added non-null columns, and provide an optional `MEMTRACE_TEST_DATABASE_URL`-guarded PostgreSQL `alembic upgrade head` smoke test.

***

### Task H16: Redacted Trace Bundle Export / Schema Validation

**Goal:** Provide a safe debug artifact for reproducing access/run issues without leaking raw secrets.

**Scope for this plan:** implement redacted `export_run_bundle`, `export_access_bundle`, and `validate_bundle_schema` only. Do not implement write-import into production repositories in this slice; import semantics create id/workspace collisions, redaction-trust, and schema-evolution decisions that are larger than §13 hardening.

**Files:**

- Modify or add under: `apps/api/app/observability/`
- Modify: `apps/api/app/runtime/memory_runtime.py` facade methods if needed
- Modify: `apps/api/app/api/routes.py` if exposing HTTP endpoints
- Modify: `packages/python-sdk/src/memtrace_sdk/cli.py` if exposing CLI command
- Test: `apps/api/tests/observability/test_trace_bundle.py`
- Test: `packages/python-sdk/tests/test_cli.py`
- [x] **Step 1: Add bundle redaction tests**

```python
@pytest.mark.asyncio
async def test_trace_bundle_export_redacts_secret_event_and_memory_content(tmp_path):
    runtime = MemoryRuntime(InMemoryRepository())
    run = await runtime.start_run(StartRunRequest(workspace_id="ws_bundle", session_id="s", task="bundle"))
    step = await runtime.start_step(StartStepRequest(run_id=run.run_id, name="step"))
    await runtime.write_event(
        WriteEventRequest(step_id=step.step_id, role=EventRole.user, type=EventType.message, content="password is hunter2")
    )
    bundle = await runtime.export_trace_bundle(run_id=run.run_id, redacted=True)
    payload = json.dumps(bundle.model_dump(mode="json"), ensure_ascii=False)
    assert "hunter2" not in payload
    assert "[REDACTED]" in payload
```

- [x] **Step 2: Implement minimal bundle DTO**

Add a Pydantic model with versioned schema:

```python
class TraceBundle(_Base):
    schema_version: str = "trace-bundle-v1"
    redacted: bool = True
    runs: list[AgentRun] = Field(default_factory=list)
    steps: list[AgentStep] = Field(default_factory=list)
    events: list[AgentEvent] = Field(default_factory=list)
    state_nodes: list[StateNode] = Field(default_factory=list)
    memories: list[MemoryItem] = Field(default_factory=list)
    access_logs: list[MemoryAccessLog] = Field(default_factory=list)
    gate_logs: list[MemoryGateLog] = Field(default_factory=list)
    profile_events: list[ProfileEvent] = Field(default_factory=list)
    compaction_logs: list[ContextCompactionLog] = Field(default_factory=list)
```

- [x] **Step 3: Export with redaction-first copies**

Use `memory.secrets.redact()` for event content, memory content/summary/value where textual, context/gate/report payloads. Preserve ids and policy snapshot fields.

- [x] **Step 4: Add validation-only schema check only if needed**

For this hardening batch, `validate_bundle_schema(...)` may validate schema and return counts without writing production stores. Do not add write-import behavior here. If future work implements writing, it must require explicit `workspace_id_prefix`, id-collision handling, and local-only defaults.

- [x] **Step 5: Verify tests**

Run:

```bash
uv run --extra dev pytest apps/api/tests/observability/test_trace_bundle.py packages/python-sdk/tests/test_cli.py -q
```

**Acceptance:** Exported bundle contains enough ids/logs for local reproduction and no raw secret text when `redacted=True`; validation can inspect bundle shape/counts, but no production write-import path is introduced.

**Status (2026-06-13):** Complete. `observability/trace_bundle.py` adds `TraceBundle`, `TraceBundleValidation`, redacted run/access exports, and validation-only schema checks. `MemoryRuntime` exposes the read-only facade methods. Tests cover event/memory redaction, access-centered gate/memory inclusion, schema counts, and unsupported schema rejection.

***

### Task H17: Deterministic Dogfood Agent Scenarios

**Goal:** Demonstrate and continuously test MemTrace as an agent runtime through realistic, deterministic flows rather than only unit-level fixtures.

**Files:**

- Modify: `examples/simple_agent/main.py` or add focused scripts under `examples/dogfood/`
- Modify: `packages/python-sdk/tests/test_examples_smoke.py`
- Possibly modify: `scripts/reproduce.sh`
- [x] **Step 1: Add smoke tests for three scenarios**

Scenarios:

1. coding-agent recovery: failed `npm test` → rollback → `bun test` success → later retrieval avoids repeating npm;
2. multi-session project constraint: session 2 retrieves project runtime/package manager from session 1;
3. destructive failure sanitized: `rm -rf` style failure yields sanitized avoided attempt and never raw command.

Test shape:

```python
def test_dogfood_coding_agent_scenario_outputs_safe_recovery():
    result = subprocess.run([sys.executable, "examples/dogfood/coding_agent.py"], check=True, text=True, capture_output=True)
    assert "variant_2 avoids npm" in result.stdout
    assert "bun test" in result.stdout
```

- [x] **Step 2: Implement deterministic scenario scripts**

Use `MemTrace.in_memory(...)`, not real LLMs or network. Keep outputs short and stable.

- [x] **Step 3: Wire reproduction script only after smoke tests pass**

If adding to `scripts/reproduce.sh`, ensure runtime stays fast and deterministic.

No `scripts/reproduce.sh` change was needed: the dogfood scripts are covered by `packages/python-sdk/tests/test_examples_smoke.py`, while `reproduce.sh` remains focused on deterministic generated reports.

- [x] **Step 4: Verify examples**

Run:

```bash
uv run --package memtrace-sdk --extra dev pytest packages/python-sdk/tests/test_examples_smoke.py -q
bash scripts/reproduce.sh
```

**Acceptance:** Dogfood scripts prove runtime-level behavior without external dependencies and without raw unsafe output.

**Status (2026-06-13):** Complete. Added deterministic no-network scripts for coding-agent recovery, multi-session project-constraint carryover, and destructive-failure sanitization under `examples/dogfood/`, with SDK smoke coverage.

***

### Task H18: Documentation and Project Memory Closeout

**Goal:** Keep resume/project-state recovery accurate and mark completed §13 slices without stale next-action references.

**Files:**

- Modify: `docs/design/ROADMAP.md:255-306`
- Modify: `.ai/PROJECT_STATE.md`
- Modify: `.ai/REQUIREMENTS.md`
- Modify: `.ai/IMPLEMENTATION_PLAN.md`
- Modify: `.ai/PITFALLS.md`
- Possibly modify: `README.md` if strategy/auth/user-facing behavior changed.
- [x] **Step 1: Update ROADMAP §13 task checkboxes**

After each batch lands, tick only the specific completed bullets. Keep incomplete §13.4 items unchecked.

- [x] **Step 2: Update project memory**

Record:

- implemented task batch;
- key files changed;
- exact verification commands and pass counts;
- next recommended action.
- [x] **Step 3: Update pitfalls**

Add any new traps discovered during implementation, especially around auth default-off, policy snapshot hash stability, timeout-only-around-trace semantics, and benchmark token-count changes.

- [x] **Step 4: Run final verification**

Run:

```bash
uv run --extra dev python -m compileall -q apps/api/app packages/python-sdk/src examples
uv run --extra dev pytest -q
uv run python -m app.benchmark.runner --output-dir reports
bash scripts/reproduce.sh
```

Expected: compile passes, full pytest passes, benchmark acceptance remains all true, reproducibility script passes.

**Acceptance:** A fresh `resume项目进展` points to the correct next slice and does not claim §13 complete until all selected sub-batches are implemented and verified.

**Status (2026-06-13):** Complete after H15-H17 implementation and final verification; resume-facing project memory now points beyond §13 to §10 Provider Registry / §11 Controlled Memory Key Ontology, with I7 still deferred.

***

### Future hardening candidates after H1-H18

These are intentionally not part of the current implementation plan, but should be retained as follow-up candidates if §13 hardening continues after closeout:

- **H19 optional — Error code taxonomy:** document stable HTTP/SDK public error classes/codes (`BadRequest`, `NotFound`, `Unauthorized`, `Forbidden`, `Conflict`) without broadening implementation scope.
- **H20 optional — Local report/bundle retention policy:** document that generated observability reports and trace bundles may contain sensitive operational data, default all bundle exports to redacted mode, and require an explicit unsafe flag for any future raw export.

***

## 4. Batch-Level Verification Matrix

### After Batch A1 — Safety-floor closure

```bash
uv run --extra dev pytest apps/api/tests/retrieval/ -q
uv run --extra dev pytest apps/api/tests/benchmark/test_runner.py -q
```

### After Batch A2 — Lightweight auth

```bash
uv run --extra dev pytest apps/api/tests/api/ -q
uv run --package memtrace-sdk --extra dev pytest packages/python-sdk/tests/test_http_backend.py packages/python-sdk/tests/test_cli.py -q
```

### After Batch B1 — Runtime error/state boundaries

```bash
uv run --package memtrace-sdk --extra dev pytest packages/python-sdk/tests/test_backend_isomorphism.py packages/python-sdk/tests/test_http_backend.py -q
uv run --extra dev pytest apps/api/tests/runtime/ apps/api/tests/api/test_observability.py -q
```

### After Batch B2 — Atomic event append

```bash
uv run --extra dev pytest apps/api/tests/runtime/test_memory_runtime_trace.py apps/api/tests/storage/test_migrations.py -q
uv run --extra dev pytest apps/api/tests/runtime/ apps/api/tests/api/ -q
```

### After Batch B3 — Timeout semantics

```bash
uv run --extra dev pytest apps/api/tests/retrieval/test_retrieval_flow.py apps/api/tests/retrieval/test_retrieval_trace.py apps/api/tests/observability/test_replay.py -q
```

### After Batch C — Determinism/schema alignment

```bash
uv run --extra dev pytest apps/api/tests/observability/test_replay.py apps/api/tests/storage/test_migrations.py -q
```

### After Batch D1 — Policy snapshot

```bash
uv run --extra dev pytest apps/api/tests/retrieval/test_retrieval_trace.py apps/api/tests/observability/test_replay.py apps/api/tests/storage/test_migrations.py -q
```

### After Batch D2 — Conformance suite

```bash
uv run --extra dev pytest apps/api/tests/conformance/ apps/api/tests/retrieval/test_retrieval_trace.py apps/api/tests/observability/test_replay.py -q
```

### After Batch E1 — Benchmark fairness

```bash
uv run --extra dev pytest apps/api/tests/benchmark/test_runner.py -q
uv run python -m app.benchmark.runner --output-dir reports
```

### After Batch E2 — Precision/robustness

```bash
uv run --extra dev pytest apps/api/tests/retrieval/ apps/api/tests/runtime/ apps/api/tests/memory/test_summarizer_provider.py apps/api/tests/benchmark/test_runner.py -q
uv run python -m app.benchmark.runner --output-dir reports
```

### Final closeout

```bash
uv run --extra dev python -m compileall -q apps/api/app packages/python-sdk/src examples
uv run --extra dev pytest -q
uv run python -m app.benchmark.runner --output-dir reports
bash scripts/reproduce.sh
```

***

## 5. Migration Plan

### Migration boundary for H5

- No new unique index is needed in `0006_security_consistency_hardening`: `0001_initial` already enforces `(run_id, sequence_no)` with `uq_event_run_seq`.
- `0006_security_consistency_hardening` records the H4/H5/H6/H13 hardening boundary without adding a duplicate same-column constraint under a second name.
- If a developer database lacks `uq_event_run_seq`, treat it as schema drift and fail loudly rather than silently creating a second differently named constraint or rewriting trace order.

### Migration needed for H9

- Add nullable/default-compatible fields to access logs:
  - `policy_version` string nullable or default `retrieval-policy-v1`;
  - `policy_hash` string nullable;
  - `policy_snapshot` JSONB default `{}`.
- Existing old accesses with empty policy snapshot should replay with `policy_snapshot_missing` warning rather than `policy_drift` critical failure.

### Migration not needed for H8

- Migration `0005_context_compaction` already creates the intended compound index. H8 aligns ORM metadata to the migration.

***

## 6. Risk Register

| Risk                                                             |   Tasks | Mitigation                                                                                                                                                                                            |
| ---------------------------------------------------------------- | ------: | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Redaction changes token counts and benchmark averages            | H1, H11 | Assert acceptance booleans and safety invariants; update numeric snapshots only when deterministic and justified.                                                                                     |
| `variant_1` metrics improve/change after risk policy restoration |      H2 | Document as security correction; keep six-strategy order and explanation.                                                                                                                             |
| Auth breaks local quickstart                                     |      H3 | Default `auth_enabled=False`; add default-open API test.                                                                                                                                              |
| Exception mapping hides internal bugs as client errors           | H4, H13 | Map only known `StateTreeError`, `RunNotFoundError`, `StepNotFoundError`; let unexpected exceptions remain 500.                                                                                       |
| Atomic event API touches protocol widely                         |      H5 | Add new `append_event(...)` first; migrate runtime callsite; keep old methods temporarily for compatibility; SQL uses namespaced advisory lock + bounded retry with unique-index backstop.            |
| Timeout cancellation causes minimal/full access split-brain      |      H6 | Apply `wait_for` only to trace construction; persist a minimal access only when trace times out; successful trace persistence happens outside the timeout window without background shield semantics. |
| Policy snapshot contains non-deterministic or secret values      |      H9 | Hash sorted JSON; include provider capability names only, never API keys or environment values.                                                                                                       |
| Conformance suite becomes brittle                                |     H10 | Layer non-bypassable invariants separately from strategy-specific invariants; encode stable lifecycle, workspace, redaction, backend error mapping, and replay side-effect-free contracts.            |
| Migration tests become environment-dependent                     |     H15 | Keep declaration tests always-on; guard live PostgreSQL upgrade tests behind explicit env var.                                                                                                        |
| Trace bundle becomes a schema product too early                  |     H16 | Version bundle schema, implement export + schema validation only, default to redacted export, and defer write-import.                                                                                 |

***

## 7. Self-Review Checklist

- Spec coverage: every ROADMAP §13.1, §13.2, §13.3, and §13.4 item has at least one task: H1-H3, H4-H8, H11-H14, H9-H10/H15-H17 respectively.
- Security coverage: positive context, negative evidence, reports/bundles, SDK/CLI HTTP tokens, and strategy gate contracts are all covered.
- Consistency coverage: SQL/InMemory ordering, atomic event sequence, timeout access persistence, runtime/HTTP/in-process error semantics, replay drift semantics, migration schema alignment are covered.
- Determinism coverage: policy hash, gate tie-breaks, benchmark snapshot, token estimator, replay no-side-effect conformance are covered.
- Scope check: full multi-tenant governance, Redis/Celery, real reflection scheduler, provider registry, key ontology, advanced storage, and UI are explicitly excluded.
- Placeholder scan: no task uses open-ended “fill later” instructions; each task includes files, tests, implementation shape, commands, and acceptance.
