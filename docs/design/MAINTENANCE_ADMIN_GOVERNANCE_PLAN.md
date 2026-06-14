# Maintenance Scheduler / Admin Governance Depth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the post-Phase-4 maintenance scheduler and admin governance depth slice: durable scheduler run/task-attempt records, the full first-wave maintenance task family, owner-gated admin APIs for maintenance/lifecycle/conflicts/API keys/quota overrides, and closeout verification without changing default local/benchmark behavior.

**Architecture:** Build on the completed Phase 4 foundations rather than replacing them. `MemoryRuntime` remains the semantic boundary, `Repository` remains the storage boundary, maintenance work stays callable as direct async functions and optionally via Celery, and all admin mutation paths go through existing lifecycle/version/conflict/auth/quota helpers. Admin surfaces are disabled by default and owner-gated when enabled; no frontend/UI is included in this slice.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy async, Alembic, PostgreSQL/pgvector, optional Redis/Celery, pytest/pytest-asyncio, uv, existing MemTrace runtime/repository/governance abstractions.

---

## 0. Source-Verified Current State

- `docs/design/PHASE4_PLATFORM_PLAN.md` is complete through P4-D4. This follow-up must not reopen completed Phase 4 semantics.
- Existing maintenance code is `apps/api/app/memory/scheduler.py`: `score_memory`, `decay_memory`, `archive_memory`, `quarantine_memory`, and `profile_refresh` are direct async functions over `Repository`.
- Existing Celery maintenance wrapper is `apps/api/app/async_tasks/tasks.py`: `process_memory_maintenance(...)` dispatches only the five current operations and uses task-envelope idempotency.
- Existing lifecycle transition helper is `apps/api/app/memory/lifecycle.py`; new manual/admin lifecycle changes must use it and persist `MemoryLifecycleAuditRecord`.
- Existing conflict detector is `apps/api/app/memory/conflicts.py`; it detects active same-key/scope single-valued conflicts using key ontology helpers and currently supports read-only conflict records.
- Existing governance primitives are `apps/api/app/governance/auth.py`, `permissions.py`, `quota.py`, and `redaction_policy.py`; admin routes must reuse `Principal`, `WorkspacePermission.owner`, `QuotaUnit`, and existing resource-ownership helpers rather than introducing parallel auth semantics.
- Existing API route file `apps/api/app/api/routes.py` already contains workspace/resource authorization helpers for runtime/read/report/telemetry routes. Admin routes should live in a separate router file to avoid growing `routes.py` further.

## 1. Scope

### In Scope

1. Durable scheduler-run and task-attempt records, including per-operation status, per-run idempotency keys, preview/dry-run support, and redacted failure summaries. Distributed durable leases are explicitly deferred.
2. Full first-wave maintenance task family:
   - existing: `score_memory`, `decay_memory`, `archive_memory`, `quarantine_memory`, `profile_refresh`;
   - new: `conflict_scan`, `dedup_memory`, `reindex_memory`, `summary_refresh`, `procedural_refresh`.
3. Unified maintenance orchestrator that can run one operation or an ordered workspace maintenance plan directly, through admin API, or through the Celery maintenance wrapper.
4. Owner-gated admin APIs for:
   - starting/listing/reading maintenance runs;
   - listing lifecycle audits;
   - manual memory lifecycle transitions;
   - resolving memory conflicts;
   - creating/listing/revoking DB API keys;
   - managing quota limit overrides.
5. Repository, SQL, migration, in-memory, tests, docs/ROADMAP/`.ai` closeout.

### Non-Goals

- No React/admin UI in this slice.
- No JWT/OIDC, membership table, organization model, or hosted billing model.
- No Elasticsearch/OpenSearch, Neo4j, graph sync, or external reindex worker beyond current pgvector/deterministic embedding contract.
- No production scheduler-beat deployment requirement; Celery beat/cron can be documented as an operator choice after callable/admin-triggered orchestration exists.
- No distributed durable lease / heartbeat / scheduler-beat claim protocol in this slice. Existing Celery task-envelope idempotency plus per-run task-attempt records are sufficient for first-wave direct/admin/Celery orchestration.
- No raw payload store implementation. Existing redaction/raw-payload guard remains authoritative.
- No default-on governance, Redis, Celery, or network provider dependency for local tests, benchmark, reproduce, quickstart, or release smoke.

## 2. Durable Invariants

- **Default-off:** new admin APIs are disabled unless `MEMTRACE_ADMIN_API_ENABLED=true`; governance/auth/quota defaults must not affect existing local/dev/benchmark behavior.
- **Owner-gated:** when admin APIs are enabled, mutating admin routes require a real authenticated `Principal` with `WorkspacePermission.owner` for the target workspace. Anonymous admin calls are not supported in this slice, even for local development.
- **No runtime bypass:** maintenance and admin paths may use repository methods, but any semantic memory changes must go through existing runtime/lifecycle/versioning helpers: `transition_memory_status(...)`, `Repository.transition_memory_with_audit(...)`, `Repository.update_memory(...)` version behavior, and conflict detection.
- **Redacted observability:** scheduler errors/results/admin audits must not store raw API keys, Authorization headers, raw payload refs, destructive commands, production paths, or raw event/memory content beyond already-redacted MemoryItem fields.
- **Workspace isolation:** every scheduler/admin record is workspace-scoped; cross-workspace session or memory mutations are forbidden.
- **Deterministic tests:** all new tests run without real Redis, Celery workers, Postgres, LLM providers, or OTLP endpoints unless explicitly env-gated.
- **Benchmark non-regression:** benchmark/reproduce acceptance remains `13/13`; scheduler/admin changes must not alter retrieval, gate, context packing, compaction, telemetry, or benchmark semantics unless explicitly task-scoped and tested.

---

## 3. File Structure

### New Files

- `apps/api/app/memory/maintenance.py` — orchestration layer for maintenance task selection, dry-run planning, scheduler-run/task-attempt updates, and operation dispatch.
- `apps/api/app/governance/admin.py` — admin request/response helpers, one-time API-key generation, admin gating helper, and redacted admin audit payload helpers.
- `apps/api/app/api/admin_routes.py` — separate FastAPI router mounted under `/v1/admin`.
- `apps/api/tests/memory/test_maintenance_orchestrator.py` — direct scheduler/orchestrator unit tests.
- `apps/api/tests/api/test_admin_maintenance.py` — admin maintenance route tests.
- `apps/api/tests/api/test_admin_governance.py` — API-key/quota/lifecycle/conflict admin route tests.
- `apps/api/tests/governance/test_admin_helpers.py` — admin gating/API-key generation/redaction tests.
- `migrations/versions/0012_maintenance_admin_governance.py` — scheduler-run/task-attempt/admin-audit/quota-override schema.

### Modified Files

- `apps/api/app/config.py` — admin API settings and maintenance limits.
- `apps/api/app/runtime/models.py` — maintenance/admin DTOs and records.
- `apps/api/app/runtime/repository.py` — repository protocol + in-memory implementation for new records and quota overrides.
- `apps/api/app/storage/orm.py` — SQLAlchemy ORM tables/indexes.
- `apps/api/app/storage/sql_repository.py` — SQL mappings and repository implementation.
- `apps/api/app/api/routes.py` — include `admin_routes.router` from the main `/v1` routing module or app router registration point.
- `apps/api/app/async_tasks/tasks.py` — dispatch all maintenance operations through `maintenance.py`.
- `apps/api/app/memory/scheduler.py` — add new direct task functions or delegate to focused helpers.
- `apps/api/app/memory/conflicts.py` — add conflict stale-resolution helper if not better placed in `maintenance.py`.
- `apps/api/app/governance/quota.py` — consult quota override records when available.
- `apps/api/tests/storage/test_migrations.py` — migration/schema policy coverage for `0012`.
- `packages/python-sdk/src/memtrace_sdk/types.py`, `packages/python-sdk/src/memtrace_sdk/backends.py`, `packages/python-sdk/tests/test_http_backend.py` — only if admin HTTP client coverage is selected for this slice; otherwise explicitly defer SDK admin facade.
- `README.md`, `docs/deployment.md`, `docs/design/ROADMAP.md`, `.ai/PROJECT_STATE.md`, `.ai/REQUIREMENTS.md`, `.ai/IMPLEMENTATION_PLAN.md`, `.ai/OPEN_QUESTIONS.md`, `.ai/PITFALLS.md` — closeout documentation/memory sync.

