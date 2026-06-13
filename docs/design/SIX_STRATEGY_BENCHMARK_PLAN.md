# 6-Strategy Benchmark + Eval-Table Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand the deterministic benchmark from 4 to the full 6 strategies declared in `docs/design/ROADMAP.md` §7 (no-memory / long-context / vector / state-aware / +gate / +reflection), prove each layer's benefit with a new reflection-retention case, and persist every benchmark run into the `eval_cases / eval_runs / eval_results` tables (ROADMAP §7 "benchmark report 落库，配合 §2 eval 表").

**Architecture:** Two new `RetrievalStrategy` values are added: `long_context` (an all-context baseline that includes every retrievable workspace memory, disables the hard/risk/state gate policies, admits failed/rolled_back branches, and uses an effectively unbounded context budget — demonstrating token bloat + failed-branch contamination; it still flows through the same controller/gate/logging pipeline for observability and still preserves the `_RETRIEVABLE_STATUSES` lifecycle filter) and `variant_3` (variant_2's full gate/state + a deterministic *reflection-lite / retention-rerank* of accepted memories that prioritizes high-retention memories using `trust/freshness/access_count`, where `access_count` is a usage-frequency signal `variant_2`'s soft-ranking ignores). A new `case_12` deterministically shows `variant_3` retains a high-retention memory under a tight budget where `variant_2` drops it.

**Benchmark fairness (critical):** `variant_3` reads `access_count`, but `retrieve_context` mutates accepted memories by bumping `access_count` (`RetrievalController._bump_access_counts`). Because `_run_case` runs all strategies sequentially against the same seeded repo with `variant_3` last, the runner must snapshot seed-time `access_count` after `case.seed(...)` and restore it before each strategy retrieval; otherwise `variant_3` observes side effects from the earlier strategies and the reflection contrast becomes order-dependent. Task 4a establishes this isolation before `variant_3` lands.

The benchmark runner additionally writes one `EvalRunRecord` (with `finished_at`) plus per-case `EvalCaseRecord` and per-(case,strategy) `EvalResultRecord` rows, reusing the existing Phase 3-A eval schema (no new migration). Each `EvalResultRecord.passed=True` means the benchmark row executed successfully (per-strategy task quality is stored in `metrics["task_success"]`); overall benchmark pass/fail is expressed by `EvalRunRecord.config["acceptance"]["passed"]`. The real §3.2 Reflection/Forgetting scheduler will later supersede reflection-lite; ROADMAP is annotated accordingly.

**Tech Stack:** Python 3 / FastAPI / Pydantic v2 / SQLAlchemy 2.0 async, `uv` workspace, pytest. All changes stay deterministic (no LLM, no external embedding) so `scripts/reproduce.sh` keeps passing.

---

## Background before this plan

