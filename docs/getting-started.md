# Getting Started

This guide gets you from a fresh checkout to a representative MemTrace demo. The default path is deterministic and does not require Docker, Redis, Celery, a live LLM provider, or network access beyond dependency installation.

## Prerequisites

- Python 3.12+
- [`uv`](https://docs.astral.sh/uv/)
- Docker Compose only for the PostgreSQL-backed HTTP path
- Bun for TypeScript paths. If Bun is not installed globally, use the local fallback shown below:

```bash
npm exec --yes --package bun -- bun --version
```

This repository uses `bun.lock`. Do not add npm, pnpm, or yarn lockfiles for routine local work.

## Track 1: no-network Python CLI demo

Install dependencies and run the canonical release-readiness smoke. It runs the in-process CLI demo and Python SDK example, verifies their stable markers, and skips service-dependent checks unless you opt in with environment variables:

```bash
uv sync --extra dev
./scripts/smoke-release-readiness.sh
```

Expected stable output:

```text
baseline_1 action: npm test (contamination=1)
variant_2 action: bun test (contamination=0)
contamination eliminated: true
```

The demo seeds a Bun-vs-Node scenario where a failed `npm test` branch is rolled back. The baseline memory strategy repeats the failed command, while the state-aware gated strategy chooses `bun test`.

You can run the same scenario through a small custom agent loop using the public Python SDK:

```bash
uv run --package memtrace-sdk python examples/simple_agent/main.py
```

To run only the CLI demo without the smoke wrapper:

```bash
uv run --package memtrace-sdk memtrace demo --in-process
```

Optional live-service smoke checks are disabled by default. After starting the HTTP service, enable them explicitly:

```bash
MEMTRACE_SMOKE_HTTP_URL=http://127.0.0.1:8000 ./scripts/smoke-release-readiness.sh
MEMTRACE_SMOKE_TS=1 MEMTRACE_BASE_URL=http://127.0.0.1:8000 ./scripts/smoke-release-readiness.sh
```

## Track 2: local HTTP service

Use this path when you want persistent `/v1` HTTP APIs and SQL-backed storage. It requires Docker Compose and PostgreSQL/pgvector.

```bash
docker-compose up -d
until docker inspect --format='{{.State.Health.Status}}' memtrace-postgres | grep -q healthy; do sleep 1; done
uv run alembic upgrade head
uv run uvicorn app.main:app --app-dir apps/api --reload
```

In another shell:

```bash
curl http://localhost:8000/health
uv run --package memtrace-sdk memtrace --http http://127.0.0.1:8000 demo
```

Operational CLI commands require `--http` because each shell invocation is a new process and cannot share a throwaway in-memory runtime:

```bash
uv run --package memtrace-sdk memtrace --http http://127.0.0.1:8000 start-run --session-id demo --task "trace my agent"
uv run --package memtrace-sdk memtrace --http http://127.0.0.1:8000 retrieve --run-id <run_id> --query "How do I run tests?" --json
```

If auth is enabled with `MEMTRACE_AUTH_ENABLED=true`, pass `--api-key` to the CLI or configure SDK/MCP clients with a bearer token.

## Track 3: TypeScript SDK example

The TypeScript example is a live HTTP client. Start the local service first, then run:

```bash
export MEMTRACE_BASE_URL="http://127.0.0.1:8000"
npm exec --yes --package bun -- bun examples/ts-simple-agent/src/index.ts
```

Expected output is JSON containing these fields:

```json
{
  "run_id": "...",
  "step_id": "...",
  "event_id": "...",
  "access_id": "...",
  "context_block_count": 2
}
```

`context_block_count` is an example count from the current local-service path; treat it as a numeric smoke marker rather than a public API guarantee.

If the service is not running, the example exits with a connection error. That is expected: this example is not a no-network/in-process demo.

## Track 4: deterministic benchmark and reproducibility

Run the benchmark only:

```bash
uv run python -m app.benchmark.runner --output-dir reports
```

Run the full reproducibility bundle:

```bash
./scripts/reproduce.sh
```

Generated report files under `reports/` are ignored by git and can be regenerated.

## Troubleshooting

### `bun: command not found`

Use the temporary Bun fallback:

```bash
npm exec --yes --package bun -- bun run typecheck
npm exec --yes --package bun -- bun test
```

### `docker compose` does not work

This environment has historically used standalone `docker-compose`. Prefer:

```bash
docker-compose up -d
```

### PostgreSQL image or volume errors

The default compose file uses `pgvector/pgvector:pg16`. Existing PostgreSQL 15 volumes are not compatible with the PostgreSQL 16 image. Removing old volumes is destructive, so only run `docker-compose down -v` when you intentionally want to reset local database state.

### Optional services and providers

Redis/Celery, live PostgreSQL integration tests, real LLM extraction, real embedding providers, and live HTTP smoke tests are opt-in. Default local tests and docs should pass without these environment variables.