---

## 4. Data Model Plan

Add these Pydantic records in `apps/api/app/runtime/models.py` and mirror them in ORM/migrations/repository mappings.

```python
class MaintenanceOperation(str, Enum):
    score_memory = "score_memory"
    decay_memory = "decay_memory"
    archive_memory = "archive_memory"
    quarantine_memory = "quarantine_memory"
    conflict_scan = "conflict_scan"
    dedup_memory = "dedup_memory"
    reindex_memory = "reindex_memory"
    summary_refresh = "summary_refresh"
    procedural_refresh = "procedural_refresh"
    profile_refresh = "profile_refresh"


class SchedulerRunStatus(str, Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class SchedulerTaskStatus(str, Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    skipped = "skipped"


class MaintenanceRunRecord(_Base):
    scheduler_run_id: str = Field(default_factory=lambda: _new_id("msrun"))
    workspace_id: str
    requested_by: str = "system"
    reason: str | None = None
    operations: list[MaintenanceOperation] = Field(default_factory=list)
    dry_run: bool = False
    status: SchedulerRunStatus = SchedulerRunStatus.pending
    summary: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class MaintenanceTaskAttemptRecord(_Base):
    attempt_id: str = Field(default_factory=lambda: _new_id("mstat"))
    scheduler_run_id: str
    workspace_id: str
    operation: MaintenanceOperation
    status: SchedulerTaskStatus = SchedulerTaskStatus.pending
    idempotency_key: str | None = None
    attempt_no: int = 1
    result: dict[str, Any] = Field(default_factory=dict)
    error_summary: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class AdminActionAuditRecord(_Base):
    admin_action_id: str = Field(default_factory=lambda: _new_id("admact"))
    workspace_id: str
    principal_id: str
    action: str
    target_type: str
    target_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_now)


class QuotaLimitRecord(_Base):
    quota_limit_id: str = Field(default_factory=lambda: _new_id("qlim"))
    workspace_id: str
    principal_id: str | None = None
    unit: QuotaUnitName
    limit: int
    window_seconds: int
    created_by: str
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)
```

Use a string enum or `Literal[...]` for `QuotaUnitName` to avoid importing `governance.quota.QuotaUnit` into core models if that creates dependency direction issues. Repository/route code can convert between strings and `QuotaUnit` at the boundary.

---

## 5. Implementation Tasks

### Task 1: Admin/Maintenance Settings and Gating Helper

**Files:**
- Modify: `apps/api/app/config.py`
- Create: `apps/api/app/governance/admin.py`
- Test: `apps/api/tests/governance/test_admin_helpers.py`

- [x] **Step 1: Write RED tests for admin defaults**

  Add tests asserting:

  ```python
  from fastapi import HTTPException

  from app.config import Settings
  from app.governance.admin import require_admin_api_enabled, require_admin_owner
  from app.runtime.models import Principal, WorkspacePermission


  def test_admin_api_disabled_by_default():
      settings = Settings()
      try:
          require_admin_api_enabled(settings)
      except HTTPException as exc:
          assert exc.status_code == 404
          assert exc.detail == "admin api disabled"
      else:
          raise AssertionError("expected admin api disabled")


  def test_admin_requires_owner_role_when_enabled():
      settings = Settings(admin_api_enabled=True)
      principal = Principal(
          principal_id="reader",
          kind="api_key",
          workspace_ids=["ws_1"],
          roles=[WorkspacePermission.reader.value],
      )
      try:
          require_admin_owner(principal, "ws_1", settings)
      except HTTPException as exc:
          assert exc.status_code == 403
          assert exc.detail == "admin owner permission required"
      else:
          raise AssertionError("expected owner permission failure")


  def test_admin_never_allows_anonymous_principal():
      settings = Settings(admin_api_enabled=True, auth_enabled=False, governance_enabled=False)
      principal = Principal(
          principal_id="anonymous",
          kind="anonymous",
          workspace_ids=["*"],
          roles=[WorkspacePermission.owner.value],
      )
      try:
          require_admin_owner(principal, "ws_1", settings)
      except HTTPException as exc:
          assert exc.status_code == 403
          assert exc.detail == "admin owner permission required"
      else:
          raise AssertionError("expected anonymous admin rejection")
  ```

- [x] **Step 2: Add settings**

  Add these fields to `Settings`:

  ```python
  admin_api_enabled: bool = False
  maintenance_default_operations: list[str] = Field(
      default_factory=lambda: [
          "score_memory",
          "conflict_scan",
          "dedup_memory",
          "decay_memory",
          "archive_memory",
          "quarantine_memory",
          "reindex_memory",
          "summary_refresh",
          "procedural_refresh",
          "profile_refresh",
      ]
  )
  maintenance_max_operations_per_run: int = 10
  ```

- [x] **Step 3: Implement admin helpers**

  `governance/admin.py` should expose:

  ```python
  from fastapi import HTTPException, status

  from app.config import Settings
  from app.governance.permissions import has_workspace_permission
  from app.memory.secrets import redact
  from app.runtime.models import Principal, WorkspacePermission


  def require_admin_api_enabled(settings: Settings) -> None:
      if not settings.admin_api_enabled:
          raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="admin api disabled")


  def require_admin_owner(principal: Principal, workspace_id: str, settings: Settings) -> None:
      require_admin_api_enabled(settings)
      if principal.kind == "anonymous":
          raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin owner permission required")
      if not has_workspace_permission(principal, workspace_id, WorkspacePermission.owner):
          raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin owner permission required")


  def redact_admin_metadata(value: object) -> object:
      if isinstance(value, str):
          return redact(value)
      if isinstance(value, list):
          return [redact_admin_metadata(v) for v in value]
      if isinstance(value, dict):
          return {str(k): redact_admin_metadata(v) for k, v in value.items()}
      return value
  ```

- [x] **Step 4: Verify**

  Run: `uv run --extra dev pytest apps/api/tests/governance/test_admin_helpers.py -q`

  Expected: tests pass and no existing auth tests fail.

### Task 2: Scheduler Run / Task Attempt / Admin Audit / Quota Override Storage

**Files:**
- Modify: `apps/api/app/runtime/models.py`
- Modify: `apps/api/app/runtime/repository.py`
- Modify: `apps/api/app/storage/orm.py`
- Modify: `apps/api/app/storage/sql_repository.py`
- Create: `migrations/versions/0012_maintenance_admin_governance.py`
- Test: `apps/api/tests/storage/test_migrations.py`
- Test: `apps/api/tests/memory/test_maintenance_orchestrator.py`

