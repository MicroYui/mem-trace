# Phase 4 Async/Lifecycle/Governance + I7 + TS/MCP/IDE Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` (recommended) or `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Status (2026-06-14): completed / superseded umbrella plan.** The streams originally sketched here have been delivered through their dedicated, source-refreshed plans: I7 compaction-negative retained metadata is complete via `docs/design/I7_COMPACTION_NEGATIVE_RETENTION_PLAN.md`; Phase 4 P4-A/P4-B/P4-C/P4-D is complete via `docs/design/PHASE4_PLATFORM_PLAN.md`; integrations INT-A TypeScript SDK, INT-B MCP Server, and INT-C MCP config templates / IDE thin-layer decision are complete via `docs/design/INTEGRATIONS_PLAN.md`. The unchecked checklist items below are historical planning detail unless explicitly marked complete/superseded; do not use this umbrella file as the current next-action source. Current remaining roadmap candidates are OpenTelemetry/OpenInference exporter, advanced UI/dashboard, admin/manual governance depth, or advanced retrieval/storage work; dedicated IDE package remains deferred until MCP adoption feedback.

**Goal:** Move MemTrace from a deterministic single-process/runtime prototype into a production-oriented agent memory platform with async cold-path infrastructure, durable memory lifecycle/governance, retained negative lessons through compaction, and external ecosystem entrypoints.

**Architecture:** This is intentionally a portfolio plan split into independently testable streams. The implementation order is: shared contracts and migration discipline first; I7 negative-retention safety next because it is small and protects current behavior; Phase 4 async infrastructure before lifecycle/governance because Redis/Celery are required for distributed buffering, retries, quota, and scheduler locks; TypeScript/MCP/IDE integrations last because they should consume the stable HTTP/SDK contract rather than create alternate runtime paths.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async, Alembic, PostgreSQL/pgvector, Redis, Celery, Pydantic v2, pytest/pytest-asyncio, uv workspace, TypeScript package under `packages/ts-sdk`, MCP server under `packages/mcp-server`, deterministic tests by default with optional Redis/PostgreSQL integration gates.

---

## 0. Scope Check and Decomposition

The requested next direction covers three large, partially independent subsystems:

1. **Phase 4 core platform:** async infrastructure, lifecycle/reflection scheduler, memory versions/conflicts, and multi-tenant governance.
2. **Deferred I7:** preserve failure-aware negative lessons through context compaction and replay.
3. **External integrations:** TypeScript SDK, MCP server, and IDE adoption surfaces.

To keep delivery reviewable, this plan treats them as one umbrella roadmap with three execution streams. Each issue below must land as a self-contained PR/commit-sized slice with targeted RED/GREEN tests, affected regression, docs/project-memory sync, and no hidden behavior changes outside its stream.

### Recommended execution order

| Order | Stream | Why now |
|---|---|---|
| 1 | **I7 compaction-negative retention** | Smallest correctness gap; protects existing failure-learning behavior before larger lifecycle/scheduler changes mutate memory state. |
| 2 | **P4-A async foundation** | Redis/Celery abstractions, queue configuration, idempotency, and worker lifecycle are dependencies for distributed buffer, retries, quota, and scheduled maintenance. |
| 3 | **P4-B lifecycle/reflection scheduler** | Replaces `variant_3` reflection-lite with durable retention/reflection signals and auditable lifecycle transitions. |
| 4 | **P4-C versions/conflicts** | Builds on lifecycle/audit data; prepares admin/governance without a full UI. |
| 5 | **P4-D multi-tenant governance** | Uses Redis for rate/quota and DB-backed API keys/workspace permissions; extends H3 default-off auth rather than replacing it. |
| 6 | **INT-A TypeScript SDK** | Mirrors stable HTTP contract after governance shape is known. |
| 7 | **INT-B MCP server** | Built on TS/Python SDK contract; exposes runtime operations without bypassing `MemoryRuntime`. |
| 8 | **INT-C IDE integrations** | Thin wrappers around MCP/TS SDK; no new memory semantics. |

### Non-goals for this plan

- No Elasticsearch/OpenSearch, Neo4j, graph retrieval, or LoCoMo/MemoryArena full benchmark.
- No React dashboard/admin UI beyond API/table/report surfaces. Conflict admin workflow is represented by API/table rows only.
- No training-based gate model.
- No production raw-payload import/export. Trace bundle remains redacted export + validation only unless a later governance design explicitly adds write-import.
- No provider-specific real LLM judge behavior; keep `JudgeProvider` contract-only unless a later plan selects it.

---

## 1. Current Code Anchors and Constraints

### Existing source boundaries