- Strategy enum: `RetrievalStrategy` in [models.py](apps/api/app/runtime/models.py#L141-L147) has `baseline_0`, `baseline_1`, `variant_1`, `variant_2`.
- Per-strategy gate behavior: `GateConfig.for_strategy(...)` in [gate.py](apps/api/app/retrieval/gate.py#L47-L71).
- Candidate selection + accepted sort + packing: `RetrievalController.trace(...)` / `_select_candidates(...)` in [controller.py](apps/api/app/retrieval/controller.py#L181-L512). `baseline_0` short-circuits to an empty context at [controller.py#L208-L216](apps/api/app/retrieval/controller.py#L208-L216). Accepted memories are sorted by `final_score` desc at [controller.py#L275](apps/api/app/retrieval/controller.py#L275).
- Benchmark cases + strategy list: [cases.py](apps/api/app/benchmark/cases.py#L444-L485) (`CASES`, `ALL_STRATEGIES`).
- Evaluator metrics: `CaseMetrics` + `evaluate_case(...)` in [evaluator.py](apps/api/app/benchmark/evaluator.py#L54-L269).
- Runner summary/markdown/acceptance/persistence: [runner.py](apps/api/app/benchmark/runner.py).
- Dashboard benchmark summary: `_benchmark_summary_from_records(...)` in [memory_runtime.py](apps/api/app/runtime/memory_runtime.py#L943-L999).
- Eval schema + repository methods already exist: `EvalCaseRecord` / `EvalRunRecord` / `EvalResultRecord` in [models.py](apps/api/app/runtime/models.py#L385-L414); repository protocol + `InMemoryRepository` + `SqlRepository` `add_eval_case/run/result`, `list_eval_*` already implemented (see [repository.py](apps/api/app/runtime/repository.py#L123-L398)); ORM tables `eval_cases/eval_runs/eval_results` shipped in migration `0004_phase3a_observability`. **No new migration is required.**

## Test/verification commands (reference)

- Targeted: `uv run --extra dev pytest <path>::<test> -q`
- Full regression: `uv run --extra dev pytest -q`
- Compile: `uv run --extra dev python -m compileall -q apps/api/app`
- Benchmark + reproducibility: `uv run python -m app.benchmark.runner --output-dir reports && bash scripts/reproduce.sh`

## Count changes locked in by this plan (for cross-task consistency)

- Strategies: 4 → **6** (`baseline_0`, `long_context`, `baseline_1`, `variant_1`, `variant_2`, `variant_3`).
- Benchmark cases: 11 → **12** (adds `case_12_reflection_retention`).
- Benchmark results & accesses: 44 → **72** (12 cases × 6 strategies).
- Memory runs seeded by benchmark: 13 → **14** (`case_12` seeds exactly 1 run).
- New acceptance checks: `variant_3_retains_high_value_memory_under_budget` + `long_context_shows_token_bloat` (total checks 10 → **12**).
- New metric: `reflection_retention_hit` (+ `reflection_retention_hit_present`), surfaced as `reflection_retention_hit_rate`.

---

## Task 1: Add `long_context` and `variant_3` strategy enum values

**Files:**
- Modify: `apps/api/app/runtime/models.py:141-147`
- Test: `apps/api/tests/runtime/test_models_strategy.py` (create)

- [x] **Step 1: Write the failing test**

Create `apps/api/tests/runtime/test_models_strategy.py`:

```python
"""6-strategy enum coverage."""
from __future__ import annotations

from app.runtime.models import RetrievalStrategy


def test_retrieval_strategy_has_six_members():
    values = {s.value for s in RetrievalStrategy}
    assert values == {
        "baseline_0",
        "long_context",
        "baseline_1",
        "variant_1",
        "variant_2",
        "variant_3",
    }
```

- [x] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest apps/api/tests/runtime/test_models_strategy.py -q`
Expected: FAIL (`long_context` / `variant_3` not defined; set mismatch).

- [x] **Step 3: Edit the enum**

In `apps/api/app/runtime/models.py`, replace the `RetrievalStrategy` body:

```python
class RetrievalStrategy(str, Enum):
    """Strategy modes used by demo/benchmark to prove the differentiation.

    Ordered as the 6-strategy benchmark layers (ROADMAP §7):
    no-memory -> long-context -> vector -> state-aware -> +gate -> +reflection.
    """

    baseline_0 = "baseline_0"  # no memory
    long_context = "long_context"  # all-context baseline: same gate/log path, policies disabled, include_all + unbounded budget
    baseline_1 = "baseline_1"  # vector/lexical memory only, ignores state + gate
    variant_1 = "variant_1"  # state-aware rerank, failed branch only downweighted
    variant_2 = "variant_2"  # state-aware + hard/risk admission gate
    variant_3 = "variant_3"  # variant_2 + deterministic reflection-lite retention rerank
```

- [x] **Step 4: Run test to verify it passes**

Run: `uv run --extra dev pytest apps/api/tests/runtime/test_models_strategy.py -q`
Expected: PASS

---

## Task 2: Gate config for the two new strategies + reflection-rerank flag

**Files:**
- Modify: `apps/api/app/retrieval/gate.py:36-71`
- Test: `apps/api/tests/retrieval/test_gate.py` (append)

**Design:** `long_context` reuses the all-policies-off config (identical to `baseline_1`: no hard/risk policy, no state match, failed/rolled_back admitted). Its distinct "stuff everything" behavior is implemented in the controller (Task 3), not the gate. `variant_3` reuses `variant_2`'s full gate (hard + risk + state + failure learning) and adds `enable_reflection_rerank=True`, consumed by the controller (Task 4).

- [x] **Step 1: Write the failing tests**

Append to `apps/api/tests/retrieval/test_gate.py`:

```python
def test_long_context_config_matches_baseline_1_all_policies_off():
    cfg = GateConfig.for_strategy(RetrievalStrategy.long_context)
    assert cfg.enable_hard_policy is False
    assert cfg.enable_risk_policy is False
    assert cfg.enable_state_match is False
    assert cfg.allow_failed_branch is True
    assert cfg.allow_rolled_back is True
    assert cfg.enable_failure_learning is False
    assert cfg.enable_reflection_rerank is False


def test_variant_3_config_is_variant_2_plus_reflection_rerank():
    cfg = GateConfig.for_strategy(RetrievalStrategy.variant_3)
    assert cfg.enable_hard_policy is True
    assert cfg.enable_risk_policy is True
    assert cfg.enable_state_match is True
    assert cfg.enable_failure_learning is True
    assert cfg.enable_reflection_rerank is True


def test_reflection_rerank_enabled_only_for_variant_3():
    for strategy in (
        RetrievalStrategy.baseline_0,
        RetrievalStrategy.long_context,
        RetrievalStrategy.baseline_1,
        RetrievalStrategy.variant_1,
        RetrievalStrategy.variant_2,
    ):
        assert GateConfig.for_strategy(strategy).enable_reflection_rerank is False
    assert GateConfig.for_strategy(RetrievalStrategy.variant_3).enable_reflection_rerank is True
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run --extra dev pytest apps/api/tests/retrieval/test_gate.py -k "long_context or variant_3 or reflection_rerank" -q`
Expected: FAIL (`enable_reflection_rerank` attribute missing; new strategies fall through to default config).

- [x] **Step 3: Edit `GateConfig`**

In `apps/api/app/retrieval/gate.py`, add the field to the dataclass (after `enable_failure_learning`):

```python
    enable_failure_learning: bool = False
    enable_reflection_rerank: bool = False
```

Then update `for_strategy` so `baseline_1` and `long_context` share the all-off config and `variant_3` extends `variant_2`:

```python
    @classmethod
    def for_strategy(cls, strategy: RetrievalStrategy) -> "GateConfig":
        if strategy in (RetrievalStrategy.baseline_1, RetrievalStrategy.long_context):
            return cls(
                enable_hard_policy=False,
                enable_risk_policy=False,
                enable_state_match=False,
                allow_failed_branch=True,
                allow_rolled_back=True,
                enable_failure_learning=False,
            )
        if strategy == RetrievalStrategy.variant_1:
            return cls(
                enable_hard_policy=False,
                enable_risk_policy=False,
                enable_state_match=True,
                allow_failed_branch=True,
                allow_rolled_back=True,
                enable_failure_learning=False,
            )
        if strategy == RetrievalStrategy.variant_2:
            return cls(enable_failure_learning=True)
        if strategy == RetrievalStrategy.variant_3:
            return cls(enable_failure_learning=True, enable_reflection_rerank=True)
        # baseline_0 has no candidates, but keep its config contract explicit:
        # neither failure learning nor reflection rerank is enabled.
        return cls(enable_failure_learning=False)
```

- [x] **Step 4: Run tests to verify they pass**

Run: `uv run --extra dev pytest apps/api/tests/retrieval/test_gate.py -q`
Expected: PASS (new tests pass; existing gate tests unchanged).

---

## Task 3: Controller `long_context` candidate stuffing + unbounded budget

**Files:**
- Modify: `apps/api/app/retrieval/controller.py:181-228` (trace setup), `apps/api/app/retrieval/controller.py:464-512` (`_select_candidates`)
- Test: `apps/api/tests/retrieval/test_retrieval_flow.py` (append)

**Design:** `long_context` includes every retrievable workspace memory (skip the `rel > 0.0` filter and the `[:top_k]` truncation) and packs with an effectively unbounded budget so nothing is dropped — demonstrating maximal token overhead and failed-branch contamination. It still flows through the normal controller/gate/logging path for observability; it is not a separate no-gate retrieval path — its policy relaxation lives in `GateConfig` (Task 2). Workspace scoping is unchanged, so cross-workspace leakage stays impossible by construction. `_RETRIEVABLE_STATUSES` lifecycle filtering still applies (ROADMAP cross-cutting constraint ①).

> **Test robustness:** Do NOT assert on `rel == 0` to prove `baseline_1` excludes an off-topic memory. Vector retrieval is on by default (`retrieval_use_vector=True`) and the deterministic hashed embedding can produce a nonzero cosine for unrelated text, so a `rel == 0` filter is not a stable test signal. Instead use `top_k=1`: `long_context` ignores `top_k` and includes all retrievable memories, while `baseline_1` is `top_k`-limited and keeps only the single most relevant block, which is reliably the on-topic memory rather than the off-topic one.

- [x] **Step 1: Write the failing test**

Append to `apps/api/tests/retrieval/test_retrieval_flow.py` (reuse the file's existing imports for `MemoryRuntime`, `InMemoryRepository`, request/enum/model types; add any missing imports near the top of the test file):

```python
async def test_long_context_includes_all_memories_while_top_k_limits_baseline_1():
    repo = InMemoryRepository()
    rt = MemoryRuntime(repo, default_workspace_id="ws_lc")
    run = await rt.start_run(StartRunRequest(session_id="s", task="run tests", workspace_id="ws_lc"))
    s1 = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="planning"))
    await rt.write_event(WriteEventRequest(
        run_id=run.run_id, step_id=s1.step_id, role=EventRole.user,
        event_type=EventType.message, content="这个项目使用 Bun，不用 Node.js"))
    await rt.finish_step(FinishStepRequest(run_id=run.run_id, step_id=s1.step_id, status=StepStatus.completed))
    # An on-topic memory (overlaps the query) and an off-topic one.
    await repo.add_memory(MemoryItem(
        workspace_id="ws_lc", run_id=run.run_id, memory_type=MemoryType.episodic,
        content="bun test runner configuration notes for this project",
        summary="bun test runner notes", branch_status=BranchStatus.completed))
    await repo.add_memory(MemoryItem(
        workspace_id="ws_lc", run_id=run.run_id, memory_type=MemoryType.episodic,
        content="zzqqxx unrelated trivia about ancient pottery glazing techniques",
        summary="unrelated trivia", branch_status=BranchStatus.completed))
    s2 = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="debugging", goal="choose runner"))

    # top_k=1: long_context ignores top_k and includes all; baseline_1 keeps only
    # the single most-relevant block, which is the on-topic memory, not pottery.
    lc = await rt.retrieve_context(RetrievalRequest(
        run_id=run.run_id, step_id=s2.step_id, query="bun test runner",
        strategy=RetrievalStrategy.long_context, top_k=1))
    b1 = await rt.retrieve_context(RetrievalRequest(
        run_id=run.run_id, step_id=s2.step_id, query="bun test runner",
        strategy=RetrievalStrategy.baseline_1, top_k=1))

    lc_text = " ".join(b.content.lower() for b in lc.context_blocks)
    b1_text = " ".join(b.content.lower() for b in b1.context_blocks)
    assert "pottery" in lc_text           # long_context includes the off-topic memory
    assert "pottery" not in b1_text        # baseline_1 is top_k-limited to the on-topic block
    assert lc.profile["accepted_count"] > b1.profile["accepted_count"]
    assert lc.profile["actual_tokens"] >= b1.profile["actual_tokens"]
```

- [x] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest apps/api/tests/retrieval/test_retrieval_flow.py::test_long_context_includes_all_memories_while_top_k_limits_baseline_1 -q`
Expected: FAIL (`long_context` currently behaves like `baseline_1` and is truncated to `top_k=1`, so `pottery` is excluded and `accepted_count` is equal).

- [x] **Step 3: Add `include_all` to `_select_candidates`**

In `apps/api/app/retrieval/controller.py`, change the `_select_candidates` signature and body. Update the signature line:

```python
    async def _select_candidates(
        self,
        *,
        workspace_id: str,
        run_id: str,
        query: str,
        top_k: int,
        include_all: bool = False,
    ) -> list[RetrievalCandidateTrace]:
```

Replace the scoring loop's filter + truncation tail (currently the block from `for m in memories:` through `return scored[:top_k]`) with:

```python
        scored: list[RetrievalCandidateTrace] = []
        for m in memories:
            if m.status not in _RETRIEVABLE_STATUSES:
                continue  # skip superseded/archived/dormant/deleted lifecycle states
            lex = lexical_similarity(query, m.content)
            vec = vector_scores.get(m.memory_id, 0.0)
            rel = round(w_lex * lex + w_vec * vec, 6)
            # project constraints are always relevant to coding queries
            if m.memory_type.value == "project" and rel == 0.0:
                rel = 0.2
            if rel > 0.0 or include_all:
                scored.append(
                    RetrievalCandidateTrace(
                        memory=m,
                        lexical_score=lex,
                        vector_score=vec,
                        relevance_score=rel,
                    )
                )
        scored.sort(key=lambda c: c.relevance_score, reverse=True)
        if include_all:
            return scored
        return scored[:top_k]
```

- [x] **Step 4: Thread `long_context` through `trace(...)`**

In `apps/api/app/retrieval/controller.py`, inside `trace(...)`, compute the long-context flag after the request/default budget is read:

```python
        budget = request.token_budget or self._default_budget
        long_context = request.strategy == RetrievalStrategy.long_context
```

Then update the `_select_candidates(...)` call (around line 223) to pass `include_all`:

```python
        candidates = await self._select_candidates(
            workspace_id=workspace_id,
            run_id=request.run_id,
            query=request.query,
            top_k=request.top_k,
            include_all=long_context,
        )
```

After the initial pack, if `long_context` sees `pack_result.pre_compaction_tokens > budget`, repack with `budget = pack_result.pre_compaction_tokens` and persist that effective budget. This preserves the normal gate/logging path while making the all-context baseline genuinely unbounded for the current candidate set instead of relying on a fixed large sentinel.

- [x] **Step 5: Run test to verify it passes**

Run: `uv run --extra dev pytest apps/api/tests/retrieval/test_retrieval_flow.py::test_long_context_includes_all_memories_while_top_k_limits_baseline_1 -q`
Expected: PASS

- [x] **Step 6: Run retrieval regression**

Run: `uv run --extra dev pytest apps/api/tests/retrieval/ -q`
Expected: PASS (existing flows unaffected; `include_all` defaults False).

---

## Task 4a: Benchmark runner `access_count` snapshot/restore isolation

**Files:**
- Modify: `apps/api/app/benchmark/runner.py:114-158` (`_run_case` + add snapshot/restore helpers)
- Test: `apps/api/tests/benchmark/test_runner.py` (append)

**Design:** `_run_case` seeds once then runs every strategy against the same repo. `retrieve_context` bumps `access_count` on accepted memories (`RetrievalController._bump_access_counts`), so a strategy mutates state the next strategy reads. This is harmless today but breaks `variant_3`'s retention rerank (Task 4b), which reads `access_count`. Snapshot seed-time access counts after `case.seed(...)` and restore them before every strategy retrieval, so all six strategies see the identical seeded state. Establish this isolation BEFORE `variant_3` lands so its benchmark contrast is order-independent.

- [x] **Step 1: Write the failing test**

Append to `apps/api/tests/benchmark/test_runner.py`:

```python
from app.benchmark.runner import _restore_access_counts, _snapshot_access_counts
from app.runtime.models import MemoryItem, MemoryType


async def test_snapshot_restore_resets_access_counts():
    repo = InMemoryRepository()
    mem = await repo.add_memory(MemoryItem(
        workspace_id="ws_snap", memory_type=MemoryType.episodic,
        content="snapshot target", access_count=3))
    snapshot = await _snapshot_access_counts(repo, workspace_id="ws_snap")
    assert snapshot[mem.memory_id] == 3

    # Simulate a strategy bumping the access count.
    stored = (await repo.list_memories(workspace_id="ws_snap"))[0]
    stored.access_count = 9
    await repo.update_memory(stored)

    await _restore_access_counts(repo, snapshot, workspace_id="ws_snap")
    restored = (await repo.list_memories(workspace_id="ws_snap"))[0]
    assert restored.access_count == 3
```

- [x] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest apps/api/tests/benchmark/test_runner.py::test_snapshot_restore_resets_access_counts -q`
Expected: FAIL (`_snapshot_access_counts` / `_restore_access_counts` do not exist).

- [x] **Step 3: Add the helpers and wire them into `_run_case`**

In `apps/api/app/benchmark/runner.py`, add the helpers (before `_run_case`):

```python
async def _snapshot_access_counts(repo: Repository, *, workspace_id: str) -> dict[str, int]:
    """Capture seed-time access counts so each strategy sees identical state."""
    return {
        mem.memory_id: mem.access_count
        for mem in await repo.list_memories(workspace_id=workspace_id)
    }


async def _restore_access_counts(repo: Repository, snapshot: dict[str, int], *, workspace_id: str) -> None:
    """Restore access counts mutated by a prior strategy's retrieval bump."""
    for mem in await repo.list_memories(workspace_id=workspace_id):
        if mem.memory_id in snapshot and mem.access_count != snapshot[mem.memory_id]:
            mem.access_count = snapshot[mem.memory_id]
            await repo.update_memory(mem)
```

In `_run_case`, snapshot after seeding and restore before each strategy's retrieval. Change the body so it reads:

```python
async def _run_case(case: BenchmarkCase, workspace_id: str, repo: Repository | None = None) -> list[CaseMetrics]:
    repo = repo or InMemoryRepository()
    runtime = MemoryRuntime(repo, default_workspace_id=workspace_id)
    seed = await case.seed(runtime, workspace_id)
    access_count_snapshot = await _snapshot_access_counts(repo, workspace_id=seed.workspace_id)

    metrics: list[CaseMetrics] = []
    for strategy in ALL_STRATEGIES:
        await _restore_access_counts(repo, access_count_snapshot, workspace_id=seed.workspace_id)
        ctx = await runtime.retrieve_context(
            RetrievalRequest(
                run_id=seed.run_id,
                step_id=seed.step_id,
                query=seed.query,
                strategy=strategy,
                token_budget=seed.extra.get("token_budget"),
                top_k=seed.extra.get("top_k", 10),
            )
        )
        # ... rest of the loop body is unchanged ...
```

(Keep the remainder of the existing loop body — `inspect_access`, `get_profile`, `list_compaction_logs`, `evaluate_case(...)` — exactly as-is.)

- [x] **Step 4: Run test to verify it passes**

Run: `uv run --extra dev pytest apps/api/tests/benchmark/test_runner.py::test_snapshot_restore_resets_access_counts -q`
Expected: PASS

- [x] **Step 5: Run the benchmark suite (no behavior change yet)**

Run: `uv run --extra dev pytest apps/api/tests/benchmark/test_runner.py -q`
Expected: PASS (snapshot/restore is a no-op for the current strategies since none reads `access_count`).

---

## Task 4b: Controller `variant_3` reflection-lite retention rerank

**Files:**
- Modify: `apps/api/app/retrieval/controller.py:274-277` (accepted sort) + add a module-level helper
- Test: `apps/api/tests/retrieval/test_retrieval_flow.py` (append)

**Design:** `variant_3` runs `variant_2`'s full gate and state matching, but re-orders the *accepted* (positive) memories by a blended key `0.5*final_score + 0.5*retention_score(mem)` instead of `final_score` alone. `retention_score` deterministically rewards high-retention memories using `trust_score`, `freshness_score`, and `access_count` — including `access_count`, a usage-frequency signal `variant_2`'s soft-ranking ignores. Under a tight budget the packer keeps earlier-ordered ordinary blocks, so a high-retention memory survives where `variant_2` would drop it. This is a deterministic placeholder for the real §3.2 Reflection/Forgetting scheduler.

> **Scope of the rerank:** the rerank changes the *accepted memory order before packing*. The packer still applies its block-type priority (`_TYPE_ORDER` / protected tier) and sorts stably, so the retention signal primarily reorders ordinary blocks of the same priority class — in practice episodic memories — and must NOT override protected / `project_constraints` ordering. `case_12` (Task 6) is therefore built from same-type (episodic) memories so the contrast is driven by the rerank, not by cross-type priority.

- [x] **Step 1: Write the failing test**

Append to `apps/api/tests/retrieval/test_retrieval_flow.py`:

```python
async def _seed_reflection_fixture(strategy):
    """Fresh repo per strategy so variant_2's access_count bump never leaks into
    the variant_3 retrieval (mirrors the Task 4a runner isolation)."""
    repo = InMemoryRepository()
    rt = MemoryRuntime(repo, default_workspace_id="ws_ref")
    run = await rt.start_run(StartRunRequest(session_id="s", task="recall fact", workspace_id="ws_ref"))
    s1 = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="planning"))
    await rt.finish_step(FinishStepRequest(run_id=run.run_id, step_id=s1.step_id, status=StepStatus.completed))
    # High-retention memory: frequently used (access_count high), distinctive marker,
    # but LOWER query relevance than the noise memories.
    await repo.add_memory(MemoryItem(
        workspace_id="ws_ref", run_id=run.run_id, memory_type=MemoryType.episodic,
        content="users service RETAIN-CRITICAL-FACT", summary="users service retain-critical-fact",
        branch_status=BranchStatus.completed, access_count=10))
    # Noise: HIGHER query relevance (repeats query tokens), never used (access_count 0).
    for i in range(6):
        await repo.add_memory(MemoryItem(
            workspace_id="ws_ref", run_id=run.run_id, memory_type=MemoryType.episodic,
            content="users service reference users service reference note",
            summary=f"users service reference note {i}",
            branch_status=BranchStatus.completed, access_count=0))
    s2 = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="debugging", goal="recall critical fact"))
    return await rt.retrieve_context(RetrievalRequest(
        run_id=run.run_id, step_id=s2.step_id, query="users service reference",
        strategy=strategy, token_budget=32, top_k=20))