**MADM-A closeout status (2026-06-15):** Task 1 and Task 2 are implemented and re-reviewed. Final hardening requires `require_admin_owner(...)` to accept only persisted per-workspace DB API-key owners (no anonymous, legacy/global, wildcard `workspace_ids=["*"]`, or synthetic API-key principals), `redact_admin_metadata(...)` to redact raw-payload-ref keys as well as values, quota upserts to preserve immutable `(workspace_id, principal_id, unit)` plus `created_by`/`created_at`, and maintenance task-attempt updates to preserve `(scheduler_run_id, workspace_id, operation)` plus `created_at`. Latest verification for this slice: admin helper tests **8 passed**, maintenance repository tests **12 passed**, combined admin+maintenance tests **20 passed**, migration tests **21 passed, 1 skipped**, targeted governance+memory+storage suite **56 passed, 1 skipped**, full pytest **680 passed, 2 skipped**, compileall passed, and `git diff --check` passed.

- [x] **Step 1: Write RED repository tests**

  Test in-memory repository behavior first:

  ```python
  import pytest

  from app.runtime.models import (
      MaintenanceOperation,
      MaintenanceRunRecord,
      MaintenanceTaskAttemptRecord,
      SchedulerRunStatus,
      SchedulerTaskStatus,
      QuotaLimitRecord,
  )
  from app.runtime.repository import InMemoryRepository


  @pytest.mark.asyncio
  async def test_maintenance_run_and_attempt_round_trip():
      repo = InMemoryRepository()
      run = await repo.add_maintenance_run(
          MaintenanceRunRecord(workspace_id="ws_1", operations=[MaintenanceOperation.score_memory])
      )
      attempt = await repo.add_maintenance_task_attempt(
          MaintenanceTaskAttemptRecord(
              scheduler_run_id=run.scheduler_run_id,
              workspace_id="ws_1",
              operation=MaintenanceOperation.score_memory,
              idempotency_key=f"maintenance:{run.scheduler_run_id}:score_memory",
          )
      )
      attempt.status = SchedulerTaskStatus.completed
      attempt.result = {"scored_count": 2}
      await repo.update_maintenance_task_attempt(attempt)
      run.status = SchedulerRunStatus.completed
      await repo.update_maintenance_run(run)

      assert (await repo.get_maintenance_run(run.scheduler_run_id)).status == SchedulerRunStatus.completed
      attempts = await repo.list_maintenance_task_attempts(scheduler_run_id=run.scheduler_run_id)
      assert attempts[0].result == {"scored_count": 2}


  @pytest.mark.asyncio
  async def test_quota_workspace_wide_override_is_unique_when_principal_is_none():
      repo = InMemoryRepository()
      first = await repo.upsert_quota_limit(
          QuotaLimitRecord(
              workspace_id="ws_1",
              principal_id=None,
              unit="write_event",
              limit=1,
              window_seconds=60,
              created_by="admin",
          )
      )
      second = await repo.upsert_quota_limit(
          first.model_copy(update={"limit": 2})
      )
      limits = await repo.list_quota_limits(workspace_id="ws_1", principal_id=None)
      assert len(limits) == 1
      assert limits[0].quota_limit_id == second.quota_limit_id
      assert limits[0].limit == 2
  ```

- [x] **Step 2: Add models and repository protocol methods**

  Add records from §4 plus request/response DTOs used by Task 5/6.

  Repository methods:

  ```python
  async def add_maintenance_run(self, run: MaintenanceRunRecord) -> MaintenanceRunRecord: ...
  async def get_maintenance_run(self, scheduler_run_id: str) -> Optional[MaintenanceRunRecord]: ...
  async def update_maintenance_run(self, run: MaintenanceRunRecord) -> MaintenanceRunRecord: ...
  async def list_maintenance_runs(
      self,
      *,
      workspace_id: Optional[str] = None,
      limit: int = 100,
      offset: int = 0,
  ) -> list[MaintenanceRunRecord]: ...
  async def add_maintenance_task_attempt(self, attempt: MaintenanceTaskAttemptRecord) -> MaintenanceTaskAttemptRecord: ...
  async def update_maintenance_task_attempt(self, attempt: MaintenanceTaskAttemptRecord) -> MaintenanceTaskAttemptRecord: ...
  async def list_maintenance_task_attempts(
      self,
      *,
      scheduler_run_id: str,
      limit: int = 100,
      offset: int = 0,
  ) -> list[MaintenanceTaskAttemptRecord]: ...
  async def add_admin_action_audit(self, audit: AdminActionAuditRecord) -> AdminActionAuditRecord: ...
  async def list_admin_action_audits(
      self,
      *,
      workspace_id: Optional[str] = None,
      limit: int = 100,
      offset: int = 0,
  ) -> list[AdminActionAuditRecord]: ...
  async def upsert_quota_limit(self, limit: QuotaLimitRecord) -> QuotaLimitRecord: ...
  async def list_quota_limits(
      self,
      *,
      workspace_id: str,
      principal_id: Optional[str] = None,
      limit: int = 100,
      offset: int = 0,
  ) -> list[QuotaLimitRecord]: ...
  async def delete_quota_limit(self, quota_limit_id: str) -> None: ...
  ```

  Extend existing list methods touched by admin routes with pagination too: `list_lifecycle_audits(..., limit=100, offset=0)`, `list_api_keys(..., workspace_id: str | None = None, limit=100, offset=0)`, and `list_memory_conflicts(..., limit=100, offset=0)`. Route-level validation must cap `limit <= 500` and require `offset >= 0`.

- [x] **Step 3: Implement in-memory repository**

  Store deep copies, sort `list_maintenance_runs` by `(created_at, scheduler_run_id)`, sort attempts by `(created_at, attempt_id)`, enforce one attempt per `(scheduler_run_id, operation)`, reject duplicate operations in one run, and enforce unique quota limit identity `(workspace_id, principal_id or "*", unit)` by replacing the old record.

- [x] **Step 4: Add ORM and migration**

  Migration `0012_maintenance_admin_governance.py` creates:

  - `maintenance_runs`, indexed by `(workspace_id, created_at)` and `(workspace_id, status, created_at)`;
  - `maintenance_task_attempts`, indexed by `(scheduler_run_id, created_at)` and unique `(scheduler_run_id, operation)`; `idempotency_key` is nullable metadata for Celery retry/idempotency and must not make later maintenance runs collide;
  - `admin_action_audits`, indexed by `(workspace_id, created_at)`;
  - `quota_limits`, indexed by `(workspace_id, unit)`, with two PostgreSQL partial unique indexes:
    - `uq_quota_limits_workspace_unit` on `(workspace_id, unit)` where `principal_id IS NULL`;
    - `uq_quota_limits_workspace_principal_unit` on `(workspace_id, principal_id, unit)` where `principal_id IS NOT NULL`.

  Do not use a normal unique constraint over nullable `(workspace_id, principal_id, unit)` because PostgreSQL allows multiple `NULL` values and would permit duplicate workspace-wide overrides.

  JSONB columns must use explicit server defaults:

  ```python
  sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False)
  sa.Column("warnings", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False)
  ```

- [x] **Step 5: Implement SQL mappings**

  Use `model_dump(mode="json")` for JSON fields and `Model.model_validate(...)` on reads. Never return raw API-key material from SQL mappings.

- [x] **Step 6: Verify**

  Run:

  - `uv run --extra dev pytest apps/api/tests/memory/test_maintenance_orchestrator.py -q`
  - `uv run --extra dev pytest apps/api/tests/storage/test_migrations.py -q`

  Expected: new storage tests pass; migration policy accepts `0012` and all previous migration tests remain green.

### Task 3: Expanded Maintenance Task Functions

**Files:**
- Modify: `apps/api/app/memory/scheduler.py`
- Modify: `apps/api/app/memory/conflicts.py`
- Modify: `apps/api/app/runtime/repository.py`
- Test: `apps/api/tests/memory/test_maintenance_orchestrator.py`

