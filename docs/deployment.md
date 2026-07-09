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
| **scale** | `docker-compose -f docker-compose.yml -f docker-compose.scale.yml up -d --scale api=N` | core **+** N stateless API replicas **+** an nginx load balancer (`:8080`), for horizontal throughput scaling over the shared Postgres. Opt-in only (see "Horizontal scaling" below). |

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

### Real semantic embeddings — Qwen3 embedding server

The default `deterministic` embedding is a lexical hash (~42% recall@1 on
paraphrased queries); a real semantic model gets ~92% (see
`app/benchmark/semantic_bench.py`). `app/embedding_server.py` is a turnkey
OpenAI-compatible `/v1/embeddings` server backed by Qwen3-Embedding-0.6B (FP16),
honoring the `dimensions` param via Matryoshka truncation to the pgvector 256-dim
column. Start it (heavy; needs the model, ~1.2GB) and point the runtime at it:

```bash
# 1. serve Qwen3 as an OpenAI-compatible /v1/embeddings endpoint
uv run --with fastapi --with "uvicorn[standard]" --with sentence-transformers \
  uvicorn app.embedding_server:app --app-dir apps/api --host 0.0.0.0 --port 8090

# 2. verify end-to-end through MemTrace's provider (skips if the server is down)
MEMTRACE_EMBEDDING_BASE_URL=http://localhost:8090/v1 ./scripts/smoke-embedding-server.sh

# 3. wire the running MemTrace service to it (real semantic retrieval)
export MEMTRACE_EMBEDDING_PROVIDER=openai
export MEMTRACE_EMBEDDING_BASE_URL=http://localhost:8090/v1
export MEMTRACE_EMBEDDING_MODEL=qwen3-embedding-0.6b
export MEMTRACE_EMBEDDING_API_KEY=local   # the server does not check auth; the provider sends a Bearer
```

The provider degrades to the deterministic 256-dim embedding on any failure, so
retrieval never breaks if the server is down. For production, run the embedding
server as its own scaled service (GPU or CPU) behind the same load balancer.

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

## Performance & scaling (production)

Measured characteristics (see `docs/benchmark.md` and `app/benchmark/perf_bench.py`)
and the settings that make retrieval production-grade at scale:

- **Bound retrieval cost.** By default retrieval scores every workspace memory
  (O(N)) — ~2.2 s p50 at 20k memories. Set `MEMTRACE_RETRIEVAL_CANDIDATE_LIMIT`
  (e.g. `800`, generously above `top_k`) to load only a bounded, relevance-ranked
  candidate set: in-memory ~**56 ms** @20k (~39×); on Postgres, with migration
  `0014`'s `pg_trgm` GIN index, ~**16 ms** @20k (~72×) and latency stays ~flat
  with workspace size.
- **Use real semantic embeddings.** The default `deterministic` embedding is a
  lexical hash (recall@1 ~42% on paraphrased queries). Point
  `MEMTRACE_EMBEDDING_PROVIDER=openai` + `MEMTRACE_EMBEDDING_BASE_URL` at an
  OpenAI-compatible `/embeddings` endpoint (e.g. Qwen3-Embedding served with
  256-dim MRL to match the pgvector column) for real semantic recall (~92%).
- **Scale throughput horizontally.** Retrieval is CPU-bound and single-process
  asyncio pegs ~one core (~**16 retrievals/s**, p99 ~110 ms at 20k under 16-way
  concurrency — stable, no degradation). Requests are stateless and PostgreSQL is
  the shared source of truth, so run multiple API replicas / uvicorn workers
  behind a load balancer to scale linearly. `scripts/perf-scale.sh` measures this
  directly: at 3k memories on the heavy path it saw **5.3 → 18.2 req/s going 1→4
  `uvicorn --workers` (≈3.4×, ~86% of ideal)**. `docker-compose.scale.yml` is the
  cross-host form — N stateless API replicas behind an nginx LB over the shared
  core Postgres (see "Horizontal scaling" below).
- **Offload writes.** Enable the async path (`MEMTRACE_ASYNC_TASKS_ENABLED=true`
  + Redis) so extraction/maintenance run off the write hot path and the candidate
  buffer is shared across workers (see the async section above). Two live opt-in
  checks validate this end-to-end (both skip cleanly without the backends):
  `tests/integration/test_async_cross_worker.py` proves a buffered write on one
  worker is drained and extracted by a *separate* worker through the shared Redis
  buffer + shared Postgres (with cross-worker idempotency), and
  `scripts/smoke-async-worker.sh` drives a real (non-eager) Celery worker
  consuming from the Redis broker to extract a persisted event into Postgres,
  asserting the Redis idempotency store de-duplicates redelivery.

### Horizontal scaling — multi-replica API behind a load balancer

`docker-compose.scale.yml` is the deployable form of the "scale horizontally"
guidance: **N stateless API replicas behind an nginx load balancer, over the
shared core Postgres.** Like the dev worker, the API runs on the `uv` base image
with the repo mounted (no separate build step), and it builds its linux venv
outside the mount (`UV_PROJECT_ENVIRONMENT`) so it never clobbers a host `.venv`.

```bash
docker-compose up -d                       # start/keep Postgres (source of truth)
uv run alembic upgrade head                # migrate once
docker-compose -f docker-compose.yml -f docker-compose.scale.yml up -d --scale api=3
curl http://localhost:8080/health          # through the nginx LB (:8080)
```

The nginx config (`deploy/nginx.conf`) uses per-request DNS resolution against
Docker's embedded resolver, so it round-robins across every `--scale api=N`
replica (a static upstream would pin to one). Because replicas are stateless and
Postgres is the single source of truth, a run started on one replica is
immediately usable on another.

This was verified live: with `--scale api=2`, the LB distributed traffic across
both replicas, and a full `POST /v1/runs` → `POST /v1/steps/start` →
`POST /v1/context/retrieve` round-trip worked end-to-end through the LB (the run
created on one replica, retrieved on another, over shared Postgres). For the
single-host form and the measured 1→4-worker speedup, see
`scripts/perf-scale.sh` above. Set `MEMTRACE_RETRIEVAL_CANDIDATE_LIMIT` (the
overlay defaults it to `800`) so each replica's retrieval stays sublinear.

## Release posture

R1 release readiness is complete: public docs, package metadata/package-shape checks, default CI, release hygiene, deterministic benchmark/reproduce closeout, and the maintainer [release checklist](release-checklist.md) are in place. R1 does not publish npm or PyPI packages automatically. Maintainers should explicitly decide when to publish, run the checklist verification commands, verify generated artifact cleanup, and ensure no local reports, package tarballs, lockfile drift, `node_modules`, or TypeScript build info are tracked.
