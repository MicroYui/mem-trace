# OpenTelemetry / OpenInference Exporter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` (recommended) or `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a default-off telemetry export layer that turns MemTrace runs, steps, events, retrieval accesses, gate decisions, profiler phases, replay/report summaries, and benchmark outcomes into redacted OpenTelemetry/OpenInference-compatible traces without changing runtime retrieval, gate, context-packing, or benchmark semantics.

**Architecture:** The exporter is a read-only observability projection. It consumes persisted runtime records and hot-path lifecycle hooks through narrow DTO builders, emits sanitized span/event attributes through a pluggable exporter sink, and never becomes the source of truth for trace, memory, replay, or policy state. Runtime hooks may build or enqueue spans, but they must not synchronously perform network OTLP export; OTLP delivery must use OpenTelemetry SDK batching or an internal best-effort queue. OpenTelemetry/OpenInference semantic mapping is implemented in MemTrace-owned code first; LangSmith/Phoenix/Langfuse are treated as OTLP/OpenInference-compatible destinations, not vendor SDK dependencies in this slice.

**Tech Stack:** Python 3.12, existing FastAPI/MemoryRuntime/Repository boundaries, existing `app.observability` modules, optional `opentelemetry-sdk` / `opentelemetry-exporter-otlp` extras, deterministic in-memory/file exporters for tests, existing redaction helpers, uv/pytest, optional HTTP OTLP smoke gated by env vars.

---

## 0. Source-Verified Current State

- `docs/design/ROADMAP.md` §6 tracks OpenTelemetry/OpenInference exporter as complete through Segment 4 closeout.
- `apps/api/app/telemetry/` now contains the exporter implementation: `models.py`, `semconv.py`, `redaction.py`, `builder.py`, `exporters.py`, `factory.py`, and `service.py`. Runtime hooks, FastAPI run export route, and public docs are implemented; CLI export and richer access/backfill surfaces remain deferred.
- Runtime semantics are already exposed through stable boundaries: `MemoryRuntime`, `Repository`, `/v1`, Python SDK/CLI, TypeScript SDK, and MCP server.
- Observability records already exist as Pydantic DTOs in `apps/api/app/runtime/models.py`: `AgentRun`, `AgentStep`, `AgentEvent`, `MemoryAccessLog`, `MemoryGateLog`, `ProfileEvent`, `ContextCompactionLog`, `ReplayRetrievalResult`, `ObservabilitySummary`, and report DTOs.
- Report/replay code already has defensive redaction paths in `apps/api/app/observability/reports.py` and `apps/api/app/observability/replay.py`; exporter output must reuse the same safety posture rather than inventing a weaker public surface.
- Provider Registry and retrieval policy snapshots are complete and non-secret by contract; exporter attributes may include policy version/hash/provider capability snapshots only after redaction and size caps.
- Governance/auth/quota remain default-off for local/dev/benchmark. The telemetry exporter must follow the same default-off rule and must never require network access in default tests or quickstarts.

---

## 1. Selected Scope and Non-Goals

### 1.1 Selected Scope

Implement **OTLP/OpenInference core exporter first**:

- Default-off exporter configuration in `Settings`.
- A semantic mapping layer from MemTrace DTOs to stable OpenTelemetry/OpenInference span names and attributes.
- A pluggable exporter protocol with:
  - `NoopTelemetryExporter` for the default path.
  - `InMemoryTelemetryExporter` for deterministic unit tests.
  - `JsonlTelemetryExporter` for local no-network smoke/debug output.
  - `OtlpTelemetryExporter` only when optional OTel dependencies and endpoint settings are present.
- Hot-path hooks for terminal run/step snapshots plus event/retrieval/profile lifecycle that are non-blocking, fail-open even if a strict service is injected, and never synchronously perform network export.
- A read-only run export API over persisted run/step/event records without mutating memory counters, replay state, or trace logs. Access-level export and richer backfill surfaces remain deferred future work.
- Docs and tests that demonstrate local JSONL output and optional OTLP export without making networked telemetry mandatory.

### 1.2 Non-Goals

- Do not add LangSmith, Phoenix, Langfuse, or other vendor SDK dependencies in this slice.
- Do not claim public support for any vendor destination until OTLP/OpenInference export is implemented and documented with clear configuration.
- Do not change retrieval, gate, context packing, compaction, negative-evidence, provider, governance, or benchmark algorithms.
- Do not make telemetry export required for default CI, benchmark, reproduce, release readiness smoke, or quickstart commands.
- Do not persist telemetry spans as a second source of truth in PostgreSQL. Existing runtime records remain authoritative.
- Do not export raw event content, raw memory content, raw failed-attempt text, API keys, auth headers, raw payload refs, destructive commands, or production-path markers.
- Do not build a React dashboard or observability UI in this slice.

---

## 2. Architecture and Data Flow

