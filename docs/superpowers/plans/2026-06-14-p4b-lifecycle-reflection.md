# P4-B Lifecycle and Reflection Scheduler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement Phase 4 P4-B lifecycle/reflection scheduler end to end without changing deterministic local/benchmark defaults.

**Architecture:** Add two durable records (`MemoryLifecycleAuditRecord`, `MemoryRetentionSignal`) and focused memory modules (`lifecycle.py`, `retention.py`, `scheduler.py`). Keep `MemoryRuntime`/`RetrievalController` as the behavior boundary; Celery task wrappers only call scheduler/runtime-level functions. `variant_3` uses persisted scheduler signals when present and falls back to existing deterministic reflection-lite scoring otherwise.

**Tech Stack:** Python 3.12, Pydantic v2, SQLAlchemy async, Alembic, pytest/pytest-asyncio, optional Celery/Redis.

---

## File Map

- Create `apps/api/app/memory/lifecycle.py`: transition validation and audit-record construction.
- Create `apps/api/app/memory/retention.py`: deterministic retention/reflection scoring.
- Create `apps/api/app/memory/scheduler.py`: pure async scheduler functions.
- Modify `apps/api/app/runtime/models.py`: add `MemoryLifecycleAuditRecord` and `MemoryRetentionSignal`.
- Modify `apps/api/app/runtime/repository.py`: add protocol and in-memory methods for audits/signals.
- Modify `apps/api/app/storage/orm.py`: add `MemoryLifecycleAuditORM` and `MemoryRetentionSignalORM`.
- Modify `apps/api/app/storage/sql_repository.py`: add ORM conversions and SQL methods.
- Create Alembic migrations `0008_phase4_lifecycle.py` and `0009_memory_retention_signals.py`.
- Modify `apps/api/app/retrieval/controller.py`: update access timestamps; bulk-load retention signals for `variant_3`.
- Modify `apps/api/app/retrieval/policy.py`: add reflection signal source/version fields to policy snapshot.
- Modify `apps/api/app/async_tasks/tasks.py`: add maintenance scheduler task wrappers.
- Tests: `apps/api/tests/memory/test_lifecycle.py`, `apps/api/tests/memory/test_retention_scheduler.py`, `apps/api/tests/retrieval/test_retrieval_flow.py`, `apps/api/tests/conformance/test_strategy_conformance.py`, `apps/api/tests/benchmark/test_runner.py`, `apps/api/tests/observability/test_replay.py`, `apps/api/tests/storage/test_migrations.py`.

---

## Task 1: B1 Lifecycle Transition Policy and Audit

**Files:**
- Create: `apps/api/app/memory/lifecycle.py`
- Modify: `apps/api/app/runtime/models.py`
- Modify: `apps/api/app/runtime/repository.py`
- Modify: `apps/api/app/storage/orm.py`
- Modify: `apps/api/app/storage/sql_repository.py`
- Create: `migrations/versions/0008_phase4_lifecycle.py`
- Test: `apps/api/tests/memory/test_lifecycle.py`
- Test: `apps/api/tests/storage/test_migrations.py`

- [ ] Write RED tests for allowed transitions, rejected transitions, pin/unpin previous-status restoration, scheduler refusing to archive pinned memory, and audit persistence.
- [ ] Run `uv run --extra dev pytest apps/api/tests/memory/test_lifecycle.py -q` and confirm failures are due to missing lifecycle module/models/repository methods.
- [ ] Add `MemoryLifecycleAuditRecord` to `runtime/models.py` with `audit_id`, `workspace_id`, `memory_id`, `from_status`, `to_status`, `reason`, `actor`, `scheduler_run_id`, `metadata`, and `created_at`.
- [ ] Implement `transition_memory_status(memory, to_status, reason, actor, scheduler_run_id=None, metadata=None)` in `memory/lifecycle.py`; return `(updated_memory, audit_record)` and never mutate invalid transitions.
- [ ] Add repository protocol/in-memory `add_lifecycle_audit` and `list_lifecycle_audits`.
- [ ] Add SQL ORM/table/conversions/methods and migration `0008_phase4_lifecycle.py` with index `(workspace_id, memory_id, created_at)`.
- [ ] Run `uv run --extra dev pytest apps/api/tests/memory/test_lifecycle.py apps/api/tests/storage/test_migrations.py -q` and confirm pass.

## Task 2: B2 Retention Signal Storage and Access Timestamp

**Files:**
- Create: `apps/api/app/memory/retention.py`
- Modify: `apps/api/app/runtime/models.py`
- Modify: `apps/api/app/runtime/repository.py`
- Modify: `apps/api/app/storage/orm.py`
- Modify: `apps/api/app/storage/sql_repository.py`
- Modify: `apps/api/app/retrieval/controller.py`
- Create: `migrations/versions/0009_memory_retention_signals.py`
- Test: `apps/api/tests/memory/test_retention_scheduler.py`
- Test: `apps/api/tests/retrieval/test_retrieval_flow.py`

