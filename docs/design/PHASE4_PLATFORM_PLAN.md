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
- Do not create memory versions for access-count-only updates.

---

## 2. Stream P4-A — Async Foundation

### P4-A1 Settings, Task Contracts, and Dependencies

**Files:**
- Modify: `pyproject.toml`
- Modify: `apps/api/app/config.py`
- Create: `apps/api/app/async_tasks/__init__.py`
- Create: `apps/api/app/async_tasks/contracts.py`
- Test: `apps/api/tests/async_tasks/test_contracts.py`

- [ ] **Step 1: Write RED contract tests**
  - Assert `TaskEnvelope` JSON contains `task_id`, `task_type`, `workspace_id`, `dedupe_key`, `payload`, and `created_at`.
  - Assert payload validation rejects secret-like keys such as `api_key`, `authorization`, `password`, `secret`, and `token` unless stored under an explicitly redacted field name such as `redacted_event`.
  - Assert settings defaults keep async disabled and eager-safe: `async_tasks_enabled=False`, `celery_task_always_eager=True`.

- [ ] **Step 2: Add dependencies and settings**
  - Add `celery>=5.4` and `redis>=5.0` to root dependencies.
  - Add settings: `redis_url`, `celery_broker_url`, `celery_result_backend`, `async_tasks_enabled`, `celery_task_always_eager`, `memory_queue_name`, `maintenance_queue_name`, `eval_queue_name`, `async_task_default_ttl_seconds`.
  - Defaults must not open network connections during import or pytest collection.

- [ ] **Step 3: Implement contracts**
  - `TaskEnvelope` and `TaskResult` live in `async_tasks/contracts.py`.
  - Use Pydantic models and JSON-compatible payloads only.
  - Validation must reject non-redacted secret-like payload keys and non-finite numeric metadata.

- [ ] **Step 4: Verify**
  - Command: `uv run --extra dev pytest apps/api/tests/async_tasks/test_contracts.py -q`
  - Expected: all pass.

### P4-A2 Celery App and Idempotency

**Files:**
- Create: `apps/api/app/async_tasks/celery_app.py`
- Create: `apps/api/app/async_tasks/idempotency.py`
- Create: `apps/api/app/async_tasks/tasks.py`
- Test: `apps/api/tests/async_tasks/test_celery_eager.py`

- [ ] **Step 1: Write RED tests**
  - `make_celery_app(settings)` registers memory, maintenance, and eval queues.
  - Eager mode executes a task inline without Redis.
  - `InMemoryIdempotencyStore.acquire(key, ttl_seconds)` returns `True` once, then `False` for duplicates until release/expiry.
  - Celery serialization is JSON-only.

- [ ] **Step 2: Implement Celery app factory**
  - Read settings lazily from function arguments, not module import side effects.
  - Disable result persistence unless `celery_result_backend` is configured.
  - Use `task_always_eager=True` by default for deterministic tests.

- [ ] **Step 3: Implement idempotency abstraction**
  - Protocol: `async def acquire(key: str, ttl_seconds: int) -> bool` and `async def release(key: str) -> None`.
  - Provide in-memory implementation for tests.
  - Provide Redis implementation behind settings, covered by optional integration tests only.

- [ ] **Step 4: Verify**
  - Command: `uv run --extra dev pytest apps/api/tests/async_tasks -q`
  - Expected: all async task unit tests pass without Redis.

### P4-A3 Async Candidate Buffer Protocol and Redis Buffer

**Files:**
- Create: `apps/api/app/memory/buffer.py`
- Modify: `apps/api/app/memory/candidate_buffer.py`
- Create: `apps/api/app/memory/redis_candidate_buffer.py`
- Modify: `apps/api/app/runtime/memory_runtime.py`
- Modify: `apps/api/app/api/deps.py`
- Test: `apps/api/tests/memory/test_candidate_buffer.py`