```text
MemoryRuntime / RetrievalController / Reports
  -> TelemetryEventBuilder (pure DTO -> redacted span/events)
  -> TelemetryExporter protocol
      -> NoopTelemetryExporter        (default)
      -> InMemoryTelemetryExporter    (tests)
      -> JsonlTelemetryExporter       (local smoke/debug)
      -> OtlpTelemetryExporter        (optional dependency + endpoint)
  -> external OTLP/OpenInference collector or local JSONL file
```

Key boundaries:

- **Builder is pure:** no repository writes, no network, no mutation of DTOs.
- **Exporter is replaceable:** tests inject memory/file sinks; production config can select OTLP.
- **Runtime hooks are best-effort:** failures create warnings/log messages and never fail agent runtime calls, even if a fail-closed `TelemetryService` is used for explicit tests/admin export outside the hot path. Hooks may build/enqueue spans, but OTLP network export must use batching/queueing and must not run synchronously inside `write_event`, `retrieve_context`, or other hot-path calls. Runtime hooks avoid duplicate lifecycle span ids by exporting run/step snapshots at terminal lifecycle boundaries rather than both start and finish.
- **Export/backfill is read-only:** the implemented run export endpoint reconstructs spans from persisted run/step/event rows without incrementing access counters or writing gate/profile rows. Access-level export and broader backfill remain future optional work.
- **OpenInference mapping is explicit:** `memtrace.*` attributes are the stable contract. OpenInference-compatible keys are emitted where safe and documented as a compatibility layer; downstream compatibility must not depend on exporting raw prompt, model response, memory, or failed-attempt content.

---

## 3. File Map

### New production files

- `apps/api/app/telemetry/__init__.py` — public telemetry package exports.
- `apps/api/app/telemetry/models.py` — internal `TelemetrySpan`, `TelemetryEvent`, `TelemetryAttributeValue`, `TelemetryExportResult` DTOs.
- `apps/api/app/telemetry/semconv.py` — span names, attribute keys, OpenInference/OpenTelemetry semantic constants, size limits.
- `apps/api/app/telemetry/redaction.py` — exporter-specific recursive redaction/capping helpers built on existing `app.memory.secrets` helpers.
- `apps/api/app/telemetry/builder.py` — pure mapping from MemTrace runtime/retrieval/profile/replay DTOs to telemetry spans/events.
- `apps/api/app/telemetry/exporters.py` — `TelemetryExporter` protocol plus noop, in-memory, JSONL, and optional OTLP implementations.
- `apps/api/app/telemetry/factory.py` — settings-driven exporter construction with optional dependency degradation.
- `apps/api/app/telemetry/service.py` — fail-open `TelemetryService` facade for `export_spans(...)`, `export_run_records(...)`, and `export_retrieval_records(...)`; runtime hooks and the minimal persisted run export surface are implemented, while access-level export/backfill helpers remain deferred.

### Existing production files to modify

- `apps/api/app/config.py` — add default-off telemetry settings.
- `apps/api/app/api/deps.py` — construct and expose `TelemetryService` through FastAPI dependency state.
- `apps/api/app/main.py` — wire telemetry service initialization if app state currently owns runtime/repository setup.
- `apps/api/app/runtime/memory_runtime.py` — add optional `telemetry_service` and best-effort hooks around run/step/event/retrieval lifecycle.
- `apps/api/app/retrieval/controller.py` — expose completed retrieval trace data to telemetry hooks without adding new persistence.
- `apps/api/app/api/routes.py` — add optional read-only export endpoint only after service-level tests exist.
- `apps/api/app/runtime/models.py` — add request/result DTOs for explicit export endpoint if needed.
- `apps/api/app/observability/reports.py` — optionally include telemetry export summary metadata in report output, never raw spans.
- `pyproject.toml` — add optional telemetry extra dependencies if OTLP implementation needs OTel packages.
- `README.md`, `docs/deployment.md`, `docs/concepts.md` — document exporter status and configuration after implementation.
- `docs/design/ROADMAP.md` and `.ai/*` — update progress as tasks complete.

### New tests

- `apps/api/tests/telemetry/test_redaction.py`
- `apps/api/tests/telemetry/test_builder.py`
- `apps/api/tests/telemetry/test_exporters.py`
- `apps/api/tests/telemetry/test_service.py`
- `apps/api/tests/runtime/test_memory_runtime_telemetry.py`
- `apps/api/tests/api/test_telemetry_export.py`
- `apps/api/tests/integration/test_telemetry_docs.py` if docs add machine-checked snippets.

---

## 3.1 Execution Segments

The detailed TEL-A/TEL-B/TEL-C/TEL-D/TEL-E/TEL-F checklist below is intentionally explicit for TDD handoff, but implementation should proceed in **four reviewable segments** rather than one large change or six fragmented closeouts:

1. **Segment 1 — Contracts, redaction, and pure builders:** TEL-A1, TEL-A2, TEL-B1, TEL-B2, and the minimal replay summary part of TEL-B3. This segment must not touch runtime hooks, API routes, CLI, or optional OTel dependencies.
2. **Segment 2 — Exporters, settings/factory, and service:** TEL-C1, TEL-C2, and TEL-D1. This segment establishes noop default behavior, deterministic in-memory/JSONL sinks, optional OTLP construction, and `TelemetryService` without changing hot paths.
3. **Segment 3 — Runtime hooks, optional export surface, and docs:** ✅ complete (2026-06-14). TEL-D2 runtime hooks are wired through `MemoryRuntime`; TEL-D3 minimal read-only run export endpoint is implemented; TEL-E2 docs are updated. CLI export remains deferred.
4. **Segment 4 — Verification and closeout:** ✅ complete (2026-06-14). TEL-F targeted/affected/full regression, compileall, benchmark/reproduce, release hygiene, diff checks, ROADMAP, and `.ai` sync are complete and final-review hardened. Default CI/reproduce/benchmark remain telemetry-free and vendor claims stay scoped to OTLP/OpenInference compatibility.

Checkpoint after each segment: targeted tests must pass, `git diff --check` must pass, and `.ai/PROJECT_STATE.md` should record the current segment if meaningful code landed.

---

## 4. Stream TEL-A — Telemetry Contracts, Semantic Mapping, and Redaction

### TEL-A1 Internal Telemetry DTOs and Semantic Constants

**Files:**
- Create: `apps/api/app/telemetry/__init__.py`
- Create: `apps/api/app/telemetry/models.py`
- Create: `apps/api/app/telemetry/semconv.py`
- Test: `apps/api/tests/telemetry/test_builder.py`

- [x] **Step 1: Write RED tests for stable span names and required attributes**
  - Assert builder constants include span names for `memtrace.run`, `memtrace.step`, `memtrace.event`, `memtrace.retrieve`, `memtrace.gate`, `memtrace.context_pack`, `memtrace.profile_phase`, `memtrace.replay`, and `memtrace.benchmark_case`.
  - Assert stable `memtrace.*` attribute keys include `memtrace.workspace_id`, `memtrace.run_id`, `memtrace.step_id`, `memtrace.access_id`, `memtrace.strategy`, `memtrace.gate.decision`, `memtrace.policy.version`, `memtrace.policy.hash`, `memtrace.context.block_count`, `memtrace.context.token_count`, and `memtrace.negative_evidence.count`.
  - Assert OpenInference-compatible keys such as `openinference.span.kind` are emitted only by documented compatibility helpers where safe; they are not the stable MemTrace contract.
  - Run: `uv run --extra dev pytest apps/api/tests/telemetry/test_builder.py -q`.
  - Expected RED: import failure for `app.telemetry`.

- [x] **Step 2: Add DTOs and constants**
  - Define `TelemetryEvent(name, attributes, timestamp)` and `TelemetrySpan(name, trace_id, span_id, parent_span_id, start_time, end_time, attributes, events, status)` as Pydantic models or dataclasses with OTLP-friendly JSON-safe attribute values.
  - Restrict `TelemetryAttributeValue` to primitives and lists of primitives (`str | bool | int | float | list[str | bool | int | float]`). `None` must be omitted during sanitization before constructing `TelemetrySpan` / `TelemetryEvent`; nested dict/list structures must be redacted and serialized into capped JSON-string attributes such as `memtrace.policy.snapshot_json`; do not pass arbitrary nested dicts directly to OTel SDK spans.
  - Define `TelemetryExportResult(exported_span_count, dropped_span_count, warnings)`.
  - Define semantic constants in one file; do not scatter string literals through builders/exporters.

- [x] **Step 3: Verify constants and DTO shape**
  - Run: `uv run --extra dev pytest apps/api/tests/telemetry/test_builder.py -q`.
  - Expected GREEN for import/constant/DTO tests.

### TEL-A2 Redaction and Attribute Budgeting

**Files:**
- Create: `apps/api/app/telemetry/redaction.py`
- Test: `apps/api/tests/telemetry/test_redaction.py`

- [x] **Step 1: Write RED tests for telemetry redaction**
  - Inputs must include nested dict/list payloads with `authorization`, `api_key`, `token`, `client_secret`, `secret_key`, `id_token`, `session_token`, `password`, `raw_payload_ref`, `rm -rf /prod`, `/prod`, `sk-...`, and benign `token_budget`.
  - Assert secret-like values are replaced with `[REDACTED]`, destructive command text is sanitized, `token_budget` is preserved, and nested structures are capped deterministically.
  - Run: `uv run --extra dev pytest apps/api/tests/telemetry/test_redaction.py -q`.
  - Expected RED: missing module.

