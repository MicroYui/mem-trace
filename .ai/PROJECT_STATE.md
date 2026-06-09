# Project State

- **Current state:** P0 + P1 complete; **P2 complete (6/6)** — completed-run reuse / procedural memory, dedup/merge + conflict resolver, candidate buffer / idle flush, benchmark cases 7-8, and the **config-gated LLM extraction pipeline**. A full MVP conformance audit (mvp.md §13 acceptance list + §3/§4/§7/§8/§9) was then performed and **4 audit findings were fixed**. All implemented and verified end-to-end. Uncommitted working-tree changes on top of commit `b7b8828`.
- **Last updated:** 2026-06-09 (MVP audit + fixes).

## Current Goal

P2 is feature-complete and a full MVP audit has been completed and remediated. The remaining milestone is review/commit. The audit confirmed all 15 mvp.md §13 acceptance items pass; the only gaps found were 1 real (§11 retrieval timeout never enforced) + 3 edge/hardening issues, all now fixed.

## Implemented (MVP audit fixes — 2026-06-09)

- **Retrieval hot-path timeout (mvp.md §11 / §12.3):** `RetrievalController.retrieve` now wraps `_retrieve_impl` in `asyncio.wait_for(timeout=settings.retrieval_timeout_ms/1000)`; on `TimeoutError` it degrades to an empty `MemoryContext` with a "timed out" warning instead of blocking. `retrieval_timeout_ms` was previously a dead config (`controller.py`).
- **Rollback memory-flip degenerate branch (`memory_runtime.py` `rollback_branch`):** memories are now flipped via a single `affected_node_ids` set; when the step's node is missing but its id is known it is still targeted, and matching never falls back to a `None` source-node id (which previously could either skip the flip entirely or wrongly match every memory lacking a source node). Removed the redundant `== step.state_node_id` or-clause.
- **Recovery parent dangling reference (`memory_runtime.py` `start_step` + new `StateTreeError`):** if a failed node has a `parent_id` that cannot be resolved, recovery no longer silently reattaches to root (which would misplace it in a multi-level tree); it raises `StateTreeError`. Root-level steps (no parent) still legitimately attach to root.
- **Access inspection candidates vs gate_decisions (`memory_runtime.py` `inspect_access`):** `candidates` is now the retrieval-input view ranked by `relevance_score`; `gate_decisions` stays the gate-output view in processing order. Both cover the same memory set but expose distinct orderings/intent (mvp.md §3.2).
- **Tests:** `tests/runtime/test_memory_runtime_trace.py` (dangling-parent recovery raises `StateTreeError`) and `tests/retrieval/test_retrieval_flow.py` (candidates ranked by relevance + cover same set as gate_decisions; retrieve times out to empty context with warning).

## Latest Verification (2026-06-09 MVP audit + fixes)

- `uv run pytest -q` -> **98 passed** (was 95; +3 audit-fix tests).
- Benchmark: **8 cases / 32 results**, `acceptance.passed=true` (deterministic path unchanged).
- Demo re-verified: baseline_1 contamination=1, variant_2 contamination=0, contamination_eliminated=True.
- Audit result: all 15 mvp.md §13 acceptance items ✅; §3.1 endpoints 12/12; §4 entities + 12 ORM tables covered; Alembic chain 0001→0002→0003 intact.

## Implemented (P2 — LLM extraction pipeline)

- **`app/memory/llm_extractor.py`** (new, pure + storage-agnostic): `ExtractionCandidate` (fixed Pydantic schema, `extra="ignore"` per architecture.md §11.4), `ExtractionProvider` Protocol, deterministic `FakeExtractionProvider` (wraps the writer rules so output is identical to the rule-based path), and `build_results(event, candidates) -> list[MemoryWriteResult]` (validates + drops invalid candidates, stable `(scope, key, value)` sort, builds `MemoryItem` with provenance + risk flags, emits `supersede_keys` when `supersede=True`).
- **Config** (`app/config.py`): `llm_extraction_enabled: bool = False` (env `MEMTRACE_LLM_EXTRACTION_ENABLED`).
- **Runtime** (`app/runtime/memory_runtime.py`): `__init__` takes keyword-only `extraction_provider: Optional[ExtractionProvider] = None`; new `_extract_user_message` helper branches (provider when injected, else `writer.write_from_user_message`); `_apply_write_rules` calls it. Tool_result / working_state / summarizer paths unchanged. Buffered/idle-flush path reuses `_apply_write_rules`, so the provider works under deferred extraction too.
- **DI** (`app/api/deps.py`): injects `FakeExtractionProvider()` when enabled, else `None` (TODO marker for a real LLM client).
- **Secret safety:** secret events are redacted and skip the whole extraction branch in `write_event` before any provider is consulted (verified by test).
- **Tests:** `tests/memory/test_llm_extractor.py` (pure-function: schema validation, invalid/extra-field dropping, provenance, supersede_keys, deterministic ordering) and `tests/runtime/test_llm_extraction_flow.py` (provider path persists via resolver, no-provider keeps rule-based, resolver dedup, secret skips provider, provider works under buffered flush).