- [x] **Step 1: Write RED direct-function tests for new operations**

  Cover deterministic behavior:

  ```python
  @pytest.mark.asyncio
  async def test_conflict_scan_persists_and_resolves_stale_conflicts(repo_with_conflicting_memories):
      result = await scheduler.conflict_scan(repo_with_conflicting_memories, workspace_id="ws_1")
      assert result["open_conflict_count"] == 1
      # After resolving source conflict by superseding one memory, rerun scan.
      result = await scheduler.conflict_scan(repo_with_conflicting_memories, workspace_id="ws_1")
      assert "stale_resolved_count" in result


  @pytest.mark.asyncio
  async def test_dedup_memory_supersedes_same_value_lower_priority_duplicates(repo_with_duplicate_memories):
      result = await scheduler.dedup_memory(repo_with_duplicate_memories, workspace_id="ws_1")
      assert result["deduped_count"] == 1
      memories = await repo_with_duplicate_memories.list_memories(workspace_id="ws_1")
      assert sum(1 for m in memories if m.status.value == "superseded") == 1
  ```

- [x] **Step 2: Implement `conflict_scan`**

  Use existing `detect_memory_conflicts(...)`, upsert open conflicts, and mark stale open conflicts resolved when their `conflict_id` is not present in the fresh scan. Return:

  ```python
  {
      "workspace_id": workspace_id,
      "open_conflict_count": len(current),
      "created_or_updated_count": upserted,
      "stale_resolved_count": resolved,
      "scheduler_run_id": scheduler_run_id,
  }
  ```

- [x] **Step 3: Implement `dedup_memory`**

  Only auto-deduplicate exact same canonical key + same scope + normalized same value among `active` memories. Never auto-dedup `pinned`, `quarantined`, `conflicted`, secret-sensitive, redaction-managed, or different-value memories. Treat a memory as secret/redaction-managed when `memory.sensitivity == Sensitivity.secret`, `memory.risk_flags.contains_secret`, `memory.redaction_status`-style lifecycle metadata is one of `redacted/digest_only/blocked`, or secret-like metadata keys indicate retained sensitive content. Choose survivor by:

  1. highest `trust_score`,
  2. highest `confidence`,
  3. highest `access_count`,
  4. oldest `created_at`,
  5. lexical `memory_id`.

  Supersede duplicates via `transition_memory_status(..., MemoryStatus.superseded, reason="maintenance_dedup", actor="scheduler")` and set `superseded_by=survivor.memory_id` before `repo.transition_memory_with_audit(...)`. `dry_run=True` must report exact candidate survivor/duplicate pairs and selected reasons without mutating memories or writing lifecycle audits.

- [x] **Step 4: Implement `reindex_memory`**

  First version is deterministic-only and local: recompute `stable_embedding(memory.content, 256)` for memories with `embedding_vector is None` or `embedding_status in {pending, failed, stale}`. It must not call real embedding providers or network APIs. Use `repo.update_memory(...)` so versioning ignores embedding-only changes. Return `reindexed_count`, `skipped_count`, `provider="deterministic_stable_embedding"`, and `provider_backed=False`.

- [x] **Step 5: Implement `summary_refresh`**

  Identify completed runs in the workspace that have events but no existing `MemoryItem` with `memory_type=episodic`, `source_run_id=<run_id>`, and `key="run.summary"`. Do not construct summary memories directly inside the scheduler. Extract a shared helper from `MemoryRuntime.complete_run(...)` that reuses `summarizer.build_run_summary(...)`, `_supersede_run_summary_key(...)`, `_prepare_embedding(...)`, existing redaction/summarizer output, `source_run_id`, and repository version/conflict semantics. The scheduler may call this helper for missing completed runs only; it must not mutate running/failed/cancelled runs. Return `created_summary_count`.

- [x] **Step 6: Implement `procedural_refresh`**

  Identify completed runs that have successful tool/action evidence but no existing `MemoryItem` with `memory_type=procedural`, `source_run_id=<run_id>`, and `key="procedure.learned"`. Reuse the same shared complete-run summary/procedural helper from Step 5 so procedural memories keep the existing summarizer, source provenance, redaction, embedding, supersede, versioning, and conflict behavior. If the helper cannot safely create only missing procedural output without recreating existing summary output, keep this operation preview/report-only in this slice and return `created_procedural_count=0` plus a warning explaining that helper extraction is required before writes.

- [x] **Step 7: Keep `profile_refresh` read-only**

  Existing `profile_refresh` should remain a status-count report and not write profile rows until a separate profile persistence design exists.

- [x] **Step 8: Verify**

  Run: `uv run --extra dev pytest apps/api/tests/memory/test_maintenance_orchestrator.py -q`

  Expected: direct function tests pass with no Celery/Redis/Postgres.

### Task 4: Maintenance Orchestrator and Celery Wrapper Integration

**Files:**
- Create: `apps/api/app/memory/maintenance.py`
- Modify: `apps/api/app/async_tasks/tasks.py`
- Test: `apps/api/tests/memory/test_maintenance_orchestrator.py`
- Test: `apps/api/tests/async_tasks/test_celery_eager.py`

- [x] **Step 1: Write RED orchestrator tests**

  Assert ordered execution, dry-run, attempt records, failure isolation, and summary aggregation:

  ```python
  @pytest.mark.asyncio
  async def test_run_workspace_maintenance_records_attempts_and_summary(repo_with_memories):
      run = await run_workspace_maintenance(
          repo_with_memories,
          workspace_id="ws_1",
          operations=[MaintenanceOperation.score_memory, MaintenanceOperation.conflict_scan],
          requested_by="admin:alice",
          dry_run=False,
      )
      assert run.status == SchedulerRunStatus.completed
      attempts = await repo_with_memories.list_maintenance_task_attempts(
          scheduler_run_id=run.scheduler_run_id
      )
      assert [a.operation for a in attempts] == [
          MaintenanceOperation.score_memory,
          MaintenanceOperation.conflict_scan,
      ]
      assert run.summary["completed_count"] == 2
  ```

  Add tests that duplicate operations are rejected before any mutation:

  ```python
  with pytest.raises(ValueError, match="duplicate maintenance operation"):
      await run_workspace_maintenance(
          repo_with_memories,
          workspace_id="ws_1",
          operations=[MaintenanceOperation.score_memory, MaintenanceOperation.score_memory],
          requested_by="admin:alice",
      )
  ```

- [x] **Step 2: Implement operation registry**

  `maintenance.py` should define:

  ```python
  OPERATION_HANDLERS: dict[MaintenanceOperation, Callable[..., Awaitable[dict[str, Any]]]] = {
      MaintenanceOperation.score_memory: scheduler.score_memory,
      MaintenanceOperation.decay_memory: scheduler.decay_memory,
      MaintenanceOperation.archive_memory: scheduler.archive_memory,
      MaintenanceOperation.quarantine_memory: scheduler.quarantine_memory,
      MaintenanceOperation.conflict_scan: scheduler.conflict_scan,
      MaintenanceOperation.dedup_memory: scheduler.dedup_memory,
      MaintenanceOperation.reindex_memory: scheduler.reindex_memory,
      MaintenanceOperation.summary_refresh: scheduler.summary_refresh,
      MaintenanceOperation.procedural_refresh: scheduler.procedural_refresh,
      MaintenanceOperation.profile_refresh: scheduler.profile_refresh,
  }
  ```

- [x] **Step 3: Implement dry-run semantics**

  Dry-run records a `MaintenanceRunRecord` and `MaintenanceTaskAttemptRecord`s with `status=skipped` and a preview result containing `operation`, `workspace_id`, and reason `dry_run`; it must not call handlers or mutate memories/conflicts/signals.

