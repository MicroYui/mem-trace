# I7 Compaction Negative Retention Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` (recommended) or `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve failure-aware negative lessons through context compaction, replay, observability, and benchmark reporting without ever converting failed/rolled-back memories into positive prompt context.

**Architecture:** I7 extends the existing negative-evidence channel instead of changing retrieval admission semantics. Dropped `avoided_attempts` blocks are converted into a dedicated `RetainedNegativeEvidence` DTO and persisted on compaction logs through a dedicated JSONB column; positive `retained_facts` remains reserved for positive `key=value` facts. Prompt packing stays budget-driven: retained negative evidence is metadata for replay/observability and must not force `avoided_attempts` blocks into the final prompt.

**Tech Stack:** Python 3.12, Pydantic v2, FastAPI runtime models, SQLAlchemy async + Alembic, pytest/pytest-asyncio, deterministic benchmark runner.

---

## 0. Source-Verified Decisions

- `NegativeEvidence` already exists as a safe DTO with only `safe_text` exposed to the packer; unsafe failures use fixed sanitized templates in `apps/api/app/runtime/models.py` and `apps/api/app/retrieval/negative_evidence.py`.
- `ContextBlock(type="avoided_attempts", source="negative_evidence")` is already the negative prompt block shape, built by `build_negative_evidence_block(...)` in `apps/api/app/retrieval/packer.py`.
- `ContextCompactionLog` currently has `retained_facts` but no generic metadata field in either Pydantic or SQL ORM models. Therefore this plan **does not** adopt the suggestion to use `metadata["retained_negative_evidence"]`; it adopts the semantic intent and uses a dedicated `retained_negative_evidence` field/JSONB column instead.
- `retained_facts` is currently consumed by evaluator, reports, replay, and trace-bundle redaction as positive `key=value` facts. I7 must not overload that field.
- `NegativeEvidence.risk_kind` currently comes from a small internal alias (`secret`, `destructive`, `tool_sensitive`, `unknown`), but retained observability metadata should not crash if future risk reasons expand. `RetainedNegativeEvidence.risk_kind` therefore uses `str | None`; the conversion helper may normalize known aliases but must tolerate unknown strings.
- `build_negative_evidence_block(...)` currently copies `ev.provenance` into `ContextBlock.provenance` and separately has access to `ev.source_state_node_id`; if `ev.provenance` is `None`, a state-node fallback would otherwise be lost.
- `pack_context(...)` currently builds `memory_by_id = {m.memory_id: m for m in accepted}`. This map is accepted-positive-memory-only by design and usually excludes failed/rolled_back memories that produced negative evidence; I7 retention must use negative-evidence maps, not `memory_by_id`, for negative lookup.
- The current Alembic head revision is source-verified in `migrations/versions/0006_security_consistency_hardening.py` as `revision = "0006_security_consistency_hardening"`; implementation must still read the actual current head before creating the I7 migration rather than inferring it from a filename prefix.
- `_bump_access_counts(...)` currently increments only `access_count`; I7 does not modify lifecycle scoring, but Phase 4 later should update `last_accessed_at` together with access count.

## 1. Non-Goals and Invariants

- Do not change gate decisions: failed/rolled_back memories remain excluded from positive accepted context.
- Do not make `avoided_attempts` protected blocks. They remain ordinary prompt blocks and may be dropped under budget pressure.
- Do not persist raw unsafe commands or raw secret-bearing content in compaction logs, reports, replay, trace bundles, or benchmark JSON.
- Do not add Redis/Celery, lifecycle scheduler, governance, TypeScript SDK, MCP, or IDE changes in this slice.
- Do not update `AGENTS.md` unless implementation discovers a durable working agreement change.

## 2. File Map

### Core models and storage

- Modify: `apps/api/app/runtime/models.py`
  - Add `RetainedNegativeEvidence` next to `NegativeEvidence`.
  - Add `retained_negative_evidence: list[RetainedNegativeEvidence]` to `ContextCompactionLog` and `PendingCompactionLog`.
  - Materialize pending logs with both positive retained facts and retained negative lessons.