- [ ] **Step 1: Write RED protocol tests**
  - Tests call `await buffer.append(event)`, `await buffer.pending(session_id)`, `await buffer.drain(session_id)`, `await buffer.size(session_id)`, `await buffer.total_size()`, and `await buffer.sessions()`.
  - Assert in-memory buffer keeps FIFO order and drains idempotently.
  - Assert buffered objects are deep copies and cannot be mutated through returned references.

- [ ] **Step 2: Extract async protocol**
  - Define `CandidateBufferProtocol` in `memory/buffer.py` with async methods only.
  - Convert existing `CandidateBuffer` to async methods while keeping its deterministic in-process behavior.
  - Update `MemoryRuntime` to accept `candidate_buffer: CandidateBufferProtocol | None` and default to `CandidateBuffer()`.

- [ ] **Step 3: Add fake Redis RED tests**
  - Use a fake async Redis object in unit tests.
  - Assert Redis keys include only workspace/session ids and never content snippets.
  - Assert Redis values contain only post-redaction `AgentEvent` JSON and never raw `WriteEventRequest` payloads.
  - Seed an event with `content="sk-raw-secret password=hunter2"` after runtime redaction and assert stored Redis value contains `[REDACTED]` but not the raw markers.

- [ ] **Step 4: Implement Redis buffer**
  - Store serialized post-redaction `AgentEvent` JSON under workspace/session-scoped list keys.
  - Use atomic drain semantics in the real Redis implementation; unit tests may simulate the behavior with a fake.
  - Real Redis integration remains gated behind `MEMTRACE_TEST_REDIS_URL`.

- [ ] **Step 5: Wire runtime selection**
  - `api/deps.py` chooses in-memory buffer by default.
  - Redis buffer is selected only when `async_tasks_enabled=True` and `redis_url` is configured.

- [ ] **Step 6: Verify**
  - Command: `uv run --extra dev pytest apps/api/tests/memory/test_candidate_buffer.py packages/python-sdk/tests/test_backend_isomorphism.py -q`
  - Expected: all pass; sync/default behavior remains isomorphic.

### P4-A4 Extraction Mode Matrix and Async Enqueue Fallback

**Files:**
- Modify: `apps/api/app/runtime/models.py`
- Modify: `apps/api/app/runtime/memory_runtime.py`
- Modify: `apps/api/app/async_tasks/tasks.py`
- Test: `apps/api/tests/runtime/test_extraction_modes.py`
- Test: `packages/python-sdk/tests/test_backend_isomorphism.py`

- [ ] **Step 1: Extend `ExtractionMode` safely**
  - Code enum members:
    - `sync = "sync"`
    - `buffered = "buffered"` as backward-compatible alias
    - `async_ = "async"`
    - `sync_flush = "sync_flush"`
    - `lazy = "lazy"`
    - `no_extract = "no_extract"`
  - Normalize `buffered` to lazy/deferred behavior internally.

- [ ] **Step 2: Extend `WriteEventResult`**
  - Add backward-compatible fields:
    - `queued: bool = False`
    - `task_id: str | None = None`
    - `warnings: list[str] = Field(default_factory=list)`
  - Existing clients that read only `event`, `created_memory_ids`, and `buffered` remain compatible.

- [ ] **Step 3: Write RED matrix tests**
  - `sync`: current inline extraction.
  - `sync_flush`: raw event persisted; extraction happens synchronously at explicit flush.
  - `lazy`: raw event persisted; event buffered and flushed at retrieve/finish/session flush boundaries.
  - `async_`: raw event persisted; enqueue task and return with `queued=True`, `task_id` set.
  - `no_extract`: raw event persisted; no derived memories and no buffer entry.

- [ ] **Step 4: Implement async enqueue fallback**
  - If enqueue succeeds: `queued=True`, `buffered=False`, `task_id=<id>`, no inline extraction.
  - If enqueue fails after raw event persistence: add post-redaction event to buffer, return `queued=False`, `buffered=True`, `warnings=["async enqueue failed; fell back to lazy buffer"]`.
  - Fallback warning must not affect default sync benchmark behavior.

