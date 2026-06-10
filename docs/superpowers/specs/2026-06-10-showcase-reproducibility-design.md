# Showcase Assets and Reproducibility Baseline Design

## Goal

Turn MemTrace from a feature-complete internal prototype into a project that a new reader can understand, run, and verify locally. The deliverable is a reproducible showcase package: README, lightweight compose baseline, deterministic report generation, smoke coverage, and project-memory updates.

## Scope

In scope:

- Add a top-level `README.md` that explains the product value, architecture, quickstart, report outputs, API surface, benchmark interpretation, and optional real-LLM validation bench.
- Keep the existing `docker-compose.yml` as the core PostgreSQL + pgvector baseline and add an optional API compose layer if needed for local HTTP exploration.
- Add a deterministic reproduction script that generates demo, benchmark, and observability report artifacts under ignored `reports/`.
- Add smoke/integration tests that protect the deterministic reproducibility path from drift.
- Update `.gitignore` so visual companion state under `.superpowers/` is not accidentally tracked.
- Update `.ai/PROJECT_STATE.md` and `ROADMAP.md` after implementation and verification.

Out of scope:

- React dashboard or frontend visualization.
- Hosted public demo, auth, rate limiting, public reset flow, or API-key governance.
- Redis, Celery, Elasticsearch, Neo4j, or other deferred infrastructure.
- Committing generated `reports/` artifacts.
- Requiring the real LLM bench to pass by default; it needs a live OpenAI-compatible endpoint and remains opt-in.

## Proposed File Layout

```text
README.md
docker-compose.yml
docker-compose.api.yml          # optional API layer if implementation needs it
scripts/
  reproduce.sh                  # deterministic showcase report generation
  smoke.sh                      # local smoke command bundle
apps/api/tests/integration/
  test_reproducibility.py       # deterministic baseline checks
.ai/PROJECT_STATE.md
ROADMAP.md
.gitignore
```

The implementation should avoid extra files unless they directly support the reproducible showcase. Existing entrypoints must be reused before adding wrappers.

## README Design

The README should be optimized for first-time readers:

1. Project positioning: MemTrace is a state-aware memory runtime and profiler for long-horizon LLM agents.
2. Why it matters: vector-only memory can recall failed branches, stale facts, cross-workspace facts, or risky tool evidence; MemTrace combines execution state, admission gates, and profiling.
3. Architecture diagram using Mermaid so no image asset is required.
4. Quickstart using deterministic commands first:
   - install dependencies with `uv`
   - run `./scripts/reproduce.sh`
   - inspect generated reports
5. Optional PostgreSQL/API path:
   - start pgvector Postgres with compose
   - run migrations
   - start FastAPI
   - call `/health` and selected observability endpoints
6. Report guide:
   - `demo_report.{md,json}`
   - `benchmark_report.md`
   - `benchmark_results.json`
   - `observability_report.{json,md,html}`
7. Benchmark interpretation:
   - `baseline_0`: no memory
   - `baseline_1`: vector/lexical memory without state/gate isolation
   - `variant_1`: state-aware retrieval
   - `variant_2`: state-aware retrieval plus admission gate
8. Optional real LLM bench with `MEMTRACE_LLM_*` environment variables.
9. Roadmap pointer to `ROADMAP.md`.

## Reproduction Script Design

`scripts/reproduce.sh` should be deterministic and database-free by default. It should:

1. Generate the Bun-vs-Node failed-branch demo report using `app.demo.run_demo`.
2. Run the deterministic benchmark using `app.benchmark.runner`.
3. Generate the observability static report using `app.observability.reports`.
4. Assert `reports/benchmark_results.json` contains `acceptance.passed=true`.
5. Print the generated file paths and next commands.

The script should use `set -euo pipefail` and avoid hiding failures. It should not require Docker, PostgreSQL, real LLM keys, or network access.

## Compose Design

The existing `docker-compose.yml` remains the canonical core database baseline:

- `pgvector/pgvector:pg16`
- database `memtrace`
- user/password `memtrace`
- host port `5433`

If an API compose layer is added, it should be optional and combined with the core file. It must not introduce Redis, Celery, ES, Neo4j, or a frontend. The README should clearly mark this as optional, because deterministic reproduction does not depend on Docker.

## Test Design

Add smoke/integration tests that run against temporary directories and in-memory repositories where possible:

- Verify the deterministic benchmark reports `acceptance.passed=true`.
- Verify demo and observability report entrypoints write the expected files.
- Verify README references core commands and modules that exist.

The tests should not require Docker or a live LLM endpoint. They should use `tmp_path` for generated artifacts to avoid polluting the real `reports/` directory.

## Safety and Drift Controls

- Add `.superpowers/` to `.gitignore` to keep brainstorming visual-companion state out of commits.
- Keep `reports/` ignored; generated reports are reproducible artifacts, not source.
- Clearly label the real LLM bench as optional/manual.
- Keep observability report generation under the existing `reports/` output-dir safety policy.
- Any new retrieval/reporting path must preserve lifecycle filtering assumptions already documented in `ROADMAP.md`.

## Verification Plan

Implementation is complete only after:

- `./scripts/reproduce.sh` succeeds.
- `uv run pytest -q` succeeds.
- `uv run python -m app.benchmark.runner --output-dir reports` produces `acceptance.passed=true`.
- README quickstart commands match actual entrypoints.
- `.ai/PROJECT_STATE.md` and `ROADMAP.md` reflect completion of the showcase/reproducibility baseline.

## Self-Review

- No unresolved TBD/TODO placeholders.
- Scope is focused on showcase and reproducibility; hosted demo, frontend, auth, and heavy infra are excluded.
- The deterministic baseline is intentionally database-free; PostgreSQL/API usage is optional.
- Generated reports remain ignored and reproducible.
