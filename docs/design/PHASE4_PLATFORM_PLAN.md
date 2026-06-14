# Phase 4 Platform Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` (recommended) or `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add production-oriented async infrastructure, durable memory lifecycle/reflection signals, version/conflict records, and default-off multi-tenant governance while preserving MemTrace's deterministic local/benchmark behavior.

**Architecture:** Phase 4 is split into four independently shippable streams: P4-A async foundation, P4-B lifecycle/reflection scheduler, P4-C versions/conflicts, and P4-D governance. `MemoryRuntime` remains the semantic boundary and `Repository` remains the storage boundary; Redis/Celery, schedulers, and governance dependencies must be optional by default and must not affect benchmark/reproduce unless explicitly enabled.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy async, Alembic, PostgreSQL/pgvector, optional Redis, optional Celery, pytest/pytest-asyncio, uv.

---

## 0. Source-Verified Decisions

- `ExtractionMode` currently has only `sync` and `buffered`; adding a Python enum member literally named `async` would be invalid because `async` is a reserved keyword. Use `async_ = "async"` in code while preserving JSON value `"async"`.
- `CandidateBuffer` is currently synchronous and stores full post-redaction `AgentEvent` copies. Phase 4 should introduce an async `CandidateBufferProtocol` because `MemoryRuntime` and repository APIs are already async.
- `AgentEvent` is redacted before buffering in the current write path; Redis buffering must store only post-redaction `AgentEvent` JSON, never raw `WriteEventRequest` payloads.
- `WriteEventResult` currently has `event`, `created_memory_ids`, and `buffered`. Async enqueue needs backward-compatible optional fields: `queued`, `task_id`, and `warnings`.
- `MemoryStatus.pinned` is a status, not a bool flag. Manual unpin must preserve and restore `previous_status` through lifecycle audit metadata.
- `MemoryItem` already has `value_score`, `freshness_score`, `trust_score`, `risk_score`, `access_count`, `last_accessed_at`, and `expires_at`, but no persisted scheduler output fields. Use a separate `memory_retention_signals` table for scheduler-derived retention/reflection signals.
- `_bump_access_counts(...)` currently increments only `access_count`; Phase 4 lifecycle scoring requires updating `last_accessed_at` at the same time.
- API routes include many resource-id endpoints (`run_id`, `step_id`, `access_id`) without explicit `workspace_id`. Governance must resolve resource ownership from ids before authorization.

## 1. Non-Goals and Durable Invariants

- Do not implement I7 in this plan; use `docs/design/I7_COMPACTION_NEGATIVE_RETENTION_PLAN.md` first.
- Do not add Elasticsearch/OpenSearch, Neo4j, graph retrieval, React dashboard, production LLM judge, or LoCoMo/MemoryArena benchmark in Phase 4.
- Do not require Redis/Celery for default local development, root pytest, deterministic benchmark, or `scripts/reproduce.sh`.
- Do not store raw secret payloads by default. Any encrypted raw-payload reference remains disabled unless governance explicitly enables and validates it.
- Do not bypass `MemoryRuntime` from API, SDK, workers, or schedulers.
- Celery task implementations must call `MemoryRuntime`-level methods or dedicated runtime service methods; they must not bypass redaction, writer/resolver, provider fallback, lifecycle audit, or governance checks by calling writer/resolver/storage internals directly.
- Celery workers must not import FastAPI `app_state` / `get_runtime()` for runtime access. Worker processes need a lazy runtime factory that owns settings, engine/session factory, repository, provider registry, runtime construction, and shutdown lifecycle outside the FastAPI startup hook.
- Do not create memory versions for access-count-only updates.

**Recommended execution slices:** do not implement all Phase 4 streams in one change. Start with P4-A1 + P4-A2 only; then P4-A3; then P4-A4 + P4-A5; then P4-B1 + P4-B2; then P4-B3 + P4-B4; then P4-C; and leave P4-D governance for the final cross-cutting stream.

---

## 2. Stream P4-A — Async Foundation

### P4-A1 Settings, Task Contracts, and Dependencies ✅ complete (2026-06-14)

**Files:**
- Modify: `pyproject.toml`
- Modify: `apps/api/app/config.py`
- Create: `apps/api/app/async_tasks/__init__.py`
- Create: `apps/api/app/async_tasks/contracts.py`
- Test: `apps/api/tests/async_tasks/test_contracts.py`

- [x] **Step 1: Write RED contract tests**
  - Assert `TaskEnvelope` JSON contains `task_id`, `task_type`, `workspace_id`, `dedupe_key`, `payload`, and `created_at`.
  - Assert payload validation rejects secret-like keys such as `api_key`, `authorization`, `password`, `secret`, and `token` unless stored under an explicitly redacted field name such as `redacted_event`.
  - Assert settings defaults keep async disabled and eager-safe: `async_tasks_enabled=False`, `celery_task_always_eager=True`.

- [x] **Step 2: Add dependencies and settings**
  - Add `celery>=5.4` and `redis>=5.0` to root dependencies.
  - Add settings: `redis_url`, `celery_broker_url`, `celery_result_backend`, `async_tasks_enabled`, `celery_task_always_eager`, `memory_queue_name`, `maintenance_queue_name`, `eval_queue_name`, `async_task_default_ttl_seconds`.
  - Defaults must not open network connections during import or pytest collection.

- [x] **Step 3: Implement contracts**
  - `TaskEnvelope` and `TaskResult` live in `async_tasks/contracts.py`.
  - Use Pydantic models and JSON-compatible payloads only.
  - Validation must reject non-redacted secret-like payload keys and non-finite numeric metadata.

- [x] **Step 4: Verify**
  - Command: `uv run --extra dev pytest apps/api/tests/async_tasks/test_contracts.py -q`
  - Expected: all pass.

### P4-A2 Celery App and Idempotency ✅ complete (2026-06-14)

**Files:**
- Create: `apps/api/app/async_tasks/celery_app.py`
- Create: `apps/api/app/async_tasks/runtime_factory.py`
- Create: `apps/api/app/async_tasks/idempotency.py`
- Create: `apps/api/app/async_tasks/tasks.py`
- Test: `apps/api/tests/async_tasks/test_celery_eager.py`