- Modify: `apps/api/app/storage/orm.py`
  - Add `ContextCompactionORM.retained_negative_evidence` as JSONB with default empty list.
- Modify: `apps/api/app/storage/sql_repository.py`
  - Map `retained_negative_evidence` in both ORM -> model and model -> ORM conversions.
- Modify: `apps/api/app/runtime/repository.py`
  - In-memory compaction logs already store model copies; no new repository method is needed.
- Create migration: `migrations/versions/0007_i7_retained_negative_evidence.py`
  - Add nullable/backfilled-compatible JSONB column with PostgreSQL JSONB server default `sa.text("'[]'::jsonb")`, following the H15 migration policy.

### Negative evidence and packing

- Modify: `apps/api/app/retrieval/negative_evidence.py`
  - Add conversion helper `to_retained_negative_evidence(...)`.
- Modify: `apps/api/app/retrieval/packer.py`
  - Extract retained negative evidence from dropped `avoided_attempts` blocks.
  - Carry retained negative evidence into `PendingCompactionLog` and `PackResult` without changing final prompt behavior.

### Observability and safety surfaces

- Modify: `apps/api/app/observability/replay.py`
  - Surface persisted retained negative evidence from compaction logs; do not rerun summarizers or reconstruct raw failed text.
- Modify: `apps/api/app/observability/metrics.py`
  - Add summary counters distinct from actual prompt block counters.
- Modify: `apps/api/app/observability/reports.py`
  - Add JSON/Markdown/HTML report fields/rows for retained negative evidence.
- Modify: `apps/api/app/observability/trace_bundle.py`
  - Redact retained negative evidence keys/text defensively in exported bundles.

### Benchmark and docs

- Modify: `apps/api/app/benchmark/cases.py`, `evaluator.py`, `runner.py`
  - Add `case_13_compaction_retains_negative_lesson` and acceptance metric.
- Modify tests under `apps/api/tests/retrieval/`, `observability/`, `benchmark/`, `storage/`.
- Modify closeout docs: `docs/design/CONTEXT_COMPACTION_PLAN.md`, `docs/design/FAILURE_AWARE_NEGATIVE_MEMORY_PLAN.md`, `docs/design/ROADMAP.md`, `.ai/PROJECT_STATE.md`, `.ai/REQUIREMENTS.md`, `.ai/IMPLEMENTATION_PLAN.md`, `.ai/OPEN_QUESTIONS.md`, `.ai/PITFALLS.md`.

---

## 3. Task I7.1 — Retained Negative Evidence Contract

**Files:**
- Modify: `apps/api/app/runtime/models.py`
- Modify: `apps/api/app/retrieval/negative_evidence.py`
- Test: `apps/api/tests/retrieval/test_packer_negative.py`

- [x] **Step 1: Add RED tests for conversion shape**
  - Add `test_negative_retained_conversion_preserves_safe_failed_attempt_only()`:
    - Build a safe `NegativeEvidence(mode="raw_failed_attempt", safe_text="npm install failed with lockfile mismatch")`.
    - Convert it with `to_retained_negative_evidence(...)`.
    - Assert `safe_text`, `source_memory_id`, `source_state_node_id`, `mode`, `reason`, and provenance survive.
    - Assert no field named `content`, `raw_content`, or `memory_content` appears in `model_dump()`.
  - Add `test_negative_retained_conversion_uses_sanitized_text_for_risky_attempt()`:
    - Build `NegativeEvidence(mode="sanitized_risk_notice", risk_kind="destructive", safe_text=SANITIZED_TEMPLATES["destructive"])`.
    - Assert the retained dump does not contain `rm -rf`, `/prod`, `sk-`, `password`, or `Authorization`.

- [x] **Step 2: Run the RED tests**
  - Command: `uv run --extra dev pytest apps/api/tests/retrieval/test_packer_negative.py -k "negative_retained_conversion" -q`
  - Expected before implementation: import failure or attribute error for missing `RetainedNegativeEvidence` / `to_retained_negative_evidence`.

