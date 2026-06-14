# OTel/OpenInference Segment 3 Runtime Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire default-off telemetry into MemTrace runtime lifecycle, add a minimal read-only run export API, and document JSONL/OTLP usage without changing retrieval, gate, context-packing, or benchmark semantics.

**Architecture:** Reuse Segment 1/2 `TelemetryService` and builders. Inject an optional service into `MemoryRuntime`, call it after authoritative persistence succeeds, and expose one explicit FastAPI run-export endpoint that returns only counts/warnings. Keep CLI export deferred and docs scoped to JSONL/runtime hooks plus HTTP run export.

**Tech Stack:** Python 3.12, FastAPI, existing `MemoryRuntime`/`Repository` abstractions, Pydantic DTOs, pytest, existing telemetry builders/exporters/factory.

---

## File Map

- Modify `apps/api/app/runtime/memory_runtime.py`: accept optional `TelemetryService`, add best-effort hook helpers, call hooks after persisted run/step/event/retrieval lifecycle operations.
- Modify `apps/api/app/api/deps.py`: build telemetry service from settings and expose `get_telemetry_service` dependency.
- Modify `apps/api/app/api/routes.py`: add `POST /v1/telemetry/export/runs/{run_id}` route with report-reader authz.
- Modify `apps/api/app/runtime/models.py`: add concise telemetry export request/response DTOs.
- Modify `apps/api/app/telemetry/service.py`: add service-level step/event helpers if needed.
- Create `apps/api/tests/runtime/test_memory_runtime_telemetry.py`: runtime hook tests.
- Create `apps/api/tests/api/test_telemetry_export.py`: HTTP endpoint tests.
- Modify docs and project memory after tests pass.

---

### Task 1: Runtime Hook Tests

**Files:**
- Create: `apps/api/tests/runtime/test_memory_runtime_telemetry.py`
- Reference: `apps/api/tests/runtime/test_memory_runtime_trace.py`
- Reference: `apps/api/tests/telemetry/test_service.py`

- [x] **Step 1: Write the failing lifecycle hook test**

Create a test that constructs `MemoryRuntime` with `InMemoryRepository` and `TelemetryService(InMemoryTelemetryExporter)`, performs start run, start step, write event, finish step, and retrieve context, then asserts telemetry spans exist and raw event content is absent.

```python
from app.runtime.memory_runtime import MemoryRuntime
from app.runtime.models import FinishStepRequest, RetrievalRequest, StartRunRequest, StartStepRequest, StepStatus, WriteEventRequest
from app.runtime.repository import InMemoryRepository
from app.telemetry.exporters import InMemoryTelemetryExporter
from app.telemetry.service import TelemetryService


async def test_runtime_hooks_emit_redacted_spans_after_successful_lifecycle() -> None:
    exporter = InMemoryTelemetryExporter()
    rt = MemoryRuntime(InMemoryRepository(), telemetry_service=TelemetryService(exporter=exporter))

    run = await rt.start_run(StartRunRequest(session_id="s1", task="use Bun for tests", workspace_id="ws1"))
    step = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="implement"))
    result = await rt.write_event(
        WriteEventRequest(
            run_id=run.run_id,
            step_id=step.step_id,
            role="user",
            event_type="message",
            content="raw secret-ish user prompt with password=hunter2 and use bun",
        )
    )
    await rt.finish_step(FinishStepRequest(run_id=run.run_id, step_id=step.step_id, status=StepStatus.completed))
    context = await rt.retrieve_context(RetrievalRequest(run_id=run.run_id, query="what package manager?"))

    names = [span.name for span in exporter.spans]
    assert "memtrace.run" in names
    assert "memtrace.step" in names
    assert "memtrace.event" in names
    assert "memtrace.retrieve" in names
    rendered = "\n".join(span.model_dump_json() for span in exporter.spans)
    assert result.event.event_id in rendered
    assert context.access_id in rendered
    assert "hunter2" not in rendered
    assert "raw secret-ish user prompt" not in rendered
```

- [x] **Step 2: Run the test to verify it fails**

Run: `uv run --extra dev pytest apps/api/tests/runtime/test_memory_runtime_telemetry.py -q`

Expected: fail because `MemoryRuntime.__init__` does not accept `telemetry_service`.

- [x] **Step 3: Write the failing fail-open test**