- Runtime facade: `apps/api/app/runtime/memory_runtime.py` owns hot-path orchestration and must remain the semantic boundary for SDK/HTTP/MCP.
- Repository protocol: `apps/api/app/runtime/repository.py` is the storage boundary; add methods here before SQL/in-memory implementations.
- Domain models: `apps/api/app/runtime/models.py` already contains `MemoryStatus`, `MemoryItem.value_score/freshness_score/trust_score/risk_score`, `expires_at`, `last_accessed_at`, `access_count`, `ContextCompactionLog`, and governance-ready `workspace_id` fields.
- SQL schema: `apps/api/app/storage/orm.py` already has `workspaces`, `sessions`, `memory_items`, `memory_access_logs`, `context_compaction_logs`, and eval tables.
- Retrieval lifecycle filtering: `_RETRIEVABLE_STATUSES` in `apps/api/app/retrieval/controller.py` is currently the single candidate-stage lifecycle allowlist. Every new retrieval/search/export path must preserve it or deliberately route through the same helper.
- Negative evidence: `apps/api/app/retrieval/negative_evidence.py`, `apps/api/app/retrieval/packer.py`, `apps/api/app/observability/replay.py`, and `apps/api/app/observability/metrics.py` are the single-source path for safe failed-lesson rendering.
- Auth: `apps/api/app/api/deps.py` currently implements default-off single API-key auth for `/v1`. Phase 4 must extend this into identity/workspace permissions without breaking local/dev/benchmark default-off behavior.
- Package manager: Python uses `uv`; no JS workspace exists yet. TS/MCP work should introduce Bun-based JS tooling, not npm/pnpm/yarn commands.

### Durable invariants to preserve

- Positive prompt blocks must be packer-redacted defense-in-depth.
- Failed/rolled-back memories must never enter positive accepted context. Safe lessons only enter `avoided_attempts`/negative evidence; unsafe lessons render sanitized notices.
- Benchmark and `scripts/reproduce.sh` must remain deterministic even when Redis/Celery/real providers are configured.
- Retrieval policy snapshots must hash stable, non-secret config. Any behavior-affecting retrieval/lifecycle/retention setting change should update policy snapshot shape/version.
- Replay must distinguish data drift from policy/config/code drift; old rows without new fields should degrade to warnings, not crashes.
- Multi-tenant auth must fail closed for hosted mode but remain default-off for local/dev/test.

---

## 2. File Map by Stream

### Stream I7 — Compaction negative retained

**Modify:**
- `apps/api/app/runtime/models.py` — add negative-retention DTO fields/models if existing `RetainedFact` is insufficient.
- `apps/api/app/retrieval/packer.py` — retain high-priority negative evidence through budget compaction without making raw unsafe text protected.
- `apps/api/app/retrieval/negative_evidence.py` — expose sanitized retained-fact conversion helpers.
- `apps/api/app/observability/replay.py` — reconstruct retained negative lessons from persisted compaction logs.
- `apps/api/app/observability/metrics.py` / `reports.py` — count retained negative lessons distinctly from positive retained facts.
- `apps/api/app/benchmark/cases.py`, `runner.py`, `evaluator.py` — add acceptance coverage.
- `apps/api/tests/retrieval/test_packer_negative.py`, `apps/api/tests/observability/test_replay.py`, `apps/api/tests/benchmark/test_runner.py` — targeted tests.
- `docs/design/CONTEXT_COMPACTION_PLAN.md`, `docs/design/FAILURE_AWARE_NEGATIVE_MEMORY_PLAN.md`, `docs/design/ROADMAP.md`, `.ai/PROJECT_STATE.md`, `.ai/REQUIREMENTS.md`, `.ai/IMPLEMENTATION_PLAN.md` — closeout sync after implementation.

### Stream P4-A — Async foundation

**Create:**
- `apps/api/app/async_tasks/__init__.py`
- `apps/api/app/async_tasks/celery_app.py`
- `apps/api/app/async_tasks/contracts.py`
- `apps/api/app/async_tasks/idempotency.py`
- `apps/api/app/async_tasks/tasks.py`
- `apps/api/app/memory/redis_candidate_buffer.py`
- `apps/api/tests/async_tasks/`

**Modify:**
- `pyproject.toml` — add `celery` and `redis` dependencies.
- `docker-compose.yml` or create `docker-compose.dev.yml` — add Redis/worker without making core Postgres-only path heavy.
- `apps/api/app/config.py` — add Redis/Celery/extraction mode settings.
- `apps/api/app/api/deps.py` — initialize/shutdown long-lived Redis/provider resources.
- `apps/api/app/runtime/models.py` — extend `ExtractionMode` from `sync/buffered` to `async/sync_flush/lazy/no_extract` while preserving backward-compatible aliases.
- `apps/api/app/runtime/memory_runtime.py` — enqueue async extraction and flush paths through buffer interface.
- `packages/python-sdk/tests/test_backend_isomorphism.py` / API tests — prove HTTP/in-process semantics remain stable for sync paths.

### Stream P4-B — Lifecycle/reflection scheduler

**Create:**
- `apps/api/app/memory/lifecycle.py`
- `apps/api/app/memory/retention.py`
- `apps/api/app/memory/scheduler.py`
- `apps/api/tests/memory/test_lifecycle.py`
- `apps/api/tests/memory/test_retention_scheduler.py`

**Modify:**
- `apps/api/app/runtime/models.py` — add audit DTOs and scheduler result DTOs.
- `apps/api/app/runtime/repository.py`, `storage/sql_repository.py`, `storage/orm.py` — add lifecycle audit records and query/update methods.
- `migrations/versions/0007_phase4_async_lifecycle.py` — schema for audit/task metadata if needed.
- `apps/api/app/retrieval/controller.py` — replace reflection-lite score with persisted retention/reflection fields when available.
- `apps/api/app/retrieval/policy.py` — include lifecycle/retention policy version.
- `apps/api/app/benchmark/runner.py` and `test_runner.py` — keep `case_12` deterministic while proving real scheduler signal can drive `variant_3`.

