# Project State

- **Current state:** P0 + P1 fully implemented and re-verified end-to-end against mvp.md (uncommitted working-tree changes on top of P0 commit `b2923b9`).
- **Last updated:** 2026-06-09 (full P0/P1 correctness audit).

## Current Goal

P1 code path is complete: active-path context, state-aware strategy modes, four deterministic benchmark cases, benchmark persistence, JSON/Markdown reports, and a minimal dashboard tables API. Next milestone is review/commit, then optional P2 scope selection.

## Latest Verification (2026-06-09 full audit)

A full P0/P1 logic + mvp.md conformance audit was performed:
- `uv run pytest -q` -> **50 passed** (supersedes earlier 49; one additional test present).
- Benchmark runner -> `acceptance.passed=true`: variant_2 failed_branch_contamination_rate=0.0 < baseline_1=0.25; cross_workspace_leakage_rate=0.0; tool_sensitive_blocked_rate=1.0; task_success_rate=1.0.
- Demo -> baseline_1 contamination=1 (`npm test`), variant_2 contamination=0 (`bun test`), contamination_eliminated=True; state tree shows recovery attached under root (not under failed step) with failure_reason preserved.
- mvp.md §13 P0 checklist verified item-by-item against code; mvp.md §2.2/§10 P1 scope verified. No logic defects found.

## Resolved Blocking Decisions

1. **Package manager / scaffold:** `uv` + `apps/api/app/...` monorepo layout.
2. **Storage:** PostgreSQL source of truth via SQLAlchemy 2.0 async + Alembic (docker-compose). pgvector image unreachable here, so `embedding_vector` is `float[]` (P0 retrieval is lexical). Compose defaults to `public.ecr.aws/docker/library/postgres:15.6`, overridable via `MEMTRACE_PG_IMAGE`.
3. **Retrieval similarity:** deterministic lexical (token overlap), no external embedding provider.
4. **Demo:** deterministic scripted loop, no external LLM.

(See `.ai/DECISIONS.md` ADR-006..013 for rationale.)

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

## Open Risks / Notes

- pgvector deferred to `float[]`; KNN/semantic retrieval pending a reachable pgvector image (re-enable: swap ORM column + `CREATE EXTENSION vector`).
- Cross-workspace leakage prevented by workspace-scoped candidate retrieval; gate `workspace_mismatch` is defense-in-depth (unit-tested).
- Lifecycle filtering of superseded/archived memory lives only in the retrieval candidate stage (see PITFALLS); keep it in sync if a second retrieval path is added.
- Generated reports live under ignored `reports/`; regenerate them with the benchmark runner rather than treating them as source artifacts.

## Next Recommended Action

Review and commit the P1 working-tree changes. After that, choose P2 scope (LLM extraction/conflict handling/completed-run reuse) or restore pgvector/semantic retrieval when a reliable image/provider is available.