- [x] **Step 3: Add `RetainedNegativeEvidence` model**
  - Add next to `NegativeEvidence` in `apps/api/app/runtime/models.py`:
    - `source_memory_id: str | None`
    - `source_state_node_id: str | None`
    - `mode: Literal["raw_failed_attempt", "sanitized_risk_notice"]`
    - `risk_kind: str | None`
    - `reason: str`
    - `safe_text: str`
    - `provenance: Provenance | None`
    - `created_from_block_type: Literal["avoided_attempts"] = "avoided_attempts"`
  - Keep the model intentionally small; do not include raw `MemoryItem.content`.

- [x] **Step 4: Implement conversion helper**
  - Add `to_retained_negative_evidence(evidence: NegativeEvidence) -> RetainedNegativeEvidence` in `negative_evidence.py`.
  - It must copy only safe DTO fields and pass `safe_text` through `redact(...)` as defense-in-depth.
  - It must not look up or read `MemoryItem.content`; retained metadata is derived from `NegativeEvidence.safe_text` only.
  - If normalizing risk kinds, map `destructive_command`/`destructive` to `destructive`, `production_env`/`tool_sensitive` to `tool_sensitive`, `secret` to `secret`, and otherwise preserve the string or use `unknown` without raising validation errors.
  - Export it in `__all__`.

- [x] **Step 5: Run GREEN tests**
  - Command: `uv run --extra dev pytest apps/api/tests/retrieval/test_packer_negative.py -k "negative_retained_conversion" -q`
  - Expected: both tests pass.

---

## 4. Task I7.2 — Persist Dedicated Compaction-Log Field

**Files:**
- Modify: `apps/api/app/runtime/models.py`
- Modify: `apps/api/app/storage/orm.py`
- Modify: `apps/api/app/storage/sql_repository.py`
- Create: `migrations/versions/0007_i7_retained_negative_evidence.py`
- Test: `apps/api/tests/storage/test_migrations.py`
- Test: `apps/api/tests/observability/test_trace_bundle.py`

- [x] **Step 1: Add RED storage/migration assertions**
  - In migration tests, assert every migration after `0006_security_consistency_hardening` declares revision/down_revision/upgrade/downgrade.
  - Add a test that the new migration adds `retained_negative_evidence` with server default/backfill semantics.
  - In trace-bundle tests, create a `ContextCompactionLog(retained_negative_evidence=[...])` and assert raw unsafe markers are redacted in exported bundle output.

- [x] **Step 2: Extend Pydantic compaction models**
  - Add `retained_negative_evidence: list[RetainedNegativeEvidence] = Field(default_factory=list)` to `ContextCompactionLog`.
  - Add the same field to `PendingCompactionLog`.
  - Update `PendingCompactionLog.materialize(...)` to pass a copied list.

- [x] **Step 3: Add SQL column and mapping**
  - Add the column with an explicit PostgreSQL JSONB default:
    ```python
    retained_negative_evidence: Mapped[list] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=sa.text("'[]'::jsonb"),
    )
    ```
  - When writing Pydantic models to ORM rows, serialize with:
    ```python
    retained_negative_evidence=[
        item.model_dump(mode="json")
        for item in log.retained_negative_evidence
    ]
    ```
  - When reading ORM rows into Pydantic models, deserialize with:
    ```python
    retained_negative_evidence=[
        RetainedNegativeEvidence.model_validate(item)
        for item in (row.retained_negative_evidence or [])
    ]
    ```
  - Old rows with `None` or missing values map to an empty list.