- [x] **Step 1: Write RED tests**
  - `make_celery_app(settings)` registers memory, maintenance, and eval queues.
  - Eager mode executes a task inline without Redis.
  - `InMemoryIdempotencyStore.acquire(key, ttl_seconds)` returns `True` once, then `False` for duplicates until release/expiry.
  - Celery serialization is JSON-only.
  - Worker task/runtime tests prove Celery tasks do not rely on FastAPI `app_state.runtime`; runtime construction is lazy and can be injected/faked in eager tests.

- [x] **Step 2: Implement Celery app factory**
  - Read settings lazily from function arguments, not module import side effects.
  - Disable result persistence unless `celery_result_backend` is configured.
  - Use `task_always_eager=True` by default for deterministic tests.
  - Task wrappers deserialize `TaskEnvelope`, acquire idempotency, and call runtime-level functions; do not directly mutate repository rows or call memory writer/resolver internals.

- [x] **Step 2b: Implement worker runtime factory**
  - Add `build_worker_runtime(settings) -> MemoryRuntime` (or an async context-manager equivalent) in `async_tasks/runtime_factory.py`.
  - The factory constructs settings-derived engine/session factory, `SqlRepository`, provider registry, and `MemoryRuntime` without importing FastAPI `app_state`.
  - The factory owns shutdown/disposal for worker-created engines; eager unit tests may inject an in-memory/fake runtime factory so no network or database connection is opened by default.

- [x] **Step 3: Implement idempotency abstraction**
  - Protocol: `async def acquire(key: str, ttl_seconds: int) -> bool` and `async def release(key: str) -> None`.
  - Provide in-memory implementation for tests.
  - Provide Redis implementation behind settings, covered by optional integration tests only.

- [x] **Step 4: Verify**
  - Command: `uv run --extra dev pytest apps/api/tests/async_tasks -q`
  - Expected: all async task unit tests pass without Redis.

### P4-A3 Async Candidate Buffer Protocol and Redis Buffer ✅ complete (2026-06-14)

**Files:**
- Create: `apps/api/app/memory/buffer.py`
- Modify: `apps/api/app/memory/candidate_buffer.py`
- Create: `apps/api/app/memory/redis_candidate_buffer.py`
- Modify: `apps/api/app/runtime/memory_runtime.py`
- Modify: `apps/api/app/api/deps.py`
- Test: `apps/api/tests/memory/test_candidate_buffer.py`

- [x] **Step 1: Write RED protocol tests**
  - Tests call `await buffer.append(event)`, `await buffer.pending(session_id, workspace_id=None)`, `await buffer.drain(session_id, workspace_id=None)`, `await buffer.size(session_id, workspace_id=None)`, `await buffer.total_size(workspace_id=None)`, and `await buffer.sessions(workspace_id=None)`.
  - Assert in-memory buffer keeps FIFO order and drains idempotently.
  - Assert buffered objects are deep copies and cannot be mutated through returned references.
  - Assert existing `flush_session(session_id)` compatibility: when `workspace_id=None`, the buffer drains all pending events for that session deterministically.

- [x] **Step 2: Extract async protocol**
  - Define `CandidateBufferProtocol` in `memory/buffer.py` with async methods only.
  - Protocol methods that read/drain/size by session accept optional `workspace_id: str | None = None`; existing runtime calls may pass only `session_id`.
  - Convert existing `CandidateBuffer` to async methods while keeping its deterministic in-process behavior.
  - Update `MemoryRuntime` to accept `candidate_buffer: CandidateBufferProtocol | None` and default to `CandidateBuffer()`.
  - Update all `MemoryRuntime` buffer call sites to `await` `append`, `drain`, `pending`, `size`, `total_size`, and `sessions`; public runtime/API/SDK method signatures stay unchanged.

- [x] **Step 3: Add fake Redis RED tests**
  - Use a fake async Redis object in unit tests.
  - Assert Redis keys include only workspace/session ids and never content snippets.
  - Assert Redis values contain only post-redaction `AgentEvent` JSON and never raw `WriteEventRequest` payloads.
  - Seed an event with `content="sk-raw-secret password=hunter2"` after runtime redaction and assert stored Redis value contains `[REDACTED]` but not the raw markers.

- [x] **Step 4: Implement Redis buffer**
  - Store serialized post-redaction `AgentEvent` JSON under workspace/session-scoped list keys.
  - Preserve the existing `flush_session(session_id)` API: `drain(session_id, workspace_id=None)` must deterministically drain all workspace-scoped Redis queues for that session (for example via a session-to-workspace key index) unless a specific `workspace_id` is supplied.
  - P4-D governance may later require a resolved/authorized workspace for cross-workspace session flushes, but P4-A must remain backward-compatible with current session-only API and SDK behavior.
  - Use atomic drain semantics in the real Redis implementation; unit tests may simulate the behavior with a fake.
  - Real Redis integration remains gated behind `MEMTRACE_TEST_REDIS_URL`.

- [x] **Step 5: Wire runtime selection**
  - `api/deps.py` chooses in-memory buffer by default.
  - Redis buffer is selected only when `async_tasks_enabled=True` and `redis_url` is configured.

- [x] **Step 6: Verify**
  - Command: `uv run --extra dev pytest apps/api/tests/memory/test_candidate_buffer.py packages/python-sdk/tests/test_backend_isomorphism.py -q`
  - Expected: all pass; sync/default behavior remains isomorphic.