### Stream P4-C — Versions/conflicts

**Create:**
- `apps/api/app/memory/versioning.py`
- `apps/api/app/memory/conflicts.py`
- `apps/api/tests/memory/test_versioning.py`
- `apps/api/tests/memory/test_conflicts.py`

**Modify:**
- `runtime/models.py`, `repository.py`, `storage/orm.py`, `sql_repository.py` — add `MemoryVersionRecord` and `MemoryConflictRecord`.
- `api/routes.py` — add read-only conflict/version APIs under `/v1/memories/...`.
- `observability/metrics.py`, `reports.py`, dashboard tables — expose conflict counts and unresolved conflict rows.
- `migrations/versions/0008_memory_versions_conflicts.py` — add tables/indexes.

### Stream P4-D — Multi-tenant governance

**Create:**
- `apps/api/app/governance/__init__.py`
- `apps/api/app/governance/auth.py`
- `apps/api/app/governance/permissions.py`
- `apps/api/app/governance/quota.py`
- `apps/api/app/governance/redaction_policy.py`
- `apps/api/tests/governance/`

**Modify:**
- `config.py` — add `governance_enabled`, quota/rate-limit settings, redaction-state settings.
- `api/deps.py` — replace single-token check with default-off identity resolution + workspace authorization.
- `api/routes.py` — apply workspace permission dependency to all workspace-scoped endpoints.
- `runtime/models.py`, `repository.py`, `storage/orm.py`, `sql_repository.py` — add API key/workspace membership/quota records.
- `migrations/versions/0009_governance.py` — governance tables.
- `packages/python-sdk/src/memtrace_sdk/backends.py` and CLI tests — continue bearer token support and add workspace forbidden mapping.

### Stream INT-A/B/C — TypeScript SDK, MCP, IDE

**Create:**
- `package.json`, `bun.lockb` or Bun lockfile generated by Bun, `tsconfig.base.json`.
- `packages/ts-sdk/package.json`, `packages/ts-sdk/tsconfig.json`, `packages/ts-sdk/src/index.ts`, `packages/ts-sdk/src/client.ts`, `packages/ts-sdk/src/types.ts`, `packages/ts-sdk/src/errors.ts`.
- `packages/mcp-server/package.json`, `packages/mcp-server/src/server.ts`, `packages/mcp-server/src/tools.ts`, `packages/mcp-server/src/config.ts`.
- `examples/ts-simple-agent/` and `examples/mcp/`.
- `packages/ide/` only for thin VS Code/Cursor/Claude Code wiring after MCP contract stabilizes.

**Modify:**
- `README.md`, `docs/design/ROADMAP.md`, `.ai/*` memory files after each completed integration slice.
- `scripts/reproduce.sh` only if adding JS smoke checks remains deterministic and fast; otherwise add separate `scripts/smoke-integrations.sh`.

---

## 3. Stream I7 — Compaction Negative Retained Facts

### I7.1 Define retained negative lesson contract

**Files:**
- Modify: `apps/api/app/runtime/models.py`
- Modify: `apps/api/app/retrieval/negative_evidence.py`
- Test: `apps/api/tests/retrieval/test_packer_negative.py`

- [ ] **Step 1: Write RED tests for safe vs unsafe retained negative conversion**
  - Add tests that build `NegativeEvidence(mode="raw_failed_attempt")` and `NegativeEvidence(mode="sanitized_risk_notice")`.
  - Assert the retained representation contains only `safe_text`, ids, mode, reason, and provenance ids.
  - Assert it never contains raw unsafe command markers when mode is sanitized.
  - Run: `uv run --extra dev pytest apps/api/tests/retrieval/test_packer_negative.py -k "negative_retained" -q`
  - Expected before implementation: fail because conversion helper/model field is missing.

- [ ] **Step 2: Add a small DTO rather than overloading positive `RetainedFact`**
  - Preferred model name: `RetainedNegativeEvidence` in `runtime/models.py`.
  - Fields: `source_memory_id`, `source_state_node_id`, `mode`, `risk_kind`, `reason`, `safe_text`, `provenance`, `created_from_block_type="avoided_attempts"`.
  - Keep it serializable under `ContextCompactionLog.retained_facts` as JSON until a later migration adds a dedicated column.

- [ ] **Step 3: Implement conversion in `negative_evidence.py`**
  - Add `to_retained_negative_evidence(evidence: NegativeEvidence) -> RetainedNegativeEvidence`.
  - Re-run the RED tests; expected: pass.

### I7.2 Teach packer compaction to retain negative lessons under budget pressure

**Files:**
- Modify: `apps/api/app/retrieval/packer.py`
- Test: `apps/api/tests/retrieval/test_packer_negative.py`

- [ ] **Step 1: Write RED budget-pressure test**
  - Construct project constraints + one safe `avoided_attempts` block + ordinary episodic blocks.
  - Use a tight token budget where ordinary episodic blocks drop.
  - Assert `PackResult.compacted_constraints` or equivalent compaction payload includes a retained negative lesson entry without moving raw failed text into a positive block.
  - Run: `uv run --extra dev pytest apps/api/tests/retrieval/test_packer_negative.py -k "negative_retained_under_compaction" -q`.