- [x] **Step 4: Add Alembic migration**
  - Revision name: `0007_i7_retained_negative_evidence`.
  - Set `down_revision` to the actual current Alembic head revision id from `migrations/versions`, not merely to an inferred filename prefix. At plan-writing time the source-verified head is `0006_security_consistency_hardening`.
  - `upgrade()` adds JSONB column to `context_compaction_logs` with non-null empty-list default:
    ```python
    op.add_column(
        "context_compaction_logs",
        sa.Column(
            "retained_negative_evidence",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    ```
  - `downgrade()` drops the column.
  - Keep the migration deterministic and compatible with H15 migration tests.

- [x] **Step 5: Run storage and bundle tests**
  - Command: `uv run --extra dev pytest apps/api/tests/storage/test_migrations.py apps/api/tests/observability/test_trace_bundle.py -q`
  - Expected: all tests pass; no raw unsafe text appears in bundle assertions.

---

## 5. Task I7.3 — Packer Retains Dropped Negative Evidence as Metadata

**Files:**
- Modify: `apps/api/app/retrieval/packer.py`
- Test: `apps/api/tests/retrieval/test_packer_negative.py`

- [x] **Step 1: Add RED budget-pressure tests**
  - Add `test_negative_evidence_retained_when_avoided_attempt_block_dropped_by_compaction()`:
    - Build active state, project constraint, one safe `NegativeEvidence`, and enough ordinary episodic memories to exceed a tight token budget.
    - Call `pack_context(...)` with `negative_evidence=[safe_ev]`.
    - Assert final `blocks` do not necessarily contain the `avoided_attempts` block.
    - Assert `pending_compaction_logs[0].retained_negative_evidence` contains the safe retained lesson.
    - Assert `retained_constraints` still contains only positive `RetainedFact` entries.
  - Add `test_retained_negative_evidence_does_not_force_prompt_injection()`:
    - Compare `len([b for b in result.blocks if b.type == "avoided_attempts"])` against normal budget behavior.
    - Assert retention metadata can be non-empty while final prompt blocks exclude the dropped negative block.

- [x] **Step 2: Run RED tests**
  - Command: `uv run --extra dev pytest apps/api/tests/retrieval/test_packer_negative.py -k "retained_negative_evidence" -q`
  - Expected before implementation: no retained negative evidence on pending compaction logs.

- [x] **Step 3: Preserve block -> evidence mapping without raw text**
  - Add enough metadata to `build_negative_evidence_block(...)` or packer-local bookkeeping so a dropped negative block can be converted back to `RetainedNegativeEvidence` without parsing raw prompt text.
  - Preferred approach: build a `negative_by_memory_id` map from the input `negative_evidence` list before constructing blocks.
  - Do **not** use `memory_by_id` for retained negative evidence lookup: `memory_by_id` contains only accepted positive memories and intentionally excludes most failed/rolled_back negative-evidence sources.
  - For blocks without a source memory id, map by `(source_state_node_id, reason)` if present; otherwise skip retention and count it as a warning rather than parsing block content.
  - Preserve state provenance for the fallback path: when building negative evidence blocks, set `ContextBlock.provenance` to `ev.provenance` if present, otherwise use `Provenance(state_node_id=ev.source_state_node_id)` when `source_state_node_id` is available.

- [x] **Step 4: Add extraction helper in packer**
  - Implement `extract_retained_negative_evidence(dropped_blocks, negative_by_memory_id, negative_by_state_reason) -> list[RetainedNegativeEvidence]`.
  - Only process standard negative-evidence prompt blocks where `block.type == "avoided_attempts"` **and** `block.source == "negative_evidence"`.
  - Dedupe by the full semantic identity `(source_memory_id or "", source_state_node_id or "", mode, reason, safe_text)` so two distinct failed attempts with identical sanitized text are not accidentally collapsed.
  - Sort deterministically by `(source_state_node_id or "", source_memory_id or "", mode, reason, safe_text)`.

- [x] **Step 5: Thread retained lessons through compaction log creation**
  - Add a `retained_negative_evidence` parameter to `_build_pending_budget_notice_log(...)`.
  - Recompute retained negative evidence whenever `dropped` changes in the overflow loop, just like `retained_facts` is recomputed.
  - Add `retained_negative_evidence` to `PackResult` only if tests need direct inspection outside pending logs; otherwise pending logs are the durable interface.

