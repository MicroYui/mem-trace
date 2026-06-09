# Project State

- **Current state:** P0 + P1 complete; P2 slices **completed-run reuse / procedural memory** and **dedup/merge + conflict resolver** implemented and verified end-to-end. Uncommitted working-tree changes on top of commit `c383813`.
- **Last updated:** 2026-06-09 (P2 dedup/merge + conflict resolver).

## Current Goal

P2 slice "dedup/merge + conflict resolver" is implemented: the hot write path now reconciles each incoming keyed memory against same-identity (`workspace_id`+`key`+`scope`) actives — deduping equal values into one representative and resolving single-valued-key conflicts by trust→recency, with a `superseded_by` lineage column. Next milestone is review/commit, then the next P2 slice (LLM extraction / candidate buffer).

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
