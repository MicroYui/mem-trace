# Context Compaction Implementation Plan (ROADMAP §9)

> **For agentic workers:** implement this plan Issue-by-Issue using TDD (RED -> GREEN). Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Progress tracking rule:** after completing each Issue in §4, update `.ai/PROJECT_STATE.md` and tick or annotate the corresponding `docs/design/ROADMAP.md` §9 (and §1 tech-debt) checkbox. Do not leave implementation progress only in chat history.

**Goal (revised 2026-06-11):** Replace silent discard-style truncation with **trace-aware, provenance-preserving, replayable context compaction**. The runtime must explicitly record what was omitted, **preserve critical key=value constraints under budget** (not just key names), optionally summarize active-path history through a rule/LLM provider, and make every compaction decision **replayable through access/compaction logs and observability metrics** — all deterministic by default so benchmarks stay reproducible.

**Tech Stack:** Python **3.12+** (`pyproject.toml` `requires-python = ">=3.12"`), FastAPI, Pydantic v2, SQLAlchemy 2.0 async, pytest + httpx ASGI tests.

***

## 0. Background & positioning

mem-trace is a "state-aware memory runtime for long-horizon agents". The core pain of long-horizon agents is **context window blowup**. Before C0-C2, the system only did **greedy discard truncation** (`packer.pack_context` dropped remaining low-priority blocks) with **no secondary summary, no warning, no audit trail, and no replayable record** — constraints could be silently lost. C0-C5 now complete the context-compaction loop: structured pack results, rule-based budget compensation, durable audit/replay records, the summarizer-provider seam, config-gated rolling active-history summaries, and retention-quality benchmark/report/replay coverage.

MemTrace's selling point is **not** "we can summarize context too". It is "we can explain exactly what was compacted, why, which facts were retained, which were omitted, whether compaction leaked failed/stale/secret memory, and we can replay the whole decision". So compaction must be a first-class observable, not just a packer-internal heuristic.

Current state (ROADMAP §9):
- DONE — run-end summary (`summarizer.build_run_summary`, cold path, deterministic pure function): compresses "finished trajectory -> long-term memory", does not solve in-flight over-window.
- DONE — active_path progress block (`packer.build_active_path_block`): concatenation/display, not compression.
- DONE — budget-overflow context compaction with audit/replay is complete (C1/C2); rolling active-history compaction is complete (C4), with persisted `history_summary` snapshots used by replay.

## 1. Scope (this implementation)

Six Issues, dependency-ordered:

1. **C0 — `PackResult` + callsite refactor (behavior-preserving):** introduce a structured packing result and migrate every `pack_context` callsite before changing semantics, so C1 can land safely.
2. **C1 — Budget-aware packing with `compacted_constraints` + `compaction_notice` (rule, default-on):** ✅ complete — retain key=value facts from dropped low-priority blocks; emit an audit notice; reserve tokens for protected blocks. **No LLM. Default-on (safety fix).**
3. **C2 — `ContextCompactionLog` persistence + observability wiring:** ✅ complete — new log table + repository methods + Alembic migration. Budget compaction decisions are first-class records that observability/replay can read. C4 added `history_summary` producers on the same path.
4. **C3 — `SummarizerProvider` (rule/LLM dual path) with structured `RetainedFact` output:** ✅ complete — new Protocol, `RuleSummarizerProvider` (deterministic default), `LLMSummarizerProvider` (OpenAI-compatible, raise-on-failure), config-gated, failure fallback. Output is **structured retained facts + provenance**, not free-form text.
5. **C4 — In-flight rolling history summary with access-level snapshot:** ✅ complete — when active-path history exceeds threshold, fold safe early history into a protected `history_summary` block. Reuses C3 provider seam, persists to C2 compaction log, guarded by separate `compaction_timeout_ms`, degrades to no-fold (never empty context). Default-off (`compaction_enabled=False`) to keep benchmarks reproducible.
6. **C5 — Benchmark + observability + replay diff + project-memory sync:** ✅ complete — new benchmark case with **retention quality metrics**, not just `avg_compression_ratio`.

Related deferred design note:

7. **C6 / I7 — Failure-aware negative retained facts:** ✅ complete — C0-C5 compaction behavior remains complete and stable, while I7 preserves safe failed-branch lessons through compaction as a separate negative-evidence metadata channel. I7.1-I7.6 landed the DTO, dedicated compaction-log persistence field, dropped `avoided_attempts` metadata retention, replay/metrics/reports/trace-bundle surfacing, benchmark `case_13_compaction_retains_negative_lesson`, acceptance `variant_2_retains_negative_lesson_under_compaction`, and full closeout verification without protecting or forcing negative evidence into prompt context.

## 2. Non-goals (deferred)

- State-tree completed-subgoal -> summary node (ROADMAP §5, co-design item, separately scheduled).
- Lifecycle decay/archive compression (ROADMAP §3.2, depends on Celery/Redis).
- Real tokenizer replacement (keep `estimate_tokens` char/word approximation for determinism; flagged as approximate in §8).
- Unified Provider Registry family (ROADMAP §10; land only `SummarizerProvider` here, leave an aligned interface).
- Run-level summary cache table / parallel chunked summarization (ROADMAP §10 / future). C4 keeps an access-level snapshot only; cross-access cache deferred until profiling shows it is worth it.

## 3. Current-state coordinates (verified after C5)