- [ ] **Step 2: Implement retention hook**
  - During ordinary block drop/compaction, detect blocks with `type="avoided_attempts"` and `source="negative_evidence"`.
  - Convert them through `to_retained_negative_evidence(...)` if source metadata includes enough information; otherwise retain a sanitized notice only.
  - Keep `avoided_attempts` ordinary for actual context packing; retention is a compaction-log summary, not protected prompt injection.

- [ ] **Step 3: Verify no unsafe leakage**
  - Add explicit test with destructive failed memory markers such as `rm -rf /prod` and assert the retained JSON/log output does not include them.
  - Run: `uv run --extra dev pytest apps/api/tests/retrieval/test_packer_negative.py -q`.

### I7.3 Persist and replay retained negative lessons

**Files:**
- Modify: `apps/api/app/observability/replay.py`
- Modify: `apps/api/app/observability/metrics.py`
- Modify: `apps/api/app/observability/reports.py`
- Test: `apps/api/tests/observability/test_replay.py`

- [ ] **Step 1: Write RED replay drift test**
  - Execute retrieval that triggers compaction and drops/retains negative evidence.
  - Replay the access.
  - Assert replay reconstructs the retained negative lesson from `ContextCompactionLog` rather than rerunning a summarizer or reading unsafe raw memory.

- [ ] **Step 2: Add metrics**
  - Add `retained_negative_evidence_count` and `sanitized_retained_negative_evidence_count` to observability access metrics and summary/report output.
  - Existing `negative_evidence_block_count` remains actual prompt-block count.

- [ ] **Step 3: Run affected replay/metrics suite**
  - Command: `uv run --extra dev pytest apps/api/tests/observability/test_replay.py apps/api/tests/retrieval/test_packer_negative.py apps/api/tests/observability/test_reports.py -q`.
  - Expected: all pass; no raw unsafe markers in JSON/Markdown/HTML reports.

### I7.4 Benchmark acceptance and closeout

**Files:**
- Modify: `apps/api/app/benchmark/cases.py`
- Modify: `apps/api/app/benchmark/evaluator.py`
- Modify: `apps/api/app/benchmark/runner.py`
- Test: `apps/api/tests/benchmark/test_runner.py`
- Docs: `docs/design/FAILURE_AWARE_NEGATIVE_MEMORY_PLAN.md`, `docs/design/CONTEXT_COMPACTION_PLAN.md`, `docs/design/ROADMAP.md`, `.ai/*`

- [ ] **Step 1: Add benchmark case**
  - Add `case_13_compaction_retains_negative_lesson`.
  - Shape: safe failed attempt exists, token budget forces ordinary block drop, variant_2 should preserve a sanitized/retained negative lesson in compaction metadata, and positive context remains uncontaminated.

- [ ] **Step 2: Add acceptance check**
  - Add `variant_2_retains_negative_lesson_under_compaction`.
  - Extend report JSON/Markdown with the new metric.

- [ ] **Step 3: Verification**
  - Targeted: `uv run --extra dev pytest apps/api/tests/benchmark/test_runner.py -k "compaction_retains_negative" -q`.
  - Affected: `uv run --extra dev pytest apps/api/tests/retrieval apps/api/tests/observability apps/api/tests/benchmark/test_runner.py -q`.
  - Repro: `uv run python -m app.benchmark.runner --output-dir reports && bash scripts/reproduce.sh`.

---

## 4. Stream P4-A — Async Foundation

### P4-A1 Add async settings and queue contracts without starting workers

**Files:**
- Modify: `pyproject.toml`
- Modify: `apps/api/app/config.py`
- Create: `apps/api/app/async_tasks/contracts.py`
- Test: `apps/api/tests/async_tasks/test_contracts.py`

- [ ] **Step 1: Add dependencies**
  - Add `celery>=5.4` and `redis>=5.0` to root dependencies.
  - Keep tests deterministic by not requiring Redis unless marked/gated.

- [ ] **Step 2: Add settings**
  - Add `redis_url`, `celery_broker_url`, `celery_result_backend`, `async_tasks_enabled`, `celery_task_always_eager`, `memory_queue_name`, `maintenance_queue_name`, `eval_queue_name`.
  - Defaults: disabled/eager-safe for tests, no network dependency in normal pytest.

- [ ] **Step 3: Define task envelope**
  - `TaskEnvelope`: `task_id`, `task_type`, `workspace_id`, `dedupe_key`, `payload`, `created_at`.
  - `TaskResult`: `task_id`, `status`, `attempts`, `error_code`, `metadata`.
  - Tests assert stable JSON and no secret-like payload keys are accepted without redaction.

- [ ] **Step 4: Verify**
  - Run: `uv run --extra dev pytest apps/api/tests/async_tasks/test_contracts.py -q`.

### P4-A2 Celery app, eager mode, and idempotency locks

**Files:**
- Create: `apps/api/app/async_tasks/celery_app.py`
- Create: `apps/api/app/async_tasks/idempotency.py`
- Create: `apps/api/app/async_tasks/tasks.py`
- Test: `apps/api/tests/async_tasks/test_celery_eager.py`

