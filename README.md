# MemTrace

MemTrace is a state-aware memory runtime and profiler for long-horizon LLM agents. It records agent traces, builds an execution state tree, writes structured memories, retrieves context with state awareness, gates unsafe or stale memories before prompt injection, and reports every retrieval decision.

## Why MemTrace

Vector memory alone can recall the wrong thing at the wrong time: a failed branch, another workspace's preference, stale endpoint guidance, or risky tool evidence. MemTrace treats memory as runtime infrastructure rather than a generic RAG store:

- **Trace first:** raw runs, steps, and events are persisted before memory extraction.
- **State-aware retrieval:** active execution paths influence candidate selection and scoring.
- **Admission gate:** failed/rolled-back, stale, superseded, cross-workspace, secret, and risky memories are rejected or degraded before context packing.
- **Replayable observability:** access logs, gate logs, profiler events, and replay APIs explain why a memory entered or missed the prompt.

## Architecture

```mermaid
flowchart TD
    Agent[Agent / demo loop] --> Runtime[MemoryRuntime facade]
    Runtime --> Trace[Trace Collector]
    Runtime --> State[Execution State Tree]
    Runtime --> Writer[Rule / LLM Write Pipeline]
    Runtime --> Retrieval[Retrieval Controller]
    Retrieval --> Gate[Admission Gate]
    Gate --> Packer[Context Packer]
    Runtime --> Profiler[Profiler]
    Trace --> PG[(PostgreSQL + pgvector)]
    State --> PG
    Writer --> PG
    Retrieval --> PG
    Profiler --> PG
    Runtime --> Reports[JSON / Markdown / HTML Reports]
```

## Quickstart: deterministic reproducibility baseline

Prerequisites:

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)

Install dependencies and generate all deterministic showcase reports:

```bash
uv sync --extra dev
./scripts/reproduce.sh
```

The script runs these entrypoints:

```bash
uv run python -m app.demo.run_demo --out reports
uv run python -m app.benchmark.runner --output-dir reports
uv run python -m app.observability.reports --output-dir reports
```

Generated artifacts are ignored by git and can be regenerated at any time:

- `reports/demo_report.md`
- `reports/demo_report.json`
- `reports/benchmark_report.md`
- `reports/benchmark_results.json`
- `reports/observability_report.json`
- `reports/observability_report.md`
- `reports/observability_report.html`

The deterministic benchmark passes only when `reports/benchmark_results.json` contains `acceptance.passed=true`.

## What the demo proves

The canonical demo is Bun vs Node.js with failed-branch isolation:

1. The user states that the project uses Bun, not Node.js.
2. A failed branch tries `npm test` and is rolled back.
3. A recovery step asks how to run tests.
4. `baseline_1` recalls the failed `npm test` evidence and is contaminated.
5. `variant_2` uses state-aware retrieval plus the gate, rejects the rolled-back branch, and chooses `bun test`.

Run only the demo:

```bash
uv run python -m app.demo.run_demo --out reports
```

## Benchmark variants

Run only the deterministic benchmark:

```bash
uv run python -m app.benchmark.runner --output-dir reports
```

Strategies:

- `baseline_0`: no memory.
- `long_context`: includes every retrievable workspace memory with hard/risk/state policies disabled and an effectively unbounded budget, exposing token bloat and failed-branch contamination while preserving the same trace/gate logging path; non-bypassable quarantine/secret/destructive/tool-sensitive/redaction safety floors still apply.
- `baseline_1`: vector/lexical memory without state-aware isolation or the full admission gate; non-bypassable quarantine/secret/destructive/tool-sensitive/redaction safety floors still apply.
- `variant_1`: state-aware retrieval with failed/rolled-back branch rejection relaxed for ablation, while hard/risk safety policy remains enabled.
- `variant_2`: state-aware retrieval plus admission gate.
- `variant_3`: state-aware + gate + deterministic reflection-lite / retention-rerank (placeholder for the ROADMAP §3.2 Reflection scheduler).

The benchmark covers project preference, failed-branch isolation, workspace isolation, tool-call safety, explicit correction, completed-run reuse, stale rejection, no-memory failure recovery, over-budget context compaction retention, safe failure learning (`case_10`), sanitized destructive-failure handling (`case_11`), reflection-retention under a tight budget (`case_12_reflection_retention`), and retained negative lessons through compaction metadata (`case_13_compaction_retains_negative_lesson`).

## Observability and replay

Generate a static observability report fixture:

```bash
uv run python -m app.observability.reports --output-dir reports
```

The runtime also exposes observability APIs when served through FastAPI:

- `GET /health`
- `POST /v1/context/retrieve`
- `GET /v1/access/{access_id}`
- `GET /v1/replay/access/{access_id}`
- `GET /v1/replay/runs/{run_id}`
- `GET /v1/observability/summary`
- `POST /v1/observability/reports`
- `GET /v1/dashboard/tables`