- `packer.pack_context` now returns `PackResult`, including `blocks`, `used`, `pre_compaction_tokens`, `dropped_blocks`, `notice`, `retained_constraints`, and `pending_compaction_logs`. Budget overflow emits `compacted_constraints` + `compaction_notice` under the configured reserve while keeping `used <= token_budget`.
- **`pack_context` callsites are migrated:** hot-path trace, `inspect_access`, replay original-view reconstruction, and direct packer tests all consume `.blocks` / `.used`; hot path, inspect, and replay pass `compaction_notice_reserve_tokens`.
- `ContextBlock` remains the prompt block vocabulary; `RetainedFact`, `CompactionKind`, `CompactionProvider`, `ContextCompactionLog`, and `PendingCompactionLog` now live in `apps/api/app/runtime/models.py` for C1/C2 shared use.
- `RetrievalPipelineTrace` now carries `pending_compaction_logs`; `RetrievalController._persist_trace` is the single place that materializes durable `ContextCompactionLog` records after `MemoryAccessLog.access_id` exists.
- The `context_packing` profile metadata still carries whole-packing diagnostics (`pre_compaction_tokens`, `actual_tokens`, `dropped_count`, `compression_ratio`, retained/dropped snapshots), while durable observability uses `ContextCompactionLog` rows loaded by `observability/metrics.py` and `observability/replay.py`.
- `MemoryAccessLog` remains compact and is not extended with compaction-specific columns; one access can instead have multiple `ContextCompactionLog` rows (`budget_notice` and `history_summary`).
- `summarizer.build_run_summary` (`apps/api/app/memory/summarizer.py:118-124`): deterministic pure function, `RunSummary(episodic, procedural)`, stable-key idempotent.
- ExtractionProvider pattern: Protocol (`llm_extractor.py:57-61`) -> Fake/LLM dual impl -> deps gate (`deps.py:40-56` tri-state: disabled->None / enabled+key->real / enabled-no-key->Fake) -> runtime fallback (`memory_runtime.py:430-449` async + `except Exception` + fall back to rule writer). C3 mirrors this exactly.
- config (`config.py`): `retrieval_token_budget=512` (`:21`), `retrieval_timeout_ms` (`:22`, used in `controller.retrieve` wait_for), `compaction_notice_reserve_tokens=64`, C3/C4 config exists (`compaction_enabled=False`, `llm_summarizer_enabled=False`, `compaction_history_token_threshold=2048`, `compaction_summary_budget_tokens=192`, `compaction_timeout_ms=1500`), `llm_extraction_enabled=False`, and shared `llm_*` settings. C4 rolling-summary behavior remains default-off.
- benchmark metric triad: `CaseMetrics` paired `xxx`+`xxx_present` (`evaluator.py`) -> `evaluate_case` conditional scoring -> runner `_rate` divides by `_present` -> `_acceptance` boolean asserts. `test_runner.py` now asserts 9 cases x 4 strategies = 36 results, including `case_9_over_budget_compaction` and `variant_2_retains_constraints_under_compaction`.
- observability: `build_access_observability_metrics` / `build_observability_summary` load `ContextCompactionLog` rows and expose compaction trigger/drop/compression/history-summary metrics. Static JSON/Markdown/HTML reports include a Compaction section with retained facts, and benchmark C5 adds retention-quality metrics (`constraint_retention_hit`, `unsafe_compaction_leakage`, per-event `compression_ratio`). `test_metrics.py` includes exact-equality asserts that must stay synced.
- test conventions: `uv run pytest -q` (dev deps via `uv run --extra dev pytest`), `asyncio_mode=auto`, TDD RED->GREEN, test subpackages mirror `app/` layers, `conftest.py` provides `repo`/`runtime` fixtures.

## 4. Issues

### Issue C0 — `PackResult` + callsite refactor (behavior-preserving)

**Goal:** introduce a structured packing result and migrate every callsite **without changing observable behavior**. C1 then lands cleanly.

**Changes:**
- [x] `apps/api/app/retrieval/packer.py`: add
  ```python
  @dataclass(frozen=True)
  class PackResult:
      blocks: list[ContextBlock]
      used: int
      pre_compaction_tokens: int   # sum(b.tokens for b in candidate_blocks before truncation)
      dropped_blocks: list[ContextBlock]   # empty in C0, populated in C1
      notice: ContextBlock | None  # None in C0, populated in C1
      retained_constraints: list["RetainedFact"]  # empty in C0, populated in C1
  ```
  Change `pack_context(...) -> PackResult`. Behavior in C0 is identical: same block list, same `used`, `dropped_blocks=[]`, `notice=None`.
- [x] **Migrate all 4 callsites:**
  - [x] `apps/api/app/retrieval/controller.py:207` (hot-path).
  - [x] `apps/api/app/runtime/memory_runtime.py:651` (`inspect_access`).
  - [x] `apps/api/app/observability/replay.py:185` (replay original-view re-pack).
  - [x] `apps/api/tests/retrieval/test_retrieval_flow.py:261` and any other direct test callers (grep `pack_context(`).
- [x] No `tuple` compatibility shim — change is internal, atomic, and fully covered by tests.

**RED tests:**
- [x] `test_pack_result_preserves_existing_behavior_when_no_truncation`: in a budget-ample fixture, same blocks, same `used`, `pre_compaction_tokens == used`, `dropped_blocks==[]`, `notice is None`.
- [x] `test_pack_result_reports_pre_compaction_tokens_when_truncated`: in an over-budget fixture, `pre_compaction_tokens >= result.used` (they are NOT required to be equal; `pre_compaction_tokens` is the sum of all candidate blocks, `used` is the packed subset).
- [x] `test_inspect_access_unchanged_after_pack_result_refactor`.
- [x] `test_replay_original_view_unchanged_after_pack_result_refactor` (covered by replay regression: `apps/api/tests/observability/test_replay.py`).

### Issue C1 — Budget-aware packing with `compacted_constraints` + `compaction_notice` (rule, default-on)

**Goal:** under budget pressure, never silently drop constraints. Two outputs:
1. **`compacted_constraints` block (functional):** preserves key=value facts from dropped low-priority blocks so the agent can still decide. Example:
   ```
   Compacted lower-priority memories: project.database=postgres; project.runtime.excluded=node.js; endpoint.current=/v2/users. 4 other episodic/tool memories were omitted.
   ```
2. **`compaction_notice` block (audit):** short reserved system block stating "compaction occurred, dropped N blocks, kind=budget_notice".

These are **reserved/protected** blocks, not regular blocks competing in `_TYPE_ORDER`. They are constructed **after** greedy packing of protected + ordinary blocks under a **reserved token budget**.

**Default:** **on** by default. Over-budget compaction compensation is a safety fix; only the LLM rolling-summary path (C4) is config-gated.

**Block priority redesign (replaces "lowest priority"):**

| tier | blocks |
| --- | --- |
| **Reserved / protected** (never *silently* dropped; may be deterministically truncated) | `active_state`, `active_path`, `history_summary` (C4), `compacted_constraints`, `compaction_notice`, project runtime constraints (`project_memory` from `build_project_constraint_block`) |
| **Ordinary** (greedy, may be dropped entirely) | `tool_evidence`, `project_memory` (dynamic-key), `profile`, `procedural`, `episodic` |

The rationale is the conflict the reviewer flagged: putting `compaction_notice` at the lowest `_TYPE_ORDER` and also calling it "reserved" contradicts itself. The new scheme makes "reserved" explicit by **packing protected blocks first under their own reserved budget, then ordinary blocks under the remaining budget**, and synthesizing notice/constraints **last** from the dropped set with their tokens already reserved.