- [ ] **Step 5: Verify**
  - Command: `uv run --extra dev pytest apps/api/tests/runtime/test_extraction_modes.py packages/python-sdk/tests/test_backend_isomorphism.py -q`
  - Expected: all pass.

### P4-A5 Dev Compose and Optional Redis Smoke

**Files:**
- Create or modify: `docker-compose.dev.yml`
- Modify after implementation: `README.md`
- Test: `apps/api/tests/integration/test_async_infra.py`

- [ ] **Step 1: Add dev compose without changing core compose**
  - Keep existing `docker-compose.yml` focused on PostgreSQL/pgvector.
  - Add Redis and worker services in `docker-compose.dev.yml`.
  - Use `docker-compose`, not `docker compose`, in docs because the project pitfall records standalone compose behavior.

- [ ] **Step 2: Add optional Redis smoke**
  - Gate real Redis tests behind `MEMTRACE_TEST_REDIS_URL`.
  - Default full pytest skips the smoke cleanly.

---

## 3. Stream P4-B — Lifecycle and Reflection Scheduler

### P4-B1 Lifecycle Transition Policy and Audit

**Files:**
- Create: `apps/api/app/memory/lifecycle.py`
- Modify: `apps/api/app/runtime/models.py`
- Modify: `apps/api/app/runtime/repository.py`
- Modify: `apps/api/app/storage/orm.py`
- Modify: `apps/api/app/storage/sql_repository.py`
- Create migration: `migrations/versions/0008_phase4_lifecycle.py`
- Test: `apps/api/tests/memory/test_lifecycle.py`
- Test: `apps/api/tests/storage/test_migrations.py`

- [ ] **Step 1: Write RED lifecycle tests**
  - Allowed mainline: `active -> dormant -> archived -> deleted`.
  - Side transitions: `active -> pinned`, `pinned -> previous_status`, `active -> conflicted`, `active -> quarantined`, `active -> superseded`.
  - Automatic scheduler transitions must not archive pinned memory.
  - Quarantined memory remains non-injectable even if it appears in candidate lists.

- [ ] **Step 2: Implement lifecycle policy**
  - `transition_memory_status(memory, to_status, reason, actor, scheduler_run_id=None)` validates the transition.
  - When transitioning to `pinned`, audit metadata records `previous_status`.
  - Manual unpin restores `previous_status` if it is safe (`active`, `dormant`, or `archived`); otherwise it returns to `active`.

- [ ] **Step 3: Add audit record and repository methods**
  - `MemoryLifecycleAuditRecord`: `audit_id`, `workspace_id`, `memory_id`, `from_status`, `to_status`, `reason`, `actor`, `scheduler_run_id`, `metadata`, `created_at`.
  - Methods: `add_lifecycle_audit`, `list_lifecycle_audits`.

- [ ] **Step 4: Add migration and verify**
  - Add lifecycle audit table with indexes on `(workspace_id, memory_id, created_at)`.
  - Command: `uv run --extra dev pytest apps/api/tests/memory/test_lifecycle.py apps/api/tests/storage/test_migrations.py -q`
  - Expected: all pass.

### P4-B2 Retention Signal Storage and Access Timestamp

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

- [ ] **Step 1: Write RED scoring/storage tests**
  - Assert scoring uses `value_score`, `freshness_score`, `trust_score`, `risk_score`, `access_count`, `last_accessed_at`, and `expires_at` deterministically.
  - Assert accepted-memory retrieval updates both `access_count` and `last_accessed_at`.
  - Assert retention signals persist independently from `MemoryItem` content/status.

- [ ] **Step 2: Add retention signal model/table**
  - `MemoryRetentionSignal`: `memory_id`, `workspace_id`, `retention_score`, `reflection_priority`, `reason`, `policy_version`, `scored_at`, `updated_at`.
  - Add repository methods: `upsert_retention_signal`, `get_retention_signal`, `list_retention_signals`.
  - Use a separate table rather than adding scheduler-output fields to `memory_items`.

