# OTel/OpenInference Segment 3 Runtime Hooks and Export Surface Design

## Scope

Implement Segment 3 of `docs/design/OTEL_OPENINFERENCE_EXPORTER_PLAN.md` using the already-completed Segment 1/2 telemetry builders, exporters, factory, and `TelemetryService` facade.

Included:

- TEL-D2 best-effort runtime hooks in `MemoryRuntime`.
- TEL-D3 minimal read-only HTTP export endpoint for a run.
- TEL-E1 minimal report/export-surface documentation; no CLI command in this slice.
- TEL-E2 user docs and project-memory sync.

Excluded:

- No LangSmith/Phoenix/Langfuse vendor SDK bridge.
- No required OTLP/network dependency in default CI, benchmark, reproduce, or quickstart.
- No raw span payload in HTTP responses.
- No CLI `telemetry-export` command; document it as deferred.

## Architecture

`MemoryRuntime` accepts an optional `TelemetryService`. Runtime hooks execute only after authoritative persistence succeeds and call the existing service methods/builders. Hook failures are swallowed by the fail-open service and must never affect runtime results.

FastAPI `AppState` builds the telemetry service from settings once at startup and injects it into `MemoryRuntime`. Default settings still build a noop service and do not create files, import OpenTelemetry SDKs, or perform network calls.

The optional HTTP surface is a concise explicit endpoint:

```http
POST /v1/telemetry/export/runs/{run_id}
```

It checks existing run workspace ownership and `report_reader` permissions, exports run/step/event records through the service, and returns only counts and warnings.

## Data Flow

Runtime lifecycle path:

```text
MemoryRuntime method
  -> validate guards and persist authoritative records
  -> TelemetryService export helper
  -> configured exporter (noop/jsonl/otlp/in-memory)
```

Explicit export path:

```text
POST /v1/telemetry/export/runs/{run_id}
  -> authz report_reader for run workspace
  -> read run timeline and steps
  -> TelemetryService.export_run_records(...)
  -> count/warning response only
```

Retrieval runtime hooks export spans after `retrieve_context(...)` returns. They reconstruct telemetry from persisted access inspection records where possible, without writing new access/gate/profile rows or incrementing counters.

## Error Handling and Safety

- Telemetry remains fail-open by default.
- Hooks run after workspace mismatch checks and after persistence, never before side-effect guards.
- HTTP export returns 404 for missing runs and 403 for unauthorized existing runs under auth/governance.
- Telemetry redaction remains centralized in the Segment 1/2 builder/exporter stack.
- HTTP export does not return raw spans or raw event/memory/context content.
- OTLP network behavior stays behind optional exporter batching/lazy construction; runtime hooks do not directly perform network I/O.

## Testing

Add tests before implementation:

- `apps/api/tests/runtime/test_memory_runtime_telemetry.py`
  - lifecycle spans emitted for run/step/event/retrieval paths;
  - raw event content is not exported;
  - exporter failures do not break runtime calls.
- `apps/api/tests/api/test_telemetry_export.py`
  - run export endpoint returns counts/warnings;
  - missing run returns 404;
  - authz uses existing report-reader semantics;
  - endpoint does not return raw spans.

Verification includes telemetry targeted suite, affected runtime/API suites, compileall, full pytest, release hygiene, benchmark/reproduce non-regression, and `git diff --check`.

## Documentation

Update public docs after tests pass:

- telemetry is default-off;
- local JSONL smoke/debug path;
- optional OTLP endpoint and optional dependency requirements;
- LangSmith/Phoenix/Langfuse are external OTLP/OpenInference destinations only, not direct SDK integrations;
- CLI telemetry export is deferred.

Update `docs/design/ROADMAP.md` and `.ai/*` memory to mark Segment 3 complete and keep final Segment 4 closeout as the next task if full closeout remains pending.