async def test_variant_3_retains_high_retention_memory_where_variant_2_drops_it():
    v2 = await _seed_reflection_fixture(RetrievalStrategy.variant_2)
    v3 = await _seed_reflection_fixture(RetrievalStrategy.variant_3)

    v2_text = " ".join(b.content.lower() for b in v2.context_blocks)
    v3_text = " ".join(b.content.lower() for b in v3.context_blocks)
    assert "retain-critical-fact" not in v2_text  # +gate drops the high-retention fact
    assert "retain-critical-fact" in v3_text       # +reflection retains it
```

- [x] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest apps/api/tests/retrieval/test_retrieval_flow.py::test_variant_3_retains_high_retention_memory_where_variant_2_drops_it -q`
Expected: FAIL (`variant_3` currently sorts identically to `variant_2`, so the marker is dropped in both). Observed RED: marker was absent from `variant_3` and only the active-state / compaction notice blocks survived.

> **If the test does not cleanly fail/pass after Step 3** (token estimates differ from assumptions): tune only the test fixture so exactly one episodic block fits — increase `token_budget` slightly or shorten each episodic `content` so a single block (~half the budget) survives and a second does not. The invariant to preserve: noise has higher query relevance than the marker memory, and the marker memory has the higher `access_count`. Do not change production code to chase the fixture.

