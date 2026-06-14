# OTel Segment 2 Exporters and Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete OpenTelemetry/OpenInference Segment 2 by adding default-off telemetry exporters, settings-driven factory construction, and a fail-open `TelemetryService` facade without changing runtime hot paths.

**Architecture:** Keep Segment 1 builders as the only DTO-to-span mapping layer. Segment 2 adds replaceable exporter sinks plus a small service facade that accepts already-built `TelemetrySpan` instances and builder-ready DTOs, returns `TelemetryExportResult`, and never mutates runtime/repository state. OTLP stays optional and lazy-imported; missing dependencies or endpoint configuration degrade to noop through the factory.

**Tech Stack:** Python 3.12, Pydantic settings, pytest, existing `app.telemetry` DTO/builders/redaction, optional OpenTelemetry SDK packages when installed.

---

### Task 1: Exporter sinks

**Files:**
- Create: `apps/api/app/telemetry/exporters.py`
- Test: `apps/api/tests/telemetry/test_exporters.py`

- [x] **Step 1: Write RED tests** for noop, in-memory, JSONL overwrite/append, and safe serialization.
- [x] **Step 2: Run RED command**: `uv run --extra dev pytest apps/api/tests/telemetry/test_exporters.py -q`; expected failure is `ModuleNotFoundError` or missing exporter names.
- [x] **Step 3: Implement exporters** with `TelemetryExporter.export_spans(spans)`, deterministic in-memory snapshots, JSONL directory creation, and no raw nested attributes.
- [x] **Step 4: Run GREEN command**: `uv run --extra dev pytest apps/api/tests/telemetry/test_exporters.py -q`; expected pass.

### Task 2: Settings and factory

**Files:**
- Modify: `apps/api/app/config.py`
- Create: `apps/api/app/telemetry/factory.py`
- Test: `apps/api/tests/telemetry/test_exporters.py`

- [x] **Step 1: Write RED tests** for default noop settings, JSONL settings, OTLP missing endpoint/dependency degradation, and unknown exporter degradation warning.
- [x] **Step 2: Run RED command**: `uv run --extra dev pytest apps/api/tests/telemetry/test_exporters.py -q`; expected failures are missing settings/factory symbols.
- [x] **Step 3: Add settings**: `telemetry_enabled`, `telemetry_exporter`, `telemetry_jsonl_path`, `telemetry_jsonl_append`, `telemetry_otlp_endpoint`, and `telemetry_fail_open` with default-off/no-network values.
- [x] **Step 4: Implement factory** returning `(exporter, warnings)` and lazy OTLP construction.
- [x] **Step 5: Run GREEN command**: `uv run --extra dev pytest apps/api/tests/telemetry/test_exporters.py -q`; expected pass.

### Task 3: TelemetryService facade

**Files:**
- Create: `apps/api/app/telemetry/service.py`
- Modify: `apps/api/app/telemetry/__init__.py`
- Test: `apps/api/tests/telemetry/test_service.py`

- [x] **Step 1: Write RED tests** for normal export, fail-open exporter exceptions, fail-closed explicit mode, runtime DTO builder composition, and no raw content leakage.
- [x] **Step 2: Run RED command**: `uv run --extra dev pytest apps/api/tests/telemetry/test_service.py -q`; expected failure is missing service symbols.
- [x] **Step 3: Implement service** with `export_spans`, `export_run_records`, and `export_retrieval_records` methods backed by Segment 1 builders.
- [x] **Step 4: Export public symbols** from `app.telemetry.__init__`.
- [x] **Step 5: Run GREEN command**: `uv run --extra dev pytest apps/api/tests/telemetry/test_service.py -q`; expected pass.

### Task 4: Verification and project-memory sync

**Files:**
- Modify: `docs/design/OTEL_OPENINFERENCE_EXPORTER_PLAN.md`
- Modify: `docs/design/ROADMAP.md`
- Modify: `.ai/PROJECT_STATE.md`
- Modify: `.ai/REQUIREMENTS.md`
- Modify: `.ai/IMPLEMENTATION_PLAN.md`
- Modify: `.ai/PITFALLS.md`

- [x] **Step 1: Run targeted telemetry suite**: `uv run --extra dev pytest apps/api/tests/telemetry -q`.
- [x] **Step 2: Run compile check**: `uv run python -m compileall apps/api/app/telemetry apps/api/app/config.py`.
- [x] **Step 3: Run whitespace check**: `git diff --check`.
- [x] **Step 4: Sync plan/memory** marking TEL-C1/TEL-C2/TEL-D1 complete and Segment 3 as next.
- [x] **Step 5: Re-run targeted telemetry suite after docs/memory sync**: `uv run --extra dev pytest apps/api/tests/telemetry -q`.

### Self-review

- Spec coverage: TEL-C1, TEL-C2, and TEL-D1 are covered by Tasks 1-3; Segment 3 runtime/API/CLI hooks are explicitly out of scope.
- Placeholder scan: no TBD/TODO placeholders are present.
- Type consistency: all new public boundaries consume existing `TelemetrySpan`/`TelemetryExportResult` DTOs and existing Segment 1 builder functions.

### Completion / Review Hardening (2026-06-14)

- **Implemented:** TEL-C1/TEL-C2/TEL-D1: exporter protocol, noop/in-memory/JSONL/optional OTLP exporters, default-off telemetry settings, settings-driven exporter/service factory, and `TelemetryService` facade.
- **Post-review hardening:** event attributes are redacted for in-memory/JSONL/OTLP exporters; JSONL rejects absolute paths, `..`, directory symlink escapes, and final-file symlink escapes; OTLP conversion applies redaction and preserves internal trace/parent context where possible; `telemetry_fail_open` is consumed by `build_telemetry_service(...)`; `TelemetryService` fail-open covers builder/projection errors.
- **Verification:** initial Segment 2 RED tests failed on missing `app.telemetry.factory` / `app.telemetry.exporters`; review RED tests failed for final-file symlink escape and settings-to-service construction before fixes. Final telemetry suite passed with **33 passed**; compileall for telemetry/config passed; `git diff --check` passed; full pytest passed with **637 passed, 2 skipped**; release hygiene passed.
- **Boundary:** no `MemoryRuntime`, retrieval hot path, FastAPI route, CLI command, repository behavior, benchmark semantics, or public docs were changed. Current next action is Segment 3 runtime hooks + docs.
