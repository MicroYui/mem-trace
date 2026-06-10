# Phase 3-A Implementation Plan: Retrieval Replay & Observability

> **For agentic workers:** REQUIRED SUB-SKILL: use `subagent-driven-development` (recommended) or `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Progress tracking rule:** after completing each Issue in §11, update `.ai/PROJECT_STATE.md` and tick or annotate the corresponding `ROADMAP.md` checkbox/sub-checkbox. Do not leave implementation progress only in chat history.

**Goal:** make every retrieval decision reproducible and inspectable: replay a past access/run, explain candidate selection -> gate -> packing, persist eval results, surface quality/safety metrics, and emit a minimal static observability report.

**Architecture:** refactor retrieval into a side-effect-free traceable pipeline used by both hot-path retrieval and replay. Replay loads persisted access/gate/profile evidence, re-runs the same deterministic pipeline without writing logs or bumping memory access counters, and returns a structured diff between the original access and the replayed result. Observability metrics are computed from persisted access/gate/profile records plus replay traces; generated reports remain reproducible artifacts under `reports/`.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2.0 async, Alembic, PostgreSQL/pgvector, pytest + httpx ASGI tests.

***

## 1. Goal

Phase 3-A upgrades MemTrace from “benchmark/demo succeeded once” to “retrieval behavior is explainable, replayable, and measurable after the fact”.

The implemented system should answer these questions for any recorded retrieval access:

1. **What was the original request?** Query, run, step, strategy, token budget, top-k, task intent, and workspace.
2. **Which candidates were considered?** Candidate memory IDs, content summary, lifecycle/branch/risk status, lexical/vector/relevance scores, and order.
3. **Why did the gate accept or reject each candidate?** Layer, decision, reject reason, component scores, final score, and warnings.
4. **What context was packed?** Ordered context blocks, token usage, provenance, and dropped/omitted accepted memories if any.
5. **Can we replay the decision now?** Re-run retrieval/gate/packing with the same request parameters and current repository state, without side effects.
6. **What drifted?** Candidate set, scores, gate decisions, accepted memories, packed block order/content, token usage, warnings, and profile phase counts.
7. **What quality/safety signals were observed?** Failed-branch contamination, stale injection, tool-sensitive blocking, destructive-command blocking, workspace leakage, superseded injection, and packing over-budget drops.
8. **Can we inspect this without a frontend?** JSON API plus generated Markdown/HTML report.

Primary source in `ROADMAP.md`:

- Phase 3-A: Retrieval Replay, eval tables, Quality/Safety profiler, phase-aware profiler, minimal static dashboard/report.

Existing code to preserve:

- `apps/api/app/retrieval/controller.py` currently performs candidate selection, gate, packing, logging, and access-count updates in one method.
- `apps/api/app/runtime/memory_runtime.py` exposes `retrieve_context`, `inspect_access`, `dashboard_tables`, and read helpers.
- `apps/api/app/runtime/models.py` already has `MemoryAccessLog`, `MemoryGateLog`, `ProfileEvent`, `AccessInspection`, and `DashboardTables`.
- `apps/api/app/storage/orm.py` / `sql_repository.py` already persist access/gate/profile and benchmark tables.

## 2. Scope / Non-goals

### In scope

1. **Retrieval Replay APIs**
   - `GET /v1/replay/access/{access_id}`: replay one retrieval access.
   - `GET /v1/replay/runs/{run_id}`: replay all retrieval accesses for a run.
2. **Side-effect-free replay service**
   - Reuses the same scoring/gate/packing logic as hot-path retrieval.
   - Does not create new `memory_access_logs`, `memory_gate_logs`, or `profile_events`.
   - Does not increment `MemoryItem.access_count`.
   - Does not flush buffered extraction; replay reflects the persisted state at replay time.
3. **Pipeline trace model**
   - Captures candidates, gate outcomes, accepted order, packed blocks, warnings, token usage, and profile-like phase summaries.
   - Hot path converts trace -> persisted logs -> `MemoryContext`.
   - Replay converts trace -> replay result/diff.
4. **Access log fidelity improvements**
   - Persist request `top_k` in `MemoryAccessLog` / SQL table so replay can reconstruct the original request exactly.
   - Preserve backwards compatibility by defaulting missing historical `top_k` to current `RetrievalRequest.top_k` default (`10`). The value **must be 10 everywhere**: Pydantic default, API request default, DB default, Alembic server default/backfill, and replay fallback.
5. **Eval tables**
   - Add source-of-truth tables and repository methods for `eval_cases`, `eval_runs`, `eval_results`.
   - Keep existing benchmark tables; eval tables are a more general P3-A schema for future regression suites.
6. **Quality/Safety metrics**
   - Compute metrics from access/gate/profile records and replay traces.
   - Expose metrics through API and static report.
7. **Profiler phase expansion**
   - Expand `ProfilePhase` enum to architecture-aligned phases while keeping existing values stable.
   - Keep Quality/Safety metrics as computed API/report values in P3-A; do not persist `quality` / `safety` `ProfileEvent` rows by default.
8. **Report output**
   - Add a deterministic report generator that writes:
     - `reports/observability_report.json`
     - `reports/observability_report.md`
     - `reports/observability_report.html`
   - Generated reports are artifacts and should remain ignored like existing reports.
9. **Tests**
   - Unit, runtime integration, API, SQL mapping, migration-chain, and report-generation tests.

### Non-goals

1. **No React dashboard in Phase 3-A.** Static HTML/Markdown report is enough.
2. **No Celery/Redis or async observability workers.** Phase 4 owns heavy async infra.
3. **No Elasticsearch/Neo4j replay support.** Replay targets the current PostgreSQL/pgvector + in-memory repository abstraction.
4. **No LLM judge or model-based eval.** Metrics are deterministic and rule-derived.
5. **No historical immutable candidate snapshots in the first slice.** Replay is “recompute now from current repository state and diff against persisted original logs”. If later exact historical replay is required after memory mutation, add snapshots as a separate roadmap item.
6. **No hosted multi-tenant auth.** Existing workspace scoping remains; auth is a separate ROADMAP §0 / §3.4 decision.

## 3. Data Model Changes

### 3.1 Pydantic model changes (`apps/api/app/runtime/models.py`)

#### Modify existing models

- `MemoryAccessLog`
  - Add `top_k: int = 10`.
  - Rationale: current access logs persist `query`, `strategy`, `token_budget`, but not `top_k`; replay cannot reconstruct original candidate breadth without it.
- `DashboardTables`
  - Add:
    - `eval_cases: list[EvalCaseRecord] = Field(default_factory=list)`
    - `eval_runs: list[EvalRunRecord] = Field(default_factory=list)`
    - `eval_results: list[EvalResultRecord] = Field(default_factory=list)`
    - `observability_summary: ObservabilitySummary | None = None`
- `ProfilePhase`
  - Preserve existing values:
    - `retrieval`
    - `gate`
    - `context_packing`
  - Add architecture-aligned values:
    - `ingestion`
    - `construction`
    - `rerank`
    - `generation`
    - `maintenance`
    - `quality`
    - `safety`

#### Add replay models

```python
class ReplayCandidateView(_Base):
    memory_id: str
    content: str = ""
    memory_type: MemoryType | None = None
    key: str | None = None
    value: str | None = None
    status: MemoryStatus | None = None
    branch_status: BranchStatus | None = None
    sensitivity: Sensitivity | None = None
    risk_flags: RiskFlags = Field(default_factory=RiskFlags)
    lexical_score: float = 0.0
    vector_score: float = 0.0
    relevance_score: float = 0.0
    state_match_score: float = 0.0