- [ ] **Step 3: Implement deterministic scoring**
  - `compute_retention_signals(memory, now, policy)` returns scores and reason metadata.
  - Clamp all score components to `[0, 1]`.
  - Expired/high-risk memory receives low retention and is not made retrievable by scoring.

- [ ] **Step 4: Update access timestamp**
  - In `_bump_access_counts(...)`, set `last_accessed_at=now` before `repo.update_memory(mem)`.
  - Do not create memory versions for this access-only update in P4-C.

- [ ] **Step 5: Verify**
  - Command: `uv run --extra dev pytest apps/api/tests/memory/test_retention_scheduler.py apps/api/tests/retrieval/test_retrieval_flow.py -q`
  - Expected: all pass.

### P4-B3 Scheduler and Variant 3 Signal Source

**Files:**
- Create: `apps/api/app/memory/scheduler.py`
- Modify: `apps/api/app/async_tasks/tasks.py`
- Modify: `apps/api/app/retrieval/controller.py`
- Modify: `apps/api/app/retrieval/policy.py`
- Test: `apps/api/tests/memory/test_retention_scheduler.py`
- Test: `apps/api/tests/conformance/`

- [ ] **Step 1: Write RED scheduler tests**
  - Direct function tests for `score_memory(workspace_id)`, `decay_memory(workspace_id)`, `archive_memory(workspace_id)`, `quarantine_memory(workspace_id)`, and `profile_refresh(workspace_id)`.
  - Assert scheduler functions are deterministic and do not require Celery to run in tests.
  - Assert Celery wrappers use workspace/task/window idempotency keys.

- [ ] **Step 2: Implement scheduler functions**
  - Keep pure business functions callable directly.
  - Celery task wrappers only deserialize envelope, acquire idempotency, call function, and return `TaskResult`.

- [ ] **Step 3: Replace reflection-lite source when signal exists**
  - `variant_3` uses persisted `MemoryRetentionSignal.reflection_priority` when present.
  - If absent, it falls back to current deterministic reflection-lite scoring and marks policy snapshot `reflection_signal_source="fallback_lite"`.
  - If persisted signal is used, mark `reflection_signal_source="scheduler_v1"` and include `retention_policy_version` in policy snapshot.

- [ ] **Step 4: Verify lifecycle retrieval invariant**
  - Add conformance coverage: dormant/archived/deleted never enter candidates; pinned remains eligible; quarantined remains rejected by safety floor.
  - Command: `uv run --extra dev pytest apps/api/tests/conformance apps/api/tests/memory/test_retention_scheduler.py -q`
  - Expected: all pass.

### P4-B4 Benchmark and Replay Closeout

**Files:**
- Modify: `apps/api/app/benchmark/runner.py`
- Modify: `apps/api/tests/benchmark/test_runner.py`
- Modify: `docs/design/ROADMAP.md`, `.ai/*`

- [ ] **Step 1: Update case 12 tests**
  - Case 12 should pass through scheduler-derived signal when scheduler is enabled.
  - The deterministic fallback remains stable for default benchmark/reproduce.

- [ ] **Step 2: Run closeout**
  - Command: `uv run --extra dev pytest apps/api/tests/benchmark/test_runner.py apps/api/tests/retrieval/test_retrieval_flow.py apps/api/tests/observability/test_replay.py -q`
  - Command: `uv run python -m app.benchmark.runner --output-dir reports`
  - Expected: all pass; benchmark acceptance remains deterministic.

---

## 4. Stream P4-C — Memory Versions and Conflicts

### P4-C1 Redacted Memory Versioning

**Files:**
- Create: `apps/api/app/memory/versioning.py`
- Modify: `apps/api/app/runtime/models.py`
- Modify: `apps/api/app/runtime/repository.py`
- Modify: `apps/api/app/storage/orm.py`
- Modify: `apps/api/app/storage/sql_repository.py`
- Create migration: `migrations/versions/0010_memory_versions_conflicts.py`
- Test: `apps/api/tests/memory/test_versioning.py`