**Implementation notes (2026-06-14):** P4-A1 through P4-A3 are implemented and fully reviewed. Root dependencies now include optional `celery` and `redis`; async task settings default to disabled/eager-safe. `TaskEnvelope` / `TaskResult` reject secret-like payload keys, raw secret-like values anywhere in payload/error/metadata, non-JSON payload values, and non-finite numeric metadata. `make_celery_app(...)`, `WorkerRuntimeHandle` / `build_worker_runtime(...)`, `InMemoryIdempotencyStore`, `RedisIdempotencyStore`, and `process_event_extraction(...)` provide the first worker boundary without importing FastAPI `app_state`; the Celery app registers `memory.extract_event`, default tests stay process-local, and settings-enabled workers lazily use Redis idempotency when async tasks are enabled. `CandidateBufferProtocol` is async; the in-process buffer remains deterministic and deep-copy safe; `RedisCandidateBuffer` stores post-redaction `AgentEvent` JSON under encoded workspace/session-scoped keys, tolerates Redis bytes responses, and uses a Lua-backed queue detach on real Redis so drain/index updates are atomic with respect to concurrent appends. `MemoryRuntime.process_event_extraction(event_id)` is the runtime-level worker entrypoint, skips secret/redacted events, and rechecks run/step/state failed/rolled_back/cancelled state before extraction; flush paths reuse this safe entrypoint and terminal failed/cancelled status is persisted before buffered flush. `api/deps.py` selects the Redis buffer only when async tasks are enabled and `redis_url` is configured.

**Verification (2026-06-14):** RED tests first failed on missing `app.async_tasks` / missing `app.memory.redis_candidate_buffer`; review-hardening RED tests then reproduced Redis bytes/drain, Celery registration/default idempotency, delayed rollback extraction, stricter payload validation gaps, failed/cancelled buffered extraction, Redis key encoding, and metadata redaction gaps. GREEN after final fixes: `uv run --extra dev pytest apps/api/tests/async_tasks/test_contracts.py apps/api/tests/async_tasks/test_celery_eager.py apps/api/tests/memory/test_candidate_buffer.py apps/api/tests/runtime/test_candidate_buffer_flush.py -q` -> **47 passed**. P4-A related regression: `uv run --extra dev pytest apps/api/tests/async_tasks apps/api/tests/memory/test_candidate_buffer.py apps/api/tests/runtime/test_candidate_buffer_flush.py packages/python-sdk/tests/test_backend_isomorphism.py -q` -> **50 passed**. Compile: `uv run --extra dev python -m compileall -q apps/api/app packages/python-sdk/src examples` -> passed. Full regression: `uv run --extra dev pytest -q` -> **509 passed, 1 skipped**. Deterministic benchmark passed; `bash scripts/reproduce.sh` -> `acceptance.passed=true (13/13 checks true)`.

### P4-A4 Extraction Mode Matrix and Async Enqueue Fallback ✅ complete (2026-06-14)

**Files:**
- Modify: `apps/api/app/runtime/models.py`
- Modify: `apps/api/app/runtime/memory_runtime.py`
- Modify: `apps/api/app/async_tasks/tasks.py`
- Modify: `apps/api/app/async_tasks/runtime_factory.py`
- Test: `apps/api/tests/runtime/test_extraction_modes.py`
- Test: `packages/python-sdk/tests/test_backend_isomorphism.py`

- [x] **Step 1: Extend `ExtractionMode` safely**
  - Code enum members:
    - `sync = "sync"`
    - `buffered = "buffered"` as backward-compatible alias
    - `async_ = "async"`
    - `sync_flush = "sync_flush"`
    - `lazy = "lazy"`
    - `no_extract = "no_extract"`
  - Normalize `buffered` to lazy/deferred behavior internally.
  - Preserve observable compatibility for existing callers: requests using `buffered` still return `WriteEventResult.buffered=True` exactly as before, even if internal handling shares the `lazy` implementation.

- [x] **Step 2: Extend `WriteEventResult`**
  - Add backward-compatible fields:
    - `queued: bool = False`
    - `task_id: str | None = None`
    - `warnings: list[str] = Field(default_factory=list)`
  - Existing clients that read only `event`, `created_memory_ids`, and `buffered` remain compatible.

- [x] **Step 3: Write RED matrix tests**
  - `sync`: current inline extraction.
  - `sync_flush`: raw event persisted; extraction happens synchronously at explicit flush.
  - `lazy`: raw event persisted; event buffered and flushed at retrieve/finish/session flush boundaries.
  - `async_`: raw event persisted; enqueue task and return with `queued=True`, `task_id` set.
  - `no_extract`: raw event persisted; no derived memories and no buffer entry.

- [x] **Step 4: Implement async enqueue fallback**
  - Async extraction task payloads must reference persisted `event_id` plus required context ids (`run_id`, `workspace_id`, `session_id`) instead of embedding full `AgentEvent` content; workers reload events through the repository/runtime boundary.
  - Add a runtime-level extraction entrypoint such as `MemoryRuntime.process_event_extraction(event_id) -> list[str]`. It reloads the persisted post-redaction `AgentEvent`, reuses the same extraction/write-rule/resolver/provider-fallback path as sync/lazy modes, and returns created memory ids.
  - Celery extraction tasks call this runtime-level entrypoint via the worker runtime factory; they must not call private writer/resolver/storage internals directly.
  - If enqueue succeeds: `queued=True`, `buffered=False`, `task_id=<id>`, no inline extraction.
  - If enqueue fails after raw event persistence: add post-redaction event to buffer, return `queued=False`, `buffered=True`, `warnings=["async enqueue failed; fell back to lazy buffer"]`.
  - Fallback warning must not affect default sync benchmark behavior.

- [x] **Step 5: Verify**
  - Command: `uv run --extra dev pytest apps/api/tests/runtime/test_extraction_modes.py packages/python-sdk/tests/test_backend_isomorphism.py -q`
  - Expected: all pass.

**Implementation notes (2026-06-14):** `ExtractionMode` now supports `sync`, backward-compatible `buffered`, code-safe `async_ = "async"`, `sync_flush`, `lazy`, and `no_extract`. `WriteEventResult` now exposes backward-compatible `queued`, `task_id`, and `warnings` fields. `MemoryRuntime.write_event(...)` persists the redacted event first, then applies the selected extraction policy: inline sync, explicit-flush-only `sync_flush`, lazy/window-boundary flush for `lazy`/`buffered`, no derived work for `no_extract`, or event-id-only async enqueue for `async_`. Async enqueue uses `TaskEnvelope(payload={event_id, run_id, workspace_id, session_id})`; success returns `queued=True` with no inline extraction, while enqueue failure appends the post-redaction event to the lazy buffer and returns warning `"async enqueue failed; fell back to lazy buffer"`. Celery workers still call `MemoryRuntime.process_event_extraction(event_id)` through the worker runtime boundary.