- [x] **Step 3: Add the retention helper and the reflection-aware sort**

In `apps/api/app/retrieval/controller.py`, add a module-level helper near the other module functions (e.g. just below `_RETRIEVABLE_STATUSES`):

```python
def retention_score(mem: MemoryItem) -> float:
    """Deterministic reflection-lite retention priority.

    Rewards trustworthy, fresh, and frequently-used memories. ``access_count``
    is a usage-frequency signal the variant_2 soft-ranking does not use; it is
    capped at 10 accesses to keep the score in [0, 1]. This is a placeholder for
    the real ROADMAP §3.2 Reflection/Forgetting scheduler.
    """
    usage = min(1.0, mem.access_count / 10.0)
    return round(0.4 * mem.trust_score + 0.3 * mem.freshness_score + 0.3 * usage, 6)
```

Then replace the accepted-sort line (currently `accepted_outcomes.sort(key=lambda o: o.final_score, reverse=True)` at ~line 275) with:

```python
        # rank accepted by final score desc; variant_3 reflection-lite blends a
        # retention priority so high-retention memories survive tight budgets.
        if config.enable_reflection_rerank:
            accepted_outcomes.sort(
                key=lambda o: round(0.5 * o.final_score + 0.5 * retention_score(o.memory), 6),
                reverse=True,
            )
        else:
            accepted_outcomes.sort(key=lambda o: o.final_score, reverse=True)
```

- [x] **Step 4: Run test to verify it passes**

Run: `uv run --extra dev pytest apps/api/tests/retrieval/test_retrieval_flow.py::test_variant_3_retains_high_retention_memory_where_variant_2_drops_it -q`
Expected: PASS. Implemented with `token_budget=32` in the fixture so protected state + one ordinary episodic block + compaction notice can fit while still dropping later ordinary blocks.

- [x] **Step 5: Run retrieval regression**

Run: `uv run --extra dev pytest apps/api/tests/retrieval/ -q`
Expected: PASS (variant_2 and others keep `final_score` sort). Observed after review hardening: `85 passed`; compile check `uv run --extra dev python -m compileall -q apps/api/app/retrieval/controller.py` also passed. Review hardening added a clamp regression test for `retention_score(...)` so abnormal trust/freshness/access_count inputs cannot produce scores outside `[0, 1]`. Final Task 4b review checked logic/business semantics, security, robustness, performance, test coverage, benchmark fairness, negative-evidence separation, packer protected/project ordering, and memory sync; no P0/P1/P2 defects remain. Report: `/tmp/mem-trace_task4b_review/report.html`.

---

## Task 5: Expand `ALL_STRATEGIES` to 6 and fix existing count assertions

**Files:**
- Modify: `apps/api/app/benchmark/cases.py:480-485`
- Modify: `apps/api/tests/benchmark/test_runner.py` (count assertions), `apps/api/tests/api/test_dashboard.py` (count assertions)

**Design:** Add the two new strategies to `ALL_STRATEGIES` in benchmark-layer order. This immediately turns 11 cases × 4 = 44 into 11 × 6 = 66 results until Task 6 adds case_12 (→ 72). Update the count assertions in two existing test files in the SAME task so the suite stays green; the per-(case,strategy) acceptance checks only read `baseline_0/baseline_1/variant_2` rows, so they do not regress.

- [x] **Step 1: Update `ALL_STRATEGIES`**

In `apps/api/app/benchmark/cases.py`, replace the `ALL_STRATEGIES` list:

```python
ALL_STRATEGIES = [
    RetrievalStrategy.baseline_0,
    RetrievalStrategy.long_context,
    RetrievalStrategy.baseline_1,
    RetrievalStrategy.variant_1,
    RetrievalStrategy.variant_2,
    RetrievalStrategy.variant_3,
]
```

- [x] **Step 2: Update existing benchmark-count assertions**

In `apps/api/tests/benchmark/test_runner.py`:
- `test_run_benchmark_writes_markdown_and_json_reports`: change `assert len(report["results"]) == 44  # 11 cases x 4 strategies` to `assert len(report["results"]) == 66  # 11 cases x 6 strategies` (Task 6 will bump 11→12 cases / 66→72 results in this same assertion).
- `test_run_benchmark_persists_cases_and_results`: change `assert len(results) == 44` to `assert len(results) == 66`, and change the strategy-set assertion to:

```python
    assert {r.strategy for r in results} == {
        "baseline_0", "long_context", "baseline_1", "variant_1", "variant_2", "variant_3",
    }
```

In `apps/api/tests/api/test_dashboard.py`, in `test_dashboard_tables_endpoint_exposes_benchmark_and_runtime_rows`:
- `assert len(payload["accesses"]) == 44` → `assert len(payload["accesses"]) == 66`
- `assert len(payload["benchmark_results"]) == 44` → `assert len(payload["benchmark_results"]) == 66`
- leave `runs == 13` and `benchmark_cases == 11` for now (Task 6 bumps them to 14 / 12).

- [x] **Step 3: Run the two affected test files**

Run: `uv run --extra dev pytest apps/api/tests/benchmark/test_runner.py apps/api/tests/api/test_dashboard.py -q`
Expected: PASS (counts now 66; acceptance still passes because variant-specific checks are unaffected).

---

## Task 6: Add `case_12_reflection_retention` + evaluator reflection metric