## Latest Verification (2026-06-09 P2 LLM extraction)

- `uv run pytest -q` -> **95 passed** (was 84; +11 extractor/flow tests).
- Benchmark: **8 cases / 32 results**, `acceptance.passed=true` (default-off path unchanged).
- Demo re-verified: baseline_1 contamination=1, variant_2 contamination=0, contamination_eliminated=True.
- Enabled-path manual check: `MemoryRuntime(..., extraction_provider=FakeExtractionProvider())` writing "这个项目使用 Bun" produces `project.runtime=bun` via the resolver.

## Implemented (P2 — benchmark cases 7-8)

- **Case 7 `case_7_stale_rejection`** (`app/benchmark/cases.py`): seeds an expired (`expires_at` in the past) high-relevance `episodic` memory pointing at a legacy endpoint `/v1/old-users`, plus a Bun constraint. The query asks which endpoint to call. Returns `stale_markers` in `SeedResult.extra`.
- **Case 8 `case_8_no_memory_baseline`** (`app/benchmark/cases.py`): seeds only the Bun constraint; baseline_0 (no memory) returns `unknown` (task fails), state-aware strategies recall Bun and succeed.
- **Evaluator** (`app/benchmark/evaluator.py`): `stale_memory_injection` is now really computed (was hardcoded 0) — a memory whose `stale_markers` appear in any context block counts as injected. Added `stale_memory_injection_present` so the rate is averaged only over cases that seed stale memory (mirrors the `tool_sensitive_present` / `procedural_reuse_present` convention, incl. baseline_0 present=1/inj=0).
- **Runner** (`app/benchmark/runner.py`): passes `stale_markers` through; `stale_memory_injection_rate` now filtered by `_present`; two new acceptance checks: `variant_2_excludes_stale_memory` (variant_2 rate 0 AND baseline_1 rate > 0) and `variant_2_succeeds_where_no_memory_baseline_fails` (variant_2 task_success_rate > baseline_0).
- **Tests:** `tests/benchmark/test_runner.py` (6→8 cases, 24→32 results, two new acceptance asserts) and `tests/api/test_dashboard.py` (runs 8→10, accesses 24→32, cases 6→8, results 24→32).

## Latest Verification (2026-06-09 P2 cases 7-8)

- `uv run pytest -q` -> **84 passed** (test count unchanged; benchmark/dashboard counts updated in place).
- Benchmark: **8 cases / 32 results**; `acceptance.passed=true` with all 7 checks true. Case 7 per-strategy stale_injection: baseline_1=1, variant_1=1, variant_2=0. Case 8 task_success: baseline_0=0, variant_2=1. variant_2 overall task_success_rate=1.0, baseline_0=0.0.
- Demo re-verified: baseline_1 contamination=1, variant_2 contamination=0, contamination_eliminated=True.

## Implemented (P2 — candidate buffer / idle flush)

- **`ExtractionMode` enum** (`sync` / `buffered`) in `app/runtime/models.py`; `WriteEventRequest.extraction_mode` per-request override (sync_flush for explicit corrections); `WriteEventResult.buffered` flag; new `FlushRequest`/`FlushResult` models.
- **`CandidateBuffer`** `app/memory/candidate_buffer.py`: pure, deterministic, in-process, session-keyed FIFO of candidate events (append/pending/size/total_size/drain/sessions). Ephemeral — only holds event ids/copies; raw events already persisted to PG, so no DB table/migration is needed. Falls back to `run_id` grouping when an event has no session.
- **Runtime wiring** `MemoryRuntime` (`app/runtime/memory_runtime.py`): constructor takes `extraction_mode` (default `sync`) + owns a `CandidateBuffer`. `write_event` buffers non-secret events in buffered mode (honoring per-request `sync` override); secrets are never buffered. New public `flush_session()` (drains + replays `_apply_write_rules` in write order, so dedup/conflict resolution stays order-correct; idempotent). Lazy `_flush_session` hooked into `retrieve_context`, `finish_step`, `rollback_branch`, and `complete_run` so deferred extraction is materialized before reads/summaries/branch-isolation.
- **Failed-branch isolation parity:** `rollback_branch` flushes the session *before* flipping branch memories. Without this, a buffered branch's tool-evidence would stay pending and a later flush would resurrect it as a completed-branch memory; flushing first lets rollback flip it to `rolled_back`, keeping buffered-mode isolation identical to sync mode.
- **Config/wiring**: `Settings.extraction_mode` (`app/config.py`, default `sync`); `deps.py` injects `ExtractionMode(settings.extraction_mode)` into the runtime.
- **HTTP**: `POST /v1/sessions/{session_id}/flush` -> `FlushResult` (`app/api/routes.py`).
- **Tests:** `tests/memory/test_candidate_buffer.py` (pure buffer: grouping, order-preserving pending, drain empties + idempotent, unknown session, session→run fallback) and `tests/runtime/test_candidate_buffer_flush.py` (buffered defers extraction but persists raw event, explicit flush extracts, flush idempotent, lazy flush on retrieve_context / finish_step, per-request sync override, secret not buffered, buffered conflict resolves in write order with lineage, rollback-before-flush isolates buffered branch memory).

