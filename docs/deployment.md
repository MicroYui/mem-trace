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

## Compose layering (core / dev / full)

The compose setup is layered so the development environment is not heavier than
the task needs (ROADMAP §7):

| Tier | Command | Services |
|------|---------|----------|
| **core** | `docker-compose up -d` | API (run locally via `uv`) + PostgreSQL/pgvector — the only tier required for the default no-network demo, tests, and benchmark. |
| **dev** | `docker-compose -f docker-compose.yml -f docker-compose.dev.yml up -d` | core **+** Redis **+** Celery worker, for the optional async path above. |
| **full** | `docker-compose -f docker-compose.yml -f docker-compose.full.yml up -d` | core **+** Elasticsearch (hybrid BM25) **+** Neo4j (provenance graph), for the ROADMAP §4 external advanced-retrieval backends. Opt-in only. The `apps/web` dashboard runs as a separate Bun dev server (see `apps/web/README` / `docs/getting-started.md`), not a compose service. |

### Full tier — external advanced-retrieval backends

pgvector remains the source of truth. The Elasticsearch and Neo4j retrieval
backends are **default-off and degrade-safe**: with the backend flag unset (or the
service/extra absent) retrieval uses the deterministic lexical/vector path and the
benchmark stays 16/16. To actually exercise them end-to-end:

```bash
# 1. install the optional Python extras (elasticsearch / neo4j clients)
uv sync --extra search --extra graph

# 2. start the external backends (layered on core postgres)
docker-compose -f docker-compose.yml -f docker-compose.full.yml up -d elasticsearch neo4j

# 3. verify they work end-to-end (skips cleanly if a backend is down / extra missing)
#    (the smoke defaults the Neo4j password to the docker-compose.full.yml value)
MEMTRACE_ES_URL=http://localhost:9200 MEMTRACE_NEO4J_URL=bolt://localhost:7687 \
  ./scripts/smoke-advanced-backends.sh

# 4. enable them for the running API / retrieval
export MEMTRACE_RETRIEVAL_HYBRID_BACKEND=elasticsearch  # BM25 fusion
export MEMTRACE_ES_URL=http://localhost:9200
export MEMTRACE_RETRIEVAL_GRAPH_BACKEND=neo4j           # provenance neighbor expansion
export MEMTRACE_NEO4J_URL=bolt://localhost:7687
export MEMTRACE_NEO4J_PASSWORD=your-neo4j-password      # docker-compose.full.yml default: memtrace-neo4j
```

If you want the advantages of these backends without any external service, the
`inmemory` modes (`MEMTRACE_RETRIEVAL_HYBRID_BACKEND=inmemory`,
`MEMTRACE_RETRIEVAL_GRAPH_BACKEND=inmemory`) run deterministic in-process BM25 /
provenance-graph BFS with zero dependencies. The single-node ES (security
disabled) and fixed Neo4j password in `docker-compose.full.yml` are for **local
development only**; do not expose those ports publicly.


## Auth, governance, and quotas

Lightweight auth can be enabled for hosted demos:

```bash
MEMTRACE_AUTH_ENABLED=true \
MEMTRACE_API_KEY=replace-with-a-dev-token \
uv run uvicorn app.main:app --app-dir apps/api
```

When auth is enabled, `/v1` routes require `Authorization: Bearer <token>` or `X-API-Key`. `/health` remains open.

Phase 4 governance adds default-off API-key storage, workspace authorization, and quota checks. Enable these only when you have configured the expected repository-backed runtime and operational policy. Missing resources should remain 404, unauthorized existing resources should be 403, and invalid same-run workspace overrides should remain 400.

## Admin governance API (operator-only, default-off)

The maintenance scheduler and governance admin endpoints under `/v1/admin` are an operator-only surface. They are **disabled by default** and unreachable unless `MEMTRACE_ADMIN_API_ENABLED=true`. When enabled, every admin route requires a real authenticated workspace **owner** principal (anonymous/legacy/global/wildcard principals are rejected), so admin use also requires auth and governance:

```bash
MEMTRACE_ADMIN_API_ENABLED=true \
MEMTRACE_AUTH_ENABLED=true \
MEMTRACE_GOVERNANCE_ENABLED=true \
uv run uvicorn app.main:app --app-dir apps/api
```

There is **no admin UI** and **no SDK admin facade** in this slice; the surface is HTTP-only. Use an owner API key (`Authorization: Bearer <owner-key>` or `X-API-Key`). Examples:

```bash
# Start a maintenance run (direct execution). Omit "operations" to use the
# configured default operation set.
curl -X POST http://localhost:8000/v1/admin/maintenance/runs \
  -H "X-API-Key: $OWNER_KEY" -H 'Content-Type: application/json' \
  -d '{"workspace_id":"ws_1","operations":["score_memory","conflict_scan"],"dry_run":true}'

# List runs and inspect attempts.
curl "http://localhost:8000/v1/admin/maintenance/runs?workspace_id=ws_1" -H "X-API-Key: $OWNER_KEY"
curl "http://localhost:8000/v1/admin/maintenance/runs/$RUN_ID/attempts" -H "X-API-Key: $OWNER_KEY"

# Create an API key (raw key returned ONCE; only prefix+digest are stored).
curl -X POST http://localhost:8000/v1/admin/api-keys \
  -H "X-API-Key: $OWNER_KEY" -H 'Content-Type: application/json' \
  -d '{"workspace_id":"ws_1","principal_id":"alice","roles":["writer"]}'
curl -X POST http://localhost:8000/v1/admin/api-keys/$API_KEY_ID/revoke -H "X-API-Key: $OWNER_KEY"

# Quota overrides (per-principal beats workspace-wide beats settings default).
curl -X PUT http://localhost:8000/v1/admin/quota-limits \
  -H "X-API-Key: $OWNER_KEY" -H 'Content-Type: application/json' \
  -d '{"workspace_id":"ws_1","principal_id":"alice","unit":"write_event","limit":600,"window_seconds":60}'

# Manual lifecycle transition and conflict resolution.
curl -X POST http://localhost:8000/v1/admin/memories/$MEMORY_ID/status \
  -H "X-API-Key: $OWNER_KEY" -H 'Content-Type: application/json' \
  -d '{"to_status":"pinned","reason":"operator decision"}'
curl -X POST http://localhost:8000/v1/admin/memory-conflicts/$CONFLICT_ID/resolve \
  -H "X-API-Key: $OWNER_KEY" -H 'Content-Type: application/json' \
  -d '{"action":"choose_winner","winner_memory_id":"'$WINNER'","reason":"owner adjudication"}'
```

`enqueue=true` on a maintenance run requires `MEMTRACE_ASYNC_TASKS_ENABLED=true` and a configured Celery maintenance worker; otherwise it returns HTTP 400. Admin actions are recorded as redacted audit rows and surfaced (workspace-scoped) in `GET /v1/dashboard/tables?workspace_id=...` and the observability report's maintenance section. Already-resolved conflicts cannot be re-resolved (HTTP 409).

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

## Web dashboard deployment

The full React dashboard is under `apps/web`. It is a read-only browser client over `@memtrace/sdk` and `/v1`; it does not add runtime semantics or admin mutations.

Local fixture mode:

```bash
npm exec --yes --package bun -- bun run web:dev
```

Static production build:

```bash
npm exec --yes --package bun -- bun run web:build
```

The preferred deployment is same-origin: serve the built web assets and reverse-proxy `/v1` to the FastAPI service from the same host. `VITE_MEMTRACE_API_BASE_URL` defaults to same-origin and the local Vite dev server proxies `/v1` to `http://localhost:8000`. Direct cross-origin API calls are possible only when the API operator has explicitly configured CORS.

API keys must be entered by the user at runtime and are sent only as request headers. Do not bake API keys into static assets, URLs, screenshot commands, or hosting config. Fixture-backed `/showcase` and screenshot captures use synthetic data and write images to `/tmp` by default:

```bash
MEMTRACE_WEB_SCREENSHOT_URL=http://127.0.0.1:5173 \
npm exec --yes --package playwright -- node apps/web/scripts/capture-showcase-screenshots.mjs
```

The legacy `/v1/dashboard/ui` page remains a small built-in static viewer for environments that do not serve `apps/web`; it should not be expanded into the full dashboard.

## Release posture

R1 release readiness is complete: public docs, package metadata/package-shape checks, default CI, release hygiene, deterministic benchmark/reproduce closeout, and the maintainer [release checklist](release-checklist.md) are in place. R1 does not publish npm or PyPI packages automatically. Maintainers should explicitly decide when to publish, run the checklist verification commands, verify generated artifact cleanup, and ensure no local reports, package tarballs, lockfile drift, `node_modules`, or TypeScript build info are tracked.