**Files:**
- Modify: `apps/api/app/benchmark/evaluator.py:54-269` (add metric fields + scoring)
- Modify: `apps/api/app/benchmark/cases.py` (add `_seed_reflection_retention` + `CASES` entry)
- Modify: `apps/api/app/benchmark/runner.py:138-157` (pass new evaluator kwargs)
- Test: `apps/api/tests/benchmark/test_runner.py` (append unit test) + update counts

**Design:** `case_12` seeds one frequently-used high-retention memory (distinctive marker, `access_count=10`) plus six low-retention but higher-relevance noise memories, under a tight token budget. The evaluator scores `reflection_retention_hit = 1` when the marker reached context. The reflection benefit is then provable: `variant_3` hits, `variant_2` misses.

- [x] **Step 1: Write the failing evaluator unit test**

Append to `apps/api/tests/benchmark/test_runner.py`:

```python
def test_evaluator_scores_reflection_retention_hit_from_marker_presence():
    ctx_hit = MemoryContext(
        access_id="acc_ref_hit",
        context_blocks=[ContextBlock(type="episodic", content="users service RETAIN-CRITICAL-FACT")],
        profile={}, warnings=[],
    )
    ctx_miss = MemoryContext(
        access_id="acc_ref_miss",
        context_blocks=[ContextBlock(type="episodic", content="users service reference note")],
        profile={}, warnings=[],
    )
    hit = evaluate_case(
        case_id="case_12_reflection_retention", strategy=RetrievalStrategy.variant_3,
        ctx=ctx_hit, access=None, profile_events=[],
        reflection_marker="retain-critical-fact", reflection_case=True,
    )
    miss = evaluate_case(
        case_id="case_12_reflection_retention", strategy=RetrievalStrategy.variant_2,
        ctx=ctx_miss, access=None, profile_events=[],
        reflection_marker="retain-critical-fact", reflection_case=True,
    )
    assert hit.reflection_retention_hit_present == 1
    assert hit.reflection_retention_hit == 1
    assert miss.reflection_retention_hit == 0
```

- [x] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest apps/api/tests/benchmark/test_runner.py::test_evaluator_scores_reflection_retention_hit_from_marker_presence -q`
Expected: FAIL (`evaluate_case` has no `reflection_marker`/`reflection_case` kwargs; `CaseMetrics` has no `reflection_retention_hit`). Observed: failed with `TypeError: evaluate_case() got an unexpected keyword argument 'reflection_marker'`.

- [x] **Step 3: Add metric fields + scoring to the evaluator**

In `apps/api/app/benchmark/evaluator.py`, add two fields to `CaseMetrics` (after the `sanitized_notice_present_present` field, before `warnings`):

```python
    reflection_retention_hit: int = 0
    reflection_retention_hit_present: int = 0
```

Add two parameters to `evaluate_case(...)` (after `sanitized_failure_case: bool = False`):

```python
    reflection_marker: Optional[str] = None,
    reflection_case: bool = False,
```

Add the scoring block just before `return m` (after the `sanitized_failure_case` block):

```python
    # Reflection-lite retention: the high-retention marker reached context.
    if reflection_case:
        joined = " ".join(block.content.lower() for block in ctx.context_blocks)
        marker = (reflection_marker or "").lower()
        m.reflection_retention_hit_present = 1
        m.reflection_retention_hit = 1 if marker and marker in joined else 0
```

- [x] **Step 4: Run the evaluator unit test**

Run: `uv run --extra dev pytest apps/api/tests/benchmark/test_runner.py::test_evaluator_scores_reflection_retention_hit_from_marker_presence -q`
Expected: PASS. Observed: **1 passed**.

- [x] **Step 5: Add the `case_12` seeder + register it**

In `apps/api/app/benchmark/cases.py`, add the seeder after `_seed_sanitized_failed_destructive_attempt` (before the `CASES` list):

```python
# --------------------------------------------------------------------------- #
# Case 12: reflection-lite retention (variant_3 keeps a high-retention memory
# under a tight budget where variant_2 drops it).
# --------------------------------------------------------------------------- #
async def _seed_reflection_retention(rt: MemoryRuntime, ws: str) -> SeedResult:
    run = await rt.start_run(StartRunRequest(session_id="bench", task="recall critical fact", workspace_id=ws))
    s1 = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="planning"))
    await rt.finish_step(FinishStepRequest(run_id=run.run_id, step_id=s1.step_id, status=StepStatus.completed))

    # High-retention but lower-relevance memory (frequently used).
    await rt._repo.add_memory(  # noqa: SLF001 - deterministic benchmark seeding
        MemoryItem(
            workspace_id=ws, run_id=run.run_id, memory_type=MemoryType.episodic,
            content="users service RETAIN-CRITICAL-FACT",
            summary="users service retain-critical-fact",
            branch_status=BranchStatus.completed, access_count=10,
        )
    )
    # Low-retention, higher-relevance noise (never used).
    for i in range(6):
        await rt._repo.add_memory(  # noqa: SLF001 - deterministic benchmark seeding
            MemoryItem(
                workspace_id=ws, run_id=run.run_id, memory_type=MemoryType.episodic,
                content="users service reference users service reference note",
                summary=f"users service reference note {i}",
                branch_status=BranchStatus.completed, access_count=0,
            )
        )
    s2 = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="debugging", goal="recall critical fact"))
    return SeedResult(
        run.run_id, s2.step_id, "users service reference", ws,
        extra={
            "token_budget": 32,
            "top_k": 20,
            "reflection_marker": "retain-critical-fact",
            "reflection_case": True,
        },
    )
```

Append the case to `CASES`:

```python
    BenchmarkCase("case_12_reflection_retention", "Reflection-lite retention",
                  "A frequently-used high-retention memory is retained under a tight budget by +reflection where +gate drops it.",
                  _seed_reflection_retention),
```

- [x] **Step 6: Pass the new kwargs through the runner**

In `apps/api/app/benchmark/runner.py`, inside `_run_case(...)`, add to the `evaluate_case(...)` call (after `sanitized_failure_case=...`):

```python
                reflection_marker=seed.extra.get("reflection_marker"),
                reflection_case=seed.extra.get("reflection_case", False),
```

- [x] **Step 7: Bump case/result counts to 12 cases / 72 results**

In `apps/api/tests/benchmark/test_runner.py`:
- `test_run_benchmark_writes_markdown_and_json_reports`: `len(report["cases"]) == 11` → `== 12`; add `"case_12_reflection_retention"` to the `{c["case_id"] ...}` set; `len(report["results"]) == 66` → `== 72  # 12 cases x 6 strategies`.
- `test_run_benchmark_persists_cases_and_results`: `len(cases) == 11` → `== 12`; `len(results) == 66` → `== 72`.

In `apps/api/tests/api/test_dashboard.py`, `test_dashboard_tables_endpoint_exposes_benchmark_and_runtime_rows`:
- `len(payload["runs"]) == 13` → `== 14` (case_12 seeds exactly 1 run); update the inline comment to mention case 12 seeds one run.
- `len(payload["accesses"]) == 66` → `== 72`
- `len(payload["benchmark_cases"]) == 11` → `== 12`
- `len(payload["benchmark_results"]) == 66` → `== 72`

- [x] **Step 8: Run benchmark + dashboard tests**

Run: `uv run --extra dev pytest apps/api/tests/benchmark/test_runner.py apps/api/tests/api/test_dashboard.py -q`
Expected: PASS. Observed: **18 passed**.

- [x] **Step 9: Sanity-check the reflection contrast in the real benchmark**

Run:
```bash
uv run python -m app.benchmark.runner --output-dir reports && \
uv run python - <<'PY'
import json
rows = json.load(open("reports/benchmark_results.json"))["results"]
def hit(strategy):
    return next(r["reflection_retention_hit"] for r in rows
               if r["case_id"] == "case_12_reflection_retention" and r["strategy"] == strategy)
print("variant_2", hit("variant_2"), "variant_3", hit("variant_3"))
assert hit("variant_2") == 0 and hit("variant_3") == 1
print("OK: reflection contrast holds")
PY
```
Expected: prints `variant_2 0 variant_3 1` then `OK`. Observed: `variant_2 0 variant_3 1` and `OK: reflection contrast holds`. Initial fixture budget `10` was too tight for protected active-state/path plus compaction notice, so the final seeder uses `token_budget=32`; this tunes the fixture only, not production rerank code.

---

## Task 7: Surface the reflection metric in summary / markdown / acceptance