- [x] **Step 2: Implement redaction helper**
  - Reuse `app.memory.secrets.redact(...)` and `is_secret_like_key(...)`.
  - Add exporter-specific caps: max string length, max list length, max dict keys, max serialized attribute bytes.
  - Return JSON-safe primitive/list/dict values only.

- [x] **Step 3: Verify redaction and cap behavior**
  - Run: `uv run --extra dev pytest apps/api/tests/telemetry/test_redaction.py -q`.
  - Expected GREEN.

---

## 5. Stream TEL-B — Pure Builders for Runtime, Retrieval, Replay, and Benchmark Records

### TEL-B1 Runtime Run/Step/Event Spans

**Files:**
- Create: `apps/api/app/telemetry/builder.py`
- Test: `apps/api/tests/telemetry/test_builder.py`

- [x] **Step 1: Write RED builder tests for run/step/event DTOs**
  - Build sample `AgentRun`, `AgentStep`, and `AgentEvent` objects.
  - Assert stable trace/span ids are derived from MemTrace ids without leaking content.
  - Assert event content is redacted or summarized; raw event text is not exported.
  - Assert status and timestamps map to span status/start/end fields.

- [x] **Step 2: Implement pure builders**
  - `build_run_span(run: AgentRun) -> TelemetrySpan`.
  - `build_step_span(step: AgentStep, run: AgentRun | None = None) -> TelemetrySpan`.
  - `build_event_span(event: AgentEvent) -> TelemetrySpan` or event-on-step representation, choosing the simpler stable shape and documenting it in `semconv.py`.
  - Keep the builder side-effect-free.

- [x] **Step 3: Verify runtime builder tests**
  - Run: `uv run --extra dev pytest apps/api/tests/telemetry/test_builder.py -q`.
  - Expected GREEN for runtime builders.

### TEL-B2 Retrieval, Gate, Context, and Profile Spans

**Files:**
- Modify: `apps/api/app/telemetry/builder.py`
- Test: `apps/api/tests/telemetry/test_builder.py`

- [x] **Step 1: Write RED tests for retrieval access mapping**
  - Create a `MemoryAccessLog`, `MemoryGateLog` list, and `ProfileEvent` list.
  - Assert a retrieve span includes strategy, token budget/actual tokens, accepted/rejected/degraded/warn counts, policy version/hash, context block counts, negative evidence counts, compaction counts, and profile phase child spans/events.
  - Assert `degrade` is counted as negative evidence, not accepted positive context.

- [x] **Step 2: Implement retrieval/profile builders**
  - `build_retrieval_span(access, gate_logs, profile_events, compaction_logs) -> TelemetrySpan`.
  - `build_gate_event(gate_log) -> TelemetryEvent` with safe reason/score attributes.
  - `build_profile_phase_span(profile_event, parent_span_id) -> TelemetrySpan` for phase-level latency.

- [x] **Step 3: Verify retrieval builder tests**
  - Run: `uv run --extra dev pytest apps/api/tests/telemetry/test_builder.py -q`.
  - Expected GREEN for retrieval/profile builders.

### TEL-B3 Replay, Report, and Benchmark Projection Builders

**Files:**
- Modify: `apps/api/app/telemetry/builder.py`
- Test: `apps/api/tests/telemetry/test_builder.py`

- [x] **Step 1: Write RED tests for replay/report/benchmark projection**
  - Replay span must include replay diff counts by severity and policy drift classification without exporting raw context blocks.
  - Benchmark span/event must include strategy, case id, task success, contamination metrics, negative evidence metrics, compaction metrics, and acceptance flags where present.
  - Generated attributes must be redacted and bounded.

- [x] **Step 2: Implement projection builders**
  - Add `build_replay_span(replay: ReplayRetrievalResult) -> TelemetrySpan`.
  - Add `build_benchmark_case_span(...)` around existing benchmark result records or runner output dicts.
  - Keep the mapping tolerant of missing optional metrics by using explicit present flags where benchmark acceptance already requires them.

- [x] **Step 3: Verify projection builders**
  - Run: `uv run --extra dev pytest apps/api/tests/telemetry/test_builder.py -q`.
  - Expected GREEN.

**Segment 1 checkpoint (2026-06-14):** TEL-A1/TEL-A2/TEL-B1/TEL-B2 and TEL-B3 minimal replay/benchmark projection are implemented as pure code only. Detailed review hardened the egress contract: telemetry attributes exclude `None`, raw-content-like metadata keys (`prompt`, `query`, `content`, `raw_context`, `messages`, `context_blocks`, etc.) are redacted, benign token metric spellings (`token_budget`, `token_count`, `token_input`, `token_output`, `input_tokens`, `output_tokens`) are preserved, benchmark projection uses an explicit metric allowlist, and optional-run-id spans fall back to stable record ids instead of a shared `unknown` trace. Historical next action after this checkpoint was Segment 2; Segments 2, 3, and 4 are now complete.