**Protected ≠ unlimited (the `used <= token_budget` invariant fix):** "protected" means *cannot silently disappear*, **not** *cannot be truncated*. If a single protected block (e.g. a very long `active_state`) exceeds its budget slice, it must be **deterministically truncated** (not dropped) and a warning recorded, so the hard invariant `used <= token_budget` always holds. A pure helper enforces this:
```python
def fit_block(block: ContextBlock, max_tokens: int) -> ContextBlock:
    if block.tokens <= max_tokens:
        return block
    # deterministic truncation; recompute tokens; mark via reason/suffix
    return truncated_block_with_suffix(block, max_tokens, suffix=" … (truncated)")
```

**Algorithm:**
```
1. Build all candidate blocks (active_state, active_path, project_constraints,
   per-memory blocks).
2. pre_compaction_tokens = sum(b.tokens for b in candidates).
3. Split into protected_blocks vs ordinary_blocks. **Protected-tier internal
   order (highest -> lowest, never reordered by `_block_order`):**
   active_state > history_summary (C4) > active_path > project runtime
   constraints > compacted_constraints > compaction_notice.
   (Rationale: project runtime constraints are already-accepted structured
   *current* facts, so they outrank `compacted_constraints`, which is only the
   *compensation* for dropped ordinary blocks; the audit `compaction_notice` is
   lowest but still never silently dropped.)
4. reserve_for_compaction:
       if token_budget < 32: reserve = max(0, token_budget // 3)
       else: reserve = min(Settings.compaction_notice_reserve_tokens,
                           max(16, token_budget // 8))
   (deterministic; covers a typical compacted_constraints + notice line.)
5. effective_budget = max(0, token_budget - reserve_for_compaction)
   (the `max(0, ...)` guard prevents a negative budget under tiny budgets,
   e.g. token_budget=10/20 in tests).
6. Pack protected_blocks first under effective_budget. **Protected blocks are
   never dropped; if a protected block exceeds the remaining slice, apply
   `fit_block(...)` to deterministically truncate it and record a warning
   "protected block truncated to fit budget".**
7. Greedy-pack ordinary_blocks under remaining budget; collect dropped_blocks.
8. If dropped_blocks:
   8a. retained_constraints = extract_retained_facts(dropped_blocks, memory_by_id)
       — RetainedFact key/value come from MemoryItem.key/value (looked up by
       block.memory_id), NEVER parsed from rendered block.content. Whitelist
       keys: project.* / endpoint.* / profile.* (extensible to procedure.*).
   8b. compacted_constraints_block = render retained_constraints (deterministic
       sort by key, "k=v" join). Skipped if empty.
   8c. compaction_notice_block = "Compaction: dropped {n} blocks ({kinds}); "
       "retained {m} constraints; kind=budget_notice."
   8d. Token check: notice + constraints must fit in reserve_for_compaction. If
       they don't (e.g. very long retained values), trim values deterministically
       and append "(truncated)" suffix. Final invariant: used <= token_budget.
9. Return PackResult(blocks, used, pre_compaction_tokens, dropped_blocks,
                     notice, retained_constraints). When dropped_blocks is
   non-empty, also build a `PendingCompactionLog(kind=budget_notice,
   provider=rule, ...)` (returned alongside / attached to the result so the
   controller can append it to the trace's pending list).
```

**Changes:**
- [x] `apps/api/app/retrieval/packer.py`:
  - Implement the algorithm above, including `fit_block(...)` for protected-block truncation.
  - Add pure helpers: `extract_retained_facts(dropped_blocks: list[ContextBlock], memory_by_id: Mapping[str, MemoryItem]) -> list[RetainedFact]` (key/value sourced from `MemoryItem.key`/`MemoryItem.value` via `block.memory_id`, whitelist-gated, value-truncated), `build_compacted_constraints_block(facts) -> ContextBlock | None`, `build_compaction_notice(dropped, kind) -> ContextBlock`.
  - `RetainedFact` model lives in `runtime/models.py` (shared with C3 provider): `key: str, value: str, source_memory_id: str | None, provenance: Provenance | None`.
- [x] `apps/api/app/retrieval/controller.py`:
  - Adapt to `PackResult`; `actual_tokens = result.used`; write `dropped_count`, `pre_compaction_tokens`, `compression_ratio = result.used / max(1, result.pre_compaction_tokens)`, `notice_kind` into `phase_profile[context_packing]` (still useful for profiler view, but **C2 owns the durable record**).
  - In `_build_warnings`, append `"context budget exceeded: omitted N blocks"` when `dropped_count > 0`.
- [x] `apps/api/app/config.py`: add `compaction_notice_reserve_tokens: int = 64` (deterministic; safely > worst-case rule notice).
- [x] **Failed/rolled_back/secret/stale safety:** dropped blocks come from already-gate-accepted memories, so failed-branch / stale / secret are already excluded by gate. C1 does **not** widen gate semantics. Add an assertion test (`test_compaction_never_includes_failed_branch_block`) to lock this in.

**RED tests** (`tests/retrieval/test_retrieval_flow.py`, mirror `test_pack_context_emits_dynamic_key_project_memory:249`):
- [x] `test_compacted_constraints_preserve_key_values_when_over_budget`: tiny budget; assert a `compacted_constraints` block exists with text containing `project.database=postgres` (value, not just key).
- [x] `test_compaction_notice_emitted_when_over_budget`: dropped_count>0, notice block kind=`budget_notice`, content lists dropped count.
- [x] `test_compaction_notice_absent_when_within_budget`: ample budget -> no notice/constraints block, dropped_count==0, pre_compaction_tokens==used.
- [x] `test_active_state_is_protected_under_tiny_budget`: even with budget=20, `active_state` survives (possibly truncated, never dropped).
- [x] `test_protected_block_truncated_not_dropped_when_oversized`: an oversized `active_state` is truncated via `fit_block`, a "protected block truncated" warning is present, and `used <= token_budget`.
- [x] `test_notice_and_summary_never_exceed_budget`: under any tiny budget, `used <= token_budget`.
- [x] `test_compaction_notice_is_in_blocks_when_protected_block_fills_budget`: protected block consumes the initial budget but ordinary blocks are dropped -> the packer truncates protected content enough to include a real `compaction_notice` block.
- [x] `test_pack_context_respects_custom_compaction_notice_reserve_tokens`: `compaction_notice_reserve_tokens` is wired into `pack_context` and changes retained constraint capacity.
- [x] `test_compaction_never_includes_failed_branch_block`: failed-branch memory was rejected by gate -> never appears in dropped/retained lists.
- [x] `test_pack_result_pre_compaction_tokens_equals_sum_of_candidates`.