## Latest Verification (2026-06-09 P2 candidate buffer)

- `uv run pytest -q` -> **84 passed** (was 70; +14 buffer/flush tests incl. rollback isolation).
- Benchmark `acceptance.passed=true` (default `sync` mode unchanged; buffer is opt-in).
- Demo re-verified: baseline_1 contamination=1, variant_2 contamination=0, contamination_eliminated=True (sync default path intact).
- No new DB migration required (buffer is ephemeral; raw events remain the durable source of truth in PG).
- Correctness review note: in-process buffer is single-process and not shared across workers; acceptable for the deterministic MVP (raw events are durable in PG; architecture.md defers the Redis-backed buffer to post-P2).

## Implemented (P2 — dedup/merge + conflict resolver)

- **`superseded_by` lineage column** added: `MemoryItem.superseded_by` (`app/runtime/models.py`), `MemoryORM.superseded_by` (`app/storage/orm.py`), `_mem_to_orm`/`_mem_from_orm` mappings (`app/storage/sql_repository.py`), and migration `0003_memory_superseded_by` (down_revision `0002_pgvector`).
- **Resolver** `app/memory/resolver.py`: pure, deterministic, no-LLM. `resolve(incoming, existing_active) -> ResolveResult(add, updates)`. Same value (normalized) → dedup/merge into the strongest representative (union `source_event_ids`, max scores), retire other duplicates to `superseded`. Different value on a single-valued key (`project.runtime`) → conflict resolved by `trust_score` then `updated_at`; loser `superseded` with `superseded_by`=winner; a genuine tie marks both `conflicted` (gate degrades). Multi-valued keys (`project.runtime.excluded`) coexist.
- **Runtime hook** `MemoryRuntime._apply_write_rules` (`app/runtime/memory_runtime.py`): user-message memories now flow through `_resolve_and_persist` / `_same_identity_actives`; the existing explicit-correction `_supersede_keys` path is preserved and runs first. The resolver never rewrites `content`, so embeddings never go stale.
- **Benchmark** P2 case 5 (`case_5_explicit_correction`): user states Node then states Bun (conflicting positive prefs); the older Node preference is superseded at write time and never recalled. New evaluator metric `superseded_injection` (+`superseded_injection_present`) + summary `superseded_injection_rate` + acceptance check `variant_2_excludes_superseded_memory`.
- **Tests:** `tests/memory/test_resolver.py` (pure-function: dedup-merge, duplicate supersede, trust/recency conflict, tie→conflicted, multi-valued coexist, lineage) and `tests/runtime/test_dedup_merge.py` (dedup to one active, conflict supersede + lineage, superseded not recalled, idempotency). Updated benchmark/dashboard counts (now 6 cases / 24 results / 8 runs / 24 accesses).

## Latest Verification (2026-06-09 P2 dedup/merge)

- `uv run pytest -q` -> **70 passed** (was 59; +11 resolver/dedup tests, benchmark/dashboard counts updated).
- Benchmark `acceptance.passed=true` with new check `variant_2_excludes_superseded_memory=true`; case 5 per-strategy `superseded_injection=0` for all strategies (resolver retires the loser at write time, so it is strategy-independent).
- Migration chain validated: `0003_memory_superseded_by` down_revision `0002_pgvector`, upgrade/downgrade callable.

## Implemented (P2 — completed-run reuse / procedural memory)