**Verification (2026-06-14):** RED matrix tests first failed on missing enum members/result fields, missing mode behavior, and missing `task_enqueue`; GREEN after implementation: `uv run --extra dev pytest apps/api/tests/runtime/test_extraction_modes.py -q` -> **8 passed**. SDK/HTTP shape regression: `uv run --extra dev pytest packages/python-sdk/tests/test_backend_isomorphism.py -q` -> **4 passed**. Final P4-A4/A5 review added coverage for per-request `buffered` under default `sync` and per-request `sync_flush` under default `lazy`; final combined P4-A regression with P4-A5: **67 passed, 1 skipped**.

### P4-A5 Dev Compose and Optional Redis Smoke ✅ complete (2026-06-14)

**Files:**
- Create or modify: `docker-compose.dev.yml`
- Modify after implementation: `README.md`
- Test: `apps/api/tests/integration/test_async_infra.py`

- [x] **Step 1: Add dev compose without changing core compose**
  - Keep existing `docker-compose.yml` focused on PostgreSQL/pgvector.
  - Add Redis and worker services in `docker-compose.dev.yml`.
  - Use `docker-compose`, not `docker compose`, in docs because the project pitfall records standalone compose behavior.

- [x] **Step 2: Add optional Redis smoke**
  - Gate real Redis tests behind `MEMTRACE_TEST_REDIS_URL`.
  - Default full pytest skips the smoke cleanly.

**Implementation notes (2026-06-14):** `docker-compose.dev.yml` adds opt-in Redis and Celery worker services while leaving `docker-compose.yml` PostgreSQL/pgvector-only. README documents the `docker-compose -f docker-compose.yml -f docker-compose.dev.yml ...` startup path and the `MEMTRACE_TEST_REDIS_URL`-gated Redis smoke. `apps/api/tests/integration/test_async_infra.py` verifies the dev compose boundary and skips real Redis smoke by default.

**Verification (2026-06-14):** `uv run --extra dev pytest apps/api/tests/integration/test_async_infra.py -q` -> **1 passed, 1 skipped**. Initial P4-A regression: **60 passed, 1 skipped**. Post-review fixes added coverage for Celery eager execution/error propagation from a running event loop and local fallback buffering/draining when the primary Redis-backed lazy buffer fails after enqueue failure or direct lazy/buffered/sync_flush append failure. Final P4-A4/A5 review additionally fixed request-level lazy/buffered natural-boundary flushing under default `sync`, kept request-level `sync_flush` explicit-only under lazy defaults, deduped primary/local fallback drains by `event_id`, made real Redis append atomic via Lua, and restored Redis buffer indexes/popped values after mid-drain failure; final P4-A regression `uv run --extra dev pytest apps/api/tests/async_tasks apps/api/tests/memory/test_candidate_buffer.py apps/api/tests/runtime/test_candidate_buffer_flush.py apps/api/tests/runtime/test_extraction_modes.py packages/python-sdk/tests/test_backend_isomorphism.py apps/api/tests/integration/test_async_infra.py -q` -> **67 passed, 1 skipped**. Closeout: `uv run --extra dev python -m compileall -q apps/api/app packages/python-sdk/src examples` passed; full `uv run --extra dev pytest -q` -> **526 passed, 2 skipped**; deterministic benchmark passed; `bash scripts/reproduce.sh` -> `acceptance.passed=true (13/13 checks true)`.

---

## 3. Stream P4-B — Lifecycle and Reflection Scheduler

### P4-B1 Lifecycle Transition Policy and Audit ✅ complete (2026-06-14)

**Files:**
- Create: `apps/api/app/memory/lifecycle.py`
- Modify: `apps/api/app/runtime/models.py`
- Modify: `apps/api/app/runtime/repository.py`
- Modify: `apps/api/app/storage/orm.py`
- Modify: `apps/api/app/storage/sql_repository.py`
- Create migration: `migrations/versions/0008_phase4_lifecycle.py`
- Test: `apps/api/tests/memory/test_lifecycle.py`
- Test: `apps/api/tests/storage/test_migrations.py`

- [x] **Step 1: Write RED lifecycle tests**
  - Allowed mainline: `active -> dormant -> archived -> deleted`.
  - Side transitions: `active -> pinned`, `pinned -> previous_status`, `active -> conflicted`, `active -> quarantined`, `active -> superseded`.
  - Automatic scheduler transitions must not archive pinned memory.
  - Quarantined memory may remain observable as a candidate if existing retrieval policy includes it, but the gate safety floor must hard-reject it; it must never reach `accepted_memories` or prompt blocks.

- [x] **Step 2: Implement lifecycle policy**
  - `transition_memory_status(memory, to_status, reason, actor, scheduler_run_id=None)` validates the transition.
  - When transitioning to `pinned`, audit metadata records `previous_status`.
  - Manual unpin restores `previous_status` if it is safe (`active`, `dormant`, or `archived`); otherwise it returns to `active`.
  - Runtime, scheduler, and future admin lifecycle transitions must go through `transition_memory_status(...)` and write `MemoryLifecycleAuditRecord`. Existing resolver conflict/supersede mutations may remain in the resolver path during this stream, but new scheduler/manual transitions must not silently mutate `MemoryItem.status` via bare `repo.update_memory(...)`.

- [x] **Step 3: Add audit record and repository methods**
  - `MemoryLifecycleAuditRecord`: `audit_id`, `workspace_id`, `memory_id`, `from_status`, `to_status`, `reason`, `actor`, `scheduler_run_id`, `metadata`, `created_at`.
  - Methods: `add_lifecycle_audit`, `list_lifecycle_audits`.

- [x] **Step 4: Add migration and verify**
  - Add lifecycle audit table with indexes on `(workspace_id, memory_id, created_at)`.
  - Command: `uv run --extra dev pytest apps/api/tests/memory/test_lifecycle.py apps/api/tests/storage/test_migrations.py -q`
  - Expected: all pass.

### P4-B2 Retention Signal Storage and Access Timestamp ✅ complete (2026-06-14)

