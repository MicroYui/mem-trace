# Deployment Notes

These notes describe the current launch-readiness posture. MemTrace has production-oriented foundations, but R1 is not an enterprise hardening guarantee and does not automate package publishing or hosted deployment.

## Default local/dev posture

By default, local/dev/benchmark behavior is deterministic and low-friction:

- auth disabled,
- governance disabled,
- quota checks disabled,
- Redis/Celery disabled,
- real LLM and embedding providers disabled,
- telemetry export disabled/noop,
- raw payload retention disabled.

This keeps no-network demos, tests, benchmark runs, and `scripts/reproduce.sh` reproducible.

## Core PostgreSQL path

Start the SQL-backed service locally:

```bash
docker-compose up -d
until docker inspect --format='{{.State.Health.Status}}' memtrace-postgres | grep -q healthy; do sleep 1; done
uv run alembic upgrade head
uv run uvicorn app.main:app --app-dir apps/api --reload
```

Check health:

```bash
curl http://localhost:8000/health
```

The compose file uses `pgvector/pgvector:pg16` and exposes PostgreSQL on host port `5433`. Existing PostgreSQL 15 volumes are incompatible with the PostgreSQL 16 image.

## Optional Redis/Celery development path

Redis/Celery async infrastructure is optional and config-gated:

```bash
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up -d
MEMTRACE_ASYNC_TASKS_ENABLED=true \
MEMTRACE_REDIS_URL=redis://localhost:6379/0 \
MEMTRACE_CELERY_BROKER_URL=redis://localhost:6379/1 \
MEMTRACE_CELERY_RESULT_BACKEND=redis://localhost:6379/2 \
MEMTRACE_CELERY_TASK_ALWAYS_EAGER=false \
uv run uvicorn app.main:app --app-dir apps/api --reload
```

Default test and benchmark runs do not require Redis. Real Redis smoke tests are opt-in, for example:

```bash
MEMTRACE_TEST_REDIS_URL=redis://localhost:6379/15 uv run --extra dev pytest apps/api/tests/integration/test_async_infra.py -q
```

## Auth, governance, and quotas

Lightweight auth can be enabled for hosted demos:

```bash
MEMTRACE_AUTH_ENABLED=true \
MEMTRACE_API_KEY=replace-with-a-dev-token \
uv run uvicorn app.main:app --app-dir apps/api
```

When auth is enabled, `/v1` routes require `Authorization: Bearer <token>` or `X-API-Key`. `/health` remains open.

Phase 4 governance adds default-off API-key storage, workspace authorization, and quota checks. Enable these only when you have configured the expected repository-backed runtime and operational policy. Missing resources should remain 404, unauthorized existing resources should be 403, and invalid same-run workspace overrides should remain 400.

## Redaction and raw payload safety

MemTrace redacts secrets before prompt context and observability output. Raw payload retention is disabled by default. Any future raw-payload storage must be encrypted/configured explicitly and should not be enabled for ordinary local demos.

MCP output adds another redaction/capping layer for IDE chat surfaces, but it does not replace server-side redaction and gate policies.

## Optional LLM and provider configuration

Deterministic providers are the default. Real LLM extraction, summarization, or embedding providers are config-gated and should degrade safely when unavailable.

Manual real-provider validation can be run only when you intentionally provide network access and credentials, for example:

```bash
MEMTRACE_LLM_API_KEY=... \
MEMTRACE_LLM_BASE_URL=https://ark.cn-beijing.volces.com/api/v3 \
MEMTRACE_LLM_MODEL=deepseek-v4-pro-260425 \
uv run python -m app.benchmark.llm_bench --output-dir reports
```

Do not make real provider calls part of default CI or first-time quickstarts.

## Optional telemetry export

OpenTelemetry/OpenInference-compatible export is default-off and must be enabled explicitly. Local JSONL output is the safest no-network smoke path:

```bash
MEMTRACE_TELEMETRY_ENABLED=true \
MEMTRACE_TELEMETRY_EXPORTER=jsonl \
MEMTRACE_TELEMETRY_JSONL_PATH=reports/telemetry.jsonl \
uv run uvicorn app.main:app --app-dir apps/api
```

The configured JSONL path must stay under `reports/...`; absolute paths, `..` traversal, and symlink escapes are rejected by the factory. Runtime hooks write redacted terminal run/step snapshots plus event/retrieval spans after persistence succeeds and fail open if telemetry export fails.

For OTLP, install the optional telemetry extra and provide an HTTP(S) endpoint without embedded credentials:

```bash
uv sync --extra dev --extra telemetry
MEMTRACE_TELEMETRY_ENABLED=true \
MEMTRACE_TELEMETRY_EXPORTER=otlp \
MEMTRACE_TELEMETRY_OTLP_ENDPOINT=https://otel-collector.example.invalid/v1/traces \
uv run uvicorn app.main:app --app-dir apps/api
```

If optional OTLP dependencies or endpoint configuration are missing, default fail-open construction degrades to noop with warnings. LangSmith, Phoenix, and Langfuse can consume OTLP/OpenInference-compatible output when configured externally, but MemTrace does not ship vendor-specific SDK bridges in this slice.

The read-only run export API returns counts and warnings, not raw spans:

```bash
curl -X POST http://127.0.0.1:8000/v1/telemetry/export/runs/<run_id> \
  -H 'Content-Type: application/json' \
  -d '{"include_steps":true,"include_events":true}'
```

When auth/governance is enabled, this endpoint requires report-reader access to the run workspace and consumes the same `report_export` quota unit as observability report export. A CLI telemetry-export command is deferred; use runtime JSONL settings or the HTTP endpoint.

## Client integration deployment

- Python SDK/CLI can use in-process runtime for tests and HTTP runtime for persistent service use.
- TypeScript SDK requires a reachable HTTP service.
- MCP server requires a reachable HTTP service and should be configured with environment variables rather than inline secrets.

For MCP templates, use `examples/mcp/claude-code.json` or `examples/mcp/cursor.json` as local-development starting points and replace relative paths with absolute/installed commands when the MCP client launches outside the repository root.

## Release posture

R1 release readiness is complete: public docs, package metadata/package-shape checks, default CI, release hygiene, deterministic benchmark/reproduce closeout, and the maintainer [release checklist](release-checklist.md) are in place. R1 does not publish npm or PyPI packages automatically. Maintainers should explicitly decide when to publish, run the checklist verification commands, verify generated artifact cleanup, and ensure no local reports, package tarballs, lockfile drift, `node_modules`, or TypeScript build info are tracked.