- [x] **Step 6: Run GREEN packer suite**
  - Command: `uv run --extra dev pytest apps/api/tests/retrieval/test_packer_negative.py -q`
  - Expected: all packer-negative tests pass; existing positive compaction tests remain unchanged.

---

## 6. Task I7.4 — Replay, Metrics, Reports, and Trace Bundle

**Files:**
- Modify: `apps/api/app/observability/replay.py`
- Modify: `apps/api/app/observability/metrics.py`
- Modify: `apps/api/app/observability/reports.py`
- Modify: `apps/api/app/observability/trace_bundle.py`
- Test: `apps/api/tests/observability/test_replay.py`
- Test: `apps/api/tests/observability/test_reports.py`
- Test: `apps/api/tests/observability/test_trace_bundle.py`

- [x] **Step 1: Add RED replay/report tests**
  - Replay test: retrieve with compaction that drops a negative block, then `replay_access(access_id)`, and assert `result.compaction_logs[0].retained_negative_evidence` is populated from storage.
  - Metrics test: assert `retained_negative_evidence_count` differs from `negative_evidence_block_count` when metadata is retained but the prompt block is dropped.
  - Report test: assert JSON report includes retained negative evidence counts and sanitized rows; Markdown/HTML must not include unsafe raw markers.

- [x] **Step 2: Update metrics**
  - Add `retained_negative_evidence_count` and `sanitized_retained_negative_evidence_count` to `ObservabilitySummary` and per-access metric calculations.
  - Keep `negative_evidence_block_count` as “actual prompt block count”.

- [x] **Step 3: Update replay**
  - Replay should read `ContextCompactionLog.retained_negative_evidence` directly.
  - Do not rerun summarizers or rebuild negative evidence from raw failed memories for compaction-retained metadata.
  - Do not infer an “I7-era access” from retrieval policy snapshots; I7 changes compaction-log metadata schema, not retrieval admission or prompt semantics.
  - Old rows where `retained_negative_evidence` is missing/`None` map silently to `[]` unless a future dedicated compaction-log schema version is added.

- [x] **Step 4: Update reports and bundles**
  - Add JSON report row field `retained_negative_evidence` with each item serialized in JSON mode.
  - Add Markdown/HTML columns/counts named “Retained negative evidence”.
  - In trace-bundle redaction, apply the same recursive redaction used for retained facts to every retained negative evidence field.

- [x] **Step 5: Run observability suite**
  - Command: `uv run --extra dev pytest apps/api/tests/observability/test_replay.py apps/api/tests/observability/test_reports.py apps/api/tests/observability/test_trace_bundle.py -q`
  - Expected: all pass.

---

## 7. Task I7.5 — Benchmark Case 13 and Acceptance

**Files:**
- Modify: `apps/api/app/benchmark/cases.py`
- Modify: `apps/api/app/benchmark/evaluator.py`
- Modify: `apps/api/app/benchmark/runner.py`
- Test: `apps/api/tests/benchmark/test_runner.py`

- [x] **Step 1: Add RED benchmark tests**
  - Add a test expecting `case_13_compaction_retains_negative_lesson` in the case list.
  - Add a test expecting acceptance key `variant_2_retains_negative_lesson_under_compaction`.
  - Add assertions for these four metrics on the case/strategy row:
    - `positive_contamination == 0`
    - `retained_negative_evidence_count > 0`
    - `unsafe_negative_leakage == 0`
    - `task_success == 1`
  - Add a test comment/assertion explaining that `task_success == 1` proves I7 did not break the existing positive/project-context success path; it must not depend on retained negative metadata entering the prompt.

- [x] **Step 2: Implement case seed**
  - Seed a safe failed attempt that should become negative evidence, plus enough ordinary memory to trigger compaction.
  - Use a tight budget that drops ordinary prompt blocks but still writes a compaction log.
  - Ensure the task already succeeds from positive/project context; retained negative evidence is metadata-only and must not be required for prompt-time task success.
  - Keep unsafe/destructive marker coverage in a separate case/assertion so safe and unsafe semantics are independently visible.