- [ ] **Step 1: RED tests**
  - Assert `make_celery_app(settings)` registers queues `memory_queue`, `maintenance_queue`, `eval_queue`.
  - Assert eager mode executes a task inline without Redis.
  - Assert idempotency key prevents duplicate task execution in an in-memory fake lock backend.

- [ ] **Step 2: Implement app factory**
  - Read settings from `get_settings()`.
  - Use JSON serializer only.
  - Disable result persistence by default unless explicitly configured.

- [ ] **Step 3: Implement idempotency abstraction**
  - Define protocol `IdempotencyStore.acquire(key, ttl_seconds) -> bool` and `release(key)`.
  - Provide in-memory implementation for tests and Redis implementation for enabled deployments.

- [ ] **Step 4: Verify**
  - Run: `uv run --extra dev pytest apps/api/tests/async_tasks -q`.

### P4-A3 Redis-backed candidate buffer with in-memory compatibility

**Files:**
- Create: `apps/api/app/memory/buffer.py`
- Modify: `apps/api/app/memory/candidate_buffer.py`
- Create: `apps/api/app/memory/redis_candidate_buffer.py`
- Modify: `apps/api/app/runtime/memory_runtime.py`
- Test: `apps/api/tests/memory/test_candidate_buffer.py`

- [ ] **Step 1: Extract protocol**
  - `CandidateBufferProtocol.append(event)`, `pending(session_id)`, `drain(session_id)`, `size(session_id)`, `total_size()`, `sessions()`.
  - Existing `CandidateBuffer` implements it unchanged.

- [ ] **Step 2: Write RED Redis fake tests**
  - Use a fake async Redis object; do not require a real Redis server for unit tests.
  - Assert FIFO order, drain idempotency, session key isolation, and no raw secrets in Redis keys.

- [ ] **Step 3: Implement Redis buffer**
  - Store serialized event JSON values keyed by workspace/session.
  - Use atomic pop/drain semantics with a Lua script or transaction wrapper in real Redis; unit-test against fake behavior and mark real integration optional.

- [ ] **Step 4: Wire runtime selection**
  - `api/deps.py` selects in-memory buffer by default; Redis buffer only when `async_tasks_enabled` and Redis URL configured.
  - `MemoryRuntime` accepts optional buffer dependency instead of constructing `CandidateBuffer()` directly.

### P4-A4 Write mode matrix and async retry path

**Files:**
- Modify: `apps/api/app/runtime/models.py`
- Modify: `apps/api/app/runtime/memory_runtime.py`
- Modify: `apps/api/app/async_tasks/tasks.py`
- Test: `apps/api/tests/runtime/test_extraction_modes.py`
- Test: `packages/python-sdk/tests/test_backend_isomorphism.py`

- [ ] **Step 1: Extend `ExtractionMode`**
  - Values: `sync`, `buffered` (backcompat alias), `async`, `sync_flush`, `lazy`, `no_extract`.
  - `buffered` maps to `lazy` internally for compatibility.

- [ ] **Step 2: RED mode matrix tests**
  - `sync`: current behavior.
  - `sync_flush`: raw event written, extraction happens on flush boundary synchronously.
  - `lazy`: raw event written, buffer flushed at retrieve/finish boundaries.
  - `async`: enqueue extraction task and return quickly.
  - `no_extract`: raw event only, no memory derived.

- [ ] **Step 3: Implement minimal mode routing**
  - Keep benchmark defaults on `sync`.
  - If async task enqueue fails, store buffered candidate and emit profile warning rather than losing raw trace.

- [ ] **Step 4: Verify**
  - Run: `uv run --extra dev pytest apps/api/tests/runtime/test_extraction_modes.py packages/python-sdk/tests/test_backend_isomorphism.py -q`.

### P4-A5 Dev compose split and optional Redis smoke

**Files:**
- Modify or create: `docker-compose.dev.yml`
- Modify: `README.md` after implementation
- Test: `apps/api/tests/integration/test_async_infra.py`

- [ ] **Step 1: Compose split**
  - Keep existing `docker-compose.yml` core Postgres-only.
  - Add `docker-compose.dev.yml` with Redis and worker service.
  - Use `docker-compose`, not `docker compose`, in docs/scripts because the current environment previously only had standalone compose.

- [ ] **Step 2: Optional integration test**
  - Gate real Redis tests behind `MEMTRACE_TEST_REDIS_URL`.
  - Default full pytest must skip them cleanly.

---

## 5. Stream P4-B — Lifecycle, Reflection, and Scheduler

### P4-B1 Lifecycle transition policy and audit log

**Files:**
- Create: `apps/api/app/memory/lifecycle.py`
- Modify: `apps/api/app/runtime/models.py`
- Modify: `apps/api/app/runtime/repository.py`
- Modify: `apps/api/app/storage/orm.py`
- Modify: `apps/api/app/storage/sql_repository.py`
- Create migration: `migrations/versions/0007_phase4_async_lifecycle.py`
- Test: `apps/api/tests/memory/test_lifecycle.py`, `apps/api/tests/storage/test_migrations.py`

- [ ] **Step 1: Define transition table**
  - Allowed mainline: `active -> dormant -> archived -> deleted`.
  - Side states: `pinned`, `superseded`, `conflicted`, `quarantined`.
  - Pinned blocks automatic decay/archive but can still be manually unpinned.
  - Quarantined is never retrievable even if a future retrieval path forgets soft policy; gate safety floor remains.