```

```python
class ReplayGateDecisionView(_Base):
    memory_id: str
    layer: GateLayer
    decision: GateDecisionType
    reject_reason: str | None = None
    relevance_score: float = 0.0
    state_match_score: float = 0.0
    freshness_score: float = 0.0
    trust_score: float = 0.0
    risk_score: float = 0.0
    final_score: float = 0.0
```

```python
class ReplayDiffItem(_Base):
    kind: str
    memory_id: str | None = None
    field: str | None = None
    original: Any = None
    replayed: Any = None
    severity: str = "info"  # info | warning | critical
```

```python
class ReplayRetrievalResult(_Base):
    access_id: str
    run_id: str | None = None
    step_id: str | None = None
    workspace_id: str
    query: str | None = None
    strategy: RetrievalStrategy
    token_budget: int
    top_k: int
    original_candidates: list[ReplayCandidateView] = Field(default_factory=list)
    original_gate_decisions: list[ReplayGateDecisionView] = Field(default_factory=list)
    # Reconstructed from original accepted gate decisions + current memory rows;
    # not a persisted historical snapshot.
    original_context_blocks_reconstructed: list[ContextBlock] = Field(default_factory=list)
    replayed_candidates: list[ReplayCandidateView] = Field(default_factory=list)
    replayed_gate_decisions: list[ReplayGateDecisionView] = Field(default_factory=list)
    replayed_context_blocks: list[ContextBlock] = Field(default_factory=list)
    diffs: list[ReplayDiffItem] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
```

```python
class RunReplayResult(_Base):
    run_id: str
    access_count: int = 0
    replayed: list[ReplayRetrievalResult] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)
```

#### Add eval models

```python
class EvalCaseRecord(_Base):
    eval_case_id: str
    name: str
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    config: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_now)
```

```python
class EvalRunRecord(_Base):
    eval_run_id: str = Field(default_factory=lambda: _new_id("evalrun"))
    name: str | None = None
    workspace_id: str | None = None
    status: str = "completed"
    config: dict[str, Any] = Field(default_factory=dict)
    started_at: datetime = Field(default_factory=_now)
    finished_at: datetime | None = None
    created_at: datetime = Field(default_factory=_now)
```

```python
class EvalResultRecord(_Base):
    eval_result_id: str = Field(default_factory=lambda: _new_id("evalres"))
    eval_run_id: str
    eval_case_id: str
    run_id: str | None = None
    access_id: str | None = None
    strategy: RetrievalStrategy | str | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    passed: bool = True
    created_at: datetime = Field(default_factory=_now)