- [ ] **Step 1: Write RED version tests**
  - Status/content/scope/value changes create versions.
  - `access_count` and `last_accessed_at` updates do not create versions.
  - Snapshot redacts content, summary, key, value, metadata, and nested risk fields.

- [ ] **Step 2: Implement redacted snapshot helper**
  - `redacted_memory_snapshot(memory: MemoryItem) -> dict[str, Any]` must be the only helper used to build version snapshots.
  - Do not call `memory.model_dump()` directly in version-writing code.

- [ ] **Step 3: Add version records**
  - `MemoryVersionRecord`: `version_id`, `memory_id`, `workspace_id`, `version_no`, `snapshot`, `change_reason`, `created_at`.
  - Repository methods: `add_memory_version`, `list_memory_versions`.

- [ ] **Step 4: Verify**
  - Command: `uv run --extra dev pytest apps/api/tests/memory/test_versioning.py apps/api/tests/storage/test_migrations.py -q`
  - Expected: all pass.

### P4-C2 Conflict Scan and Read APIs

**Files:**
- Create: `apps/api/app/memory/conflicts.py`
- Modify: `apps/api/app/api/routes.py`
- Modify: `apps/api/app/observability/metrics.py`
- Modify: `apps/api/app/observability/reports.py`
- Modify: dashboard table models/routes as needed
- Test: `apps/api/tests/memory/test_conflicts.py`
- Test: `apps/api/tests/api/test_dashboard.py`

- [ ] **Step 1: Write RED conflict tests**
  - Same canonical key + same scope + different value for single-valued ontology keys creates a conflict.
  - Historical alias keys are treated as the same identity.
  - Tool-result evidence can explain but not auto-overwrite higher-trust project constraints.

- [ ] **Step 2: Implement conflict scan using ontology helpers**
  - Use `same_memory_key_identity(...)` and `is_single_valued_key(...)` from `app.memory.key_ontology`.
  - Do not reimplement key alias or cardinality semantics in `conflicts.py`.

- [ ] **Step 3: Add conflict records and read APIs**
  - `MemoryConflictRecord`: `conflict_id`, `workspace_id`, `subject_key`, `memory_ids`, `status`, `detected_by`, `explanation`, `created_at`, `resolved_at`.
  - Add `GET /v1/memory-conflicts` and `GET /v1/memories/{memory_id}/versions`.
  - APIs are read-only in this stream; manual conflict resolution belongs to a later admin workflow.

- [ ] **Step 4: Verify**
  - Command: `uv run --extra dev pytest apps/api/tests/memory/test_conflicts.py apps/api/tests/api/test_dashboard.py -q`
  - Expected: all pass.

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

- [ ] **Step 1: Write RED auth tests**
  - With `MEMTRACE_AUTH_ENABLED=false`, existing local behavior remains no-auth.
  - With auth enabled and governance tables empty, legacy `MEMTRACE_API_KEY` remains accepted as admin/demo token.
  - API keys are stored as prefix + digest, never raw.
  - Revoked keys fail closed.

- [ ] **Step 2: Add API key model**
  - Fields: `api_key_id`, `workspace_id`, `principal_id`, `key_prefix`, `key_digest`, `roles`, `created_at`, `last_used_at`, `revoked_at`.
  - Use prefix lookup plus constant-time digest comparison.
  - Do not log raw token values.

- [ ] **Step 3: Add principal and permission DTOs**
  - `Principal`: `principal_id`, `kind`, `workspace_ids`, `roles`, `api_key_id`.
  - `WorkspacePermission`: `owner`, `writer`, `reader`, `report_reader`.

- [ ] **Step 4: Authorize explicit workspace routes**
  - Enforce body/query/path `workspace_id` for create/list/report endpoints.
  - Reject body workspace mismatches with 403.