---

## 6. Stream TEL-C — Exporter Protocol and Default-Off Factory

### TEL-C1 Exporter Protocol, Noop, In-Memory, and JSONL Exporters

**Files:**
- Create: `apps/api/app/telemetry/exporters.py`
- Test: `apps/api/tests/telemetry/test_exporters.py`

- [x] **Step 1: Write RED exporter tests**
  - `NoopTelemetryExporter.export_spans(...)` returns zero exported and does not mutate input.
  - `InMemoryTelemetryExporter` records spans for assertions.
  - `JsonlTelemetryExporter` writes one redacted JSON object per span under a safe relative `reports/` path and rejects absolute/parent/symlink escapes.
  - JSONL write mode is explicit: default `mode="overwrite"` for deterministic tests/smoke; `mode="append"` is allowed only when configured/documented, and tests must prove repeated overwrite runs produce stable output.
  - Run: `uv run --extra dev pytest apps/api/tests/telemetry/test_exporters.py -q`.
  - Expected RED.

- [x] **Step 2: Implement exporters**
  - Define `TelemetryExporter` Protocol with `export_spans(spans: list[TelemetrySpan]) -> TelemetryExportResult` and optional concrete `shutdown()` for OTLP.
  - Implement noop, memory, JSONL, and lazy optional OTLP exporters.
  - Reuse report output-dir safety logic or factor a shared helper if duplication becomes risky.

- [x] **Step 3: Verify exporter tests**
  - Run: `uv run --extra dev pytest apps/api/tests/telemetry/test_exporters.py -q`.
  - Expected GREEN.

### TEL-C2 Optional OTLP Exporter and Settings Factory

**Files:**
- Modify: `apps/api/app/config.py`
- Create: `apps/api/app/telemetry/factory.py`
- Modify: `pyproject.toml`
- Test: `apps/api/tests/telemetry/test_exporters.py`
- Test: `apps/api/tests/telemetry/test_service.py`

- [x] **Step 1: Write RED tests for settings-driven factory**
  - With telemetry disabled or no endpoint, factory returns noop.
  - With `MEMTRACE_TELEMETRY_EXPORTER=jsonl`, factory returns JSONL exporter and requires safe `reports/...` path.
  - With `MEMTRACE_TELEMETRY_EXPORTER=otlp` but missing optional OTel dependency, factory degrades to noop with a warning unless strict mode is explicitly enabled.
  - With invalid endpoint scheme or embedded credentials, factory rejects config.

- [x] **Step 2: Add settings**
  - Add default-off settings such as:
    - `telemetry_enabled: bool = False`
    - `telemetry_exporter: Literal["noop", "jsonl", "otlp"] = "noop"`
    - `telemetry_otlp_endpoint: str | None = None`
    - `telemetry_headers: dict[str, str] = {}` with secret redaction and no logging.
    - `telemetry_jsonl_path: str = "reports/telemetry_spans.jsonl"`
    - `telemetry_strict: bool = False`
    - `telemetry_sample_rate: float = 1.0`
  - Validate sample rate in `[0.0, 1.0]` and endpoint as HTTP(S) without userinfo.

- [x] **Step 3: Implement factory and optional OTLP wrapper**
  - Import OTel packages lazily inside the OTLP exporter.
  - Do not require optional dependencies for default tests.
  - Convert internal `TelemetrySpan` objects to OTel spans/attributes in one place.
  - OTLP export must use OTel SDK batching (`BatchSpanProcessor`) or an internal best-effort queue. Do not call a network exporter synchronously from runtime hook methods.

- [x] **Step 4: Verify factory tests**
  - Run: `uv run --extra dev pytest apps/api/tests/telemetry/test_exporters.py apps/api/tests/telemetry/test_service.py -q`.
  - Expected GREEN.

---

## 7. Stream TEL-D — TelemetryService and Runtime/API Integration

### TEL-D1 TelemetryService Facade

**Files:**
- Create: `apps/api/app/telemetry/service.py`
- Test: `apps/api/tests/telemetry/test_service.py`

- [x] **Step 1: Write RED service tests**
  - Service exports run/step/event/retrieval spans using injected `InMemoryTelemetryExporter`.
  - Exporter exceptions are captured as warnings and do not propagate when strict mode is false.
  - Strict mode propagates exporter errors only in explicit service tests; runtime defaults remain non-strict.

- [x] **Step 2: Implement service**
  - Add service methods `export_spans`, `export_run_records`, and `export_retrieval_records` for already-built spans and read-only record projections.
  - Keep repository interactions out of Segment 2; explicit persisted snapshot/backfill helpers remain Segment 3/optional surface work.

- [x] **Step 3: Verify service tests**
  - Run: `uv run --extra dev pytest apps/api/tests/telemetry/test_service.py -q`.