**Files:**
- Modify: `apps/api/app/benchmark/runner.py` (`_METRIC_FIELDS`, `_summarize`, `_write_markdown` header prose + columns, `_acceptance`)
- Test: `apps/api/tests/benchmark/test_runner.py` (append acceptance test)

- [x] **Step 1: Write the failing acceptance test**

Append to `apps/api/tests/benchmark/test_runner.py`:

```python
async def test_acceptance_includes_reflection_and_long_context_checks(tmp_path):
    report = await run_benchmark(output_dir=tmp_path)
    acc = report["acceptance"]
    assert acc["checks"]["variant_3_retains_high_value_memory_under_budget"] is True
    assert acc["checks"]["long_context_shows_token_bloat"] is True
    assert acc["passed"] is True
    assert report["summary"]["variant_3"]["reflection_retention_hit_rate"] == 1
    assert report["summary"]["variant_2"]["reflection_retention_hit_rate"] == 0
    overhead = {s: report["summary"][s]["avg_memory_token_overhead"] for s in report["strategies"]}
    assert overhead["long_context"] == max(overhead.values())
```

- [x] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev pytest apps/api/tests/benchmark/test_runner.py::test_acceptance_includes_reflection_and_long_context_checks -q`
Expected: FAIL (`reflection_retention_hit_rate` and the two new acceptance checks do not exist). Observed: failed with `KeyError: 'variant_3_retains_high_value_memory_under_budget'`.

- [x] **Step 3: Add the metric to `_METRIC_FIELDS`**

In `apps/api/app/benchmark/runner.py`, add `"reflection_retention_hit"` to `_METRIC_FIELDS` (after `"sanitized_notice_present"`).

- [x] **Step 4: Add the rate to `_summarize`**

In `_summarize(...)`, add inside the per-strategy dict (after `"sanitized_notice_rate": ...`):

```python
            "reflection_retention_hit_rate": _average(
                [r.reflection_retention_hit for r in rows if r.reflection_retention_hit_present]
            ),
```

- [x] **Step 5: Update the markdown header prose + add the summary column**

In `_write_markdown(...)`:
- Replace the hardcoded strategy sentence `"Deterministic benchmark for \`baseline_0\`, \`baseline_1\`, \`variant_1\`, and \`variant_2\`."` with:

```python
        "Deterministic benchmark for six retrieval strategies: "
        "`baseline_0`, `long_context`, `baseline_1`, `variant_1`, `variant_2`, and `variant_3`.",
```

- Add `reflection_retention_hit_rate` to the Summary header row and its `|---:|` separator, and add `{reflection_retention_hit_rate}` at the end of the per-strategy `.format(...)` summary line (the `**row` expansion already provides the value).

- [x] **Step 6: Add the acceptance checks**

In `_acceptance(...)`, add a `v3 = summary.get("variant_3", {})` lookup near the `v2`/`b1` lookups, then add these two entries to the `checks` dict (after `variant_2_sanitizes_destructive_failure_without_leakage`):

```python
        "variant_3_retains_high_value_memory_under_budget": (
            v3.get("reflection_retention_hit_rate", 0.0) == 1.0
            and v2.get("reflection_retention_hit_rate", 1.0) == 0.0
            and _case_present(results, "case_12_reflection_retention", "variant_3", "reflection_retention_hit_present")
            and _case_present(results, "case_12_reflection_retention", "variant_2", "reflection_retention_hit_present")
            and _case_metric(results, "case_12_reflection_retention", "variant_3", "reflection_retention_hit") == 1
            and _case_metric(results, "case_12_reflection_retention", "variant_2", "reflection_retention_hit") == 0
        ),
        "long_context_shows_token_bloat": (
            "long_context" in summary
            and "variant_2" in summary
            and summary["long_context"].get("avg_memory_token_overhead", 0.0)
            == max(row.get("avg_memory_token_overhead", 0.0) for row in summary.values())
            and summary["long_context"].get("avg_memory_token_overhead", 0.0)
            > summary["variant_2"].get("avg_memory_token_overhead", 0.0)
        ),
```

- [x] **Step 7: Run test to verify it passes**

Run: `uv run --extra dev pytest apps/api/tests/benchmark/test_runner.py -q`
Expected: PASS (all benchmark tests, including the two new acceptance checks). Observed: targeted Task 7 test passed; review-hardening negative tests now cover missing `variant_2` comparator and missing `case_12` present rows; final detailed review found no P0/P1/P2 defects after updating the Step 6 snippet to match the hardened implementation; `uv run --extra dev pytest apps/api/tests/benchmark/test_runner.py -q` -> **18 passed**.

---

## Task 8: Persist each benchmark run into the eval_* tables

**Files:**
- Modify: `apps/api/app/benchmark/runner.py` (`run_benchmark`, add `_persist_eval_records`)
- Test: `apps/api/tests/benchmark/test_runner.py` (append)

**Design:** When a repository is supplied, in addition to the existing `benchmark_cases`/`benchmark_results` persistence, write one `EvalRunRecord` (`finished_at` set, config carries strategies + summary + acceptance), one `EvalCaseRecord` per benchmark case (tagged `benchmark`), and one `EvalResultRecord` per (case, strategy) row. `EvalResultRecord.passed=True` means the row executed successfully — per-strategy task quality lives in `metrics["task_success"]`, and the overall benchmark verdict is `EvalRunRecord.config["acceptance"]["passed"]`. This reuses the Phase 3-A eval schema with no migration. Eval `add_*` methods upsert by id (SQL uses `merge`, InMemory overwrites), so case rows are stable across repeated runs while each run appends a fresh `eval_run_id` + its results. Task 11 review hardened repeatability by requiring each persisted benchmark invocation to use an isolated workspace prefix; otherwise fixed `bench_ws_{index}` workspaces let memories from an earlier run pollute the next run's candidate set and acceptance.

- [x] **Step 1: Write the failing tests**

Append to `apps/api/tests/benchmark/test_runner.py`:

```python
async def test_run_benchmark_persists_eval_records(tmp_path):
    repo = InMemoryRepository()
    await run_benchmark(output_dir=tmp_path, repo=repo)

    eval_cases = await repo.list_eval_cases()
    eval_runs = await repo.list_eval_runs()
    assert len(eval_cases) == 12
    assert len(eval_runs) == 1
    eval_run = eval_runs[0]
    assert eval_run.config["strategies"] == [
        "baseline_0", "long_context", "baseline_1", "variant_1", "variant_2", "variant_3",
    ]
    assert eval_run.config["acceptance"]["passed"] is True
    assert eval_run.finished_at is not None

    results = await repo.list_eval_results(eval_run_id=eval_run.eval_run_id)
    assert len(results) == 72  # 12 cases x 6 strategies
    assert {r.eval_case_id for r in eval_cases} >= {"case_12_reflection_retention"}
    assert any(
        r.eval_case_id == "case_12_reflection_retention"
        and str(r.strategy) in ("RetrievalStrategy.variant_3", "variant_3")
        and r.metrics["reflection_retention_hit"] == 1
        for r in results
    )


async def test_run_benchmark_eval_persistence_is_repeatable(tmp_path):
    repo = InMemoryRepository()
    first = await run_benchmark(output_dir=tmp_path / "a", repo=repo)
    second = await run_benchmark(output_dir=tmp_path / "b", repo=repo)

    # case_ids are stable -> upserted; each run appends a fresh run + its results.
    assert first["acceptance"]["passed"] is True
    assert second["acceptance"]["passed"] is True
    assert first["summary"] == second["summary"]
    assert len(await repo.list_eval_cases()) == 12
    assert len(await repo.list_eval_runs()) == 2
    assert len(await repo.list_eval_results()) == 144  # 2 runs x 72
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run --extra dev pytest apps/api/tests/benchmark/test_runner.py::test_run_benchmark_persists_eval_records apps/api/tests/benchmark/test_runner.py::test_run_benchmark_eval_persistence_is_repeatable -q`
Expected: FAIL (no eval rows are written). Observed: **2 failed** with `len(eval_cases) == 0`, proving no eval rows were written before Task 8 implementation.

- [x] **Step 3: Add `_persist_eval_records` and call it**

In `apps/api/app/benchmark/runner.py`, add the imports (extend the existing model import and add `datetime`):

```python
from datetime import datetime, timezone