- **MemoryType.procedural** added (`app/runtime/models.py`); `CompleteRunRequest`/`CompleteRunResult` request/result models added.
- **Summarizer** `app/memory/summarizer.py`: pure, deterministic, no-LLM. `build_run_summary` emits an episodic completed-run summary (active-path progress) and, for successful runs only, a procedural memory distilling the successful approach (positive project constraint + successful non-risky tool evidence on the active path). Failed/rolled-back branches and tool-sensitive/destructive evidence are never distilled.
- **Runtime** `MemoryRuntime.complete_run` (cold path, not on hot retrieve path): marks run completed, runs the summarizer, persists memories, and supersedes prior same-(run-scoped-)key summaries so re-running is idempotent. Stable keys `run.summary.<run_id>` / `procedure.<run_id>`.
- **Packer** maps `MemoryType.procedural` to the reserved `procedural` block (mvp.md §8 ordering).
- **HTTP** `POST /v1/runs/{run_id}/complete` (path param is authoritative; request body `run_id` optional).
- **Failed-branch isolation extended to summaries:** a failed run's episodic summary is written with `branch_status=failed` (not `completed`), so it is never recalled as a successful path.
- **Benchmark** P2 case 6 (`case_6_completed_run_reuse`): first run fixes a pytest suite and is completed (procedural extracted); a second similar run recalls it. New evaluator metric `procedural_reuse_hit` + summary `procedural_reuse_hit_rate` + acceptance check `variant_2_reuses_procedural_memory`.
- **Tests:** `tests/runtime/test_completed_run_reuse.py` (episodic+procedural write, failed-run produces no procedural, idempotency, later-run recall). Updated benchmark/dashboard counts (now 5 cases / 20 results / 7 runs).

## Latest Verification (2026-06-09 P2)

- `uv run pytest -q` -> **59 passed** (was 55; +4 procedural tests, benchmark/dashboard counts updated).
- Benchmark `acceptance.passed=true` with new check `variant_2_reuses_procedural_memory=true`; case 6 per-strategy: baseline_0 hit=0 (no memory), baseline_1/variant_1/variant_2 hit=1.
- Demo unchanged: baseline_1 contamination=1 (`npm test`), variant_2 contamination=0 (`bun test`), contamination_eliminated=True.

## Latest Verification (2026-06-09 full audit)

A full P0/P1 logic + mvp.md conformance audit was performed:
- `uv run pytest -q` -> **50 passed** (supersedes earlier 49; one additional test present).
- Benchmark runner -> `acceptance.passed=true`: variant_2 failed_branch_contamination_rate=0.0 < baseline_1=0.25; cross_workspace_leakage_rate=0.0; tool_sensitive_blocked_rate=1.0; task_success_rate=1.0.
- Demo -> baseline_1 contamination=1 (`npm test`), variant_2 contamination=0 (`bun test`), contamination_eliminated=True; state tree shows recovery attached under root (not under failed step) with failure_reason preserved.
- mvp.md §13 P0 checklist verified item-by-item against code; mvp.md §2.2/§10 P1 scope verified. No logic defects found.

## Resolved Blocking Decisions

1. **Package manager / scaffold:** `uv` + `apps/api/app/...` monorepo layout.
2. **Storage:** PostgreSQL source of truth via SQLAlchemy 2.0 async + Alembic (docker-compose). **pgvector semantic retrieval is now restored** (`pgvector/pgvector:pg16`): `embedding_vector` is a `Vector(256)` column with an HNSW cosine index (migration `0002_pgvector`); retrieval is hybrid lexical + deterministic-vector cosine. Compose defaults to `pgvector/pgvector:pg16`, overridable via `MEMTRACE_PG_IMAGE`.
3. **Retrieval similarity:** hybrid — lexical token overlap blended with deterministic hashed-embedding cosine (no external embedding provider; reproducible).
4. **Demo:** deterministic scripted loop, no external LLM.

(See `.ai/DECISIONS.md` ADR-006..014 for rationale.)

## Implemented (P0)

- **Runtime core:** `app/runtime/` models/enums, repository protocol + `InMemoryRepository`, pure `state_tree` helpers, `MemoryRuntime` facade (start_run/start_step/write_event/finish_step/rollback_branch/retrieve_context + read models + inspect_access).
- **Memory writer:** `app/memory/` rule-based writer (project +/- constraints, correction supersede, tool_evidence, working_state) + secret redaction.
- **Retrieval:** `app/retrieval/` lexical similarity, 3-layer gate (hard/risk/soft), context packer, profiler; strategy modes baseline_0/1, variant_1/2.
- **Storage:** `app/storage/` SQLAlchemy ORM (all MVP tables) + `SqlRepository`; Alembic migration `0001_initial`.
- **HTTP:** `app/api/` + `app/main.py` — all mvp.md §3.1 endpoints + `/health`.
- **Demo:** `app/demo/run_demo.py` -> `reports/demo_report.{md,json}` (in-memory or `--sql`).

