# go-trace-collector (scale-only)

A thin, high-throughput trace ingestion gateway for MemTrace — **not part of the
default deployment**. Trigger condition (ROADMAP §6 / architecture §3.2): the
Python ingestion QPS becomes a real bottleneck. Until then, agents talk to the
Python runtime's `/v1/events` directly.

## What it does

Accepts agent trace events over HTTP (`POST /collect/events`), validates they are
JSON, buffers them, and forwards each unchanged to the MemTrace runtime's
`/v1/events`. It **never interprets** events: the Python runtime remains the
source of truth and owns all memory / state-tree / gate / compaction semantics.
This collector only buffers and forwards, so it cannot drift from runtime
behavior.

## Config (environment)

| Var | Default | Meaning |
|-----|---------|---------|
| `COLLECTOR_LISTEN_ADDR` | `:8088` | Listen address |
| `MEMTRACE_BASE_URL` | `http://localhost:8000` | MemTrace runtime base URL |
| `MEMTRACE_API_KEY` | _(none)_ | Optional bearer token forwarded upstream |

## Build & run

Requires Go 1.22+ (not bundled; default CI does not build this component):

```bash
cd components/go-trace-collector
go build ./...
go vet ./...
./go-trace-collector
```

## Boundary

Thin over `/v1`; no duplication of Python runtime semantics. If richer behavior
is ever needed, add it to the Python runtime, not here.