- [ ] **Step 2: Add audit record**
  - `MemoryLifecycleAuditRecord`: `audit_id`, `workspace_id`, `memory_id`, `from_status`, `to_status`, `reason`, `actor`, `scheduler_run_id`, `metadata`, `created_at`.
  - Repository methods: `add_lifecycle_audit`, `list_lifecycle_audits`.

- [ ] **Step 3: Migration policy**
  - Add non-null columns only with server defaults or backfills per H15.
  - Run: `uv run --extra dev pytest apps/api/tests/storage/test_migrations.py -q`.

### P4-B2 Retention/reflection scoring model

**Files:**
- Create: `apps/api/app/memory/retention.py`
- Modify: `apps/api/app/retrieval/controller.py`
- Modify: `apps/api/app/retrieval/policy.py`
- Test: `apps/api/tests/memory/test_retention_scheduler.py`, `apps/api/tests/retrieval/test_retrieval_flow.py`

- [ ] **Step 1: RED score tests**
  - Verify `value_score`, `freshness_score`, `trust_score`, `risk_score`, `access_count`, `last_accessed_at`, and `expires_at` produce deterministic `retention_score` and `reflection_priority`.
  - Verify stale/expired memory remains excluded for `variant_2`.

- [ ] **Step 2: Implement scoring**
  - Add `compute_retention_signals(memory, now, policy)` returning `retention_score`, `reflection_priority`, and reason metadata.
  - Keep deterministic formulas with versioned constants.

- [ ] **Step 3: Replace `variant_3` reflection-lite path**
  - If persisted scheduler scores exist, use them for `variant_3` rerank.
  - If absent, fall back to existing deterministic function and mark policy snapshot `reflection_signal_source="fallback_lite"`.

### P4-B3 Scheduled maintenance tasks

**Files:**
- Create: `apps/api/app/memory/scheduler.py`
- Modify: `apps/api/app/async_tasks/tasks.py`
- Test: `apps/api/tests/memory/test_retention_scheduler.py`

- [ ] **Step 1: Implement no-network deterministic scheduler functions**
  - `score_memory(workspace_id)` updates retention/reflection fields.
  - `decay_memory(workspace_id)` moves eligible active memories to dormant.
  - `archive_memory(workspace_id)` moves old dormant memories to archived.
  - `quarantine_memory(workspace_id)` quarantines unsafe/risky memories by policy.
  - `profile_refresh(workspace_id)` recomputes summary metrics.

- [ ] **Step 2: Celery wrappers**
  - Wrap scheduler functions in Celery tasks but keep the functions directly testable.
  - Use idempotency keys per workspace/task/window.

- [ ] **Step 3: Verify retrieval invariant**
  - Add conformance coverage that archived/dormant/deleted never enter candidates; pinned remains candidate but still passes gate.
  - Run: `uv run --extra dev pytest apps/api/tests/conformance apps/api/tests/memory/test_retention_scheduler.py -q`.

### P4-B4 Benchmark and replay closeout

**Files:**
- Modify: `apps/api/app/benchmark/runner.py`
- Modify: `apps/api/tests/benchmark/test_runner.py`
- Modify: `docs/design/ROADMAP.md`, `.ai/*`

- [ ] **Step 1: Update case_12**
  - Make `case_12_reflection_retention` pass via scheduler-derived signal when scheduler is enabled.
  - Keep deterministic fallback so existing reproducibility remains stable.

- [ ] **Step 2: Verification**
  - `uv run --extra dev pytest apps/api/tests/benchmark/test_runner.py apps/api/tests/retrieval/test_retrieval_flow.py apps/api/tests/observability/test_replay.py -q`.
  - `uv run python -m app.benchmark.runner --output-dir reports`.

---

## 6. Stream P4-C — Memory Versions and Conflicts

### P4-C1 Version manager

**Files:**
- Create: `apps/api/app/memory/versioning.py`
- Modify: `runtime/models.py`, `repository.py`, `storage/orm.py`, `storage/sql_repository.py`
- Create migration: `migrations/versions/0008_memory_versions_conflicts.py`
- Test: `apps/api/tests/memory/test_versioning.py`

- [ ] **Step 1: Define `MemoryVersionRecord`**
  - Fields: `version_id`, `memory_id`, `workspace_id`, `version_no`, `snapshot`, `change_reason`, `created_at`.
  - Snapshot must be redacted and exclude raw secret payloads.

- [ ] **Step 2: Capture versions on status/content-changing updates**
  - Supersede, conflict resolution, lifecycle status transitions, and manual updates record versions.
  - Access-count updates do not create versions.

### P4-C2 Conflict scan and read APIs

**Files:**
- Create: `apps/api/app/memory/conflicts.py`
- Modify: `api/routes.py`, `observability/metrics.py`, dashboard tables
- Test: `apps/api/tests/memory/test_conflicts.py`, `apps/api/tests/api/test_dashboard.py`

- [ ] **Step 1: Define conflict rules**
  - Same canonical key + same scope + different value for single-valued ontology keys.
  - Tool-result evidence can explain but not auto-overwrite higher-trust project constraints.
  - Newer high-trust explicit correction supersedes older lower-trust value.