## Context compaction

When retrieval exceeds the token budget, MemTrace does not silently discard low-priority context. It emits protected `compacted_constraints` / `compaction_notice` blocks, persists each `ContextCompactionLog`, includes compaction metrics in observability summaries, surfaces retained facts in JSON/Markdown/HTML reports, and lets replay flag `compaction_drift` if a later rerun would compact differently. The deterministic benchmark includes `case_9_over_budget_compaction`, which checks constraint retention and unsafe-compaction leakage rather than relying on compression ratio alone.

## Integration entrypoints: Python SDK / HTTP / CLI / TypeScript / MCP

Phase 3.5 adds an installable Python SDK and proves the same runtime behavior is reachable from an embedded in-process backend, the FastAPI `/v1` HTTP API, and the `memtrace` CLI. The integrations track adds a TypeScript SDK plus an MCP server for IDE/agent clients. All paths ultimately go through `/v1` and `MemoryRuntime`, so state-aware retrieval, admission gating, context compaction, negative evidence, profiler logs, and replay semantics stay shared.

### Python SDK quickstart

```python
from memtrace_sdk import MemTrace
from memtrace_sdk.types import EventRole, EventType, StartRunRequest, StartStepRequest, WriteEventRequest

client = MemTrace.in_memory(default_workspace_id="ws_demo")
run = await client.start_run(StartRunRequest(session_id="demo-session", task="remember project facts"))
step = await client.start_step(StartStepRequest(run_id=run.run_id, intent="record preference"))
await client.write_event(
    WriteEventRequest(
        run_id=run.run_id,
        step_id=step.step_id,
        role=EventRole.user,
        event_type=EventType.message,
        content="This project uses Bun, not Node.js",
    )
)
```

Use `MemTrace.in_memory(...)` for deterministic local demos/tests, or wrap an existing runtime with `MemTrace.in_process(runtime)`.

### HTTP backend

Start the API server as shown below, then point the same SDK facade at it:

```python
from memtrace_sdk import MemTrace

client = MemTrace.http("http://localhost:8000", api_key="demo-token-if-auth-enabled")
```

The HTTP backend mirrors the `/v1` surface and maps HTTP `404`/`400` responses to SDK `NotFoundError` / `BadRequestError`. `api_key` is optional unless the server is started with `MEMTRACE_AUTH_ENABLED=true`, in which case it is sent as a Bearer token. The backend also preserves backend isomorphism for list-shaped reads such as timeline, state tree, steps, profile, and memories.

### LangGraph adapter

`MemTraceLangGraphAdapter` provides framework-light lifecycle hooks without requiring `langgraph` at SDK import time:

```python
from memtrace_sdk import MemTrace, MemTraceLangGraphAdapter

client = MemTrace.in_memory(default_workspace_id="ws_graph")
adapter = MemTraceLangGraphAdapter(client, run_id=run.run_id)

step, context = await adapter.before_node("planner", "How should I run tests?")
write_result, finish_result = await adapter.after_node(step.step_id, content="Use bun test")
```

See [`examples/langgraph_adapter`](examples/langgraph_adapter) for a minimal graph that runs when LangGraph is installed and skips cleanly otherwise.

### CLI

Run the one-shot deterministic CLI demo:

```bash
uv run --package memtrace-sdk memtrace demo --in-process
```

Operational CLI commands require `--http` because each shell invocation is a new process and cannot share throwaway in-memory state:

```bash
uv run --package memtrace-sdk memtrace --http http://localhost:8000 start-run --session-id demo --task "trace my agent"
uv run --package memtrace-sdk memtrace --http http://localhost:8000 retrieve --run-id <run_id> --query "How do I run tests?" --json
```

For runnable end-to-end examples, start with [`examples/README.md`](examples/README.md), [`examples/simple_agent`](examples/simple_agent), and [`examples/langgraph_adapter`](examples/langgraph_adapter).

### TypeScript SDK and MCP server

The TypeScript workspace provides `@memtrace/sdk` as a thin fetch client over `/v1` and `@memtrace/mcp-server` as a stdio MCP server over that SDK. The MCP server never imports Python runtime or database modules; configure IDE/agent clients with environment variables rather than inline secrets. The checked-in JSON files are local-development templates: run them from the repository root, or replace `packages/mcp-server/src/server.ts` with the absolute path / installed package command your MCP client should launch.

Set the variables in your shell or IDE environment first:

```bash
export MEMTRACE_BASE_URL="http://127.0.0.1:8000"
export MEMTRACE_API_KEY="your-dev-token-if-auth-is-enabled"
```