```

#### Add observability summary model

```python
class ObservabilitySummary(_Base):
    workspace_id: str | None = None
    run_id: str | None = None
    access_count: int = 0
    candidate_count: int = 0
    accepted_count: int = 0
    rejected_count: int = 0
    failed_branch_rejected: int = 0
    failed_branch_injected: int = 0
    stale_rejected: int = 0
    stale_injected: int = 0
    tool_sensitive_blocked: int = 0
    destructive_command_blocked: int = 0
    risk_blocked: int = 0
    workspace_mismatch_rejected: int = 0
    workspace_leakage: int = 0
    superseded_injected: int = 0
    avg_latency_ms: float = 0.0
    avg_actual_tokens: float = 0.0
    by_strategy: dict[str, dict[str, float]] = Field(default_factory=dict)
```

### 3.2 Repository protocol changes (`apps/api/app/runtime/repository.py`)

Add methods:

```python
async def add_eval_case(self, case: EvalCaseRecord) -> EvalCaseRecord: ...
async def add_eval_run(self, run: EvalRunRecord) -> EvalRunRecord: ...
async def update_eval_run(self, run: EvalRunRecord) -> EvalRunRecord: ...
async def add_eval_result(self, result: EvalResultRecord) -> EvalResultRecord: ...
async def list_eval_cases(self) -> list[EvalCaseRecord]: ...
async def list_eval_runs(self, *, workspace_id: str | None = None) -> list[EvalRunRecord]: ...
async def list_eval_results(self, *, eval_run_id: str | None = None) -> list[EvalResultRecord]: ...
```

Modify existing methods/mappings:

- `add_access_log` / `get_access_log` / `list_access_logs` must preserve `MemoryAccessLog.top_k`.
- In-memory repository stores eval records in dictionaries/lists like benchmark records.

### 3.3 SQL ORM changes (`apps/api/app/storage/orm.py`)

Modify `AccessLogORM`:

```python
top_k: Mapped[int] = mapped_column(Integer, default=10)
```

Add tables:

```python
class EvalCaseORM(Base):
    __tablename__ = "eval_cases"
    eval_case_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list] = mapped_column(JSONB, default=list)
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
```

```python
class EvalRunORM(Base):
    __tablename__ = "eval_runs"
    eval_run_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    workspace_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    status: Mapped[str] = mapped_column(String)
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
```

```python
class EvalResultORM(Base):
    __tablename__ = "eval_results"
    eval_result_id: Mapped[str] = mapped_column(String, primary_key=True)
    eval_run_id: Mapped[str] = mapped_column(String, index=True)
    eval_case_id: Mapped[str] = mapped_column(String, index=True)
    run_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    access_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    strategy: Mapped[str | None] = mapped_column(String, nullable=True)
    metrics: Mapped[dict] = mapped_column(JSONB, default=dict)
    passed: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
```

### 3.4 Alembic migration

Create `migrations/versions/0004_phase3a_observability.py` with:

- `down_revision = "0003_memory_superseded_by"`
- Add `memory_access_logs.top_k INTEGER NOT NULL DEFAULT 10`.
- Create `eval_cases`, `eval_runs`, `eval_results`.
- Indexes:
  - `ix_eval_runs_workspace_id`
  - `ix_eval_results_eval_run_id`
  - `ix_eval_results_eval_case_id`
  - `ix_eval_results_run_id`
  - `ix_eval_results_access_id`
- Downgrade drops eval tables and `top_k` column.

## 4. API Design

### 4.1 Replay one access

```http
GET /v1/replay/access/{access_id}
```

Response: `ReplayRetrievalResult`.

Path style note: keep `access` singular for P3-A to minimize API churn with the existing `/v1/access/{access_id}` inspection route. Do not add a second plural alias unless a client requires it.

Error semantics:

- `404 access not found` if no access log exists.
- `404 run not found` if the original access has `run_id` but the run no longer exists.
- `200` with warnings if some original memory IDs no longer exist; diffs include `candidate_removed` / `memory_missing`.

### 4.2 Replay a run

```http
GET /v1/replay/runs/{run_id}
```

Response: `RunReplayResult`.

Semantics:

- Lists all `MemoryAccessLog` rows with `run_id` in creation order.
- Replays each access independently.
- Summary aggregates drift counts and quality/safety metrics.

### 4.3 Observability summary

```http
GET /v1/observability/summary?workspace_id={workspace_id}&run_id={run_id}
```

Response: `ObservabilitySummary`.

Filter semantics:

- `workspace_id` filters access logs by workspace.
- `run_id` filters profile events and access logs by run.
- If both are omitted, summarize all accessible repository data. This is acceptable for MVP local/demo mode; hosted auth is out-of-scope.

### 4.4 Report generation endpoint

```http
POST /v1/observability/reports
```

Request model:

```python
class ObservabilityReportRequest(_Base):
    workspace_id: str | None = None
    run_id: str | None = None
    output_dir: str = "reports"
    include_replay: bool = True
```

Response model:

```python
class ObservabilityReportResult(_Base):
    json_path: str
    markdown_path: str
    html_path: str
    summary: ObservabilitySummary