- Expected GREEN.

**Segment 2 checkpoint (2026-06-14):** TEL-C1/TEL-C2/TEL-D1 are implemented without runtime hot-path changes. Added `exporters.py` (`NoopTelemetryExporter`, `InMemoryTelemetryExporter`, `JsonlTelemetryExporter`, optional lazy `OtlpTelemetryExporter`), `factory.py` (default-off settings construction, safe JSONL `reports/...` path validation including symlink escape rejection for directory components and final file, OTLP endpoint/no-userinfo validation, dependency degradation, settings-driven service construction), `service.py` (`TelemetryService` fail-open facade plus run/retrieval record projection), default-off config settings, optional `telemetry` Python extra, and focused tests. Post-review hardening ensures event attributes are redacted for in-memory/JSONL/OTLP exporters, OTLP conversion preserves internal trace/parent context where possible, `telemetry_fail_open` is consumed by `build_telemetry_service(...)`, and service fail-open covers builder/projection errors. Runtime hooks, API endpoint, CLI export command, persisted snapshot/backfill helpers, and public docs remain deferred to Segment 3.

### TEL-D2 Best-Effort Runtime Hooks

**Files:**
- Modify: `apps/api/app/runtime/memory_runtime.py`
- Modify: `apps/api/app/retrieval/controller.py` only if the runtime needs trace data that is not currently returned.
- Test: `apps/api/tests/runtime/test_memory_runtime_telemetry.py`

- [x] **Step 1: Write RED runtime integration tests**
  - Inject `TelemetryService(InMemoryTelemetryExporter)` into `MemoryRuntime`.
  - Start run, start/finish step, write event, retrieve context.
  - Assert spans are emitted with expected ids and no raw event/memory content.
  - Assert runtime lifecycle hooks do not export duplicate span ids for the same run/step lifecycle.
  - Configure an exporter that raises, including fail-closed service mode, and assert runtime calls still succeed.

- [x] **Step 2: Wire runtime hooks**
  - Add optional `telemetry_service: TelemetryService | None = None` to `MemoryRuntime` constructor.
  - Call hooks after authoritative persistence succeeds, not before.
  - Export terminal run/step snapshots only once per lifecycle id; do not emit start and finish spans with the same span id.
  - Do not add duplicate access/gate/profile writes.
  - Do not let telemetry export run before workspace mismatch checks or other side-effect guards.

- [x] **Step 3: Verify runtime integration tests**
  - Run: `uv run --extra dev pytest apps/api/tests/runtime/test_memory_runtime_telemetry.py -q`.
  - Expected GREEN.

### TEL-D3 FastAPI Dependency and Read-Only Export Endpoint (Optional / Second Batch)

**Files:**
- Modify: `apps/api/app/api/deps.py`
- Modify: `apps/api/app/main.py`
- Modify: `apps/api/app/api/routes.py`
- Modify: `apps/api/app/runtime/models.py`
- Test: `apps/api/tests/api/test_telemetry_export.py`

- [x] **Step 0: Confirm endpoint scope before implementation**
  - This endpoint is optional in the first exporter slice. Implement it only after TEL-A/TEL-B/TEL-C/TEL-D1/TEL-D2 are stable and service-level read-only export is covered.
  - If it would force broad SDK/CLI/docs changes, defer it and record the deferral in ROADMAP/`.ai` rather than partially exposing a new public HTTP surface.

- [x] **Step 1: Write RED API tests**
  - Default settings return no telemetry side effects.
  - `POST /v1/telemetry/export/runs/{run_id}` or equivalent explicit endpoint requires reader/report permission for the run workspace when auth is enabled.
  - Missing run returns 404; unauthorized existing run returns 403; default-off anonymous local path follows existing auth behavior.
  - Governance quota uses the existing `report_export` unit so this egress surface cannot bypass report/export abuse controls.
  - Endpoint returns span counts and warnings, not raw spans by default.

- [x] **Step 2: Add DTOs and route**
  - Add `TelemetryExportRequest(include_replay: bool = False, include_profiles: bool = True)` and `TelemetryExportResult` reuse if appropriate.
  - Route calls `TelemetryService.export_run_snapshot(...)` or access equivalent.
  - Keep response concise; do not return full raw telemetry payload unless a future explicit debug flag is designed.

- [x] **Step 3: Verify API tests**
  - Run: `uv run --extra dev pytest apps/api/tests/api/test_telemetry_export.py -q`.
  - Expected GREEN.

---

## 8. Stream TEL-E — Reports, Optional CLI/API Surface, and Documentation

### TEL-E1 Observability Report and Optional CLI Integration

**Files:**
- Modify: `apps/api/app/observability/reports.py`
- Modify: `packages/python-sdk/src/memtrace_sdk/cli.py` if CLI exposes explicit export command.
- Test: `packages/python-sdk/tests/test_cli.py`
- Test: `apps/api/tests/observability/test_reports.py` if present, otherwise nearest report test file.