If your MCP client does not expand `${...}` placeholders inside JSON config files, render or replace `${MEMTRACE_BASE_URL}` and `${MEMTRACE_API_KEY}` before use; do not paste real secrets into version-controlled files.

Claude Code-style config (`examples/mcp/claude-code.json`):

```json
{
  "mcpServers": {
    "memtrace": {
      "command": "bun",
      "args": ["packages/mcp-server/src/server.ts"],
      "env": {
        "MEMTRACE_BASE_URL": "${MEMTRACE_BASE_URL}",
        "MEMTRACE_API_KEY": "${MEMTRACE_API_KEY}"
      }
    }
  }
}
```

Cursor-style config (`examples/mcp/cursor.json`) uses the same MCP server shape:

```json
{
  "mcpServers": {
    "memtrace": {
      "command": "bun",
      "args": ["packages/mcp-server/src/server.ts"],
      "env": {
        "MEMTRACE_BASE_URL": "${MEMTRACE_BASE_URL}",
        "MEMTRACE_API_KEY": "${MEMTRACE_API_KEY}"
      }
    }
  }
}
```

Available MCP tools are `memtrace_start_run`, `memtrace_start_step`, `memtrace_write_event`, `memtrace_retrieve_context`, `memtrace_inspect_access`, `memtrace_finish_step`, `memtrace_replay_access`, and `memtrace_report`. Tool responses are concise and redacted; replay/report responses are capped by default to avoid leaking large trace payloads into IDE chat context. Dedicated IDE extension packages are intentionally deferred until the MCP flow has real adoption feedback.

## Optional PostgreSQL + API mode

The deterministic quickstart above does not require Docker. To explore the SQL-backed runtime, start pgvector PostgreSQL with `docker-compose.yml`:

```bash
docker-compose up -d
uv run alembic upgrade head
uv run uvicorn app.main:app --app-dir apps/api --reload
```

Then check:

```bash
curl http://localhost:8000/health
```

The compose file uses `pgvector/pgvector:pg16` on host port `5433`. Existing PG15 volumes are not compatible with the PG16 image; switching images may require removing the old volume.

Optional async infrastructure for development lives in `docker-compose.dev.yml` and keeps the core PostgreSQL compose unchanged:

```bash
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up -d
MEMTRACE_ASYNC_TASKS_ENABLED=true \
MEMTRACE_REDIS_URL=redis://localhost:6379/0 \
MEMTRACE_CELERY_BROKER_URL=redis://localhost:6379/1 \
MEMTRACE_CELERY_RESULT_BACKEND=redis://localhost:6379/2 \
MEMTRACE_CELERY_TASK_ALWAYS_EAGER=false \
uv run uvicorn app.main:app --app-dir apps/api --reload
```

Real Redis smoke coverage is opt-in and skipped by default:

```bash
MEMTRACE_TEST_REDIS_URL=redis://localhost:6379/15 uv run --extra dev pytest apps/api/tests/integration/test_async_infra.py -q
```

## Optional real LLM validation bench

The real LLM bench is manual and opt-in because it requires network access and a live OpenAI-compatible API key:

```bash
MEMTRACE_LLM_API_KEY=... \
MEMTRACE_LLM_BASE_URL=https://ark.cn-beijing.volces.com/api/v3 \
MEMTRACE_LLM_MODEL=deepseek-v4-pro-260425 \
uv run python -m app.benchmark.llm_bench --output-dir reports
```

It writes `reports/llm_bench_report.json` and `reports/llm_bench_report.md`.

## Local verification

Run the full local smoke bundle:

```bash
./scripts/smoke.sh
```

Or run the pieces directly:

```bash
uv run pytest -q
./scripts/reproduce.sh
uv run python -m app.benchmark.runner --output-dir reports
```

## Roadmap

The completed MVP, Phase 3-A observability work, Context Compaction C0-C5 plus I7 retained-negative metadata, Failure-aware Negative Memory Injection I1-I7, Phase 3.5 SDK/LangGraph adapter/CLI work, the completed 6-strategy benchmark/eval-table slice, Security & Consistency Hardening, Provider Registry / Controlled Memory Key Ontology, Phase 4 platform work, TypeScript SDK, MCP server, MCP config templates, and future priorities are tracked in [`docs/design/ROADMAP.md`](docs/design/ROADMAP.md). For a narrative overview of the core idea, read [`docs/blog/why-agent-memory-is-not-just-rag.md`](docs/blog/why-agent-memory-is-not-just-rag.md). Current Phase 4 work has completed P4-A async foundation, P4-B lifecycle/reflection scheduler, P4-C memory versions/conflicts, and P4-D default-off governance; remaining roadmap candidates are OpenTelemetry/OpenInference exporter, advanced UI/dashboard, admin/manual governance depth, and advanced retrieval/storage work. A dedicated IDE extension remains deferred until MCP adoption feedback shows editor-specific needs.