- [ ] **Step 2: Implement conflict records**
  - `MemoryConflictRecord`: `conflict_id`, `workspace_id`, `subject_key`, `memory_ids`, `status`, `detected_by`, `explanation`, `created_at`, `resolved_at`.
  - Expose `GET /v1/memory-conflicts` and `GET /v1/memories/{memory_id}/versions`.

- [ ] **Step 3: Verify**
  - `uv run --extra dev pytest apps/api/tests/memory/test_conflicts.py apps/api/tests/api/test_dashboard.py -q`.

---

## 7. Stream P4-D — Multi-Tenant Governance

### P4-D1 Identity and API key model

**Files:**
- Create: `apps/api/app/governance/auth.py`
- Modify: `apps/api/app/api/deps.py`
- Modify: `runtime/models.py`, `repository.py`, `storage/orm.py`, `storage/sql_repository.py`
- Create migration: `migrations/versions/0009_governance.py`
- Test: `apps/api/tests/governance/test_auth.py`, `apps/api/tests/api/test_auth.py`

- [ ] **Step 1: Extend without breaking H3**
  - `MEMTRACE_AUTH_ENABLED=false` remains no-auth local default.
  - Existing single `MEMTRACE_API_KEY` remains accepted as legacy admin/demo token when governance tables are empty.
  - New API keys are stored hashed/digested, never raw.

- [ ] **Step 2: Add identity DTOs**
  - `Principal`: `principal_id`, `kind`, `workspace_ids`, `roles`, `api_key_id`.
  - `WorkspacePermission`: role names `owner`, `writer`, `reader`, `report_reader`.

- [ ] **Step 3: Route dependency**
  - Resolve principal once per request.
  - Enforce workspace permission for every endpoint that accepts path/query/body `workspace_id`.
  - Reject mismatched body workspace vs authorized workspace with 403.

### P4-D2 Quota and rate limit

**Files:**
- Create: `apps/api/app/governance/quota.py`
- Modify: `api/deps.py`, `api/routes.py`
- Test: `apps/api/tests/governance/test_quota.py`

- [ ] **Step 1: Define quota units**
  - `write_event`, `retrieve_context`, `report_export`, `replay`, `async_task_enqueue`.
  - Store limits in settings and optional DB records.

- [ ] **Step 2: Redis counter implementation**
  - Use fixed-window counters keyed by workspace/principal/unit.
  - Fail closed only when governance is enabled; otherwise warn/degrade for local mode.

- [ ] **Step 3: Tests**
  - Fake Redis unit tests for limit exceeded.
  - Optional real Redis integration behind `MEMTRACE_TEST_REDIS_URL`.

### P4-D3 Redaction state machine and encrypted raw payload reference

**Files:**
- Create: `apps/api/app/governance/redaction_policy.py`
- Modify: `memory/secrets.py`, `runtime/memory_runtime.py`, `observability/trace_bundle.py`
- Test: `apps/api/tests/governance/test_redaction_policy.py`, `apps/api/tests/observability/test_trace_bundle.py`

- [ ] **Step 1: Define states**
  - `none`, `redacted`, `digest_only`, `blocked`.
  - Current behavior maps to `redacted` or `digest_only`; raw secret storage remains disabled by default.

- [ ] **Step 2: Raw payload reference guard**
  - If a future encrypted store is not configured, any request asking for raw retention returns 400/disabled.
  - Trace bundle export remains redacted even when raw refs exist.

- [ ] **Step 3: Verify**
  - Ensure secrets never appear in event content, memory content, trace bundles, reports, or Redis payloads.

### P4-D4 Governance closeout

**Verification:**
- Targeted governance suite.
- Full API/SDK auth suite.
- Full regression: `uv run --extra dev pytest -q`.
- Benchmark/reproduce remain no-auth deterministic by default.

---

## 8. Stream INT-A — TypeScript SDK

### INT-A1 Bun workspace and generated/handwritten types

**Files:**
- Create: `package.json`, `tsconfig.base.json`
- Create: `packages/ts-sdk/package.json`, `packages/ts-sdk/tsconfig.json`
- Create: `packages/ts-sdk/src/types.ts`, `client.ts`, `errors.ts`, `index.ts`
- Test: `packages/ts-sdk/test/client.test.ts`

- [ ] **Step 1: Add Bun workspace**
  - Scripts: `bun test`, `bun run typecheck`.
  - Do not introduce npm/pnpm/yarn lockfiles.

- [ ] **Step 2: Mirror Python SDK HTTP surface**
  - Methods: `startRun`, `startStep`, `writeEvent`, `finishStep`, `rollbackBranch`, `retrieveContext`, `getTimeline`, `getStateTree`, `inspectAccess`, `replayAccess`, `dashboardTables`, `flushSession`, `writeObservabilityReport`.
  - Error classes: `MemTraceError`, `NotFoundError`, `BadRequestError`, `ForbiddenError`, `RateLimitedError`.

- [ ] **Step 3: Tests with mocked fetch**
  - Assert JSON request/response parsing, bearer token header, 404/400/403/429 mapping, arbitrary `session_id` flush body route.

### INT-A2 Cross-language contract smoke

**Files:**
- Create: `examples/ts-simple-agent/`
- Test: `packages/ts-sdk/test/contract.test.ts`