## Implemented (P1)

- **Active path builder:** `active_path_chain` derives an ordered active progress chain excluding failed/rolled-back branches; context packing emits an `active_path` block after `active_state`.
- **State-aware retrieval plumbing:** retrieval now passes active-path data through controller and access inspection; existing strategy modes still compare `baseline_0`, `baseline_1`, `variant_1`, and `variant_2` on identical candidates.
- **Benchmark package:** `app/benchmark/` contains deterministic case seeders and rule evaluator for the four required cases: project preference, failed branch isolation, workspace isolation, and tool-call safety.
- **Benchmark runner/report/persistence:** `python -m app.benchmark.runner --output-dir reports` writes ignored generated artifacts `reports/benchmark_report.md` / `reports/benchmark_results.json`; when passed a repository it also persists `benchmark_cases` and `benchmark_results` rows.
- **Acceptance self-check:** the runner encodes mvp.md §10.5 criteria 1-3 in an `acceptance` block (variant_2 contamination < baseline_1, zero cross-workspace leakage, tool-sensitive blocked) surfaced in both JSON and Markdown; criteria 4-6 are covered by unit tests.
- **Dashboard tables:** `GET /v1/dashboard/tables` exposes table-shaped runs, access logs, profile events, benchmark cases/results, and benchmark summary for P1 inspection.
- **Tests:** benchmark runner/persistence/acceptance and dashboard table coverage added under `apps/api/tests/benchmark/` and `apps/api/tests/api/` (with `__init__.py` for both, matching other test packages).

## Verification Done

- `uv run pytest -q` -> **45 passed**.
- Demo (both backends): baseline_1 contamination=1 (`npm test`), variant_2 contamination=0 (`bun test`), contamination_eliminated=True.
- API smoke-tested via httpx ASGI on live Postgres; `alembic upgrade head` succeeds.
- P1 latest local verification: `uv run pytest -q` -> **50 passed**.
- P1 benchmark: `uv run python -m app.benchmark.runner --output-dir reports` generated JSON/Markdown reports with an `acceptance.passed=true` block. Summary: `variant_2.failed_branch_contamination_rate=0.0 < baseline_1=0.25`, `variant_2.cross_workspace_leakage_rate=0.0`, `variant_2.tool_sensitive_blocked_rate=1.0`, `variant_2.task_success_rate=1.0`.
- SQL backend re-verified on live Postgres: benchmark persists 4 cases + 16 results and `dashboard_tables()` returns them with a per-strategy summary.
- Targeted P1 gap tests passed: benchmark persistence stores 4 cases + 16 results; `/v1/dashboard/tables` returns benchmark/dashboard table rows and summary.
- pgvector restoration verified (2026-06-09): `uv run pytest -q` -> **55 passed** (added embedding stability / cosine / in-memory vector KNN tests). Recreated the data volume on `pgvector/pgvector:pg16`, `alembic upgrade head` ran `0001` + `0002_pgvector` (extension + `vector(256)` column + HNSW index confirmed via psql). SQL-backend demo: baseline_1 contamination=1, variant_2 contamination=0, contamination_eliminated=True; all 10 stored memories carry embeddings (`embedding_status=embedded`) and pgvector `<=>` cosine ranking is correct. Benchmark acceptance still `passed=true`.

## Open Risks / Notes

- pgvector semantic retrieval is restored; embeddings are deterministic hashed bag-of-words (not learned), so similarity is a proxy. Swapping in a real embedding model later only touches `similarity.stable_embedding` (keep determinism for benchmarks or gate behind config).
- PG15 data volumes are incompatible with the `pg16` image; switching requires `docker-compose down -v` (destructive). This env uses standalone `docker-compose` (the `docker compose` subcommand is unavailable).
- Cross-workspace leakage prevented by workspace-scoped candidate retrieval (lexical AND vector KNN both filter by workspace_id); gate `workspace_mismatch` is defense-in-depth (unit-tested).
- Lifecycle filtering of superseded/archived memory lives only in the retrieval candidate stage (see PITFALLS); the new vector path reuses the same `list_memories` lifecycle filter, so it stays in sync.
- Generated reports live under ignored `reports/`; regenerate them with the benchmark runner rather than treating them as source artifacts.

## Next Recommended Action

Review and commit the dedup/merge + conflict-resolver working-tree changes (incl. migration `0003`). After that, choose the next P2 slice: LLM extraction with schema validation, or candidate buffer / idle flush; optionally extend P2 benchmark cases 7-8 (stale rejection, no-memory baseline).