from app.runtime.models import (
    BenchmarkCaseRecord,
    BenchmarkResultRecord,
    EvalCaseRecord,
    EvalResultRecord,
    EvalRunRecord,
    RetrievalRequest,
    RetrievalStrategy,
)
```

Add the new persistence function (after `_persist_results`):

```python
async def _persist_eval_records(
    repo: Repository,
    results: list[CaseMetrics],
    summary: dict[str, dict[str, float]],
    acceptance: dict[str, Any],
) -> None:
    """Persist the benchmark run into the eval_* tables (ROADMAP §7 / §2).

    ``passed=True`` records that the row executed; per-strategy task quality is
    in ``metrics["task_success"]`` and the overall verdict is in the run config.
    """
    eval_run = await repo.add_eval_run(
        EvalRunRecord(
            name="deterministic_benchmark",
            status="completed",
            finished_at=datetime.now(timezone.utc),
            config={
                "strategies": [s.value for s in ALL_STRATEGIES],
                "summary": summary,
                "acceptance": acceptance,
            },
        )
    )
    for case in CASES:
        await repo.add_eval_case(
            EvalCaseRecord(
                eval_case_id=case.case_id,
                name=case.name,
                description=case.description,
                tags=["benchmark"],
                config={"strategies": [s.value for s in ALL_STRATEGIES]},
            )
        )
    for row in results:
        await repo.add_eval_result(
            EvalResultRecord(
                eval_run_id=eval_run.eval_run_id,
                eval_case_id=row.case_id,
                run_id=None,
                strategy=row.strategy,
                metrics=row.as_dict(),
                passed=True,  # row executed; task quality is in metrics["task_success"]
            )
        )
```

In `run_benchmark(...)`, after computing `summary` and `acceptance`, persist eval records when a repo is supplied. Restructure the persistence tail so `summary` and `acceptance` are available:

```python
    summary = _summarize(results)
    acceptance = _acceptance(summary, results)
    if repo is not None:
        await _persist_results(repo, results)
        await _persist_eval_records(repo, results, summary, acceptance)

    payload: dict[str, Any] = {
        "cases": [
            {"case_id": c.case_id, "name": c.name, "description": c.description}
            for c in CASES
        ],
        "strategies": [s.value for s in ALL_STRATEGIES],
        "summary": summary,
        "results": [r.as_dict() for r in results],
        "metric_fields": list(_METRIC_FIELDS),
        "acceptance": acceptance,
    }
```

> Note: remove the now-duplicated earlier `if repo is not None: await _persist_results(repo, results)` block and the earlier standalone `summary = _summarize(results)` / `"acceptance": _acceptance(summary, results)` so `_persist_results`, `summary`, and `acceptance` are each computed exactly once.

- [x] **Step 4: Run tests to verify they pass**

Run: `uv run --extra dev pytest apps/api/tests/benchmark/test_runner.py::test_run_benchmark_persists_eval_records apps/api/tests/benchmark/test_runner.py::test_run_benchmark_eval_persistence_is_repeatable -q`
Expected: PASS. Observed: **2 passed**.

- [x] **Step 5: Run the full benchmark suite**

Run: `uv run --extra dev pytest apps/api/tests/benchmark/test_runner.py -q`
Expected: PASS (existing `benchmark_cases`/`benchmark_results` persistence unchanged; eval rows added). Observed: **20 passed**. Compile check `uv run --extra dev python -m compileall -q apps/api/app/benchmark/runner.py` also passed.

---

## Task 9: Surface the reflection rate in the dashboard benchmark summary

**Files:**
- Modify: `apps/api/app/runtime/memory_runtime.py:943-999` (`_benchmark_summary_from_records`)
- Test: `apps/api/tests/api/test_dashboard.py` (extend the existing field-comparison loop)

- [x] **Step 1: Update the dashboard summary builder**

In `apps/api/app/runtime/memory_runtime.py`, add to `_benchmark_summary_from_records(...)` (after `"sanitized_notice_rate": ...`):

```python
            "reflection_retention_hit_rate": _avg([
                float(r.get("reflection_retention_hit", 0)) for r in rows if r.get("reflection_retention_hit_present")
            ]),