- [ ] Write RED tests for deterministic scoring inputs, expired/high-risk low retention, signal upsert/list/get, and retrieval updating `last_accessed_at` with `access_count`.
- [ ] Run targeted tests and confirm failures are missing scoring/model/repository/timestamp behavior.
- [ ] Add `MemoryRetentionSignal` to `runtime/models.py` with `memory_id`, `workspace_id`, `retention_score`, `reflection_priority`, `reason`, `policy_version`, `scored_at`, and `updated_at`.
- [ ] Implement `compute_retention_signals(memory, now, policy=RetentionPolicy())` in `memory/retention.py`; clamp all components to `[0, 1]`, lower expired/high-risk retention, and return `MemoryRetentionSignal`.
- [ ] Add repository protocol/in-memory and SQL methods: `upsert_retention_signal`, `get_retention_signal`, and `list_retention_signals(workspace_id, memory_ids=None)`.
- [ ] Add SQL ORM/table/conversions/methods and migration `0009_memory_retention_signals.py` with primary key `memory_id` and index `(workspace_id, reflection_priority)`.
- [ ] Update `RetrievalController._bump_access_counts(...)` to set `last_accessed_at` to one shared `now` while incrementing access counts.
- [ ] Run `uv run --extra dev pytest apps/api/tests/memory/test_retention_scheduler.py apps/api/tests/retrieval/test_retrieval_flow.py -q` and confirm pass.

## Task 3: B3 Scheduler Functions, Celery Wrappers, and Variant 3 Signal Source

**Files:**
- Create: `apps/api/app/memory/scheduler.py`
- Modify: `apps/api/app/async_tasks/tasks.py`
- Modify: `apps/api/app/retrieval/controller.py`
- Modify: `apps/api/app/retrieval/policy.py`
- Test: `apps/api/tests/memory/test_retention_scheduler.py`
- Test: `apps/api/tests/conformance/test_strategy_conformance.py`

- [ ] Write RED tests for `score_memory`, `decay_memory`, `archive_memory`, `quarantine_memory`, `profile_refresh`, Celery wrapper idempotency keys, bulk signal loading, and `variant_3` using `reflection_priority` when present.
- [ ] Run targeted tests and confirm failures are missing scheduler/wrapper/policy behavior.
- [ ] Implement pure async scheduler functions in `memory/scheduler.py`; each accepts `repo`, `workspace_id`, optional `now`, and `scheduler_run_id`, and returns deterministic count/metadata dicts.
- [ ] Add Celery-compatible wrappers in `async_tasks/tasks.py` that call the scheduler functions through an injected/runtime repository boundary and return `TaskResult`.
- [ ] Update `RetrievalController.trace(...)` to bulk-load retention signals for accepted memory ids when `GateConfig.enable_reflection_rerank` is true.
- [ ] Update `variant_3` scoring to blend `final_score` with persisted `reflection_priority` if present, otherwise fallback to existing `retention_score(mem)`.
- [ ] Update `retrieval/policy.py` to include `reflection_signal_source` and `retention_policy_version` in policy snapshots and therefore hashes.
- [ ] Add/extend conformance tests for dormant/archived/deleted exclusion, pinned eligibility, and quarantined hard rejection.
- [ ] Run `uv run --extra dev pytest apps/api/tests/conformance apps/api/tests/memory/test_retention_scheduler.py -q` and confirm pass.

## Task 4: B4 Benchmark and Replay Closeout

**Files:**
- Modify: `apps/api/app/benchmark/runner.py` if metrics need scheduler-source surfacing.
- Modify: `apps/api/tests/benchmark/test_runner.py`
- Modify: `apps/api/tests/observability/test_replay.py`
- Modify: `docs/design/PHASE4_PLATFORM_PLAN.md`
- Modify: `docs/design/ROADMAP.md`
- Modify: `.ai/PROJECT_STATE.md`
- Modify: `.ai/REQUIREMENTS.md`
- Modify: `.ai/IMPLEMENTATION_PLAN.md`
- Modify: `.ai/PITFALLS.md`

- [ ] Write/update tests proving case 12 uses scheduler-derived signal when present and default benchmark/reproduce remain fallback-lite deterministic.
- [ ] Add replay/policy drift coverage showing `reflection_signal_source` or `retention_policy_version` changes policy hashes.
- [ ] Run `uv run --extra dev pytest apps/api/tests/benchmark/test_runner.py apps/api/tests/retrieval/test_retrieval_flow.py apps/api/tests/observability/test_replay.py -q`.
- [ ] Run P4-B affected suite: `uv run --extra dev pytest apps/api/tests/memory/test_lifecycle.py apps/api/tests/memory/test_retention_scheduler.py apps/api/tests/conformance apps/api/tests/benchmark/test_runner.py apps/api/tests/retrieval/test_retrieval_flow.py apps/api/tests/observability/test_replay.py apps/api/tests/storage/test_migrations.py -q`.
- [ ] Run compile: `uv run --extra dev python -m compileall -q apps/api/app packages/python-sdk/src examples`.
- [ ] Run full regression: `uv run --extra dev pytest -q`.
- [ ] Run deterministic benchmark: `uv run python -m app.benchmark.runner --output-dir reports`.
- [ ] Run reproducibility: `bash scripts/reproduce.sh` and verify `acceptance.passed=true`.
- [ ] Update plan checkboxes/docs/project memory with observed verification results.

## Self-Review

- Spec coverage: B1 lifecycle/audit, B2 retention/timestamp, B3 scheduler/signal-backed variant_3, and B4 benchmark/replay/docs are each mapped to a task.
- Placeholder scan: no TBD/TODO placeholders remain.
- Type consistency: model names, repository method names, policy field names, and file paths are consistent across tasks.