**Files:**
- Create: `apps/api/app/memory/retention.py`
- Modify: `apps/api/app/runtime/models.py`
- Modify: `apps/api/app/runtime/repository.py`
- Modify: `apps/api/app/storage/orm.py`
- Modify: `apps/api/app/storage/sql_repository.py`
- Modify: `apps/api/app/retrieval/controller.py`
- Create migration: `migrations/versions/0009_memory_retention_signals.py`
- Test: `apps/api/tests/memory/test_retention_scheduler.py`
- Test: `apps/api/tests/retrieval/test_retrieval_flow.py`

- [x] **Step 1: Write RED scoring/storage tests**
  - Assert scoring uses `value_score`, `freshness_score`, `trust_score`, `risk_score`, `access_count`, `last_accessed_at`, and `expires_at` deterministically.
  - Assert accepted-memory retrieval updates both `access_count` and `last_accessed_at`.
  - Assert retention signals persist independently from `MemoryItem` content/status.

- [x] **Step 2: Add retention signal model/table**
  - `MemoryRetentionSignal`: `memory_id`, `workspace_id`, `retention_score`, `reflection_priority`, `reason`, `policy_version`, `scored_at`, `updated_at`.
  - Add repository methods: `upsert_retention_signal`, `get_retention_signal`, `list_retention_signals(workspace_id, memory_ids: list[str] | None = None)`.
  - Use a separate table rather than adding scheduler-output fields to `memory_items`.

- [x] **Step 3: Implement deterministic scoring**
  - `compute_retention_signals(memory, now, policy)` returns scores and reason metadata.
  - Clamp all score components to `[0, 1]`.
  - Expired/high-risk memory receives low retention and is not made retrievable by scoring.

- [x] **Step 4: Update access timestamp**
  - In `_bump_access_counts(...)`, set `last_accessed_at=now` before `repo.update_memory(mem)`.
  - Do not create memory versions for this access-only update in P4-C.

- [x] **Step 5: Verify**
  - Command: `uv run --extra dev pytest apps/api/tests/memory/test_retention_scheduler.py apps/api/tests/retrieval/test_retrieval_flow.py -q`
  - Expected: all pass.

### P4-B3 Scheduler and Variant 3 Signal Source ✅ complete (2026-06-14)

**Files:**
- Create: `apps/api/app/memory/scheduler.py`
- Modify: `apps/api/app/async_tasks/tasks.py`
- Modify: `apps/api/app/retrieval/controller.py`
- Modify: `apps/api/app/retrieval/policy.py`
- Test: `apps/api/tests/memory/test_retention_scheduler.py`
- Test: `apps/api/tests/conformance/`

- [x] **Step 1: Write RED scheduler tests**
  - Direct function tests for `score_memory(workspace_id)`, `decay_memory(workspace_id)`, `archive_memory(workspace_id)`, `quarantine_memory(workspace_id)`, and `profile_refresh(workspace_id)`.
  - Assert scheduler functions are deterministic and do not require Celery to run in tests.
  - Assert Celery wrappers use workspace/task/window idempotency keys.

- [x] **Step 2: Implement scheduler functions**
  - Keep pure business functions callable directly.
  - Celery task wrappers only deserialize envelope, acquire idempotency, call function, and return `TaskResult`.

- [x] **Step 3: Replace reflection-lite source when signal exists**
  - `variant_3` uses persisted `MemoryRetentionSignal.reflection_priority` when present.
  - Retrieval loads retention signals in bulk for the candidate memory ids; do not perform per-candidate N+1 `get_retention_signal(...)` calls.
  - If absent, it falls back to current deterministic reflection-lite scoring and marks policy snapshot `reflection_signal_source="fallback_lite"`.
  - If persisted signal is used, mark `reflection_signal_source="scheduler_v1"` and include `retention_policy_version` in policy snapshot.
  - Changing `reflection_signal_source` or `retention_policy_version` must change the retrieval policy hash because it changes `variant_3` ranking semantics.

- [x] **Step 4: Verify lifecycle retrieval invariant**
  - Add conformance coverage: dormant/archived/deleted never enter candidates; pinned remains eligible; quarantined remains rejected by safety floor.
  - Command: `uv run --extra dev pytest apps/api/tests/conformance apps/api/tests/memory/test_retention_scheduler.py -q`
  - Expected: all pass.

### P4-B4 Benchmark and Replay Closeout ✅ complete (2026-06-14)

**Files:**
- Modify: `apps/api/app/benchmark/runner.py`
- Modify: `apps/api/tests/benchmark/test_runner.py`
- Modify: `docs/design/ROADMAP.md`, `.ai/*`

- [x] **Step 1: Update case 12 tests**
  - Case 12 should pass through scheduler-derived signal when scheduler is enabled.
  - The deterministic fallback remains stable for default benchmark/reproduce.

- [x] **Step 2: Run closeout**
  - Command: `uv run --extra dev pytest apps/api/tests/benchmark/test_runner.py apps/api/tests/retrieval/test_retrieval_flow.py apps/api/tests/observability/test_replay.py -q`
  - Command: `uv run python -m app.benchmark.runner --output-dir reports`
  - Expected: all pass; benchmark acceptance remains deterministic.

**Implementation notes (2026-06-14):** P4-B1 through P4-B4 are implemented and re-reviewed. `app.memory.lifecycle.transition_memory_status(...)` validates mainline and side lifecycle transitions, records pin `previous_status`, restores safe unpin targets, and prevents scheduler archive of pinned memories. `MemoryLifecycleAuditRecord` and `memory_lifecycle_audits` persist audit rows; `MemoryItem.lifecycle_metadata` stores lifecycle metadata such as pinned previous status. Repository lifecycle writes reject stale `audit.from_status` before updating memory or writing audit, so scheduler stale reads cannot overwrite concurrently pinned memories. `app.memory.retention.compute_retention_signals(...)` writes deterministic `MemoryRetentionSignal` rows in `memory_retention_signals`, deriving `retention_score` and `reflection_priority` from value/freshness/trust/risk/access/recency/expiry while treating non-finite inputs as safe low scores. Retrieval now updates `last_accessed_at` together with `access_count`. `app.memory.scheduler` adds direct async `score_memory`, `decay_memory`, `archive_memory`, `quarantine_memory`, and `profile_refresh`; `maintenance.memory` Celery wrapper calls these functions with idempotency. `variant_3` bulk-loads retention signals and uses persisted `reflection_priority` when present, otherwise falls back to deterministic reflection-lite; policy snapshots include `reflection_signal_source`, `retention_policy_version`, and scheduler/fallback memory-id coverage so hash changes track mixed ranking semantics. Replay policy drift compares against the current side-effect-free trace policy snapshot. Conformance explicitly covers pinned eligibility and quarantined hard rejection.