```

- [x] **Step 2: Extend the dashboard parity assertion**

In `apps/api/tests/api/test_dashboard.py`, `test_dashboard_tables_endpoint_exposes_benchmark_and_runtime_rows`, add `"reflection_retention_hit_rate"` to the `for field in [...]` list that asserts dashboard summary equals the runner report summary.

- [x] **Step 3: Run the dashboard tests**

Run: `uv run --extra dev pytest apps/api/tests/api/test_dashboard.py -q`
Expected: PASS. Targeted RED before implementation: `uv run --extra dev pytest apps/api/tests/api/test_dashboard.py::test_dashboard_tables_endpoint_exposes_benchmark_and_runtime_rows -q` failed with `KeyError: 'reflection_retention_hit_rate'`. Targeted GREEN after implementation: same command -> **1 passed**. Dashboard suite: **3 passed**. Affected benchmark+dashboard suite: `uv run --extra dev pytest apps/api/tests/benchmark/test_runner.py apps/api/tests/api/test_dashboard.py -q` -> **23 passed**. Compile check: `uv run --extra dev python -m compileall -q apps/api/app/runtime/memory_runtime.py` -> passed. Final focused review rechecked dashboard/runner metric parity, present-flag filtering, dashboard JSON compatibility, test coverage, plan status, and project-memory freshness; result **0 P0 / 0 P1 / 0 P2**. Review artifacts: `/tmp/mem-trace_task9_final_review/report.html` / `/tmp/mem-trace_task9_final_review/report.md`.

---

## Task 10: Documentation — ROADMAP, reflection-lite supersede note, README

**Files:**
- Modify: `docs/design/ROADMAP.md` (§7 checkboxes, §3.2 supersede note, appendix step 7)
- Modify: `README.md:94-99` (strategy list)

- [x] **Step 1: Tick the §7 benchmark items**

In `docs/design/ROADMAP.md` §7 (around lines 139-140):
- Change `- [ ] **完整 6 策略对比**...` to `- [x] **完整 6 策略对比**...` and append: `已实现：strategies = no-memory(`baseline_0`) / long-context(`long_context`) / vector(`baseline_1`) / state-aware(`variant_1`) / +gate(`variant_2`) / +reflection(`variant_3`)；+reflection 为确定性 reflection-lite（retention_score 用 trust/freshness/access_count 重排 accepted），由 case_12 证明在紧预算下保留高价值记忆而 +gate 丢弃。`
- Change `- [ ] **benchmark report 落库**（配合 §2 eval 表）。` to `- [x] **benchmark report 落库**（配合 §2 eval 表）。`并注明：`run_benchmark(repo=...) 现额外写入 eval_run/eval_cases/eval_results（复用 Phase 3-A eval schema，无新迁移）。`

- [x] **Step 2: Add the reflection-lite supersede note under §3.2**

In `docs/design/ROADMAP.md` §3.2 (after the existing `- [ ] **决策分数分离**...` bullet at ~line 68), add:

```markdown
- [ ] **真实 Reflection 取代 reflection-lite**：§7 6 策略对比中的 `variant_3` 目前使用确定性 reflection-lite（`retention_score = 0.4*trust + 0.3*freshness + 0.3*min(1, access_count/10)`，仅对 accepted 记忆重排，见 `apps/api/app/retrieval/controller.py`）。它是占位实现，本调度器落地后应以真实 `retention_score / reflection_priority` 取代之，并让 `case_12_reflection_retention` 改由真实衰减/反思信号驱动。
```

- [x] **Step 3: Update appendix step 7 status**

In `docs/design/ROADMAP.md` appendix (line ~234), change step 7 from a pending bullet to completed:

```markdown
7. ~~**完整 6 策略对比 + benchmark 落库**（§7 主线）~~ ✅ **已完成 (2026-06-12)**：6 策略（含 `long_context` / `variant_3` reflection-lite）逐层量化；新增 `case_12_reflection_retention` 与 acceptance `variant_3_retains_high_value_memory_under_budget` + `long_context_shows_token_bloat`；benchmark 现额外落 `eval_*` 表，并已加固同一 repo 重复落库运行的 workspace 隔离；Task 11 已完成 full regression / reproducibility / report-shape / project-memory sync，当前 acceptance 为 12/12。**+reflection 为确定性占位，待 §3.2 调度器落地后取代**（见 §3.2）。原先的 §10/§11 Provider Registry / Key Ontology 候选已被 §13 安全与一致性加固（ADR-020）前置。
```

- [x] **Step 4: Update the README strategy list**

In `README.md` (lines ~94-97), replace the four-bullet strategy list with the six layers (use accurate `long_context` wording — it still runs through the same gate/logging path, only with policies disabled and an unbounded budget):

```markdown
- `baseline_0`: no memory.
- `long_context`: includes every retrievable workspace memory with hard/risk/state policies disabled and an effectively unbounded budget, exposing token bloat and failed-branch contamination while preserving the same trace/gate logging path.
- `baseline_1`: vector/lexical memory without state-aware isolation or admission gate.
- `variant_1`: state-aware retrieval.
- `variant_2`: state-aware retrieval plus admission gate.
- `variant_3`: state-aware + gate + deterministic reflection-lite / retention-rerank (placeholder for the ROADMAP §3.2 Reflection scheduler).
```

Review hardening: the adjacent README benchmark coverage sentence was also refreshed so it includes safe failure learning (`case_10`), sanitized destructive-failure handling (`case_11`), and `case_12_reflection_retention` instead of stopping at context compaction.

- [x] **Step 5: Verify docs reference the README command guard**

Run: `uv run --extra dev pytest apps/api/tests/integration/test_reproducibility.py -q`
Expected: PASS (guards README command drift; strategy prose edits do not affect commands). Observed: **4 passed**.

---

## Task 11: Full regression, benchmark acceptance, reproducibility, project-memory sync

**Files:**
- Modify: `.ai/PROJECT_STATE.md` (append a new Implemented + Latest Verification section)

- [x] **Step 1: Compile + full regression**

Run: `uv run --extra dev python -m compileall -q apps/api/app && uv run --extra dev pytest -q`
Expected: PASS (target count ≈ prior 285 + the new tests added across tasks; no failures).
Observed: **304 passed**.

- [x] **Step 2: Deterministic benchmark + reproducibility**

Run: `uv run python -m app.benchmark.runner --output-dir reports && bash scripts/reproduce.sh`
Expected: `acceptance.passed=true (12/12 checks true)` and the reproducibility baseline regenerates without error.
Observed: passed; printed `acceptance.passed=true (12/12 checks true)`.

- [x] **Step 3: Confirm the 6-strategy report shape**

Run:
```bash
uv run python - <<'PY'
import json
p = json.load(open("reports/benchmark_results.json"))
assert p["strategies"] == ["baseline_0","long_context","baseline_1","variant_1","variant_2","variant_3"], p["strategies"]
assert len(p["results"]) == 72, len(p["results"])
assert p["acceptance"]["checks"]["variant_3_retains_high_value_memory_under_budget"] is True
assert p["acceptance"]["checks"]["long_context_shows_token_bloat"] is True
# long_context should carry the highest average token overhead.
ov = {s: p["summary"][s]["avg_memory_token_overhead"] for s in p["strategies"]}
assert ov["long_context"] == max(ov.values()), ov
print("OK", ov)
PY
```
Expected: prints `OK` with `long_context` having the max token overhead.
Observed: `OK {'baseline_0': 0.0, 'long_context': 44.1667, 'baseline_1': 25.4167, 'variant_1': 25.4167, 'variant_2': 26.8333, 'variant_3': 26.5}`.

- [x] **Step 4: Update `.ai/PROJECT_STATE.md`**

Append a section summarizing: 6 strategies (`baseline_0/long_context/baseline_1/variant_1/variant_2/variant_3`), `variant_3` reflection-lite retention rerank, benchmark-runner `access_count` snapshot/restore isolation, `case_12_reflection_retention`, new acceptance `variant_3_retains_high_value_memory_under_budget` + `long_context_shows_token_bloat` (12/12 checks), 12 cases × 6 strategies = 72 results, eval-table persistence (`eval_run`/`eval_cases`/`eval_results`, no migration, repeatable), and the deferred note that the real §3.2 scheduler should later supersede reflection-lite. Record the exact verification commands/outputs from Steps 1-3. Update the tail "Next Recommended Action" to point at ROADMAP §10/§11 (Provider Registry / Key Ontology).
Observed: `.ai/PROJECT_STATE.md` now records Task 11 completion, exact verification outputs, six-strategy/72-row report shape, eval-table persistence, reflection-lite supersede note, and next recommended ROADMAP §10/§11.

**Task 11 review hardening:** detailed review found one P1 repeatability issue: persisted benchmark runs reused fixed `bench_ws_{index}` workspaces, so a second `run_benchmark(..., repo=same_repo)` could retrieve memories from the previous run and fail acceptance. Fixed by giving persisted benchmark invocations an isolated workspace prefix and hardening `test_run_benchmark_eval_persistence_is_repeatable` to require both reports to pass and deterministic summary fields to match while excluding timing-only latency fields. Final six-strategy review also found and fixed two P2 edge issues: `long_context` no longer relies on a fixed token sentinel and instead expands to the exact pre-compaction budget when needed; `variant_3` now persists its reflection-lite rerank score in `MemoryGateLog.final_score`, so replay original-view reconstruction can reuse the persisted ordering without recomputing retention from later-mutated memory state. Post-fix verification: targeted hardening tests passed, benchmark/dashboard/strategy suite **24 passed**, retrieval+replay suite **100 passed**, full regression **305 passed**, reproducibility **12/12**.

---

## Self-Review (completed by plan author)

**Spec coverage (ROADMAP §7):**
- "no memory / long-context / vector / state-aware / +gate / +reflection" → Tasks 1-4b add `long_context` + `variant_3`; existing `baseline_0/baseline_1/variant_1/variant_2` cover the other four (Task 5 wires all six).
- "逐层证明每个机制的收益" → Task 3 + the `long_context_shows_token_bloat` acceptance check (Task 7) prove long-context token bloat; the existing failed-branch contamination metrics continue to show the contamination contrast between `long_context`/`baseline_1` and the gated strategies. Task 6 `case_12` + the `variant_3_retains_high_value_memory_under_budget` check prove the +reflection layer; existing cases prove vector→state-aware→+gate.
- "+reflection 依赖 §3.2" → resolved via deterministic reflection-lite (`access_count`-aware retention rerank) with benchmark `access_count` isolation (Task 4a) and an explicit §3.2 supersede note (Task 10), per the user's decision to add it back into ROADMAP.
- "benchmark report 落库（配合 §2 eval 表）" → Task 8 writes `eval_run/eval_cases/eval_results` (with a repeatable-persistence test).

**Placeholder scan:** No TBD/TODO; every code step shows full code; the one fixture-tuning note (Task 4b Step 2 / Task 6 Step 9) gives a concrete invariant, not a placeholder.

**Type/name consistency:** `retention_score` (controller helper) and `enable_reflection_rerank` (GateConfig field) are used identically across Tasks 2/4b. `_snapshot_access_counts` / `_restore_access_counts` are consistent across Tasks 4a and the 4b fixture rationale. `reflection_retention_hit` / `reflection_retention_hit_present` (CaseMetrics) and `reflection_marker` / `reflection_case` (evaluate_case kwargs) are consistent across Tasks 6/7/9. Strategy order `baseline_0, long_context, baseline_1, variant_1, variant_2, variant_3` is identical in enum (Task 1), `ALL_STRATEGIES` (Task 5), eval config + report assertions (Tasks 8/11), and README (Task 10). Acceptance check count: 10 → 12 (`variant_3_retains_high_value_memory_under_budget` + `long_context_shows_token_bloat`), applied uniformly in Tasks 7/10/11.

**Fairness review (per external review):** `variant_3`'s `access_count` dependency is isolated both in the benchmark runner (Task 4a snapshot/restore) and in the Task 4b unit test (fresh repo per strategy), so the reflection contrast is order-independent. The `long_context` test uses `top_k=1` rather than `rel == 0`, avoiding nonzero-vector-cosine flakiness. `EvalResultRecord.passed` semantics are documented as row-execution success, with overall verdict in `EvalRunRecord.config["acceptance"]`.

**Count consistency:** 6 strategies, 12 cases, 72 results/accesses, 14 runs, 12 acceptance checks — applied uniformly across Tasks 5/6/7/8/11 and both touched test files.