```

Security note:

- For local/dev only; path must be constrained to avoid arbitrary writes. Implementation requirement: `output_dir` must be a relative path, must not contain `..`, and its resolved path must stay under the repo's `reports/` directory (default `reports`). Reject unsafe paths with HTTP 400.

### 4.5 Dashboard table extension

Extend existing:

```http
GET /v1/dashboard/tables
```

Add eval tables and `observability_summary` while preserving current fields and tests.

## 5. Service Design

### 5.1 New package layout

Create:

```text
apps/api/app/observability/
  __init__.py
  replay.py
  metrics.py
  reports.py
```

Responsibilities:

- `replay.py`
  - `RetrievalReplayService`
  - loads original access/gate/profile data
  - reconstructs `RetrievalRequest`
  - invokes side-effect-free retrieval trace
  - computes replay diffs
- `metrics.py`
  - `build_observability_summary(repo, workspace_id=None, run_id=None)`
  - deterministic quality/safety metric functions
  - reusable helpers for report and dashboard
- `reports.py`
  - `write_observability_report(...)`
  - JSON/Markdown/HTML rendering
  - no external frontend dependency

### 5.2 Retrieval pipeline refactor

Current `RetrievalController._retrieve_impl` mixes five responsibilities:

1. Create `MemoryAccessLog`.
2. Select candidates.
3. Evaluate gate.
4. Pack context.
5. Persist logs/profile and mutate accepted memory access counts.

Refactor into:

```python
class RetrievalCandidateTrace(_Base):
    memory: MemoryItem
    lexical_score: float = 0.0
    vector_score: float = 0.0
    relevance_score: float = 0.0
    state_match_score: float = 0.0
```

```python
class RetrievalPipelineTrace(_Base):
    access_record: MemoryAccessLog
    active_node: StateNode | None = None
    active_path: list[StateNode] = Field(default_factory=list)
    candidates: list[RetrievalCandidateTrace] = Field(default_factory=list)
    gate_outcomes: list[GateOutcome] = Field(default_factory=list)
    accepted_memories: list[MemoryItem] = Field(default_factory=list)
    context_blocks: list[ContextBlock] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    phase_profile: dict[str, dict[str, Any]] = Field(default_factory=dict)
    actual_tokens: int = 0
```

Implementation can keep internal dataclasses in `retrieval/controller.py` if avoiding Pydantic serialization for `GateOutcome` is simpler. Public API responses should use Pydantic replay models from `runtime/models.py`.

`RetrievalPipelineTrace.access_record` is an **in-memory access record** used for trace -> persistence conversion. It is not persisted until `_persist_trace(trace)` runs on the hot path. Replay builds the same in-memory record but never persists it.

Add controller method:

```python
async def trace(
    self,
    request: RetrievalRequest,
    *,
    workspace_id: str,
    access_id: str | None = None,
) -> RetrievalPipelineTrace:
    """Run candidate selection -> gate -> pack without persistence or mutations."""
```

Modify hot path:

```python
async def _retrieve_impl(...):
    trace = await self.trace(request, workspace_id=workspace_id)
    await self._persist_trace(trace)
    await self._bump_access_counts(trace.accepted_memories)
    return self._context_from_trace(trace)
```

Candidate scoring improvement:

- Extend `_select_candidates` to return lexical and vector component scores, not just blended relevance.
- Keep existing blended score exactly compatible:
  - if vector enabled and vector scores exist: `rel = round((1 - w_vec) * lex + w_vec * vec, 6)`
  - project constraint fallback still raises zero relevance to `0.2`.
- P3-A assumes every retrieval candidate has exactly one corresponding `MemoryGateLog` row in the hot path (accept/reject/warn/degrade all included). Current code already appends one `MemoryGateLog` per candidate in `RetrievalController._retrieve_impl`; Issue 2 must preserve this invariant. If implementation discovers a path that does not log every candidate, fix it before relying on replay diffs.

### 5.3 Runtime facade additions (`apps/api/app/runtime/memory_runtime.py`)

Add methods:

```python
async def replay_access(self, access_id: str) -> ReplayRetrievalResult | None:
    return await RetrievalReplayService(self._repo, self._retrieval).replay_access(access_id)
```

```python
async def replay_run(self, run_id: str) -> RunReplayResult:
    return await RetrievalReplayService(self._repo, self._retrieval).replay_run(run_id)
```

```python
async def observability_summary(
    self, *, workspace_id: str | None = None, run_id: str | None = None
) -> ObservabilitySummary:
    return await build_observability_summary(self._repo, workspace_id=workspace_id, run_id=run_id)
```

```python
async def write_observability_report(self, request: ObservabilityReportRequest) -> ObservabilityReportResult:
    return await write_observability_report(self._repo, self._retrieval, request)