**Verification (2026-06-14):** RED tests first failed on missing `app.memory.lifecycle`, `app.memory.retention`, missing `process_memory_maintenance`, absent `last_accessed_at` updates, and `variant_3` not using persisted signals. GREEN: memory lifecycle/retention/storage tests **26 passed, 1 skipped**; retrieval focused tests **2 passed**; async maintenance focused tests **2 passed**; benchmark/replay tests **49 passed**; conformance **15 passed**; migration tests **15 passed, 1 skipped**. Post-review fixes added atomic access bumps, atomic lifecycle transition+audit writes, task failure dedupe-key release, and replay policy drift reconstruction with scheduler signal source awareness. Final detailed P4-B review fixed stale lifecycle-transition races, non-finite score clamping, mixed scheduler/fallback policy snapshot hashing, and replay drift source-of-truth. Targeted fix suite -> **16 passed**. Final P4-B affected suite `uv run --extra dev pytest apps/api/tests/async_tasks/test_celery_eager.py apps/api/tests/memory/test_lifecycle.py apps/api/tests/memory/test_retention_scheduler.py apps/api/tests/conformance apps/api/tests/benchmark/test_runner.py apps/api/tests/retrieval/test_retrieval_flow.py apps/api/tests/observability/test_replay.py apps/api/tests/storage/test_migrations.py -q` -> **144 passed, 1 skipped**; compileall passed; full `uv run --extra dev pytest -q` -> **546 passed, 2 skipped**; deterministic benchmark passed; `bash scripts/reproduce.sh` -> `acceptance.passed=true (13/13 checks true)`.

---

## 4. Stream P4-C — Memory Versions and Conflicts

### P4-C1 Redacted Memory Versioning ✅ complete (2026-06-14)

**Files:**
- Create: `apps/api/app/memory/versioning.py`
- Modify: `apps/api/app/runtime/models.py`
- Modify: `apps/api/app/runtime/repository.py`
- Modify: `apps/api/app/storage/orm.py`
- Modify: `apps/api/app/storage/sql_repository.py`
- Create migration: `migrations/versions/0010_memory_versions_conflicts.py`
- Test: `apps/api/tests/memory/test_versioning.py`

- [x] **Step 1: Write RED version tests**
  - Status/content/scope/value changes create versions.
  - `access_count` and `last_accessed_at` updates do not create versions.
  - Snapshot recursively redacts content, summary, key, value, metadata, and nested risk fields; non-secret key/value pairs remain inspectable after `redact(...)` rather than being removed wholesale.

- [x] **Step 2: Implement redacted snapshot helper**
  - `redacted_memory_snapshot(memory: MemoryItem) -> dict[str, Any]` must be the only helper used to build version snapshots.
  - Do not call `memory.model_dump()` directly in version-writing code.
  - Add `should_create_memory_version(before: MemoryItem, after: MemoryItem) -> bool`: return true for content/summary/key/value/scope/status/risk/sensitivity changes, and false when only `access_count`, `last_accessed_at`, or `updated_at` changed.

- [x] **Step 3: Add version records**
  - `MemoryVersionRecord`: `version_id`, `memory_id`, `workspace_id`, `version_no`, `snapshot`, `change_reason`, `created_at`.
  - Repository methods: `add_memory_version`, `list_memory_versions`.

- [x] **Step 4: Verify**
  - Command: `uv run --extra dev pytest apps/api/tests/memory/test_versioning.py apps/api/tests/storage/test_migrations.py -q`
  - Expected: all pass.

### P4-C2 Conflict Scan and Read APIs ✅ complete (2026-06-14)

**Files:**
- Create: `apps/api/app/memory/conflicts.py`
- Modify: `apps/api/app/api/routes.py`
- Modify: `apps/api/app/observability/metrics.py`
- Modify: `apps/api/app/observability/reports.py`
- Modify: dashboard table models/routes as needed
- Test: `apps/api/tests/memory/test_conflicts.py`
- Test: `apps/api/tests/api/test_dashboard.py`

- [x] **Step 1: Write RED conflict tests**
  - Same canonical key + same scope + different value for single-valued ontology keys creates a conflict.
  - Historical alias keys are treated as the same identity.
  - Tool-result evidence can explain but not auto-overwrite higher-trust project constraints.

- [x] **Step 2: Implement conflict scan using ontology helpers**
  - Use `same_memory_key_identity(...)` and `is_single_valued_key(...)` from `app.memory.key_ontology`.
  - Do not reimplement key alias or cardinality semantics in `conflicts.py`.

- [x] **Step 3: Add conflict records and read APIs**
  - `MemoryConflictRecord`: `conflict_id`, `workspace_id`, `subject_key`, `memory_ids`, `status`, `detected_by`, `explanation`, `created_at`, `resolved_at`.
  - Add workspace-scoped read APIs: `GET /v1/memory-conflicts?workspace_id=...` and `GET /v1/memories/{memory_id}/versions`.
  - APIs are read-only in this stream; manual conflict resolution belongs to a later admin workflow.

- [x] **Step 4: Verify**
  - Command: `uv run --extra dev pytest apps/api/tests/memory/test_conflicts.py apps/api/tests/api/test_dashboard.py -q`
  - Expected: all pass.