- [x] **Step 4: Implement run orchestration**

  `run_workspace_maintenance(...)` validates non-empty operations, rejects duplicates in the same run, creates a run, executes operations in supplied order, updates each attempt, catches per-operation exceptions into redacted/capped `error_summary`, continues to later operations, and marks the run `failed` only if at least one operation failed; otherwise `completed`. `idempotency_key` should be `maintenance:{scheduler_run_id}:{operation}` so retries for the same run/operation are identifiable without colliding across later runs.

- [x] **Step 5: Update Celery maintenance wrapper**

  Replace the five-operation local handler map in `async_tasks/tasks.py` with a call to `run_workspace_maintenance(...)` for either a single `operation` payload or an `operations` list. Preserve existing duplicate/idempotency behavior and release existing Celery task-envelope idempotency locks on exceptions.

  Admin `enqueue=true` must fail with HTTP 400 when `settings.async_tasks_enabled` is false or no Celery enqueue function is configured; do not return a fake queued result.

- [x] **Step 6: Verify**

  Run:

  - `uv run --extra dev pytest apps/api/tests/memory/test_maintenance_orchestrator.py -q`
  - `uv run --extra dev pytest apps/api/tests/async_tasks/test_celery_eager.py -q`

  Expected: all pass; existing Celery eager tests still pass without Redis.

### Task 5: Admin Maintenance Routes

**Files:**
- Create: `apps/api/app/api/admin_routes.py`
- Modify: `apps/api/app/api/routes.py` or the app router registration point
- Modify: `apps/api/app/runtime/models.py`
- Test: `apps/api/tests/api/test_admin_maintenance.py`

- [x] **Step 1: Write RED API tests**

  Cover disabled-by-default, owner auth, dry-run, start/get/list:

  ```python
  async def test_admin_maintenance_disabled_by_default(async_client):
      response = await async_client.post(
          "/v1/admin/maintenance/runs",
          json={"workspace_id": "ws_1", "operations": ["score_memory"]},
      )
      assert response.status_code == 404
      assert response.json()["detail"] == "admin api disabled"


  async def test_owner_can_start_dry_run_maintenance(async_client_with_owner_key):
      response = await async_client_with_owner_key.post(
          "/v1/admin/maintenance/runs",
          json={
              "workspace_id": "ws_1",
              "operations": ["score_memory", "conflict_scan"],
              "dry_run": True,
              "reason": "operator preview",
          },
      )
      assert response.status_code == 200
      body = response.json()
      assert body["dry_run"] is True
      assert body["status"] == "completed"
  ```

- [x] **Step 2: Add request DTOs**

  Add:

  ```python
  class StartMaintenanceRunRequest(_Base):
      workspace_id: str
      operations: list[MaintenanceOperation] | None = None
      dry_run: bool = False
      reason: str | None = None
      enqueue: bool = False
  ```

  `operations=None` means use `settings.maintenance_default_operations` after validating every configured name maps to `MaintenanceOperation`.

- [x] **Step 3: Implement routes**

  Routes:

  - `POST /v1/admin/maintenance/runs` — owner-gated; direct-run when `enqueue=false`; Celery enqueue when `enqueue=true` and async tasks enabled; returns `MaintenanceRunRecord`.
  - `GET /v1/admin/maintenance/runs?workspace_id=...&limit=100&offset=0` — owner-gated paginated list.
  - `GET /v1/admin/maintenance/runs/{scheduler_run_id}` — owner-gated by run workspace; returns run + attempts if response model includes attempts, otherwise add `GET /attempts?limit=100&offset=0`.
  - `GET /v1/admin/lifecycle-audits?workspace_id=...&memory_id=...&limit=100&offset=0` — owner-gated paginated list of existing lifecycle audits.

  Validate `1 <= limit <= 500` and `offset >= 0` on all admin list routes.

- [x] **Step 4: Quota and audit**

  Starting a maintenance run should consume `QuotaUnit.report_export` only if `quota_enabled` is true and governance is enabled; this avoids inventing a new quota unit in this slice. Add an `AdminActionAuditRecord` for every start request with redacted reason/metadata.

- [x] **Step 5: Verify**

  Run: `uv run --extra dev pytest apps/api/tests/api/test_admin_maintenance.py -q`

  Expected: admin maintenance API tests pass and disabled-default route is unreachable.

  **MADM-C status (2026-06-15):** Task 5 complete and review-hardened. `apps/api/app/api/admin_routes.py` adds the default-off owner-gated `/v1/admin` router with `POST /maintenance/runs`, `GET /maintenance/runs`, `GET /maintenance/runs/{id}`, `GET /maintenance/runs/{id}/attempts`, and `GET /lifecycle-audits`. `StartMaintenanceRunRequest` added to `runtime/models.py`; `operations=None` falls back to `settings.maintenance_default_operations`. `enqueue=true` requires `async_tasks_enabled` and a configured Celery maintenance enqueue (wired in `deps.py` as `get_maintenance_enqueue`), otherwise HTTP 400. Quota goes through the standard `QuotaService.check(..., QuotaUnit.report_export)` so the service decides based on its own settings; every start records a redacted `AdminActionAuditRecord`. Router registered in `main.py`. Pagination validated via FastAPI `Query(ge=1, le=500)` / `Query(ge=0)`. **Detailed-review hardening fixed two real defects before closeout:** (1) the enqueue path skipped empty/duplicate/unknown-operation validation that the direct-run path enforced, so duplicate operations returned HTTP 200 + an orphan run record while the worker would later fail — both paths now share `maintenance.validate_operations(...)` before they fork and reject identically with HTTP 400; (2) the enqueue path persisted/returned raw `reason`/`requested_by` while the direct-run orchestrator redacted them, allowing secret/destructive markers to be stored and read back through the admin list/get routes — the enqueue path now reuses `maintenance.redacted_run_text(...)` for both the persisted `MaintenanceRunRecord` and the `TaskEnvelope` payload. Verification: `apps/api/tests/api/test_admin_maintenance.py` -> **14 passed** (incl. duplicate-rejection and enqueue-redaction regressions); admin/orchestrator/celery suite -> **53 passed**; full `uv run --extra dev pytest -q` -> **712 passed, 2 skipped**; `bash scripts/reproduce.sh` -> `acceptance.passed=true (13/13 checks true)`; `git diff --check` clean.

### Task 6: API Key Administration

**Files:**
- Modify: `apps/api/app/governance/admin.py`
- Modify: `apps/api/app/api/admin_routes.py`
- Modify: `apps/api/app/runtime/models.py`
- Modify: `apps/api/app/runtime/repository.py`
- Modify: `apps/api/app/storage/sql_repository.py`
- Test: `apps/api/tests/api/test_admin_governance.py`

- [x] **Step 1: Write RED API-key admin tests**

  Cover one-time raw-key return, list redaction, revoke, and legacy fallback disable.
  Also cover role/workspace constraints: roles must be non-empty valid workspace roles, owner-created keys are bound to exactly one explicit workspace, wildcard/global keys cannot be created through this API, and revoking an already revoked key is idempotent.

- [x] **Step 2: Add DTOs**

  ```python
  class CreateApiKeyRequest(_Base):
      workspace_id: str
      principal_id: str
      roles: list[WorkspacePermission]


  class CreatedApiKeyResponse(_Base):
      api_key: ApiKeyRecord
      raw_api_key: str
  ```

  Existing `ApiKeyRecord` contains `key_digest`, so public admin APIs must not return it directly. Add a public response DTO such as:

  ```python
  class PublicApiKey(_Base):
      api_key_id: str
      workspace_id: str
      principal_id: str
      key_prefix: str
      roles: list[str]
      created_at: datetime
      last_used_at: datetime | None = None
      revoked_at: datetime | None = None
  ```

  `CreatedApiKeyResponse.api_key` should use `PublicApiKey`, not `ApiKeyRecord`.

