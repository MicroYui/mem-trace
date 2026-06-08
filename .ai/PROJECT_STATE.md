# Project State

- **Current state:** P0 MVP implemented and verified (service layer + storage + HTTP + demo + tests).
- **Last updated:** 2026-06-08.

## Current Goal

Deliver the full P0 hot path from mvp.md: trace -> state tree -> state-aware retrieval -> admission gate -> profiler, with a deterministic Bun-vs-Node failed-branch isolation demo and tests.

## Resolved Blocking Decisions

1. **Package manager / scaffold:** `uv` + `apps/api/app/...` monorepo layout.
2. **Storage:** PostgreSQL source of truth via SQLAlchemy 2.0 async + Alembic, started with docker-compose. pgvector image was unreachable in this environment (Docker Hub blocked), so `embedding_vector` is stored as `float[]` (P0 retrieval is lexical; swap to pgvector.Vector later). Compose uses the cached `public.ecr.aws/docker/library/postgres:15.6` by default, overridable via `MEMTRACE_PG_IMAGE`.
3. **Retrieval similarity:** deterministic lexical (token overlap), no external embedding provider.
4. **Demo:** deterministic scripted loop, no external LLM.

## Implemented (P0)

- **Models/enums:** `app/runtime/models.py` (runs, steps, events, state nodes, memory items, access/gate/profile logs, context blocks, request/result schemas).
- **Repository:** `app/runtime/repository.py` protocol + `InMemoryRepository`; SQL impl in `app/storage/sql_repository.py` (same protocol).
- **State tree:** `app/runtime/state_tree.py` pure helpers (root/step/recovery, finish/rollback, active-path, descendants).
- **MemoryRuntime facade:** `app/runtime/memory_runtime.py` (start_run/start_step/write_event/finish_step/rollback_branch/retrieve_context + read models + inspect_access). Monotonic `sequence_no`; recovery attaches to failed node's parent; failure_reason preserved across rollback.
- **Memory writer:** `app/memory/writer.py` (project positive/negative constraints, explicit correction supersede, tool_evidence success/failed, working_state) + `app/memory/secrets.py` redaction.
- **Retrieval:** `app/retrieval/` similarity, 3-layer gate (hard/risk/soft), context packer (ordered blocks + merged Bun/Node constraint + budget), profiler (retrieval/gate/context_packing), controller orchestrating + persisting access/gate logs. Strategy modes: baseline_0/1, variant_1/2.
- **Storage:** `app/storage/orm.py` (all MVP tables), `db.py`, Alembic migration `migrations/versions/0001_initial.py`.
- **HTTP:** `app/api/` + `app/main.py` — all mvp.md §3.1 endpoints (runs, steps.start/finish, events, context.retrieve, branches.rollback, GET timeline/state-tree/profile/access/steps/memories) + `/health`.
- **Demo:** `app/demo/run_demo.py` -> `reports/demo_report.{md,json}` (in-memory or `--sql`).

## Verification Done

- `uv run pytest -q` -> 44 passed (state tree, sequence_no, recovery placement, memory writer, secrets, gate hard/risk, retrieval contamination, workspace isolation, stale/tool-sensitive rejection, packing order, profiler phases).
- Demo (both backends): baseline_1 contamination=1 (action `npm test`), variant_2 contamination=0 (action `bun test`), contamination_eliminated=True.
- API smoke-tested via httpx ASGI against live Postgres; Alembic `upgrade head` succeeds.

## Known Deviations / Notes

- pgvector not installed (image unreachable); `embedding_vector` is `float[]`. KNN not needed for P0 lexical retrieval. Re-enable pgvector by swapping the ORM column + adding `CREATE EXTENSION vector` (migration already attempts it best-effort).
- Cross-workspace leakage is enforced by workspace-scoped retrieval (candidates never cross workspaces); the gate workspace_mismatch rule is defense-in-depth and unit-tested.

## Next Recommended Action

Begin P1: active-path context builder, state-aware candidate scoring generalization, the 4 benchmark cases (project preference, failed branch, workspace isolation, tool safety), and benchmark_report.{md,json}. Consider restoring pgvector once a reachable image is available.