- [x] **Step 1: Document report/CLI deferral instead of adding a second egress surface**
  - Observability reports do not embed raw telemetry spans in this slice.
  - CLI telemetry-export is explicitly deferred; no CLI tests are required until that command is selected as a separate surface.

- [x] **Step 2: Keep user-facing command path deferred**
  - Document JSONL configuration and the minimal service/API run export usage.
  - Defer any command such as `memtrace telemetry-export --http --run-id ... --output reports/telemetry_spans.jsonl` until SDK/CLI contract work is explicitly selected.
  - Do not half-implement a CLI surface that duplicates HTTP client semantics without redaction/capping/authz tests.

- [x] **Step 3: Verify docs/deferred-surface scope**
  - Runtime/API/docs verification covers JSONL/API usage and confirms reports/CLI do not expose raw spans in this slice.

### TEL-E2 User Docs and Public Claims

**Files:**
- Modify: `README.md`
- Modify: `docs/deployment.md`
- Modify: `docs/concepts.md`
- Optional create: `docs/telemetry.md` if README/deployment sections become too long.
- Modify: `docs/design/ROADMAP.md`
- Modify: `.ai/PROJECT_STATE.md`, `.ai/REQUIREMENTS.md`, `.ai/IMPLEMENTATION_PLAN.md`, `.ai/OPEN_QUESTIONS.md`, `.ai/DECISIONS.md`, `.ai/PITFALLS.md`, `.ai/ARCHITECTURE_SUMMARY.md`

- [x] **Step 1: Update docs only after exporter tests pass**
  - Document default-off telemetry settings and local JSONL smoke.
  - Document optional OTLP endpoint configuration and dependency requirements.
  - State that LangSmith/Phoenix/Langfuse are possible OTLP/OpenInference destinations only if configured externally; do not claim vendor SDK integration.
  - Include redaction/safety guarantees and known non-goals.

- [x] **Step 2: Sync project memory**
  - Mark TEL-A/TEL-B/TEL-C/TEL-D progress as completed only as each stream lands.
  - Keep current selected target as this plan until final closeout.
  - After final closeout, update next recommended action from ROADMAP.

- [x] **Step 3: Verify docs**
  - Run `bash scripts/check-release-hygiene.sh` to ensure public docs do not include fake real secrets or unsafe raw commands.
  - Run `git diff --check`.

**Segment 3 checkpoint (2026-06-14):** TEL-D2/TEL-D3/TEL-E2 are implemented and detailed-review hardened. `MemoryRuntime` accepts an optional `TelemetryService` and emits best-effort terminal run/step snapshots plus event/retrieval spans after authoritative persistence succeeds; runtime hooks catch telemetry failures even if the service is fail-closed and avoid duplicate stable run/step lifecycle span ids. `AppState` builds the settings-driven service and injects it into runtime. `POST /v1/telemetry/export/runs/{run_id}` performs a read-only run/step/event projection with existing report-reader authz, consumes the existing `report_export` quota unit, and returns only counts/warnings. Public docs cover default-off JSONL, optional OTLP, vendor non-goals, and CLI export deferral. TEL-E1 CLI export remains intentionally deferred; report output does not include raw spans.

---

## 9. Stream TEL-F — Verification, Optional OTLP Smoke, and Closeout

### TEL-F1 Affected Regression and Default Path Verification

**Files:**
- No new files unless tests uncover missing coverage.

- [x] **Step 1: Run telemetry suite**
  - Command: `uv run --extra dev pytest apps/api/tests/telemetry apps/api/tests/runtime/test_memory_runtime_telemetry.py apps/api/tests/api/test_telemetry_export.py -q`.
  - Result: historical closeout **40 passed**; after Segment 3 detailed-review hardening **42 passed**; after final full-plan review hardening **51 passed**.

- [x] **Step 2: Run affected observability/runtime suites**
  - Command: `uv run --extra dev pytest apps/api/tests/runtime apps/api/tests/api apps/api/tests/observability -q`.
  - Result: historical closeout **189 passed**; after Segment 3 detailed-review hardening **191 passed**; after final full-plan review hardening **194 passed**.

- [x] **Step 3: Compile**
  - Command: `uv run --extra dev python -m compileall -q apps/api/app packages/python-sdk/src examples`.
  - Result: passed.

### TEL-F2 Optional OTLP Smoke

**Files:**
- Optional test: `apps/api/tests/telemetry/test_otlp_smoke.py`

- [x] **Step 1: Add env-gated smoke if practical**
  - Gate with `MEMTRACE_TEST_OTLP_ENDPOINT`.
  - Skip by default with a clear message.
  - Use a local collector endpoint if available; do not require external SaaS.
  - Result: not added in this slice; optional OTLP remains covered by factory/exporter degradation tests and no external collector is required by default verification.