- [x] **Step 3: Extend evaluator and runner**
  - Count retained negative evidence from compaction logs, not from final prompt blocks.
  - Preserve existing positive/negative block split; do not count current user query terms as contamination.
  - Document in evaluator comments that retained negative evidence is not prompt input; the acceptance key checks metadata retention and safety, not model usage of retained metadata.
  - Update report summary and acceptance count deterministically.

- [x] **Step 4: Run benchmark targeted tests**
  - Command: `uv run --extra dev pytest apps/api/tests/benchmark/test_runner.py -k "compaction_retains_negative" -q`
  - Expected: pass after implementation.

---

## 8. Task I7.6 — Closeout Verification and Documentation Sync

**Files:**
- Modify: `docs/design/CONTEXT_COMPACTION_PLAN.md`
- Modify: `docs/design/FAILURE_AWARE_NEGATIVE_MEMORY_PLAN.md`
- Modify: `docs/design/ROADMAP.md`
- Modify: `.ai/PROJECT_STATE.md`, `.ai/REQUIREMENTS.md`, `.ai/IMPLEMENTATION_PLAN.md`, `.ai/OPEN_QUESTIONS.md`, `.ai/PITFALLS.md`

- [x] **Step 1: Run affected regression**
  - Command: `uv run --extra dev pytest apps/api/tests/retrieval apps/api/tests/observability apps/api/tests/benchmark/test_runner.py apps/api/tests/storage/test_migrations.py -q`
  - Expected: all pass.

- [x] **Step 2: Run compile and full regression**
  - Command: `uv run --extra dev python -m compileall -q apps/api/app packages/python-sdk/src examples`
  - Expected: no output / success.
  - Command: `uv run --extra dev pytest -q`
  - Expected: full suite passes; record exact count in `.ai/PROJECT_STATE.md`.

- [x] **Step 3: Run benchmark and reproducibility**
  - Command: `uv run python -m app.benchmark.runner --output-dir reports`
  - Expected: benchmark exits 0 and acceptance includes case 13.
  - Command: `bash scripts/reproduce.sh`
  - Expected: `acceptance.passed=true`; record exact acceptance count.

- [x] **Step 4: Run unsafe-marker scan over generated outputs**
  - After benchmark/report generation, inspect generated JSON/Markdown/HTML and any trace-bundle outputs created by tests for unsafe markers: `rm -rf`, `/prod`, `sk-`, `password`, `Authorization`.
  - Prefer adding automated assertions in report/trace-bundle tests; if a manual grep is used during closeout, record the command and result in `.ai/PROJECT_STATE.md`.

- [x] **Step 5: Sync docs/memory**
  - Mark I7 complete in `FAILURE_AWARE_NEGATIVE_MEMORY_PLAN.md`, `CONTEXT_COMPACTION_PLAN.md`, and `ROADMAP.md`.
  - Update `.ai` files with current state, changed files, verification commands, and next recommended target.
  - Add a pitfall: retained negative evidence is metadata and must never be mixed into positive `retained_facts` or protected prompt blocks.

---

## 9. Self-Review Checklist

- [x] I7 is scoped independently from Phase 4 async/lifecycle/governance and integrations.
- [x] The plan rejects `retained_facts` overloading and uses a dedicated persisted field because source models have no generic compaction metadata field.
- [x] Prompt behavior invariant is explicit: metadata retention does not force prompt injection.
- [x] SQL JSONB defaults, Pydantic/ORM serialization, replay old-row behavior, and benchmark metadata-only semantics are specified precisely enough for implementation.
- [x] Tests cover safe conversion, unsafe redaction, budget pressure, replay, reports, trace bundle, benchmark acceptance, migration policy, and full reproducibility.
- [x] Docs/project-memory closeout is included as an implementation task.