- [ ] **Step 1: ASGI/HTTP-backed smoke**
  - Prefer running against a test HTTP app if feasible; otherwise keep deterministic mocked contract tests and document real-service smoke command.

- [ ] **Step 2: Verify**
  - `bun test packages/ts-sdk/test`.
  - `bun run typecheck`.
  - Root Python tests unchanged.

---

## 9. Stream INT-B — MCP Server

### INT-B1 MCP tools mapped to runtime APIs

**Files:**
- Create: `packages/mcp-server/package.json`
- Create: `packages/mcp-server/src/server.ts`, `tools.ts`, `config.ts`
- Test: `packages/mcp-server/test/tools.test.ts`

- [ ] **Step 1: Define tools**
  - `memtrace_start_run`, `memtrace_start_step`, `memtrace_write_event`, `memtrace_finish_step`, `memtrace_retrieve_context`, `memtrace_inspect_access`, `memtrace_replay_access`, `memtrace_report`.
  - Tools call TS SDK; no direct DB/runtime imports.

- [ ] **Step 2: Safety defaults**
  - Require explicit base URL.
  - Support API key env var.
  - Redact tool error output.

- [ ] **Step 3: Tests**
  - Mock TS SDK client and assert schemas, auth propagation, and error mapping.

### INT-B2 MCP examples and docs

**Status (2026-06-14):** ✅ superseded by and completed in `docs/design/INTEGRATIONS_PLAN.md` INT-B/INT-C. Root README now contains MCP config docs, and concrete Claude Code/Cursor JSON templates live in `examples/mcp/`.

**Files:**
- Create: `examples/mcp/README.md` only if explicitly accepted during implementation closeout; otherwise keep docs in root README section.
- Modify: `README.md`

- [x] **Step 1: Minimal config snippets**
  - Claude Code/Cursor-style server config examples.
  - Keep examples no-secret and use env var placeholders.

---

## 10. Stream INT-C — IDE Integration Thin Layer

### INT-C1 Decide IDE packaging after MCP is stable

**Status (2026-06-14):** ✅ complete as a scope decision in `docs/design/INTEGRATIONS_PLAN.md` INT-C2. No dedicated IDE package is created yet; wait for MCP adoption feedback and editor-specific requirements.

**Files:**
- Create only after review: `packages/ide/`
- Test: package-specific smoke tests

- [x] **Step 1: Scope decision**
  - Prefer MCP config templates and command palette wrappers before building full VS Code extension.
  - If a VS Code extension is selected, it should call MCP/TS SDK and expose: start run, record event, retrieve context, replay access, export redacted bundle.

- [x] **Step 2: No semantic duplication**
  - IDE layer must not implement retrieval, gate, packing, summarization, or auth logic.

---

## 11. Cross-Stream Verification Matrix

Run these at the end of each stream, not just at the final umbrella closeout:

### Always

- `uv run --extra dev python -m compileall -q apps/api/app packages/python-sdk/src examples`
- Targeted stream tests.
- Affected regression tests for touched modules.

### After schema changes

- `uv run --extra dev pytest apps/api/tests/storage/test_migrations.py -q`
- Optional PostgreSQL smoke only when `MEMTRACE_TEST_DATABASE_URL` is set.

### After retrieval/lifecycle/compaction changes

- `uv run --extra dev pytest apps/api/tests/retrieval apps/api/tests/observability apps/api/tests/conformance -q`
- `uv run python -m app.benchmark.runner --output-dir reports`
- `bash scripts/reproduce.sh`

### After SDK/integration changes

- `uv run --package memtrace-sdk --extra dev pytest packages/python-sdk/tests -q`
- `bun test packages/ts-sdk/test` once TS workspace exists.
- `bun run typecheck` once TS workspace exists.

### Final closeout

- `uv run --extra dev pytest -q`
- `uv run --extra dev python -m compileall -q apps/api/app packages/python-sdk/src examples`
- `uv run python -m app.benchmark.runner --output-dir reports`
- `bash scripts/reproduce.sh`
- If JS packages exist: `bun test` and `bun run typecheck`.

---

## 12. Documentation and Project-Memory Sync Rules

After each completed issue group:

- Update `docs/design/ROADMAP.md` checkboxes and append status notes.
- Update this plan's issue checkboxes and verification notes.
- Update `.ai/PROJECT_STATE.md`, `.ai/REQUIREMENTS.md`, `.ai/IMPLEMENTATION_PLAN.md`, and `.ai/OPEN_QUESTIONS.md` if selected next target changes.
- Update `.ai/PITFALLS.md` for any new traps discovered.
- Do not update `AGENTS.md` unless durable working agreements change.
- Do not commit generated `reports/` outputs.

---

## 13. Self-Review Checklist for This Plan

- [x] Scope is decomposed into independent streams rather than one giant implementation task.
- [x] Every stream lists concrete source/test/doc files.
- [x] Async infra lands before Redis-dependent quota/scheduler behavior.
- [x] I7 preserves negative lessons without moving failed memory into positive context.
- [x] Multi-tenant governance extends default-off H3 auth without breaking local/dev/benchmark.
- [x] TS/MCP/IDE integrations consume runtime/HTTP APIs and do not duplicate memory semantics.
- [x] Verification commands include targeted, affected, full regression, benchmark, and reproducibility checks.