```

Important:

- `replay_*` must **not** call `_flush_session`; replay is diagnostic, not a runtime read boundary.
- `retrieve_context` keeps lazy flush behavior unchanged.

## 6. Replay Semantics

### 6.1 Original vs replayed views

Replay result contains two views:

1. **Original persisted view**
   - Built from `MemoryAccessLog` + `MemoryGateLog` + current `MemoryItem` rows for content joins.
   - Represents what the original hot path recorded.
   - If a memory no longer exists, include a warning and a `memory_missing` diff.
   - Assumes every original retrieval candidate has one `MemoryGateLog` row. The original candidate set is reconstructed from those gate logs plus current memory rows.
   - `original_context_blocks_reconstructed` is rebuilt from original accepted gate decisions and current memory rows. It is **not** a historical snapshot and may differ from the exact context originally packed if memory content, status, or state tree changed after the access.
2. **Replayed current view**
   - Recomputed using the original request parameters and current repository state.
   - Uses side-effect-free `RetrievalController.trace`.
   - Does not persist logs/profile and does not mutate memory access counts.

### 6.2 Reconstructing the request

From `MemoryAccessLog`:

```python
request = RetrievalRequest(
    run_id=access.run_id,
    step_id=access.step_id,
    query=access.query or "",
    task_intent=access.task_intent,
    workspace_id=access.workspace_id,
    strategy=access.retrieval_strategy,
    token_budget=access.token_budget or None,
    top_k=access.top_k or 10,
)
```

If `access.run_id is None`, replay should return `200` with warning `access has no run_id; active-state replay unavailable` and still run workspace-scoped retrieval with no active state only if the controller supports it. If controller requires `run_id`, return `400`-style domain error mapped to HTTP `422`.

### 6.3 Diff categories

Diffs are deterministic and stable-sorted by severity rank, then fields:

```python
SEVERITY_RANK = {"critical": 0, "warning": 1, "info": 2}
sort_key = (SEVERITY_RANK[severity], kind, memory_id or "", field or "")
```

Do not sort severity lexicographically; that would place `info` before `warning`.

Candidate set diffs:

- `candidate_added`: replay found a candidate not in original gate logs.
- `candidate_removed`: original candidate no longer appears in replay.
- `candidate_order_changed`: same candidate exists but rank changed.

Score diffs:

- `score_changed`: absolute delta for relevance/final score > `0.000001`.
- `state_match_changed`: state path changed or source node status changed.

Gate diffs:

- `decision_changed`: accept/reject/warn/degrade changed.
- `reject_reason_changed`: reject reason changed.

Packing diffs:

- `context_block_added`
- `context_block_removed`
- `context_block_order_changed`
- `token_usage_changed`

Integrity diffs:

- `memory_missing`
- `run_missing`
- `step_missing`

Severity rules:

- `critical`: rejected -> accepted for failed/rolled\_back/stale/tool-sensitive/destructive/secret/workspace mismatch memory.
- `warning`: accepted -> rejected or score/order/token drift.
- `info`: content-only display drift or profile latency drift.

### 6.4 No-side-effect guarantee

Tests must prove replay does not change:

- count of `memory_access_logs`
- count of `memory_gate_logs`
- count of `profile_events`
- `MemoryItem.access_count`

This no-side-effect guarantee applies to `replay_access` and `replay_run`. Observability summary/report generation must also be read-only in P3-A unless a later explicit observability-run feature is introduced.

### 6.5 Historical exactness limitation

Phase 3-A replay is intentionally “current-state replay with diff”. It is not a frozen historical snapshot system.

If exact replay after arbitrary memory mutation becomes necessary, add a later table such as `retrieval_candidate_snapshots` or `access_context_snapshots`; do not add this complexity in P3-A unless a testable requirement appears.

## 7. Metrics Semantics

### 7.1 Access-level metrics

For one access, compute from original gate logs and replay trace:

```python
{
  "candidate_count": access.candidate_count,
  "accepted_count": access.accepted_count,
  "rejected_count": access.rejected_count,
  "actual_tokens": access.actual_tokens,
  "latency_ms": access.latency_ms,
  "failed_branch_rejected": count(reject_reason in {"failed_branch", "rolled_back"}),
  "failed_branch_injected": count(accepted memory.branch_status in {failed, rolled_back}),
  "stale_rejected": count(reject_reason == "stale"),
  "stale_injected": count(accepted memory.expires_at < now),
  "tool_sensitive_blocked": count(reject_reason == "tool_sensitive"),
  "destructive_command_blocked": count(reject_reason == "destructive_command"),
  "risk_blocked": count(reject_reason in {"tool_sensitive", "destructive_command"}),
  "workspace_mismatch_rejected": count(reject_reason == "workspace_mismatch"),
  "workspace_leakage": count(candidate.workspace_id != access.workspace_id),
  "superseded_injected": count(accepted memory.status == superseded),
  "drift_count": len(replay.diffs),
  "critical_drift_count": count(diff.severity == "critical"),
}
```

### 7.2 Run/workspace summary metrics

Aggregate by arithmetic sum for counts and average for latency/tokens:

- `access_count`
- `candidate_count`
- `accepted_count`
- `rejected_count`
- `failed_branch_rejected`
- `failed_branch_injected`
- `stale_rejected`
- `stale_injected`
- `tool_sensitive_blocked`
- `destructive_command_blocked`
- `risk_blocked`
- `workspace_mismatch_rejected`
- `workspace_leakage`
- `superseded_injected`
- `avg_latency_ms`
- `avg_actual_tokens`

### 7.3 Strategy breakdown

`ObservabilitySummary.by_strategy[strategy]` contains:

- `access_count`
- `avg_candidate_count`
- `avg_accepted_count`
- `avg_rejected_count`
- `failed_branch_injection_rate`
- `stale_injection_rate`
- `tool_sensitive_block_rate`
- `destructive_command_block_rate`
- `risk_block_rate`
- `workspace_leakage_rate`
- `superseded_injection_rate`
- `avg_latency_ms`
- `avg_actual_tokens`

### 7.4 Profiler semantics

Existing hot path continues to record:

- `retrieval`
- `gate`
- `context_packing`

P3-A expands the enum so `quality` and `safety` are available as first-class phases, but **does not persist quality/safety** **`ProfileEvent`** **rows by default**. Quality/Safety metrics are returned in APIs and reports as deterministic computed values. A later explicit observability-run feature may persist `quality` / `safety` profile events, but replay and summary/report reads stay side-effect-free in this phase.

Do not force generation/maintenance events until those phases have real operations. They can exist in the enum for schema readiness but should not be emitted as fake zero rows.

## 8. Report Output

### 8.1 Files

Report writer outputs:

```text
reports/observability_report.json
reports/observability_report.md
reports/observability_report.html
```

### 8.2 JSON shape

```json
{
  "summary": {},
  "accesses": [
    {
      "access_id": "acc_x",
      "run_id": "run_x",
      "query": "run tests",
      "strategy": "variant_2",
      "metrics": {},
      "critical_drift_count": 0,
      "context_block_count": 3
    }
  ],
  "replays": []
}
```

If `include_replay=false`, `replays` is omitted or empty.

### 8.3 Markdown report sections

```markdown
# MemTrace Observability Report