- [x] **Step 2: Verify default skip behavior**
  - Run: `uv run --extra dev pytest apps/api/tests/telemetry/test_otlp_smoke.py -q`.
  - Result: not applicable because no env-gated smoke file was added.

### TEL-F3 Full Closeout

**Files:**
- Modify: `docs/design/ROADMAP.md`
- Modify: `.ai/*` memory files as appropriate.

- [x] **Step 1: Full regression**
  - Command: `uv run --extra dev pytest -q`.
  - Result: historical closeout **647 passed, 2 skipped**; after Segment 3 detailed-review hardening **649 passed, 2 skipped**; after final full-plan review hardening **658 passed, 2 skipped**.

- [x] **Step 2: JS verification if public docs/SDK/MCP examples changed**
  - Command: `npm exec --yes --package bun -- bun run typecheck`.
  - Command: `npm exec --yes --package bun -- bun test`.
  - Result: not rerun; this segment changed Python/API/docs only and no JS package/example files changed.

- [x] **Step 3: Benchmark/reproduce non-regression**
  - Command: `uv run python -m app.benchmark.runner --output-dir reports`.
  - Command: `bash scripts/reproduce.sh`.
  - Result: reproduce printed `acceptance.passed=true (13/13 checks true)`.

- [x] **Step 4: Release hygiene and diff check**
  - Command: `bash scripts/check-release-hygiene.sh`.
  - Command: `git diff --check`.
  - Result: `release hygiene checks passed`; `git diff --check` passed.

- [x] **Step 5: Project-memory closeout**
  - Mark `docs/design/OTEL_OPENINFERENCE_EXPORTER_PLAN.md` completed in `docs/design/ROADMAP.md` and `.ai` memory.
  - Record changed files and verification results in `.ai/PROJECT_STATE.md`.
  - Add pitfalls discovered during implementation to `.ai/PITFALLS.md`.
  - Identify the next roadmap target after exporter closeout.

**Segment 4 checkpoint (2026-06-14):** TEL-F closeout is complete and was rerun after Segment 3 detailed-review hardening and a final full-plan review. Final hardening moved JSONL path safety into the exporter itself, added strict/header/sample-rate settings coverage, made public telemetry warnings generic, kept retrieval telemetry projection fully fail-open, guarded repeated terminal run/step lifecycle calls from exporting duplicate stable span ids, and removed stale ROADMAP/`.ai` wording that still pointed at OTel as the next target. Final targeted telemetry/runtime/API suite passed (**51 passed**), affected runtime/API/observability suite passed (**194 passed**), compileall passed, full pytest passed (**658 passed, 2 skipped**), benchmark/reproduce preserved current global acceptance (`acceptance.passed=true (13/13 checks true)`), release hygiene passed, and `git diff --check` passed. No env-gated OTLP collector smoke was added; optional OTLP remains default-off and covered by factory/exporter degradation tests.

---

## 10. Acceptance Criteria

The core exporter slice is complete only when all criteria are true:

- Default configuration remains `telemetry_enabled=false` / noop and default CI does not require network telemetry.
- Telemetry builder tests prove run/step/event/retrieval/gate/profile/replay/benchmark spans are stable and redacted.
- Exporter tests prove noop, in-memory, JSONL, and optional OTLP factory behavior.
- Runtime integration tests prove telemetry export is best-effort and cannot break agent hot-path calls.
- Docs expose an explicit local JSONL and optional OTLP export path without leaking raw spans by default. HTTP API and CLI surfaces are not required for the core slice if they are explicitly deferred after service-level export is implemented and documented.
- Public docs truthfully state what is implemented and do not claim direct vendor SDK integration.
- Release hygiene passes after docs changes.
- Full Python regression passes; JS checks pass if JS/docs examples changed.
- Deterministic benchmark/reproduce acceptance remains at current global `13/13` unless a deliberate benchmark expansion updates all counts and docs.

---

## 11. Key Risks and Guardrails

- **Secret leakage risk:** Telemetry is an external egress surface. Redact recursively by key semantics and value regex before export; cap payload sizes; never export raw content or raw replay context blocks.
- **Hot-path reliability risk:** Export must happen after authoritative writes and fail open by default. No exporter error should change runtime results.
- **Semantic drift risk:** Keep span names and attribute keys centralized in `semconv.py`; tests should lock important names so downstream dashboards do not silently break.
- **Dependency risk:** OTel dependencies must be optional. Import them lazily and degrade to noop with warnings unless strict mode is explicitly set.
- **Policy drift confusion:** Export policy version/hash/snapshot summaries as observability metadata, but never recompute or override retrieval policy semantics in telemetry code.
- **Vendor overclaim risk:** LangSmith/Phoenix/Langfuse remain destination examples only; no vendor-specific support claim until separate bridge work exists.