- [x] **Step 3: Implement raw key generation**

  Generate keys with `secrets.token_urlsafe(32)` and prefix them as `mtk_`. Persist via existing `create_api_key_record(...)`. Return raw key only from create response. Store only prefix+digest.

- [x] **Step 4: Implement routes**

  Routes:

  - `POST /v1/admin/api-keys` — owner-gated for `workspace_id`.
  - `GET /v1/admin/api-keys?workspace_id=...&limit=100&offset=0` — owner-gated, redacted public list.
  - `POST /v1/admin/api-keys/{api_key_id}/revoke` — owner-gated by key workspace.

  Repository needs `get_api_key(api_key_id)` and `revoke_api_key(api_key_id, revoked_at)` if not already present.

  Validate `roles` against `WorkspacePermission`; reject empty roles; reject attempts to create wildcard/global workspace keys (`workspace_id="*"` or multiple workspace ids) through this workspace-owner API. Creating an owner role is allowed only because the current principal is already owner of the same explicit workspace.

- [x] **Step 5: Audit**

  Add `AdminActionAuditRecord` for create/revoke with target `api_key_id`, never raw key or digest.

- [x] **Step 6: Verify**

  Run: `uv run --extra dev pytest apps/api/tests/api/test_admin_governance.py -q`

  Expected: raw key appears only once in create response and never in list/audit/log-style metadata.

### Task 7: Quota Override Administration

**Files:**
- Modify: `apps/api/app/governance/quota.py`
- Modify: `apps/api/app/api/admin_routes.py`
- Modify: `apps/api/app/runtime/models.py`
- Modify: `apps/api/app/runtime/repository.py`
- Modify: `apps/api/app/storage/sql_repository.py`
- Test: `apps/api/tests/governance/test_quota.py`
- Test: `apps/api/tests/api/test_admin_governance.py`

- [x] **Step 1: Write RED quota override tests**

  Assert workspace/principal override beats settings default and deletion falls back to settings:

  ```python
  @pytest.mark.asyncio
  async def test_quota_service_uses_workspace_principal_override(repo, settings):
      await repo.upsert_quota_limit(
          QuotaLimitRecord(
              workspace_id="ws_1",
              principal_id="alice",
              unit="write_event",
              limit=1,
              window_seconds=60,
              created_by="admin",
          )
      )
      service = QuotaService(InMemoryQuotaCounter(), settings, repo=repo)
      principal = Principal(principal_id="alice", kind="api_key", workspace_ids=["ws_1"], roles=["writer"])
      await service.check(principal, "ws_1", QuotaUnit.write_event)
      with pytest.raises(HTTPException) as exc:
          await service.check(principal, "ws_1", QuotaUnit.write_event)
      assert exc.value.status_code == 429
  ```

- [x] **Step 2: Extend QuotaService**

  Accept optional `repo: Repository | None`. Lookup order:

  1. `(workspace_id, principal_id, unit)` override;
  2. `(workspace_id, None, unit)` workspace-wide override;
  3. settings default.

  Keep existing no-repo behavior unchanged for unit tests and default app setup. Override lookup is only allowed inside `QuotaService.check(...)` after `settings.quota_enabled` is true; enabling `admin_api_enabled` or `governance_enabled` alone must not make hot runtime routes perform quota override DB lookups.

- [x] **Step 3: Implement admin routes**

  Routes:

  - `GET /v1/admin/quota-limits?workspace_id=...&limit=100&offset=0`;
  - `PUT /v1/admin/quota-limits` with `workspace_id`, optional `principal_id`, `unit`, `limit`, `window_seconds`;
  - `DELETE /v1/admin/quota-limits/{quota_limit_id}`.

  Validate `limit >= 0`, `window_seconds >= 1`, and known quota unit. Document and test that `limit=0` means block all requests for that unit/window; this slice does not add an unlimited flag.

- [x] **Step 4: Wire `get_quota_service`**

  Pass repository into `QuotaService` only when `quota_enabled=True`; never because `admin_api_enabled=True` by itself. If override lookup fails and `quota_enabled=True` plus `governance_enabled=True`, fail closed with 503; if `quota_enabled=False`, return before any repository lookup.

- [x] **Step 5: Verify**

  Run:

  - `uv run --extra dev pytest apps/api/tests/governance/test_quota.py -q`
  - `uv run --extra dev pytest apps/api/tests/api/test_admin_governance.py -q`

### Task 8: Manual Lifecycle and Conflict Resolution Administration

**Files:**
- Modify: `apps/api/app/api/admin_routes.py`
- Modify: `apps/api/app/runtime/models.py`
- Modify: `apps/api/app/runtime/repository.py`
- Modify: `apps/api/app/storage/sql_repository.py`
- Test: `apps/api/tests/api/test_admin_governance.py`
- Test: `apps/api/tests/memory/test_lifecycle.py`
- Test: `apps/api/tests/memory/test_conflicts.py`

- [x] **Step 1: Write RED manual lifecycle tests**

  Cover pin, unpin, archive, quarantine, delete, and forbidden unsafe transitions. Assert lifecycle audit actor is `admin:<principal_id>`.

- [x] **Step 2: Implement route `POST /v1/admin/memories/{memory_id}/status`**

  Request:

  ```python
  class AdminMemoryStatusRequest(_Base):
      to_status: MemoryStatus
      reason: str
  ```

  Flow:

  1. Resolve memory by `memory_id`; 404 if missing.
  2. Owner-gate on memory workspace.
  3. Use `transition_memory_status(memory, req.to_status, reason=req.reason, actor=f"admin:{principal.principal_id}")`.
  4. Persist with `repo.transition_memory_with_audit(...)`.
  5. Add `AdminActionAuditRecord`.

- [x] **Step 3: Write RED conflict resolution tests**

  Cases:

  - mark conflict false positive;
  - choose winner and supersede losers;
  - conflict workspace authz enforced;
  - resolved conflict is not returned in `status=open` list.

- [x] **Step 4: Add repository helpers for conflicts**

  Add `get_memory_conflict(conflict_id)` and `update_memory_conflict(conflict)` if missing. SQL update must preserve `created_at` and set `resolved_at` for resolved statuses.

- [x] **Step 5: Implement route `POST /v1/admin/memory-conflicts/{conflict_id}/resolve`**

  Request:

  ```python
  class ResolveMemoryConflictRequest(_Base):
      action: Literal["mark_false_positive", "choose_winner"]
      winner_memory_id: str | None = None
      reason: str
  ```

  For `choose_winner`, `winner_memory_id` is required, must belong to `conflict.memory_ids`, and must resolve to the same workspace as the conflict. All loser memory ids in the conflict record must be transitioned to `superseded` with `superseded_by=winner_memory_id`. Use lifecycle audit and versioning. For `mark_false_positive`, only update the conflict status to `resolved_false_positive`. Both paths add admin audit. Do not implement merge/edit/manual rewrite in this slice.

- [x] **Step 6: Verify**

  Run:

  - `uv run --extra dev pytest apps/api/tests/api/test_admin_governance.py -q`
  - `uv run --extra dev pytest apps/api/tests/memory/test_lifecycle.py apps/api/tests/memory/test_conflicts.py -q`

