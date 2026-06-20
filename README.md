# MemTrace

MemTrace is a **trace-first, state-aware memory runtime for long-horizon agents**. It records runs, steps, events, and execution state before deriving memory; retrieves context with state awareness; gates stale, failed, unsafe, or cross-workspace memories before prompt injection; and makes every retrieval decision inspectable through replay, reports, and benchmarks.

## Why not plain vector memory?

Plain vector recall can retrieve text that is semantically similar but operationally wrong: a failed branch, a rolled-back command, a stale correction, another workspace's preference, or risky tool evidence. MemTrace treats memory as runtime infrastructure instead of a generic RAG store:

- **Trace first:** raw events are persisted before derived memory extraction.
- **State-aware retrieval:** active execution paths influence candidate scoring and context packing.
- **Admission gate:** failed/rolled-back, superseded, stale, cross-workspace, secret, destructive, and tool-sensitive memories are rejected or degraded before prompt use.
- **Negative evidence:** safe failed attempts can appear as warning-only `avoided_attempts` blocks without becoming positive context.
- **Context compaction:** over-budget retrieval keeps protected constraints and records what was compacted for replay and reports.
- **Replayable observability:** access logs, gate logs, profiler spans, policy snapshots, and reports explain exactly why context changed.

## What is implemented today?

- Core `MemoryRuntime` with runs, steps, events, state tree, memory writer/resolver, retrieval controller, admission gate, context packer, profiler, and `/v1` FastAPI surface.
- PostgreSQL + pgvector source-of-truth path, plus deterministic in-memory runtime for tests and no-network demos.
- Context compaction, failure-aware negative evidence, retained negative compaction metadata, replay, JSON/Markdown/HTML reports, and deterministic benchmark acceptance.
- Provider registry and controlled memory-key ontology with deterministic defaults and config-gated real providers.
- Phase 4 platform foundations: optional async Redis/Celery, lifecycle/reflection signals, memory versions/conflicts, default-off governance/auth/quota, and redaction state protections.
- Python SDK, CLI, LangGraph adapter, TypeScript SDK (`@memtrace/sdk`), MCP server (`@memtrace/mcp-server`), and Claude Code / Cursor MCP config templates.
- Default-off OpenTelemetry/OpenInference-compatible export hooks with noop/JSONL/optional OTLP sinks and a read-only run export endpoint.
- React/TypeScript dashboard in `apps/web` with Overview, Run Explorer, Access Replay, Benchmark Lab, Memory Atlas, read-only Ops, and fixture-backed Showcase mode.

## Quickstart: 5-minute no-network demo

Prerequisites:

- Python 3.12+
- [`uv`](https://docs.astral.sh/uv/)

Install dependencies, then run the canonical release-readiness smoke. It orchestrates the deterministic in-process CLI demo and the Python SDK example, verifies the stable markers below, and skips live-service checks unless you opt in with environment variables:

```bash
uv sync --extra dev
./scripts/smoke-release-readiness.sh
```

Expected stable output markers:

```text
baseline_1 action: npm test (contamination=1)
variant_2 action: bun test (contamination=0)
contamination eliminated: true
```

This demonstrates the representative failed-branch/state-aware-memory contrast: a baseline memory strategy reuses failed `npm test` evidence, while MemTrace's state-aware gated strategy chooses `bun test`.

You can run the same no-network scenario through the Python SDK example:

```bash
uv run --package memtrace-sdk python examples/simple_agent/main.py
```

To run only the CLI demo without the smoke wrapper:

```bash
uv run --package memtrace-sdk memtrace demo --in-process
```

## Quickstart paths

| Path | Command | Runtime requirement | Stable marker / expected result |
| --- | --- | --- | --- |
| CLI in-process demo | `uv run --package memtrace-sdk memtrace demo --in-process` | Default/no-network | Prints `baseline_1 action: npm test`, `variant_2 action: bun test`, `contamination eliminated: true` |
| Python SDK example | `uv run --package memtrace-sdk python examples/simple_agent/main.py` | Default/no-network | Prints the same failed-branch contrast markers |
| Release-readiness smoke | `./scripts/smoke-release-readiness.sh` | Default/no-network; optional HTTP/TS checks are env-gated | Verifies the CLI and Python SDK demo markers; prints `release readiness smoke passed` |
| Deterministic benchmark | `uv run python -m app.benchmark.runner --output-dir reports` | Default/no-network | Writes ignored files under `reports/`; acceptance should be `passed=true` |
| Full reproducibility bundle | `./scripts/reproduce.sh` | Default/no-network | Runs demo, benchmark, reports, and acceptance checks |
| Local HTTP service | See [Local HTTP and Docker path](#local-http-and-docker-path) below | Docker/PostgreSQL required | Waits for PostgreSQL health before Alembic, then `curl http://localhost:8000/health` returns service health |
| CLI HTTP demo | `uv run --package memtrace-sdk memtrace --http http://127.0.0.1:8000 demo` | Local service required | Same high-level failed-branch contrast, persisted through `/v1` |
| TypeScript SDK example | `npm exec --yes --package bun -- bun examples/ts-simple-agent/src/index.ts` | Local service required; set `MEMTRACE_BASE_URL` if not `http://127.0.0.1:8000` | Emits JSON with `run_id`, `step_id`, `event_id`, `access_id`, and `context_block_count` |
| MCP server | `npm exec --yes --package bun -- bun packages/mcp-server/src/server.ts` | Local service required; MCP client launches stdio server | Tool results are redacted and replay/report output is capped |
| Web dashboard fixture mode | `npm exec --yes --package bun -- bun run web:dev` | Default/no live API needed after JS deps are installed | Open `/showcase`, `/memories`, `/ops`, `/benchmark`, `/runs/run_showcase_bun_recovery`, or `/access/acc_showcase_gate` |

If Bun is installed globally, replace `npm exec --yes --package bun -- bun ...` with `bun ...`. The repository uses `bun.lock`; npm/pnpm/yarn lockfiles should not be added.

## Local HTTP and Docker path

The default quickstart does not require Docker. To run the SQL-backed API path:

```bash
docker-compose up -d
until docker inspect --format='{{.State.Health.Status}}' memtrace-postgres | grep -q healthy; do sleep 1; done
uv run alembic upgrade head
uv run uvicorn app.main:app --app-dir apps/api --reload
curl http://localhost:8000/health
```

The compose file uses `pgvector/pgvector:pg16` on host port `5433`. Existing PG15 volumes are not compatible with the PG16 image; switching images may require removing the old volume.

Optional Redis/Celery development services are in `docker-compose.dev.yml` and are not required for default demos, tests, or benchmark runs:

```bash
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up -d
MEMTRACE_ASYNC_TASKS_ENABLED=true \
MEMTRACE_REDIS_URL=redis://localhost:6379/0 \
MEMTRACE_CELERY_BROKER_URL=redis://localhost:6379/1 \
MEMTRACE_CELERY_RESULT_BACKEND=redis://localhost:6379/2 \
MEMTRACE_CELERY_TASK_ALWAYS_EAGER=false \
uv run uvicorn app.main:app --app-dir apps/api --reload
```

## TypeScript SDK and MCP

`@memtrace/sdk` is a thin fetch client over `/v1`. `@memtrace/mcp-server` is a stdio MCP adapter over that SDK; it does not import Python runtime or database modules and does not reimplement retrieval, gate, replay, or packing semantics.

For MCP clients, set service configuration in the environment rather than inline secrets:

```bash
export MEMTRACE_BASE_URL="http://127.0.0.1:8000"
export MEMTRACE_API_KEY="your-dev-token-if-auth-is-enabled"
```

Checked-in local-development templates:

- Claude Code-style: [`examples/mcp/claude-code.json`](examples/mcp/claude-code.json)
- Cursor-style: [`examples/mcp/cursor.json`](examples/mcp/cursor.json)

Both templates launch `bun packages/mcp-server/src/server.ts` relative to the repository root and therefore require `bun` to be available on the MCP client's `PATH`. If your MCP client launches from another directory, replace that path with an absolute path or an installed package command. If Bun is not globally available to the client, configure an absolute Bun executable path or wait for the future installed `memtrace-mcp-server` command after package publishing is explicitly approved. If your client does not expand `${MEMTRACE_BASE_URL}` / `${MEMTRACE_API_KEY}`, render or replace those values outside version control.

Available MCP tools: `memtrace_start_run`, `memtrace_start_step`, `memtrace_write_event`, `memtrace_retrieve_context`, `memtrace_inspect_access`, `memtrace_finish_step`, `memtrace_replay_access`, and `memtrace_report`.

## Telemetry export

Telemetry is disabled/noop by default. To write local no-network JSONL spans while using the HTTP service, opt in explicitly:

```bash
MEMTRACE_TELEMETRY_ENABLED=true \
MEMTRACE_TELEMETRY_EXPORTER=jsonl \
MEMTRACE_TELEMETRY_JSONL_PATH=reports/telemetry.jsonl \
uv run uvicorn app.main:app --app-dir apps/api --reload
```

Runtime hooks export redacted terminal run/step snapshots plus event and retrieval spans after authoritative persistence succeeds. You can also request a read-only run projection; the response contains counts and warnings, not raw spans:

```bash
curl -X POST http://127.0.0.1:8000/v1/telemetry/export/runs/<run_id> \
  -H 'Content-Type: application/json' \
  -d '{"include_steps":true,"include_events":true}'
```

OTLP export is optional and requires installing the `telemetry` extra plus an HTTP(S) endpoint without embedded credentials. LangSmith, Phoenix, and Langfuse are possible external OTLP/OpenInference destinations when configured outside MemTrace; this repository does not include vendor-specific SDK bridges. A CLI telemetry-export command is intentionally deferred; use runtime JSONL settings or the HTTP endpoint.

## Benchmark and reproducibility

Run only the deterministic benchmark:

```bash
uv run python -m app.benchmark.runner --output-dir reports
```

Run the full deterministic reproduce bundle:

```bash
./scripts/reproduce.sh
```

The reproduce script is a wrapper around the same deterministic entrypoints, which can also be run directly when debugging report generation:

```bash
uv run python -m app.demo.run_demo --out reports
uv run python -m app.benchmark.runner --output-dir reports
uv run python -m app.observability.reports --output-dir reports
```

Replay data is also available through the HTTP API, including `/v1/replay/access/{access_id}` when the local service is running.

## Web dashboard

The full dashboard lives in `apps/web` and is separate from the built-in static viewer. It is a React/Vite/TypeScript app over `@memtrace/sdk` and existing read-only `/v1` APIs. Fixture mode works without a running API:

```bash
npm exec --yes --package bun -- bun run web:dev
```

Open `http://127.0.0.1:5173/showcase` for the guided sample-data walkthrough. The fixture-backed routes include Overview, Run Explorer, Access Replay, Benchmark Lab, Memory Atlas, and read-only Ops panels. API keys are entered only for live mode and are sent as headers, not URLs.

To connect to a live local service, start the HTTP path above, then use the dashboard connection form with an optional workspace id and API key. `VITE_MEMTRACE_API_BASE_URL` defaults to same-origin `/v1`; local Vite dev uses a `/v1` proxy to `http://localhost:8000` unless you configure a direct API origin.

To build static assets:

```bash
npm exec --yes --package bun -- bun run web:build
```

Optional screenshot workflow, writing PNGs under `/tmp` by default:

```bash
MEMTRACE_WEB_SCREENSHOT_URL=http://127.0.0.1:5173 \
npm exec --yes --package playwright -- node apps/web/scripts/capture-showcase-screenshots.mjs
```

When the HTTP service is running you can also open the built-in read-only static **Dashboard UI** at `/v1/dashboard/ui`. It is a single self-contained HTML page (no build step, no external JS/CDN) that calls `/v1/dashboard/tables` and `/v1/observability/summary` from the browser to show runs, access logs, profiler events, the observability summary, and per-strategy benchmark metrics. If auth is enabled, paste the token into the page's token field (sent as `Authorization: Bearer` / `X-API-Key`). This viewer is intentionally not the React/TypeScript `apps/web` dashboard.

Generated report artifacts are intentionally ignored by git and can be regenerated:

- `reports/demo_report.{md,json}`
- `reports/benchmark_report.md`
- `reports/benchmark_results.json`
- `reports/observability_report.{json,md,html}`

The benchmark currently compares six strategies (`baseline_0`, `long_context`, `baseline_1`, `variant_1`, `variant_2`, `variant_3`) across 13 cases, including failed-branch isolation, tool safety, context compaction, safe negative evidence, sanitized destructive failures, reflection-lite retention, and retained negative lessons through compaction metadata.

## User docs

- [Getting started](docs/getting-started.md): prerequisites, no-network demos, HTTP path, TypeScript example, troubleshooting.
- [Concepts](docs/concepts.md): runs, steps, events, state tree, memories, gate, negative evidence, compaction, lifecycle, governance defaults, telemetry export boundaries.
- [MCP integration](docs/mcp.md): server behavior, templates, placeholders, local path assumptions, redaction/capping.
- [Benchmark guide](docs/benchmark.md): strategies, cases, commands, and metric interpretation.
- [Deployment notes](docs/deployment.md): PostgreSQL, optional Redis/Celery, auth/governance/quota defaults, provider config, safety posture.
- [Release checklist](docs/release-checklist.md): maintainer verification, package dry-run checks, artifact hygiene, publish decision gates, and rollback notes.

Internal design and historical implementation plans live under [`docs/design/`](docs/design/). New users should not need to read them before running the quickstarts.

## Local verification

Run the common smoke bundle:

```bash
./scripts/smoke.sh
```

Run the lighter canonical public-adoption smoke:

```bash
./scripts/smoke-release-readiness.sh
```

Optional live-service checks can be enabled explicitly:

```bash
MEMTRACE_SMOKE_HTTP_URL=http://127.0.0.1:8000 ./scripts/smoke-release-readiness.sh
MEMTRACE_SMOKE_TS=1 MEMTRACE_BASE_URL=http://127.0.0.1:8000 ./scripts/smoke-release-readiness.sh
```

Or run pieces directly:

```bash
uv run --extra dev pytest -q
uv run --extra dev python -m compileall -q apps/api/app packages/python-sdk/src examples
npm exec --yes --package bun -- bun run typecheck
npm exec --yes --package bun -- bun test
./scripts/reproduce.sh
```

Default local/dev/benchmark behavior keeps auth, quotas, Redis/Celery, live PostgreSQL integration tests, and real LLM/provider calls disabled unless you opt in with environment variables.

## Roadmap

The completed MVP, observability, compaction, failure-aware negative evidence, SDK/CLI/LangGraph, six-strategy benchmark, security/consistency hardening, provider registry/key ontology, Phase 4 platform foundations, TypeScript SDK, MCP server, release-readiness work, and the core OpenTelemetry/OpenInference exporter are tracked in [`docs/design/ROADMAP.md`](docs/design/ROADMAP.md). For a narrative overview, read [Why agent memory is not just RAG](docs/blog/why-agent-memory-is-not-just-rag.md).

Advanced retrieval/storage, admin workflow depth, richer telemetry backfill/CLI surfaces, and a dedicated IDE extension remain future work; the IDE package is deferred until MCP adoption feedback shows editor-specific needs. A built-in read-only static Dashboard UI is available at `/v1/dashboard/ui`; a richer interactive React/TypeScript dashboard remains optional future work.