```python
class RaisingExporter:
    def export_spans(self, spans):
        raise RuntimeError("telemetry sink unavailable")


async def test_runtime_telemetry_failures_do_not_break_hot_path() -> None:
    rt = MemoryRuntime(InMemoryRepository(), telemetry_service=TelemetryService(exporter=RaisingExporter()))
    run = await rt.start_run(StartRunRequest(session_id="s1", task="task", workspace_id="ws1"))
    step = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="work"))
    result = await rt.write_event(WriteEventRequest(run_id=run.run_id, step_id=step.step_id, role="user", event_type="message", content="use bun"))
    assert result.event.run_id == run.run_id
```

- [x] **Step 4: Run runtime telemetry tests and verify RED**

Run: `uv run --extra dev pytest apps/api/tests/runtime/test_memory_runtime_telemetry.py -q`

Expected: fail until runtime hook wiring exists.

---

### Task 2: Implement TEL-D2 Runtime Hooks

**Files:**
- Modify: `apps/api/app/runtime/memory_runtime.py`
- Modify: `apps/api/app/telemetry/service.py`
- Test: `apps/api/tests/runtime/test_memory_runtime_telemetry.py`

- [x] **Step 1: Add optional service constructor argument**

In `MemoryRuntime.__init__`, add `telemetry_service: TelemetryService | None = None` and store `self._telemetry_service = telemetry_service`.

- [x] **Step 2: Add service-level convenience methods**

In `apps/api/app/telemetry/service.py`, add:

```python
def export_step_record(self, *, step: AgentStep, run: AgentRun | None = None) -> TelemetryExportResult:
    try:
        return self.export_spans([builder.build_step_span(step, run=run)])
    except Exception as exc:
        return self._handle_failure(exc)


def export_event_record(self, *, event: AgentEvent) -> TelemetryExportResult:
    try:
        return self.export_spans([builder.build_event_span(event)])
    except Exception as exc:
        return self._handle_failure(exc)
```

- [x] **Step 3: Add runtime telemetry helpers**

Add private helpers in `MemoryRuntime` that call the service only when non-`None`:

```python
def _export_run_telemetry(self, run: AgentRun) -> None:
    if self._telemetry_service is not None:
        self._telemetry_service.export_run_records(run=run)


def _export_step_telemetry(self, step: AgentStep, *, run: AgentRun | None = None) -> None:
    if self._telemetry_service is not None:
        self._telemetry_service.export_step_record(step=step, run=run)


def _export_event_telemetry(self, event: AgentEvent) -> None:
    if self._telemetry_service is not None:
        self._telemetry_service.export_event_record(event=event)
```

- [x] **Step 4: Add read-only retrieval export helper**

Use existing `inspect_access(access_id)` to retrieve persisted access/gate/profile/compaction views. Build lists from that result and call `export_retrieval_records(...)`. Do not call replay or retrieve again.

- [x] **Step 5: Call hooks after successful persistence**

Add calls after persistence in `start_run`, `start_step`, `write_event`, `finish_step`, `complete_run`, and after `retrieve_context` returns a context with `access_id`.

- [x] **Step 6: Run runtime telemetry tests and verify GREEN**

Run: `uv run --extra dev pytest apps/api/tests/runtime/test_memory_runtime_telemetry.py -q`

Expected: all tests pass.

---

### Task 3: API Export Endpoint Tests

**Files:**
- Create: `apps/api/tests/api/test_telemetry_export.py`
- Reference: `apps/api/tests/api/test_routes.py`
- Reference: `apps/api/tests/api/test_auth.py`

- [x] **Step 1: Write failing endpoint success test**

Create an ASGI client with dependency overrides for runtime and telemetry service. Create a run and event, call `POST /v1/telemetry/export/runs/{run_id}`, and assert the JSON response includes `exported_span_count`, `dropped_span_count`, and `warnings`, but no `spans` field and no raw content.

- [x] **Step 2: Write failing missing run test**

Assert `POST /v1/telemetry/export/runs/missing` returns 404 with `detail == "run not found"`.

- [x] **Step 3: Write failing authz test**

Reuse existing auth dependency override patterns. For an existing run, require `report_reader`; a principal without permission should get 403.

- [x] **Step 4: Run API telemetry tests and verify RED**

Run: `uv run --extra dev pytest apps/api/tests/api/test_telemetry_export.py -q`

Expected: route/DTO/dependency not found.

---

### Task 4: Implement TEL-D3 API Export Surface

**Files:**
- Modify: `apps/api/app/runtime/models.py`
- Modify: `apps/api/app/api/deps.py`
- Modify: `apps/api/app/api/routes.py`
- Test: `apps/api/tests/api/test_telemetry_export.py`

- [x] **Step 1: Add API DTOs**

In `runtime/models.py`, add:

```python
class TelemetryExportRequest(BaseModel):
    include_steps: bool = True
    include_events: bool = True


class TelemetryExportResponse(BaseModel):
    exported_span_count: int = 0
    dropped_span_count: int = 0
    warnings: list[str] = Field(default_factory=list)
```

- [x] **Step 2: Add telemetry service dependency**

In `api/deps.py`, import `build_telemetry_service` and `TelemetryService`, add `self.telemetry_service`, build it in `startup()`, pass it to `MemoryRuntime`, and expose `get_telemetry_service()`.

- [x] **Step 3: Add route**

In `api/routes.py`, add:

```python
@router.post("/telemetry/export/runs/{run_id}", response_model=TelemetryExportResponse)
async def export_run_telemetry(...):
    workspace_id = await _workspace_for_run_or_404(rt, run_id)
    _authz(principal, workspace_id, WorkspacePermission.report_reader)
    run = await rt.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    steps = await rt.get_steps(run_id) if req.include_steps else []
    events = await rt.get_timeline(run_id) if req.include_events else []
    result = telemetry.export_run_records(run=run, steps=steps, events=events)
    return TelemetryExportResponse(exported_span_count=result.exported_span_count, dropped_span_count=result.dropped_span_count, warnings=result.warnings)
```

If `MemoryRuntime.get_run` does not exist, add a read-only method that returns `await self._repo.get_run(run_id)`.

- [x] **Step 4: Run API tests and verify GREEN**

Run: `uv run --extra dev pytest apps/api/tests/api/test_telemetry_export.py -q`

Expected: pass.

---

### Task 5: Documentation and Project Memory

**Files:**
- Modify: `README.md`
- Modify: `docs/concepts.md`
- Modify: `docs/deployment.md`
- Modify: `docs/design/OTEL_OPENINFERENCE_EXPORTER_PLAN.md`
- Modify: `docs/design/ROADMAP.md`
- Modify: `.ai/PROJECT_STATE.md`
- Modify: `.ai/REQUIREMENTS.md`
- Modify: `.ai/IMPLEMENTATION_PLAN.md`
- Modify: `.ai/PITFALLS.md`
- Modify: `.ai/ARCHITECTURE_SUMMARY.md`

- [x] **Step 1: Update user docs**

Document default-off telemetry, JSONL local smoke, optional OTLP endpoint and dependency requirements, HTTP run export counts/warnings response, CLI export deferral, and vendor non-goals.

- [x] **Step 2: Update plan/progress docs**

Mark TEL-D2/TEL-D3/TEL-E2 complete and TEL-E1 CLI deferred in the OTel plan and ROADMAP. Keep Segment 4 closeout as next unless full closeout is completed in this session.

- [x] **Step 3: Update `.ai` memory**

Record changed files, verification status, and pitfalls discovered.

- [x] **Step 4: Run hygiene checks for docs**

Run: `bash scripts/check-release-hygiene.sh && git diff --check`

Expected: both pass.

---

### Task 6: Verification Closeout

**Files:**
- No new production files unless failures require fixes.

- [x] **Step 1: Run telemetry targeted suite**

Run: `uv run --extra dev pytest apps/api/tests/telemetry apps/api/tests/runtime/test_memory_runtime_telemetry.py apps/api/tests/api/test_telemetry_export.py -q`

Result: **40 passed**.

- [x] **Step 2: Run affected runtime/API/observability suites**

Run: `uv run --extra dev pytest apps/api/tests/runtime apps/api/tests/api apps/api/tests/observability -q`

Result: **189 passed**.

- [x] **Step 3: Compile Python**

Run: `uv run --extra dev python -m compileall -q apps/api/app packages/python-sdk/src examples`

Result: passed.

- [x] **Step 4: Run full Python regression**

Run: `uv run --extra dev pytest -q`

Result: **647 passed, 2 skipped**.

- [x] **Step 5: Run benchmark/reproduce**

Run: `uv run python -m app.benchmark.runner --output-dir reports && bash scripts/reproduce.sh`

Result: `acceptance.passed=true (13/13 checks true)`.

- [x] **Step 6: Final diff checks**

Run: `bash scripts/check-release-hygiene.sh && git diff --check`

Result: release hygiene passed and `git diff --check` passed.

---

## Self-Review

- Spec coverage: TEL-D2 runtime hooks, TEL-D3 HTTP export, TEL-E1 CLI deferral/report docs, TEL-E2 docs/memory sync, and verification are covered.
- Placeholder scan: no TBD/TODO placeholders remain; optional CLI is explicitly deferred.
- Type consistency: API DTO names are `TelemetryExportRequest` and `TelemetryExportResponse`; service returns existing `TelemetryExportResult`; route maps service result to API response.