**MADM-D status (2026-06-15):** Tasks 6-8 complete and review-hardened. Task 6 added `generate_api_key(...)` (`mtk_` + `secrets.token_urlsafe(32)`, digest+prefix only, salted with `settings.api_key_digest_salt` so created keys authenticate), `to_public_api_key(...)`, `CreateApiKeyRequest`/`PublicApiKey`/`CreatedApiKeyResponse` DTOs, and owner-gated `POST/GET /v1/admin/api-keys` + `POST /v1/admin/api-keys/{id}/revoke` with empty-role/wildcard rejection, redacted list (no digest), one-time raw key, idempotent revoke, and redacted audits. Task 7 extended `QuotaService` with optional `repo` override lookup (principal -> workspace-wide -> settings default, fail-closed under governance), wired `get_quota_service` to pass the repo only when `quota_enabled` (admin/governance alone never trigger hot-path DB reads), and added owner-gated `GET/PUT/DELETE /v1/admin/quota-limits` with `limit>=0`/`window_seconds>=1` validation plus a `get_quota_limit(...)` repo helper for workspace-scoped delete authz. Task 8 added `AdminMemoryStatusRequest`/`ResolveMemoryConflictRequest` DTOs, `get_memory_conflict`/`update_memory_conflict`/`get_api_key`/`revoke_api_key` repo helpers (in-memory + SQL, identity/created_at preserved, resolved_at set), `POST /v1/admin/memories/{id}/status` (lifecycle transition + audit, actor `admin:<principal>`), and `POST /v1/admin/memory-conflicts/{id}/resolve` (mark_false_positive / choose_winner with member+workspace winner validation and loser supersede). **Review hardening fixed four real defects:** (1) `conflicted -> superseded` was illegal in the lifecycle matrix, but real conflict_scan conflicts commonly contain conflicted members (resolver tie), so choose_winner would fail on them — added `conflicted: {superseded}` to `_MAINLINE` as the legitimate adjudication exit; (2) the choose_winner loser loop persisted each supersede independently, so a mid-loop illegal transition left some losers superseded while the conflict stayed open — losers are now pre-validated before any persistence to minimize the partial-state window; (3) `admin_resolve_memory_conflict` never checked `conflict.status`, so a resolved conflict could be re-resolved (e.g. flip `resolved_false_positive -> choose_winner` and supersede memories the first decision kept) — non-open conflicts now return HTTP 409 (conflict_scan stale resolution only touches open conflicts, so this is safe); (4) `upsert_quota_limit` picked an upsert "base" by `(workspace, principal)` only, so a second unit for the same principal could reuse a different unit's row id and trip the repository identity guard (HTTP 500) — the route now always hands a fresh record and lets the repository merge by `(workspace, principal, unit)`. Verification: `apps/api/tests/api/test_admin_governance.py` -> **24 passed**, `apps/api/tests/governance/test_quota.py` -> **6 passed**, affected api/governance/memory/storage suite, full `uv run --extra dev pytest -q` -> **733 passed, 2 skipped**, `bash scripts/reproduce.sh` -> `acceptance.passed=true (13/13 checks true)`, `git diff --check` clean. SDK admin facade (Task 10) deliberately deferred per plan recommendation; Task 9 observability surfacing and Task 11 closeout remain for MADM-E.

### Task 9: Dashboard / Reports / Telemetry-Safe Admin Observability

**Files:**
- Modify: `apps/api/app/observability/metrics.py`
- Modify: `apps/api/app/observability/reports.py`
- Modify: `apps/api/app/api/routes.py` or dashboard table builder
- Test: `apps/api/tests/api/test_dashboard.py`
- Test: `apps/api/tests/observability/test_reports.py`

- [x] **Step 1: Write RED observability tests**

  Assert dashboard tables include `maintenance_runs`, `maintenance_task_attempts`, `admin_action_audits`, and `quota_limits` only for the requested workspace and with redacted metadata.

- [x] **Step 2: Add dashboard table rows**

  Extend `DashboardTables` only if it already supports flexible row groups; otherwise add fields conservatively:

  ```python
  maintenance_runs: list[dict[str, Any]] = Field(default_factory=list)
  maintenance_task_attempts: list[dict[str, Any]] = Field(default_factory=list)
  admin_action_audits: list[dict[str, Any]] = Field(default_factory=list)
  quota_limits: list[dict[str, Any]] = Field(default_factory=list)
  ```

- [x] **Step 3: Add report summary**

  Observability report should include counts by maintenance status and recent failed attempts, but not raw stack traces. Use `error_summary` already redacted by the orchestrator.

- [x] **Step 4: Verify**

  Run:

  - `uv run --extra dev pytest apps/api/tests/api/test_dashboard.py -q`
  - `uv run --extra dev pytest apps/api/tests/observability -q`

### Task 10: Python SDK / CLI Boundary Decision

**Files:**
- Option A modify: `packages/python-sdk/src/memtrace_sdk/types.py`, `packages/python-sdk/src/memtrace_sdk/backends.py`, `packages/python-sdk/tests/test_http_backend.py`
- Option B docs only: `README.md`, `docs/deployment.md`

**Recommendation:** Do not add a broad SDK admin facade in the first implementation pass. Admin endpoints are operator-only, default-off, and likely to evolve. Keep the first surface HTTP-only plus docs/curl examples. Add SDK methods later only after route shapes stabilize.

- [x] **Step 1: Lock the decision in the plan execution notes**

  If implementing team agrees with the recommendation, add no SDK code in this slice and document HTTP-only admin APIs.

  **Decision (2026-06-15):** Adopted the recommendation. No SDK admin facade is added in this slice; admin APIs stay HTTP-only and are documented in `docs/deployment.md` with curl examples. SDK methods can be added later only after route shapes stabilize.

- [ ] **Step 2: If SDK is required, add only typed DTO re-exports and minimal `request(...)` escape hatch**

  Avoid duplicating every admin route in the SDK until adoption proves demand. (Not done — deliberately deferred per the Step 1 docs-only decision.)

### Task 11: Closeout Documentation and Project Memory Sync

**Files:**
- Modify: `docs/design/ROADMAP.md`
- Modify: `.ai/PROJECT_STATE.md`
- Modify: `.ai/REQUIREMENTS.md`
- Modify: `.ai/IMPLEMENTATION_PLAN.md`
- Modify: `.ai/OPEN_QUESTIONS.md`
- Modify: `.ai/PITFALLS.md`
- Modify: `README.md`
- Modify: `docs/deployment.md`

- [x] **Step 1: Update ROADMAP**

  Mark the selected target as `Maintenance Scheduler / Admin Governance Depth`, reference this plan, and keep Phase 3-B dashboard / advanced storage / dedicated IDE as future candidates.

- [x] **Step 2: Update user docs**

  Document:

  - admin APIs are default-off;
  - required env flags: `MEMTRACE_ADMIN_API_ENABLED=true`, auth/governance recommendations, and owner API key;
  - maintenance run examples using HTTP/curl;
  - no frontend UI yet.

- [x] **Step 3: Update `.ai` project memory**

  `.ai/PROJECT_STATE.md` should state this plan is the selected next target until completed. `.ai/REQUIREMENTS.md` should include non-goals/default-off/admin-owner constraints. `.ai/IMPLEMENTATION_PLAN.md` should list Task 1 as the next coding task. `.ai/PITFALLS.md` should capture admin/scheduler traps from this plan.

- [x] **Step 4: Verification closeout**

  Run:

  - `uv run --extra dev pytest apps/api/tests/memory/test_maintenance_orchestrator.py apps/api/tests/governance apps/api/tests/api/test_admin_maintenance.py apps/api/tests/api/test_admin_governance.py -q`
  - `uv run --extra dev pytest apps/api/tests/storage/test_migrations.py -q`
  - `uv run --extra dev python -m compileall -q apps/api/app packages/python-sdk/src examples`
  - `uv run --extra dev pytest -q`
  - `uv run python -m app.benchmark.runner --output-dir reports`
  - `bash scripts/reproduce.sh`
  - `bash scripts/check-release-hygiene.sh`
  - `git diff --check`

  Expected final state: full regression passes, benchmark/reproduce remains `acceptance.passed=true (13/13 checks true)`, release hygiene passes, and no generated reports/artifacts are tracked.