**Implementation notes (2026-06-14):** P4-C is implemented. `app.memory.versioning.redacted_memory_snapshot(...)` is the single version snapshot helper and recursively redacts content, summary, key, value, lifecycle metadata, and nested risk-like fields while preserving safe values; snapshots omit embedding vectors. `should_create_memory_version(...)` records semantic mutations for content/summary/key/value/scope/status/risk/sensitivity/lifecycle fields but ignores access-only `access_count`, `last_accessed_at`, and `updated_at` bumps. `MemoryVersionRecord` / `memory_versions` persist version history; `Repository.update_memory(...)` and `transition_memory_with_audit(...)` create redacted versions for semantic updates and lifecycle status transitions, while `bump_memory_access(...)` remains version-free. `app.memory.conflicts.detect_memory_conflicts(...)` uses key ontology helpers (`canonical_memory_key`, `same_memory_key_identity`, `is_single_valued_key`) for same key/scope single-valued conflicts, including historical aliases. `MemoryConflictRecord` / `memory_conflicts` store deterministic read-only conflict records; runtime write paths opportunistically scan/persist conflicts, dashboard tables include `memory_versions` and `memory_conflicts`, and HTTP read APIs expose `GET /v1/memories/{memory_id}/versions` plus `GET /v1/memory-conflicts`.

**Verification (2026-06-14):** RED tests first failed on missing `app.memory.versioning` / `app.memory.conflicts` and missing lifecycle version writes. GREEN P4-C matrix `uv run --extra dev pytest apps/api/tests/memory/test_versioning.py apps/api/tests/memory/test_conflicts.py apps/api/tests/api/test_dashboard.py apps/api/tests/storage/test_migrations.py -q` -> **28 passed, 1 skipped**. Detailed review found and fixed four Important issues: expanded credential-like metadata-key redaction, stale open conflict auto-resolution, dashboard workspace filtering for profile events, and preserving existing resolver recency semantics while keeping P4-C conflict scan read-only. Final adjacent affected suite `uv run --extra dev pytest apps/api/tests/memory/test_versioning.py apps/api/tests/memory/test_conflicts.py apps/api/tests/api/test_dashboard.py apps/api/tests/storage/test_migrations.py apps/api/tests/memory/test_lifecycle.py apps/api/tests/memory/test_retention_scheduler.py apps/api/tests/retrieval/test_retrieval_flow.py apps/api/tests/observability/test_replay.py -q` -> **109 passed, 1 skipped**. Compileall passed. Full `uv run --extra dev pytest -q` -> **559 passed, 2 skipped**. Deterministic benchmark passed; `bash scripts/reproduce.sh` -> `acceptance.passed=true (13/13 checks true)`.

---

## 5. Stream P4-D — Multi-Tenant Governance

### P4-D1 Identity, API Keys, and Resource Authorization

**Files:**
- Create: `apps/api/app/governance/__init__.py`
- Create: `apps/api/app/governance/auth.py`
- Create: `apps/api/app/governance/permissions.py`
- Modify: `apps/api/app/api/deps.py`
- Modify: `apps/api/app/api/routes.py`
- Modify: `apps/api/app/runtime/models.py`
- Modify: `apps/api/app/runtime/repository.py`
- Modify: `apps/api/app/storage/orm.py`
- Modify: `apps/api/app/storage/sql_repository.py`
- Create migration: `migrations/versions/0011_governance.py`
- Test: `apps/api/tests/governance/test_auth.py`
- Test: `apps/api/tests/api/test_auth.py`

- [x] **Step 1: Write RED auth tests**
  - With `MEMTRACE_AUTH_ENABLED=false`, existing local behavior remains no-auth.
  - With auth enabled and governance tables empty, legacy `MEMTRACE_API_KEY` remains accepted as admin/demo token; once DB API keys exist, legacy fallback is disabled unless an explicit `allow_legacy_api_key` setting is enabled.
  - API keys are stored as prefix + digest, never raw.
  - Revoked keys fail closed.

- [x] **Step 2: Add API key model**
  - Fields: `api_key_id`, `workspace_id`, `principal_id`, `key_prefix`, `key_digest`, `roles`, `created_at`, `last_used_at`, `revoked_at`.
  - Use prefix lookup plus constant-time digest comparison.
  - Do not log raw token values.

- [x] **Step 3: Add principal and permission DTOs**
  - `Principal`: `principal_id`, `kind`, `workspace_ids`, `roles`, `api_key_id`.
  - `WorkspacePermission`: `owner`, `writer`, `reader`, `report_reader`.
  - Treat roles as workspace-scoped unless explicitly marked global. The first implementation may keep API keys bound to one `workspace_id + roles` tuple rather than adding a full membership table.

- [x] **Step 4: Authorize explicit workspace routes**
  - Enforce body/query/path `workspace_id` for create/list/report endpoints.
  - Reject body workspace mismatches with 403.

- [x] **Step 5: Authorize resource-id routes**
  - Resolve workspace ownership from `run_id`, `step_id`, `access_id`, `memory_id`, and `eval_run_id` before returning data.
  - Add repository/runtime helpers such as `workspace_for_run`, `workspace_for_step`, `workspace_for_access`, `workspace_for_memory`, and `workspace_for_eval_run` (or one typed equivalent) and use them consistently in route dependencies.
  - Cover routes such as `/v1/access/{access_id}`, `/v1/replay/access/{access_id}`, `/v1/replay/runs/{run_id}`, `/v1/runs/{run_id}/timeline`, `/v1/runs/{run_id}/state-tree`, `/v1/runs/{run_id}/profile`, `/v1/runs/{run_id}/steps`, `/v1/steps/{step_id}`, and `/v1/memories/{memory_id}/versions`.
  - Resource not found remains 404; resource exists but unauthorized returns 403.

- [x] **Step 6: Verify**
  - Command: `uv run --extra dev pytest apps/api/tests/governance/test_auth.py apps/api/tests/api/test_auth.py -q`
  - Expected: all pass.

### P4-D2 Quota and Rate Limit

**Files:**
- Create: `apps/api/app/governance/quota.py`
- Modify: `apps/api/app/api/deps.py`
- Modify: `apps/api/app/api/routes.py`
- Test: `apps/api/tests/governance/test_quota.py`