- [ ] **Step 5: Authorize resource-id routes**
  - Resolve workspace ownership from `run_id`, `step_id`, `access_id`, `memory_id`, and `eval_run_id` before returning data.
  - Cover routes such as `/v1/access/{access_id}`, `/v1/replay/access/{access_id}`, `/v1/replay/runs/{run_id}`, `/v1/runs/{run_id}/timeline`, `/v1/runs/{run_id}/state-tree`, `/v1/runs/{run_id}/profile`, `/v1/runs/{run_id}/steps`, `/v1/steps/{step_id}`, and `/v1/memories/{memory_id}/versions`.
  - Resource not found remains 404; resource exists but unauthorized returns 403.

- [ ] **Step 6: Verify**
  - Command: `uv run --extra dev pytest apps/api/tests/governance/test_auth.py apps/api/tests/api/test_auth.py -q`
  - Expected: all pass.

### P4-D2 Quota and Rate Limit

**Files:**
- Create: `apps/api/app/governance/quota.py`
- Modify: `apps/api/app/api/deps.py`
- Modify: `apps/api/app/api/routes.py`
- Test: `apps/api/tests/governance/test_quota.py`

- [ ] **Step 1: Write RED quota tests**
  - Quota units: `write_event`, `retrieve_context`, `report_export`, `replay`, `async_task_enqueue`.
  - Fake Redis counter blocks over-limit requests with 429.
  - Redis failure fails closed only when governance is enabled.
  - With governance disabled, Redis quota failure emits warning/degrades without affecting deterministic benchmark defaults.

- [ ] **Step 2: Implement quota service**
  - Fixed-window counters keyed by workspace/principal/unit.
  - Settings define default per-unit limits.
  - Optional DB records can override limits per workspace/principal.

- [ ] **Step 3: Verify**
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

- [ ] **Step 1: Write RED redaction-state tests**
  - Supported states: `none`, `redacted`, `digest_only`, `blocked`.
  - Current behavior maps to `redacted` or `digest_only`.
  - Requests for raw secret retention fail with 400 when encrypted raw store is not configured.
  - Trace bundle export remains redacted even if raw refs are present.

- [ ] **Step 2: Implement policy module**
  - `decide_redaction_state(content, settings, principal) -> RedactionDecision`.
  - `raw_payload_ref` is disabled by default and requires governance-enabled configuration.
  - Blocked content is not stored in event/memory content.

- [ ] **Step 3: Verify**
  - Command: `uv run --extra dev pytest apps/api/tests/governance/test_redaction_policy.py apps/api/tests/observability/test_trace_bundle.py -q`
  - Expected: all pass; secrets never appear in event content, memory content, trace bundles, reports, or Redis payloads.

### P4-D4 Governance Closeout

**Files:**
- Modify: `docs/design/ROADMAP.md`
- Modify: `.ai/PROJECT_STATE.md`, `.ai/REQUIREMENTS.md`, `.ai/IMPLEMENTATION_PLAN.md`, `.ai/OPEN_QUESTIONS.md`, `.ai/PITFALLS.md`

- [ ] **Step 1: Run governance and API/SDK suites**
  - Command: `uv run --extra dev pytest apps/api/tests/governance apps/api/tests/api packages/python-sdk/tests/test_http_backend.py packages/python-sdk/tests/test_cli.py -q`
  - Expected: all pass.

- [ ] **Step 2: Run full verification**
  - Command: `uv run --extra dev pytest -q`
  - Command: `uv run --extra dev python -m compileall -q apps/api/app packages/python-sdk/src examples`
  - Command: `uv run python -m app.benchmark.runner --output-dir reports`
  - Command: `bash scripts/reproduce.sh`
  - Expected: full regression passes; benchmark/reproduce remain no-auth deterministic by default.

- [ ] **Step 3: Sync docs and memory**
  - Update ROADMAP Phase 4 status and `.ai` current state.
  - Add pitfalls covering resource-id authorization, prefix+digest API key lookup, Redis quota fail-closed behavior, and pinned previous-status restoration.

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
- [x] Conflict scanning reuses key ontology helpers rather than duplicating alias/cardinality rules.
- [x] Governance authorization covers resource-id routes, not only explicit workspace fields.