---

## 6. Suggested Execution Slices

1. **MADM-A — foundations:** Tasks 1-2. Adds settings, admin helper, records, migration, repository methods. No route exposure beyond tests.
2. **MADM-B — maintenance engine:** Tasks 3-4. Completes task family and orchestrator/Celery wrapper. No admin writes yet.
3. **MADM-C — admin maintenance API:** Task 5. Adds default-off owner-gated maintenance routes.
4. **MADM-D1 — API key + quota admin:** Tasks 6-7. Adds API key and quota override administration with a dedicated review point.
5. **MADM-D2 — lifecycle + conflict admin:** Task 8. Adds manual lifecycle and conflict resolution administration with a dedicated review point.
6. **MADM-E — observability and closeout:** Tasks 9-11. Adds dashboard/report surfacing, docs, ROADMAP/`.ai`, and full verification.

Each slice should finish with targeted tests and `git diff --check`. Run full regression after MADM-B, MADM-D, and MADM-E.

**MADM-B status (2026-06-15):** Tasks 3-4 are complete and fully re-reviewed. Final hardening covers failed Celery run result propagation + dedupe-key release, raw dedup value removal, maintenance-only conflict stale resolution, superseded/deleted run-memory rebuilds, paginated stale-conflict resolution, secret-like dedup key skipping, legacy same-key summary/procedure replacement, run-level redaction, authorization-like free-form admin string redaction, and maintenance-run identity/creation immutability. Verification: `uv run --extra dev pytest apps/api/tests/memory/test_maintenance_orchestrator.py -q` -> **28 passed**; `uv run --extra dev pytest apps/api/tests/async_tasks/test_celery_eager.py -q` -> **11 passed**; `uv run --extra dev pytest apps/api/tests/governance/test_admin_helpers.py -q` -> **8 passed**; affected suite -> **95 passed, 1 skipped**; `uv run --extra dev python -m compileall -q apps/api/app`, full `uv run --extra dev pytest -q` -> **698 passed, 2 skipped**, `bash scripts/reproduce.sh` -> `acceptance.passed=true (13/13 checks true)`, and `git diff --check` passed. Next slice is MADM-C admin maintenance API.

## 7. Test Strategy

- **Unit:** admin helper gating/redaction; maintenance operation direct functions; dedup survivor selection; conflict stale resolution; quota override resolution.
- **Repository:** in-memory and SQL mapping parity for maintenance runs, task attempts, admin audits, quota limits, API-key revoke helpers, conflict updates.
- **API:** default-off admin 404, owner-gated 403, enabled success paths, workspace isolation, no raw keys in list/audit, route error mapping.
- **Governance regression:** existing auth/quota/redaction tests must continue passing.
- **Observability:** dashboard/report rows are workspace-scoped and redacted.
- **Full regression:** no changes to benchmark/reproduce acceptance, release hygiene, telemetry default-off behavior, or MCP/SDK package shape unless explicitly touched.

## 8. Risks and Mitigations

- **Risk: admin routes accidentally exposed in no-auth local/hosted mode.** Mitigation: `admin_api_enabled` default false and tests assert 404 by default; owner requirement blocks non-owner principals when enabled.
- **Risk: scheduler mutates memories too aggressively.** Mitigation: automatic `dedup_memory` only supersedes exact same canonical key/scope/value and never touches pinned/quarantined/conflicted/secret/different-value memories; conflict resolution requires admin action.
- **Risk: maintenance reindex calls external providers and breaks reproducibility.** Mitigation: first reindex implementation is deterministic-only; provider-backed reindex remains future work.
- **Risk: raw secrets leak through audits/errors.** Mitigation: redacted metadata helper, generic error summaries, no raw API key storage, tests scan admin outputs for secret/destructive markers.
- **Risk: `routes.py` becomes too large.** Mitigation: put admin routes in `api/admin_routes.py` and only register the router from existing API setup.
- **Risk: quota override lookup makes hot routes depend on DB on every request.** Mitigation: keep `QuotaService` no-repo behavior for defaults; add repository lookup only when quota override support is enabled and tested. Future caching can be a separate optimization.

## 9. Acceptance Criteria

- A maintainer can enable `MEMTRACE_ADMIN_API_ENABLED=true`, authenticate as workspace owner, start a dry-run or real maintenance run, and inspect durable run/attempt results.
- The first-wave maintenance task family has ten direct async operations and one orchestrator path shared by direct/admin/Celery execution.
- Admin users can create/list/revoke API keys without raw key persistence, configure quota overrides, perform manual lifecycle transitions, and resolve conflicts.
- Admin/maintenance/dashboard/report outputs are workspace-scoped and redacted.
- Defaults remain unchanged: admin API disabled, auth/governance/quota still default-off, no Redis/Celery/network provider required.
- Full closeout verification passes, including benchmark/reproduce `13/13` and release hygiene.

---

## MADM-E status (2026-06-15): complete

Tasks 9-11 complete; the slice is fully implemented and review-hardened.

- **Task 9 (dashboard/report admin observability):** `DashboardTables` now carries `maintenance_runs`, `maintenance_task_attempts`, `admin_action_audits`, and `quota_limits`. `MemoryRuntime.dashboard_tables(...)` populates them workspace-scoped; quota overrides are listed via a new `list_quota_limits(..., all_principals=True)` repo flag (default-off so the quota override-lookup path keeps exact principal/None matching) and only surfaced when a workspace is requested. The observability report payload (JSON + Markdown) gained a `maintenance` section with run-count, runs-by-status, and recent failed attempts using the orchestrator's already-redacted `error_summary` (no raw stack traces). Records are redacted at write time, so dashboard/report reads carry no raw secrets. **Detailed-review hardening fixed one real authorization defect:** the admin governance tables were initially populated for any `report_reader` (and, with auth off, anonymous) dashboard caller, and were even returned cross-workspace when `workspace_id` was omitted — violating the owner-gated/default-off invariant. `MemoryRuntime.dashboard_tables(..., include_admin=False)` now gates those four tables, and the route only sets `include_admin=True` when `require_admin_owner(...)` passes for the requested workspace (admin API enabled + real workspace owner). report-reader / anonymous / unscoped callers now get empty admin tables. The report `maintenance` summary stays report-reader-level because it exposes only aggregate counts + redacted error summaries (no principal ids / audit metadata).
- **Task 10 (SDK/CLI boundary):** Adopted the docs-only recommendation. No SDK admin facade was added; admin APIs stay HTTP-only and are documented with curl examples.
- **Task 11 (docs/ROADMAP/`.ai` closeout):** `docs/deployment.md` adds an "Admin governance API (operator-only, default-off)" section (env flags, owner-key curl examples, enqueue/audit/409 semantics, no UI/SDK). `docs/design/ROADMAP.md` §3.2 marks MADM-A/B/C/D/E complete. `.ai/PROJECT_STATE.md`, `.ai/IMPLEMENTATION_PLAN.md`, and `.ai/OPEN_QUESTIONS.md` are synced.
- **Verification:** dashboard/report/quota targeted suite **25 passed**; full `uv run --extra dev pytest -q` green; `bash scripts/reproduce.sh` -> `acceptance.passed=true (13/13 checks true)`; release hygiene + `git diff --check` clean.