- [x] **Step 1: Write RED quota tests**
  - Quota units: `write_event`, `retrieve_context`, `report_export`, `replay`, `async_task_enqueue`.
  - Fake Redis counter blocks over-limit requests with 429.
  - Redis failure fails closed only when governance is enabled.
  - With governance disabled, Redis quota failure emits warning/degrades without affecting deterministic benchmark defaults.

- [x] **Step 2: Implement quota service**
  - Fixed-window counters keyed by workspace/principal/unit.
  - Settings define default per-unit limits.
  - Optional DB records can override limits per workspace/principal.

- [x] **Step 3: Verify**
  - Command: `uv run --extra dev pytest apps/api/tests/governance/test_quota.py -q`
  - Expected: all pass without real Redis.

### P4-D3 Redaction State Machine and Raw Payload Guard

**Files:**
- Create: `apps/api/app/governance/redaction_policy.py`
- Modify: `apps/api/app/memory/secrets.py`
- Modify: `apps/api/app/runtime/memory_runtime.py`
- Modify: `apps/api/app/observability/trace_bundle.py`
- Test: `apps/api/tests/governance/test_redaction_policy.py`
- Test: `apps/api/tests/observability/test_trace_bundle.py`

- [x] **Step 1: Write RED redaction-state tests**
  - Supported states: `none`, `redacted`, `digest_only`, `blocked`.
  - Current behavior maps to `redacted` or `digest_only`.
  - Requests for raw secret retention fail with 400 when encrypted raw store is not configured.
  - Trace bundle export remains redacted even if raw refs are present.

- [x] **Step 2: Implement policy module**
  - `decide_redaction_state(content, settings, principal) -> RedactionDecision`.
  - `raw_payload_ref` is disabled by default and requires governance-enabled configuration.
  - Blocked content is not stored in event/memory content.

- [x] **Step 3: Verify**
  - Command: `uv run --extra dev pytest apps/api/tests/governance/test_redaction_policy.py apps/api/tests/observability/test_trace_bundle.py -q`
  - Expected: all pass; secrets never appear in event content, memory content, trace bundles, reports, or Redis payloads.

### P4-D4 Governance Closeout

**Files:**
- Modify: `docs/design/ROADMAP.md`
- Modify: `.ai/PROJECT_STATE.md`, `.ai/REQUIREMENTS.md`, `.ai/IMPLEMENTATION_PLAN.md`, `.ai/OPEN_QUESTIONS.md`, `.ai/PITFALLS.md`

- [x] **Step 1: Run governance and API/SDK suites**
  - Command: `uv run --extra dev pytest apps/api/tests/governance apps/api/tests/api packages/python-sdk/tests/test_http_backend.py packages/python-sdk/tests/test_cli.py -q`
  - Expected: all pass.

- [x] **Step 2: Run full verification**
  - Command: `uv run --extra dev pytest -q`
  - Command: `uv run --extra dev python -m compileall -q apps/api/app packages/python-sdk/src examples`
  - Command: `uv run python -m app.benchmark.runner --output-dir reports`
  - Command: `bash scripts/reproduce.sh`
  - Expected: full regression passes; benchmark/reproduce remain no-auth deterministic by default.

- [x] **Step 3: Sync docs and memory**
  - Update ROADMAP Phase 4 status and `.ai` current state.
  - Add pitfalls covering resource-id authorization, prefix+digest API key lookup, Redis quota fail-closed behavior, and pinned previous-status restoration.

**Verification (2026-06-14):** governance/API/SDK closeout suite initially passed at **43 passed** and full regression at **583 passed, 2 skipped**. Final detailed P4-D review then hardened workspace-scoped session flush, run/workspace mismatch handling, quota route coverage, raw-payload guard, metadata/report/replay redaction, SDK `ForbiddenError` mapping, API-key prefix uniqueness parity, and governance migration assertions. A subsequent full Phase 4 review hardened event extraction idempotency, workspace mismatch side-effect ordering, stale lifecycle update preservation, secret digest handling, replay retained-negative redaction, dashboard version parity, and SDK versions/conflicts API coverage. Final verification: review regressions **10 passed**; affected Phase 4 suite **237 passed, 2 skipped**; compileall `uv run --extra dev python -m compileall -q apps/api/app packages/python-sdk/src examples` passed; full regression `uv run --extra dev pytest -q` -> **604 passed, 2 skipped**; deterministic benchmark passed; `bash scripts/reproduce.sh` printed `acceptance.passed=true (13/13 checks true)`. Default local/dev/benchmark behavior remains no-auth/no-quota unless explicitly enabled.

---

## 6. Cross-Stream Verification Matrix

- After P4-A: `uv run --extra dev pytest apps/api/tests/async_tasks apps/api/tests/memory/test_candidate_buffer.py apps/api/tests/runtime/test_extraction_modes.py packages/python-sdk/tests/test_backend_isomorphism.py -q`.
- After P4-B: `uv run --extra dev pytest apps/api/tests/memory/test_lifecycle.py apps/api/tests/memory/test_retention_scheduler.py apps/api/tests/conformance apps/api/tests/benchmark/test_runner.py -q` plus benchmark run.
- After P4-C: `uv run --extra dev pytest apps/api/tests/memory/test_versioning.py apps/api/tests/memory/test_conflicts.py apps/api/tests/api/test_dashboard.py apps/api/tests/storage/test_migrations.py -q`.
- After P4-D: governance/API/SDK suites plus full regression, compile, benchmark, and reproduce.

## 7. Self-Review Checklist

- [x] Async mode avoids Python reserved-word enum bug by using `async_ = "async"`.
- [x] Candidate buffer is explicitly async and Redis stores post-redaction events only.
- [x] Async enqueue fallback semantics are observable through `WriteEventResult`.
- [x] Pinned/unpin semantics preserve previous status despite `pinned` being a status enum.
- [x] Retention scheduler output uses a separate table and updates `last_accessed_at` with access count.
- [x] Conflict scanning reuses key ontology helpers rather than duplicating alias/cardinality rules. *(P4-C complete 2026-06-14.)*
- [x] Governance authorization covers resource-id routes, not only explicit workspace fields. *(P4-D complete 2026-06-14.)*