## Summary
## Strategy Breakdown
## Quality Signals
## Safety Signals
## Slowest Accesses
## Replay Drift
## Access Details
```

Markdown should include concrete access IDs so users can call:

```bash
curl http://localhost:8000/v1/replay/access/<access_id>
```

### 8.4 HTML report

HTML should be a single static file generated from the same data. It can use inline CSS only. No React, no external JS, no CDN.

Minimum sections:

- summary cards
- strategy table
- quality/safety table
- replay drift table
- per-access collapsible-ish details using `<details><summary>`

### 8.5 CLI/module entrypoint

Add a module entrypoint:

```bash
uv run python -m app.observability.reports --output-dir reports
```

For the initial implementation this may use an in-memory demo fixture or require SQL settings. Prefer API/runtime invocation in tests and avoid overbuilding a full CLI.

## 9. Test Plan

### 9.1 Unit tests: retrieval trace

File: `apps/api/tests/retrieval/test_retrieval_trace.py`

Cases:

- `test_trace_matches_retrieve_context_without_persisting_logs`
  - Seed Bun vs failed npm case.
  - Call `rt._retrieval.trace(...)`.
  - Assert candidate/gate/context are populated.
  - Assert repo access/gate/profile counts are unchanged.
- `test_hot_path_persists_trace_and_keeps_existing_context_output`
  - Call `retrieve_context`.
  - Assert same `MemoryContext` shape as before.
  - Assert access log has `top_k`.
- `test_trace_exposes_lexical_and_vector_components`
  - Seed memory with deterministic embedding.
  - Assert component scores are present and blended relevance equals existing formula.

### 9.2 Unit tests: replay diff

File: `apps/api/tests/observability/test_replay.py`

Cases:

- `test_replay_access_has_no_drift_when_repository_unchanged`
  - Run a retrieval.
  - Replay its `access_id`.
  - Assert `diffs == []` or only non-critical latency metadata diffs if latency is intentionally excluded from comparison.
- `test_replay_detects_decision_drift_after_memory_status_change`
  - Run retrieval with an accepted memory.
  - Mutate that memory to `status=quarantined` or `branch_status=rolled_back`.
  - Replay.
  - Assert `decision_changed` and severity `critical` or `warning` according to risk.
- `test_replay_detects_candidate_added_and_removed`
  - Run retrieval.
  - Add a new highly relevant memory and supersede/remove an old one.
  - Replay.
  - Assert candidate diffs.
- `test_replay_does_not_increment_access_count_or_write_logs`
  - Capture counts and memory `access_count` before replay.
  - Replay.
  - Assert unchanged.

### 9.3 Runtime/API tests

File: `apps/api/tests/api/test_observability.py`

Cases:

- `test_replay_access_endpoint_returns_replay_payload`
- `test_replay_access_endpoint_404_for_missing_access`
- `test_replay_run_endpoint_replays_all_run_accesses`
- `test_observability_summary_endpoint_returns_quality_safety_counts`
- `test_dashboard_tables_include_eval_and_observability_fields`

Report endpoint/API coverage belongs to Issue 7 and `apps/api/tests/observability/test_reports.py`.

### 9.4 Eval table tests

File: `apps/api/tests/observability/test_eval_records.py`

Cases:

- `test_in_memory_repository_persists_eval_records`
- `test_dashboard_tables_exposes_eval_records`
- SQL mapping smoke test if existing test harness supports SQL repository.

### 9.5 Migration tests

File: `apps/api/tests/storage/test_migrations.py` or extend existing migration tests if present.

Cases:

- Verify `0004_phase3a_observability.down_revision == "0003_memory_superseded_by"`.
- Verify `upgrade` and `downgrade` functions exist.
- If SQL integration is available, run `alembic upgrade head` and check tables/column exist.

### 9.6 Report tests

File: `apps/api/tests/observability/test_reports.py`

Cases:

- `test_report_writer_outputs_three_files`
- `test_markdown_report_contains_access_id_and_quality_sections`
- `test_html_report_is_static_and_contains_summary_tables`
- `test_report_json_is_deterministic_enough_for_assertions`

### 9.7 Regression tests to keep green

Run full suite:

```bash
uv run pytest -q
```

Also run deterministic benchmark:

```bash
uv run python -m app.benchmark.runner --output-dir reports
```

Expected:

- pytest passes.
- benchmark `acceptance.passed=true`.
- Existing dashboard test counts updated only if new eval/observability fields require assertions; do not break existing benchmark counts.

## 10. Acceptance Checklist

- [x] `P3A_IMPLEMENTATION_PLAN.md` is indexed from `.ai/PROJECT_STATE.md`, `.ai/REQUIREMENTS.md`, and `.ai/IMPLEMENTATION_PLAN.md`.
- [x] `.ai/PROJECT_STATE.md` and `ROADMAP.md` are updated after each completed Issue in §11. (Issue 1)
- [x] `MemoryAccessLog.top_k` is persisted in in-memory and SQL repositories. (Issue 1)
- [x] Alembic migration `0004_phase3a_observability.py` adds `top_k` and eval tables with downgrade. (Issue 1)
- [x] Hot-path `retrieve_context` output remains backward compatible. (Issue 2)
- [x] `RetrievalController.trace(...)` or equivalent side-effect-free pipeline exists and is used by both hot path and replay. (Issue 2; replay service will consume it in Issue 3)
- [ ] Replay one access returns original view, replayed view, diffs, metrics, and warnings.
- [ ] Replay one run aggregates all access replays for that run.
- [ ] Replay does not create access/gate/profile rows and does not mutate memory access counts.
- [ ] Quality/safety metrics include failed branch, stale, tool-sensitive/destructive, workspace leakage, and superseded injection signals.
- [ ] `ProfilePhase` supports architecture-aligned phase names while preserving existing phase values.
- [ ] Dashboard tables include eval rows and observability summary without removing existing fields.
- [ ] JSON/Markdown/HTML observability reports are generated under `reports/`.
- [ ] Unit/API/report tests cover replay, metrics, eval tables, and no-side-effect guarantees.
- [ ] `uv run pytest -q` passes.
- [ ] Deterministic benchmark still reports `acceptance.passed=true`.

## 11. Issue Breakdown

Each Issue should be completed independently. After each Issue:

1. Run the targeted tests listed for that Issue.
2. Update `.ai/PROJECT_STATE.md` with current progress and next action.
3. Tick or annotate the corresponding `ROADMAP.md` checkbox/sub-checkbox.
4. Commit only if explicitly instructed by the user.

### Issue 1: Add access fidelity and eval persistence schema

Status: ✅ complete (2026-06-10). Targeted verification: `uv run pytest apps/api/tests/observability/test_eval_records.py apps/api/tests/storage/test_migrations.py apps/api/tests/api/test_dashboard.py apps/api/tests/retrieval/test_retrieval_flow.py -q` -> 20 passed.

**Files:**

- Modify: `apps/api/app/runtime/models.py`
- Modify: `apps/api/app/runtime/repository.py`
- Modify: `apps/api/app/storage/orm.py`
- Modify: `apps/api/app/storage/sql_repository.py`
- Create: `migrations/versions/0004_phase3a_observability.py`
- Test: `apps/api/tests/observability/test_eval_records.py`
- Test: migration-chain test file if present, otherwise add `apps/api/tests/storage/test_migrations.py`

Steps:

- [x] Add `top_k` to `MemoryAccessLog` with default `10`.
- [x] Add eval Pydantic records and dashboard fields.
- [x] Add repository protocol methods and in-memory storage.
- [x] Add SQL ORM eval tables and `AccessLogORM.top_k`.
- [x] Add SQL conversion helpers for eval records and `top_k`.
- [x] Add migration `0004_phase3a_observability.py`.
- [x] Write eval persistence tests.
- [x] Run:

```bash
uv run pytest apps/api/tests/observability/test_eval_records.py -q
```

- [x] Run migration-chain test.

### Issue 2: Refactor retrieval into traceable side-effect-free pipeline

Status: ✅ complete (2026-06-10). Targeted verification: `uv run pytest apps/api/tests/retrieval/test_retrieval_trace.py apps/api/tests/retrieval/test_retrieval_flow.py -q` -> 16 passed.

**Files:**

- Modify: `apps/api/app/retrieval/controller.py`
- Modify: `apps/api/app/runtime/models.py` if public trace models live there
- Test: `apps/api/tests/retrieval/test_retrieval_trace.py`
- Regression: `apps/api/tests/retrieval/test_retrieval_flow.py`

Steps:

- [x] Introduce internal trace structures for candidate components, gate outcomes, accepted memories, packed blocks, warnings, and phase profile.
- [x] Change candidate selection to retain lexical and vector component scores.
- [x] Add `RetrievalController.trace(...)` that performs selection -> gate -> pack without persistence/mutations.
- [x] Rewrite hot-path `_retrieve_impl` to call trace, then persist logs/profile and bump accepted memory access counts.
- [x] Ensure timeout behavior still wraps only hot-path `retrieve(...)`; replay uses trace directly.
- [x] Persist `access_record.top_k = request.top_k` on the hot path.
- [x] Run:

```bash
uv run pytest apps/api/tests/retrieval/test_retrieval_trace.py apps/api/tests/retrieval/test_retrieval_flow.py -q
```

### Issue 3: Implement replay service and diff semantics

**Files:**

- Create: `apps/api/app/observability/__init__.py`
- Create: `apps/api/app/observability/replay.py`
- Modify: `apps/api/app/runtime/models.py`
- Modify: `apps/api/app/runtime/memory_runtime.py`
- Test: `apps/api/tests/observability/test_replay.py`

Steps:

- [ ] Add replay response models.
- [ ] Implement `RetrievalReplayService.replay_access(access_id)`.
- [ ] Implement `RetrievalReplayService.replay_run(run_id)`.
- [ ] Implement deterministic diff helpers for candidates, scores, gate decisions, context blocks, token usage, and missing rows.
- [ ] Add runtime facade methods `replay_access` and `replay_run`.
- [ ] Prove replay has no side effects.
- [ ] Run:

```bash
uv run pytest apps/api/tests/observability/test_replay.py -q
```

### Issue 4: Add replay and observability APIs

**Files:**

- Modify: `apps/api/app/api/routes.py`
- Modify: `apps/api/app/runtime/models.py`
- Test: `apps/api/tests/api/test_observability.py`

Steps:

- [ ] Add `GET /v1/replay/access/{access_id}`.
- [ ] Add `GET /v1/replay/runs/{run_id}`.
- [ ] Add `GET /v1/observability/summary`.
- [ ] Map missing access/run to HTTP 404.
- [ ] Run:

```bash
uv run pytest apps/api/tests/api/test_observability.py -q
```

### Issue 5: Add quality/safety metrics and profiler phase expansion

**Files:**

- Create: `apps/api/app/observability/metrics.py`
- Modify: `apps/api/app/runtime/models.py`
- Modify: `apps/api/app/runtime/memory_runtime.py`
- Modify: `apps/api/app/retrieval/profiler.py` only if helper support is needed
- Test: `apps/api/tests/observability/test_metrics.py`

Steps:

- [ ] Expand `ProfilePhase` enum with architecture-aligned values.
- [ ] Implement access-level quality/safety metric helpers.
- [ ] Implement `build_observability_summary(...)` with workspace/run filters.
- [ ] Add runtime facade method `observability_summary(...)`.
- [ ] Do not persist `quality` / `safety` `ProfileEvent` rows by default; return metrics as computed values from APIs/reports.
- [ ] Run:

```bash
uv run pytest apps/api/tests/observability/test_metrics.py -q
```

### Issue 6: Extend dashboard tables with eval and observability summary

**Files:**

- Modify: `apps/api/app/runtime/memory_runtime.py`
- Modify: `apps/api/app/runtime/models.py`
- Modify: `apps/api/tests/api/test_dashboard.py`

Steps:

- [ ] Include eval cases/runs/results in `DashboardTables`.
- [ ] Include `observability_summary` in `DashboardTables`.
- [ ] Preserve existing `runs`, `accesses`, `profile_events`, `benchmark_cases`, `benchmark_results`, and `benchmark_summary` behavior.
- [ ] Update dashboard tests to assert new fields exist without changing existing benchmark counts.
- [ ] Run:

```bash
uv run pytest apps/api/tests/api/test_dashboard.py -q
```

### Issue 7: Generate JSON/Markdown/HTML observability reports

**Files:**

- Create: `apps/api/app/observability/reports.py`
- Modify: `apps/api/app/api/routes.py`
- Modify: `apps/api/app/runtime/models.py`
- Modify: `apps/api/app/runtime/memory_runtime.py`
- Test: `apps/api/tests/observability/test_reports.py`

Steps:

- [ ] Add report request/result models.
- [ ] Implement JSON report writer.
- [ ] Implement Markdown report renderer.
- [ ] Implement static HTML report renderer with inline CSS only.
- [ ] Add API endpoint `POST /v1/observability/reports`.
- [ ] Ensure output paths stay under the requested output directory and default to `reports`.
- [ ] Run:

```bash
uv run pytest apps/api/tests/observability/test_reports.py apps/api/tests/api/test_observability.py -q
```

### Issue 8: Full regression, benchmark, and project-memory sync

**Files:**

- Modify: `.ai/PROJECT_STATE.md`
- Modify: `.ai/REQUIREMENTS.md` if active task changed during implementation
- Modify: `.ai/IMPLEMENTATION_PLAN.md` if next task changes
- Modify: `ROADMAP.md`

Steps:

- [ ] Run full test suite:

```bash
uv run pytest -q
```

- [ ] Run deterministic benchmark:

```bash
uv run python -m app.benchmark.runner --output-dir reports
```

- [ ] Verify benchmark JSON has `acceptance.passed=true`.
- [ ] Update `.ai/PROJECT_STATE.md` with completed P3-A scope, verification commands, and next recommended action.
- [ ] Tick or annotate the completed Phase 3-A checkboxes in `ROADMAP.md`.
- [ ] Keep generated report artifacts under ignored `reports/`; do not treat them as source unless explicitly requested.