### Issue C2 — `ContextCompactionLog` persistence + observability wiring

**Goal:** make compaction a first-class durable record. Without this, C1's metrics live only in `phase_profile` dicts, observability never reads them, and replay can't explain "what was compacted".

**Decision: introduce a new `ContextCompactionLog` table** (the reviewer's option B). Rationale: it cleanly supports both `budget_notice` (C1) and `history_summary` (C4) records, keeps `MemoryAccessLog` from accumulating compaction-specific columns, and natively supports per-access multiple compaction events.

**Schema (Pydantic + ORM):**
```python
class ContextCompactionLog(_Base):
    compaction_id: str = Field(default_factory=lambda: _new_id("cmp"))
    access_id: str
    run_id: Optional[str] = None
    step_id: Optional[str] = None
    workspace_id: str
    kind: CompactionKind             # "budget_notice" | "history_summary"
    provider: CompactionProvider     # "rule" | "llm" | "fallback_rule"
    pre_tokens: int = 0              # see token semantics below
    post_tokens: int = 0            # see token semantics below
    dropped_block_count: int = 0
    compression_ratio: float = 1.0   # post_tokens / max(1, pre_tokens)
    summary_text: Optional[str] = None
    retained_facts: list[RetainedFact] = Field(default_factory=list)
    source_memory_ids: list[str] = Field(default_factory=list)
    source_event_ids: list[str] = Field(default_factory=list)
    source_state_node_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_now)
```

**Token semantics (this log measures the COMPACTION EVENT subset, not the whole retrieval):**
- `budget_notice`: `pre_tokens = sum(tokens of dropped_blocks)`, `post_tokens = compacted_constraints.tokens + compaction_notice.tokens`.
- `history_summary`: `pre_tokens = sum(tokens of folded history input)`, `post_tokens = history_summary_block.tokens`.
- `compression_ratio = post_tokens / max(1, pre_tokens)`.
- **Whole-packing** metrics (`pre_compaction_tokens` over ALL candidate blocks, final `actual_tokens=used`) stay in `phase_profile[context_packing]` / the access-level summary — they are a *different* number from the per-event ratio above and must not be conflated.

**Scope note (keep C2 small):** C2 lands the **log model / repo / ORM / migration + observability skeleton + budget_notice persistence/replay only**. `history_summary` persistence is produced in C4; its replay/diff coverage is finished in C4/C5. Do not build full history_summary replay in C2.

**`PendingCompactionLog` (the access_id-timing fix):** compaction inputs are computed *before* the `MemoryAccessLog` (and its `access_id`) exists. So the runtime/packer produce an **access-id-less** `PendingCompactionLog` dataclass; the controller **materializes** it into a `ContextCompactionLog` after creating the access record. This is the single mechanism shared by C1 (budget_notice) and C4 (history_summary).

```python
@dataclass(frozen=True)
class PendingCompactionLog:
    kind: CompactionKind
    provider: CompactionProvider
    pre_tokens: int
    post_tokens: int
    dropped_block_count: int
    compression_ratio: float
    summary_text: str | None
    retained_facts: list[RetainedFact]
    source_memory_ids: list[str]
    source_event_ids: list[str]
    source_state_node_ids: list[str]
    warnings: list[str]

    def materialize(self, *, access_id: str, run_id: str | None,
                    step_id: str | None, workspace_id: str) -> ContextCompactionLog: ...
```

`PendingCompactionLog` is **internal-only** (a transient `@dataclass`) and is never serialized to API/DB directly; only the materialized Pydantic `ContextCompactionLog` is persisted/returned.

**Changes:**
- [x] `apps/api/app/runtime/models.py`: add `CompactionKind` / `CompactionProvider` enums, `RetainedFact`, `ContextCompactionLog`, and `PendingCompactionLog` (dataclass).
- [x] `apps/api/app/runtime/repository.py`: protocol additions `add_compaction_log`, `list_compaction_logs(access_id=..., run_id=..., workspace_id=...)`, **plus the `InMemoryRepository` implementation in the same file** (mirrors the existing gate-log pattern — there is no separate `in_memory_repository.py`).
- [x] `apps/api/app/storage/orm.py`: `ContextCompactionORM` with indexes on `(access_id)`, `(workspace_id, created_at)`, `(run_id)`. `retained_facts` / `source_*_ids` / `warnings` stored as JSON (matches existing `metadata: dict[str, Any]` pattern).
- [x] `apps/api/app/storage/sql_repository.py`: add/list mappings.
- [x] **Alembic migration** `migrations/versions/0005_context_compaction.py` with `down_revision="0004_phase3a_observability"`. Includes table create + indexes + downgrade.
- [x] **Single persistence path (no split-brain):** `RetrievalPipelineTrace` carries `pending_compaction_logs: list[PendingCompactionLog]`. `controller._persist_trace` is the **only** place that writes compaction logs:
  ```python
  for pending in trace.pending_compaction_logs:
      await self._repo.add_compaction_log(
          pending.materialize(
              access_id=access.access_id, run_id=access.run_id,
              step_id=access.step_id, workspace_id=access.workspace_id,
          )
      )
  ```
  C1's budget_notice pending log is appended inside `trace(...)`; C4's history_summary pending log is passed into `retrieve(...)` (see C4). Both end up in the same list and the same persist loop.
- [x] **observability metrics extension** (`observability/metrics.py`):
  - `build_access_observability_metrics` accepts the access's compaction logs and adds: `compaction_triggered` (0/1), `dropped_block_count`, `pre_compaction_tokens`, `post_compaction_tokens`, `compression_ratio_sum`, `compression_ratio_present`, `history_summary_count`.
  - `build_observability_summary` loads compaction logs via `repo.list_compaction_logs(access_id=...)`.
  - `_empty_totals` / `_add_totals` / `_strategy_summary` updated.
  - `ObservabilitySummary` (`models.py`) gains: `compaction_trigger_rate`, `avg_compression_ratio`, `total_dropped_blocks`, `history_summary_count`. **Naming follows the reviewer's suggestion (no `_rate` on a ratio).**
  - **Sync exact-equality asserts in `tests/observability/test_metrics.py:176-193 / 267-281`.**
- [x] **replay (budget_notice only in C2)** (`observability/replay.py`): include the access's persisted compaction logs in the access-level replay payload. Replay does **not** rerun the summarizer — it shows the **persisted** compaction record so output is stable. Diff semantics: a new `ReplayDiffItem` kind `compaction_drift` flags when a re-run trace's `budget_notice` dropped_count diverges from the persisted log (severity `warning`). history_summary replay/diff is completed in C4/C5.

**RED tests:**
- [x] `tests/storage/test_migrations.py::test_compaction_log_table_present_after_upgrade`.
- [x] `tests/observability/test_compaction_log.py`:
  - `test_retrieve_with_over_budget_persists_compaction_log` (kind=budget_notice, provider=rule, `source_memory_ids` populated; `source_event_ids`/`source_state_node_ids` populated only **when available** from `MemoryItem.provenance` — do not force them, since dropped blocks may carry only a memory_id).
  - `test_observability_summary_counts_compaction_metrics`.
  - `test_replay_includes_persisted_compaction_log_without_rerunning_summary`.
- [x] `tests/observability/test_metrics.py`: update existing exact-equality fixtures + add new field asserts.

### Issue C3 — `SummarizerProvider` (rule/LLM dual path) with structured `RetainedFact` output

**Goal:** unified summarizer for C4 rolling summary (and optionally enriching C1's notice when the LLM path is enabled). Deterministic rule default keeps benchmarks reproducible; LLM is config-gated; failure falls back to rule with no info loss.

**Provider schema (stronger than v1 plan — structured retained facts, source provenance, budget):**
```python
class SummarizeRequest(_Base):
    blocks: list[ContextBlock]              # input blocks to compress
    must_retain_facts: list[RetainedFact]   # caller-asserted constraints
    source_memory_ids: list[str]
    source_event_ids: list[str]
    source_state_node_ids: list[str]
    summary_budget_tokens: int
    run_id: Optional[str] = None
    workspace_id: str
    kind: CompactionKind                    # "budget_notice" | "history_summary"

class SummarizeResult(_Base):
    summary: str
    retained_facts: list[RetainedFact]
    omitted_count: int
    source_memory_ids: list[str]
    source_event_ids: list[str]
    source_state_node_ids: list[str]
    pre_tokens: int
    post_tokens: int
    warnings: list[str] = Field(default_factory=list)
```

**Changes:**
- [x] New `apps/api/app/memory/summarizer_provider.py` (sibling to `llm_extractor.py`, same style):
  - `@runtime_checkable class SummarizerProvider(Protocol): async def summarize(self, request: SummarizeRequest) -> SummarizeResult: ...`
  - `RuleSummarizerProvider`: deterministic. Renders summary as stable `key=value; ...` text from `must_retain_facts`; `post_tokens <= summary_budget_tokens` enforced via deterministic truncation; never raises.
  - `LLMSummarizerProvider`: OpenAI-compatible `/chat/completions`, fixed system prompt enforcing the constraints below, `temperature=0`, reuse `_strip_code_fences`; any HTTP/JSON/schema/validation failure raises (runtime falls back via the `_summarize` helper).
- [x] **LLM system prompt constraints (mandatory):**
  1. Output **JSON** matching `SummarizeResult` (`response_format=json_object` opt-in via `llm_use_json_response_format`, mirroring `LLMExtractionProvider`).
  2. **Do not introduce new facts.** Only summarize content present in input blocks.
  3. **Must preserve** `must_retain_facts` (key=value) verbatim in `retained_facts`.
  4. **Must not include** content from blocks marked failed/rolled_back/stale/secret/risky (caller filters these; prompt restates as defense-in-depth).
  5. When over `summary_budget_tokens`, prioritize project / profile / procedural facts over episodic/tool detail.
  6. Echo `source_*_ids` from request (provider must not invent provenance).
- [x] **Validation (conservative — do not over-engineer NLI):** the provider trusts structured `request.must_retain_facts` as the retained-fact allow-list (C4 can add a structured `candidate_facts` field if it needs a wider allow-list; rendered block text is not parsed because it may contain negated/stale/risky mentions). Then:
  1. Every `(key, value)` in the response's `retained_facts` **must** be in `allowed_facts`; otherwise raise `SummarizerValidationError` (runtime falls back to rule).
  2. The response **must** cover all `must_retain_facts` (no dropped constraints); otherwise raise.
  3. LLM output top-level source id sets must preserve the request source ids; `RetainedFact` identity (`key/value/source_memory_id/provenance.run_id/provenance.step_id/provenance.event_id/provenance.state_node_id`) must match required identities exactly. Missing identities, invented ids, or provenance drift raise.
  4. `post_tokens` is recomputed locally from `summary` before budget enforcement; LLM-reported token counts are not trusted.
  5. **No deep NLI on the free-form `summary` text.** As a cheap guard, the `RuleSummarizerProvider` (and the deterministic fallback) always render `summary` *from* `retained_facts`, so the rule path can never hallucinate. For the LLM path, untrusted free-form summary is acceptable as long as retained facts/provenance/token budget validation holds; do not attempt full fact-extraction over the summary string in v1.
- [x] `apps/api/app/config.py`: add
  - `compaction_enabled: bool = False` (gates C4 rolling summary; **does not** disable C1).
  - `llm_summarizer_enabled: bool = False` (gates LLM path within C3).
  - `compaction_history_token_threshold: int = 2048` (C4).
  - `compaction_summary_budget_tokens: int = 192` (C4 rolling summary block size cap).
  - `compaction_timeout_ms: int = 1500` (C4 separate timeout — reviewer's point: cannot rely on `retrieval_timeout_ms` since the fold runs at runtime entry).
- [x] `apps/api/app/api/deps.py`: tri-state injection mirroring extraction (`:40-56`):
  - `llm_summarizer_enabled` and `llm_api_key` set -> `LLMSummarizerProvider`.
  - `llm_summarizer_enabled` and no key -> `RuleSummarizerProvider` + warning log.
  - default -> `RuleSummarizerProvider` (always present; no `None` branch — the runtime always has a deterministic fallback).
- [x] `apps/api/app/runtime/memory_runtime.py`: `__init__` adds keyword-only `summarizer_provider: SummarizerProvider = RuleSummarizerProvider()`. New async helper `_summarize(request, *, deadline_ms) -> SummarizeResult` that wraps the provider call in `asyncio.wait_for(deadline_ms / 1000)`; on exception or timeout, log warning, then **`await RuleSummarizerProvider().summarize(request)`** (always async — the protocol is async even though the rule path is deterministic), and set result `provider="fallback_rule"` for the compaction log.
- [x] **packer stays decoupled:** `extract_retained_facts` / `build_compacted_constraints_block` stay pure rule (no provider dep, C1 default unchanged). The provider only takes over at the runtime layer (C4); C1 may optionally call it later, but that is **not** in scope for this Issue.

**RED tests** (new `tests/memory/test_summarizer_provider.py`, mirror `test_llm_provider.py`):
- [x] Rule provider: deterministic output, retains all `must_retain_facts`, never raises, respects `summary_budget_tokens`.
- [x] LLM provider via `httpx.MockTransport`: request shape/auth, fence tolerance, bad-JSON raises, HTTP 500 raises, JSON missing required fields raises, retained_facts roundtrip preserved.
- [x] LLM provider: invented-fact detection — if response contains a fact whose key/value is **not** in input `must_retain_facts`, the result is rejected (raised) so fallback triggers.
- [x] LLM provider: low-reported `post_tokens` cannot bypass local budget enforcement; missing/invented source ids and retained-fact identity drift (memory/run/step/event/state) are rejected; negated free-form `key=value` text is not accepted as an allowed retained fact. Rule fallback preserves same key/value facts from distinct sources and safely sorts nullable provenance identities.
- [x] New `tests/runtime/test_summarizer_fallback.py`: inject failing provider, assert fallback to rule, no info loss; provider timeout falls back; `provider="fallback_rule"` in resulting result for future compaction logs.

### Issue C4 — In-flight rolling history summary with access-level snapshot

**Goal:** when active-path history exceeds `compaction_history_token_threshold`, fold early history into a single `history_summary` block, persist it as a `ContextCompactionLog(kind=history_summary)`, inject it into context. Replay reads the **persisted** snapshot — never re-summarizes — keeping replay stable even with non-deterministic LLM providers.

**Boundary (reviewer's safety constraints, locked in tests). Two distinct filter sets — `_RETRIEVABLE_STATUSES` is a memory-status filter and does NOT cover raw events:**
- **Raw-event filter** (history is assembled from active-path events, which have no memory status):
  - active-path nodes only (`state_tree` active-path chain); skip failed/rolled_back nodes.
  - skip secret-redacted events.
  - skip tool_result events that are destructive / tool_sensitive.
- **Memory filter** (for any `MemoryItem` referenced in the summary):
  - apply `_RETRIEVABLE_STATUSES`; never leak superseded/archived/deleted.
  - never inject a stale value; stale info may appear only as text "previously-relied-on info marked stale and excluded".
- Preserve provenance: `source_event_ids` / `source_state_node_ids` / `source_memory_ids` written into the compaction log.

**Architecture (no bypass of `RetrievalController.retrieve`; controller still owns access_id + timeout + persistence):**
```
MemoryRuntime.retrieve_context(req):
  1. (NEW) pending_history = await self._maybe_fold_history(req)
       - returns Optional[(history_summary_block, PendingCompactionLog)]
       - access-id-LESS (PendingCompactionLog has no access_id yet)
       - guarded by Settings.compaction_enabled (default False -> always None)
       - guarded by its OWN asyncio.wait_for(Settings.compaction_timeout_ms)
       - on timeout/error -> None + a "history compaction skipped: <reason>"
         string collected for prelude_warnings (see step 2), never empty context
  2. context = await self._retrieval.retrieve(
         req,
         prelude_blocks=[history_summary_block] if pending_history else None,
         pending_compaction_logs=[pending_log] if pending_history else None,
         prelude_warnings=skip_warnings,   # e.g. ["history compaction skipped: timeout"]
     )
       - controller creates the MemoryAccessLog (access_id), packs with the
         prelude as a protected block, appends C1's budget_notice pending log,
         merges prelude_warnings into trace.warnings (so they reach
         MemoryAccessLog/replay/observability, NOT just the returned context),
         then materializes+persists ALL pending logs in `_persist_trace`.
  3. return context
```
This keeps `RetrievalController.retrieve` as the single entry that wraps timeout/trace/persist and returns `MemoryContext`; the runtime never calls `trace(...)` / `_persist_trace(...)` directly, and never mutates context warnings *after* the fact (warnings flow in via `prelude_warnings` so they are part of the persisted trace).

**Changes:**
- [x] `apps/api/app/retrieval/packer.py`: add `"history_summary"` to the **protected** tier (between `active_path` and project constraints, not in `_TYPE_ORDER`'s ordinary tier). Accept a `prelude_blocks: list[ContextBlock] | None = None` param; protected blocks include prelude.
- [x] `apps/api/app/retrieval/controller.py`:
  - `retrieve(...)` and `trace(...)` accept `prelude_blocks`, `pending_compaction_logs`, and `prelude_warnings`.
  - Thread `prelude_blocks` into `pack_context(...)`; merge `prelude_warnings` into the trace's `warnings` (so they are persisted to `MemoryAccessLog`/replay/observability, not appended post-hoc by the runtime).
  - Carry both C1 budget_notice and any passed-in history_summary pending logs in `RetrievalPipelineTrace.pending_compaction_logs`; `_persist_trace` materializes them with the freshly-created `access_id` (single persistence path from C2).
  - Add `ProfilePhase.context_compaction` to `phase_profile` when a history fold happened: `latency_ms`, `input_tokens=pre_tokens`, `output_tokens=post_tokens`, `metadata={provider, timed_out, kind}`. (Profiler view; the durable record is still the compaction log.)
- [x] `apps/api/app/runtime/models.py`: add `ProfilePhase.context_compaction = "context_compaction"` (currently 10 phases; this is the 11th, dedicated to compaction so reports stay clear).
- [x] `apps/api/app/runtime/memory_runtime.py`:
  - Add `_maybe_fold_history(req)` helper. It assembles input blocks from active-path history events (applying the **raw-event filter** above), computes `pre_tokens = estimate_tokens(joined_history)`, returns `None` if `pre_tokens < threshold` or `compaction_enabled is False`.
  - Wraps the configured `SummarizerProvider.summarize(SummarizeRequest(kind=history_summary, ...))` in `asyncio.wait_for(settings.compaction_timeout_ms / 1000)`; timeout/error degrades to no-fold for this hot-path rolling fold, while the lower-level C3 `_summarize` helper remains available for fallback-rule provider checks.
  - Builds a `history_summary` `ContextBlock` from `result.summary` with `tokens = result.post_tokens`, and an **access-id-less** `PendingCompactionLog(kind=history_summary, provider=...)`.
  - On timeout/exception: log warning, return `None` so retrieval proceeds with no fold; pass a `"history compaction skipped: <reason>"` string into `retrieve(..., prelude_warnings=[...])` so it lands in the persisted trace. **Never** empty context.
- [x] No `MemoryItem` is written for the rolling summary (read-only injection per ROADMAP §9). The compaction log **is** the audit record.

**RED tests** (new `tests/runtime/test_context_compaction.py`):
- [x] `test_history_compaction_disabled_by_default`: long history, `compaction_enabled=False` -> no `history_summary` block, no compaction log row, behavior identical to current.
- [x] `test_history_compaction_emits_history_summary_block_when_over_threshold`.
- [x] `test_history_compaction_persists_compaction_log_with_source_ids`.
- [x] `test_history_compaction_excludes_failed_branch_event`.
- [x] `test_history_compaction_excludes_secret_redacted_event`.
- [x] `test_history_compaction_does_not_leak_superseded_memory`.
- [x] `test_history_compaction_timeout_degrades_to_no_fold_not_empty_context` (inject a hanging provider; assert non-empty context + warning).
- [x] `test_replay_returns_persisted_history_summary_without_calling_summarizer` (inject a failing provider after persist; replay still returns the original summary).
- [x] `test_history_summary_is_protected_under_tiny_budget` (history_summary survives even when ordinary blocks are dropped).

### Issue C5 — Benchmark + observability + replay diff + project-memory sync

**Goal:** prove the feature works end-to-end with a benchmark that measures **retention quality**, not just compression ratio. Sync all docs.

**Changes:**
- [x] **New benchmark case `case_9_over_budget_compaction`** (`apps/api/app/benchmark/cases.py`): seed mixed-type memories + a tiny `token_budget` that forces compaction. **Must include negative samples** so `unsafe_compaction_leakage` has real proving power:
  - positive constraints: `project.runtime=bun`, `project.database=postgres`, `endpoint.current=/v2/users`, plus several benign episodic/tool entries (to be dropped/compacted).
  - **failed/rolled_back branch memory:** `project.runtime=npm` on a rolled-back branch (must NOT surface).
  - **stale memory:** `endpoint.current=/v1/old` expired (value must NOT be injected).
  - **secret event/memory attempt** (must be redacted, never summarized).
  - **destructive tool evidence:** e.g. `git push --force` / `rm -rf` (must NOT surface).
  Probe asks "which DB and runtime should I use?".
- [x] **Evaluator metrics** (`apps/api/app/benchmark/evaluator.py`, full triad `xxx` + `xxx_present`):
  - `compaction_triggered` (0/1).
  - `constraint_retention_hit` (0/1): all key=value constraints from seeded *positive* project facts appear either in a regular `project_memory` block or in `compacted_constraints`. **This is the retention-quality metric the reviewer asked for.**
  - `unsafe_compaction_leakage` (0/1): asserts none of the seeded failed/rolled_back/stale/secret/destructive samples appear in any compaction notice/summary/retained-facts. Should always be 0; failing it is a regression.
  - `compression_ratio` (float, present-gated): `post_tokens / max(1, pre_tokens)`.
- [x] **Runner** (`apps/api/app/benchmark/runner.py`):
  - Sync `_METRIC_FIELDS` and Markdown headers.
  - Add summary fields: `compaction_trigger_rate`, `constraint_retention_hit_rate`, `unsafe_compaction_leakage_rate`, `avg_compression_ratio` (reviewer's naming).
  - Add acceptance check: `variant_2_retains_constraints_under_compaction = constraint_retention_hit_rate == 1.0` AND `unsafe_compaction_leakage_rate == 0.0` for case_9. **No** acceptance check on `avg_compression_ratio` alone (compression rate is observation, not safety). **Do NOT add a "variant_2 better than baseline_1" check** — C1 is a global default-on packer improvement, so `baseline_1` also benefits from `compacted_constraints`; expecting only variant_2 to retain constraints would be wrong.
  - Update test count asserts: 9 cases x 4 strategies = 36 results.
- [x] **Observability report** (`apps/api/app/observability/reports.py`): add a "Compaction" section to JSON/MD/HTML output: per-access compaction kind/provider/pre/post/dropped/retained_facts; HTML uses an existing `<details>` pattern.
- [x] **Replay diff:** the new `compaction_drift` `ReplayDiffItem` (added in C2) is exercised end-to-end here.
- [x] **Docs sync:**
  - `.ai/PROJECT_STATE.md`: new "Implemented (Context Compaction)" + "Latest Verification" sections per Issue.
  - `.ai/IMPLEMENTATION_PLAN.md`: tick Context Compaction items.
  - `docs/design/ROADMAP.md` §9 + §1 tech-debt "retrieval over-budget discard" item: tick.
  - `README.md`: add a one-paragraph "Context Compaction" section under the existing observability section, pointing at the new compaction log + report.

**RED tests:**
- [x] `tests/benchmark/test_runner.py`: 9 cases / 36 results, `compaction_trigger_rate` / `constraint_retention_hit_rate` / `unsafe_compaction_leakage_rate` / `avg_compression_ratio` keys present, new acceptance check passes.
- [x] `tests/observability/test_reports.py`: report includes Compaction section with retained facts.
- [x] `tests/api/test_dashboard.py`: row counts updated.
- [x] `tests/observability/test_replay.py`: `compaction_drift` diff appears when persisted notice and replayed trace diverges in dropped_count.

## 5. Key files (modify / create)

Modify:
- `apps/api/app/retrieval/packer.py` (C0 PackResult; C1 algorithm + retained facts; C4 history_summary protected tier + prelude_blocks)
- `apps/api/app/retrieval/controller.py` (C0 callsite; C1 warning + phase_profile fields; C2 persist compaction log; C4 prelude threading)
- `apps/api/app/runtime/memory_runtime.py` (C0 `inspect_access` callsite; C3 provider injection + `_summarize`; C4 `_maybe_fold_history`)
- `apps/api/app/observability/replay.py` (C0 callsite; C2 include compaction log + `compaction_drift` diff; C4 reads persisted summary)
- `apps/api/app/observability/metrics.py` (C2 new fields + summary, sync exact-equality asserts)
- `apps/api/app/observability/reports.py` (C5 Compaction section)
- `apps/api/app/runtime/models.py` (C1 RetainedFact; C2 CompactionKind/Provider/ContextCompactionLog/PendingCompactionLog; C2 ObservabilitySummary fields; C4 `ProfilePhase.context_compaction`)
- `apps/api/app/runtime/repository.py` (C2 protocol additions **and** `InMemoryRepository` impl — both live in this one file; there is no `in_memory_repository.py`) + `storage/sql_repository.py` + `storage/orm.py` (C2)
- `apps/api/app/api/deps.py` (C3 config-gate injection)
- `apps/api/app/config.py` (C1 reserve tokens; C3/C4 compaction_* + llm_summarizer_*)
- `apps/api/app/benchmark/evaluator.py` + `runner.py` + `cases.py` (C5 case_9 + metric quad)

Create:
- `apps/api/app/memory/summarizer_provider.py` (C3)
- `migrations/versions/0005_context_compaction.py` (C2 Alembic)
- `apps/api/tests/memory/test_summarizer_provider.py`, `tests/runtime/test_summarizer_fallback.py`, `tests/runtime/test_context_compaction.py`, `tests/observability/test_compaction_log.py` (C2/C3/C4)

## 6. Dependency order

```
C0 (refactor)
  -> C1 (over-budget compensation, no LLM, default-on)
       -> C2 (compaction log + observability + replay wiring)
            -> C3 (SummarizerProvider abstraction, no rolling summary yet)
                 -> C4 (rolling history summary, persists into C2 log)
                      -> C5 (benchmark case_9 + retention metrics + docs)
```

Rationale: C0 removes the refactor risk before behavior changes; C1 ships a default-on safety fix without touching the provider stack; **C2 lands persistence before C3/C4 so observability is durable from day one** (the reviewer's key point); C3 is an abstraction with no runtime hot-path effect; C4 is the only Issue that touches the retrieval hot path and is config-gated default-off; C5 closes the loop.

## 7. Verification (end-to-end)

1. Per-Issue TDD: run new tests RED first (`uv run --extra dev pytest <file> -q`, expect fail), implement to GREEN.
2. Targeted regression: `uv run --extra dev pytest apps/api/tests/retrieval apps/api/tests/memory apps/api/tests/observability apps/api/tests/benchmark apps/api/tests/runtime apps/api/tests/storage -q`.
3. Migration: `uv run alembic upgrade head` + `downgrade -1` round-trip.
4. Full regression: `uv run --extra dev pytest -q` all green.
5. Deterministic benchmark: `uv run python -m app.benchmark.runner --output-dir reports`, confirm `reports/benchmark_results.json` `acceptance.passed=true`. C5 originally introduced **8/8** checks including `variant_2_retains_constraints_under_compaction=true`; after Failure-aware I5 the current global acceptance suite is **10/10** with the two negative-memory checks added.
6. Reproducibility script: `./scripts/reproduce.sh` passes. C5-era output printed `acceptance.passed=true (8/8 checks true)`; current output after Failure-aware I5/I6 is `acceptance.passed=true (10/10 checks true)`.
7. Enabled-path manual checks:
   - **C1 always-on:** tiny-budget run -> `compacted_constraints` block present, key=value preserved, compaction log row exists, observability summary's `compaction_trigger_rate` > 0.
   - **C4 enabled:** `compaction_enabled=True` + over-window run -> `history_summary` block present, retained_facts non-empty, replay returns identical block; LLM provider enabled with key -> LLM path; offline/bad-key/timeout -> `provider="fallback_rule"` and no info loss.
   - **Safety:** failed-branch / superseded / secret / stale memories never appear in any compaction text (regression by `unsafe_compaction_leakage_rate`).

## 8. Risks & constraints

- **Cross-cutting (lifecycle filter — ROADMAP §1 vow):** any new injection path (rolling summary, compacted_constraints) must apply `_RETRIEVABLE_STATUSES` and gate semantics; never leak superseded/failed/stale/secret. Locked in by `unsafe_compaction_leakage` benchmark metric + targeted unit tests.
- **Determinism:** C1 default-on uses pure rule logic only. C3/C4 default off. LLM provider only via config-gate. Benchmark reproducibility unchanged.
- **Token estimation bias:** `estimate_tokens` is not a real tokenizer; `compression_ratio` is a relative measure — documented as approximate.
- **Hot-path intrusion (C4):** rolling summary is on the retrieval hot path; guarded by separate `compaction_timeout_ms`, degrading to **no-fold** (warning + non-empty context), **not** to empty context (which is the existing `retrieval_timeout_ms` behavior).
- **Replay stability:** replay reads persisted compaction log and never re-invokes the summarizer, so an LLM-backed C4 stays replayable even with non-deterministic providers.
- **Cross-process compaction cache (deferred):** C4 keeps an access-level snapshot only; a `(run_id, active_path_hash, provider, threshold, summarizer_config_hash)` cache to avoid re-summarizing across many accesses in the same run is **out of scope** until profiling shows it matters (ROADMAP §10 / Phase 4).
- **Migration ordering:** `0005_context_compaction` strictly follows `0004_phase3a_observability` (tick `down_revision` accordingly). PG15 vs pg16 caveat from ROADMAP §1 still applies; no schema interaction with pgvector.
- **`MemoryAccessLog` deliberately not extended:** the reviewer offered both options; this plan picks `ContextCompactionLog` so that one access can carry multiple compaction events (`budget_notice` + `history_summary`) and so the access-log row stays tight. Documented here so future readers don't re-debate it.

## 9. Implementation invariants (read before coding — prevents drift)

These are non-negotiable rules an implementer must preserve across all Issues:

1. **Ownership:** `MemoryRuntime` may *prepare* pending compaction inputs, but `RetrievalController` owns `access_id` creation and persistence of all access-scoped records. The runtime never calls `RetrievalController.trace(...)` or `_persist_trace(...)` directly.
2. **access_id timing:** C4 returns a `PendingCompactionLog` **without** `access_id`; the controller materializes it (via `.materialize(access_id=...)`) only after the `MemoryAccessLog` is created.
3. **Single persist path:** both `budget_notice` (C1) and `history_summary` (C4) records are persisted by the same `_persist_trace` loop over `trace.pending_compaction_logs`. No second persistence site.
4. **Protected ≠ unlimited:** protected blocks are never *silently* dropped, but may be deterministically truncated (`fit_block`) to keep `used <= token_budget`. Truncation always emits a warning.
5. **Fact provenance:** `RetainedFact` key/value come from `MemoryItem.key`/`MemoryItem.value` (looked up by `block.memory_id`), never from regex over rendered `ContextBlock.content`.
6. **Two filter sets:** raw active-path events use the raw-event filter (active-path/secret/failed/tool-sensitive); `MemoryItem`s use `_RETRIEVABLE_STATUSES` + gate semantics. `_RETRIEVABLE_STATUSES` does not apply to raw events.
7. **Replay never re-summarizes:** replay reads the persisted compaction log; it must not call the summarizer provider again.
