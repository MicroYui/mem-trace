# Python SDK + LangGraph Adapter + CLI Implementation Plan (ROADMAP §6 front segment)

> **For agentic workers:** implement this plan Issue-by-Issue using TDD (RED -> GREEN). Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Progress tracking rule:** after completing each Issue in §4, update `.ai/PROJECT_STATE.md` and tick or annotate the corresponding `docs/design/ROADMAP.md` §6 (and附录 step 6) checkbox. Do not leave implementation progress only in chat history.

**Goal:** Deliver MemTrace's **pluggable-runtime** entrypoints — a standalone `packages/python-sdk` (`memtrace-sdk`) exposing a unified `MemTrace` client over **two interchangeable backends (in-process facade + HTTP** **`/v1`)**, a **LangGraph adapter** (before/after/on\_error node hooks), runnable `examples/` (custom loop + langgraph), and a **CLI** — proving "any agent loop -> plug into MemTrace -> trace/retrieve/gate/profiler" and completing the Python SDK / HTTP / CLI three-entrypoint story (draft.md §139, architecture.md §6.1/§9, ROADMAP §6 step 6).

**Tech Stack:** Python **3.12+** (`pyproject.toml` `requires-python = ">=3.12"`), Pydantic v2, `httpx` (already a core dep), uv workspace, pytest + `httpx.ASGITransport` tests, `asyncio_mode=auto`. LangGraph is an **optional** SDK extra.

***

## 0. Background & positioning

mem-trace's core thesis is that memory is a **runtime component**, not a library bolted onto one agent loop. Before Phase 3.5, that thesis was only demonstrated through the bundled in-process demo/benchmark (`apps/api/app/demo/run_demo.py`, `apps/api/app/benchmark/runner.py`) and the FastAPI HTTP API (`apps/api/app/api/routes.py`), with **no installable SDK, no framework adapter, no examples directory, and no CLI**. As of S6, the Python SDK, HTTP backend, LangGraph-style adapter, runnable examples, CLI entrypoint, README three-entrypoint docs, and project-memory sync are complete.

This phase makes the "pluggable runtime" positioning concrete and demonstrable:

- **architecture.md §5** Principle 1 (Facade first) + Principle 8 (Portable adapters): external systems depend only on `MemoryRuntime`; the agent framework (LangGraph) is an interchangeable adapter.
- **architecture.md §6.1** drafts the `MemTrace` SDK surface and HTTP `/v1` endpoints.
- **architecture.md §9.2** specifies the canonical LangGraph hook contract: before node -> `retrieve_context`; after node -> `write_event`/`finish_step`; on error -> `write_event(error)`/mark failed branch.
- **architecture.md §6.2** requires `event_source` to record which entrypoint (SDK / HTTP / langgraph\_adapter / replay / import) produced each event.
- **ROADMAP §6** front segment + appendix step 6: Python SDK + LangGraph Adapter + custom-loop example, then CLI.

MemTrace's selling point here is **not** "we have an SDK too". It is "the *same* state-aware runtime — failed-branch isolation, gate, compaction, profiler, replay — is reachable identically whether you embed it in-process, call it over HTTP, drive it from LangGraph, or run it from a CLI". So the two backends must be **behaviorally isomorphic** and proven so by a shared test suite.

## 1. Scope (this implementation)

Issues, dependency-ordered (prefix `S`). **Execution order revised after review:** S1 first (tiny, unblocks event\_source tests), then S0, then S2 split into S2a/S2b:

1. **S1 — Core** **`event_source`** **passthrough (behavior-preserving):** add `WriteEventRequest.event_source` and thread it into `AgentEvent.event_source` so adapters/SDK/CLI can stamp their entrypoint. Default `None` keeps all current behavior identical. **Done first** because it is tiny and lets every later Issue assert `event_source`. ✅ Complete (2026-06-12)
2. **S0 — Packaging & workspace skeleton:** convert the repo to a uv workspace, scaffold `packages/python-sdk` (`memtrace-sdk`), wire pytest discovery. No behavior yet. ✅ Complete (2026-06-12)
3. **S2a — Shared SDK contract + in-process backend:** `Backend` Protocol, type re-exports, errors, `InProcessBackend` (wraps `MemoryRuntime`; missing-resource → `NotFoundError`), unified `MemTrace` facade. ✅ Complete (2026-06-12)
4. **S2b — HTTP backend + missing** **`/v1/runs/{run_id}/steps`** **route + isomorphism:** add the missing steps route, `HttpBackend` (wraps `httpx`, mirrors `/v1` + 404/400 mapping + lifecycle `aclose`), and the cross-backend isomorphism test. ✅ Complete (2026-06-12)
5. **S3 — LangGraph adapter:** `before_node`/`after_node`/`on_error` hooks stamping `event_source="langgraph_adapter"`; langgraph is an optional extra with an import guard. ✅ Complete (2026-06-12)
6. **S4 — Examples:** `examples/simple_agent` (custom loop via SDK in-process) + `examples/langgraph_adapter` (graceful skip when langgraph absent). ✅ Complete (2026-06-12)
7. **S5 — CLI:** `memtrace` command (`[project.scripts]`), subcommands, **HTTP-default for operational commands** + in-process only for `demo`/one-shot, reusing the SDK client. ✅ Complete (2026-06-12)
8. **S6 — Docs & project-memory sync:** tick ROADMAP §6 + step 6, add README three-entrypoint section, sync `.ai/` memory, mark this plan complete. ✅ Complete (2026-06-12)

## 2. Non-goals (deferred, per ROADMAP §6 / architecture §15)

- **TypeScript SDK** (`packages/ts-sdk`) — ROADMAP §6 后置.
- **OpenTelemetry / OpenInference exporter** and a real `core/telemetry.py` — keep as a no-op placeholder only; ROADMAP §6 / architecture §15 后置.
- **MCP Server, IDE plugins, Go/Rust collector** — ROADMAP §6 后置.
- **Hosted-demo auth / multi-tenant governance** — ADR-016, Phase 4.
- **Refactoring** **`get_settings()`** **out of** **`MemoryRuntime`** — the implicit global settings dependency (compaction config) stays; SDK exposes it via env/Settings, not a constructor override.

## 3. Current-state coordinates (verified, read before coding)

- **Facade:** `apps/api/app/runtime/memory_runtime.py:103` `MemoryRuntime`; constructor `(repo, *, default_workspace_id="ws_default", token_budget=512, extraction_mode=ExtractionMode.sync, extraction_provider=None, summarizer_provider=None)` (`:104`). All public methods are `async`. Synchronous construction, no event loop required to instantiate.
- **Hot-path methods:** `start_run`(:138), `start_step`(:152), `write_event`(:218), `finish_step`(:279), `rollback_branch`(:317), `complete_run`(:378), `retrieve_context`(:422), `flush_session(session_id: str)`(:442, note: takes a bare `str`, not `FlushRequest`).
- **Read/observability methods:** `get_timeline`(:763), `get_state_tree`(:766), `get_steps`(:769), `get_profile`(:772), `list_memories`(:775), `dashboard_tables`(:780), `replay_access`(:807), `replay_run`(:811), `observability_summary`(:815), `write_observability_report`(:821), `inspect_access`(:827, returns `AccessInspection | None`).
- **DTOs/enums:** `apps/api/app/runtime/models.py`. `_Base` uses `use_enum_values=False` (`:192`) → cross-process JSON must use `model_dump(mode="json")`. `RetrievalStrategy` (not `StrategyMode`) at `:141`. `ExtractionMode` at `:164`.
- **`event_source`:** `AgentEvent.event_source: Optional[str]=None` (models.py:234) + ORM (`storage/orm.py:86`) + SQL mapping (`storage/sql_repository.py:79,93`) already existed before S1. S1 added `WriteEventRequest.event_source` and `MemoryRuntime.write_event(...)` now stamps it into `AgentEvent.event_source`; omitted values preserve `None` for compatibility.
- **HTTP routes:** `apps/api/app/api/routes.py`, prefix `/v1`. Write endpoints: `POST /v1/runs`, `/v1/steps/start`, `/v1/events`, `/v1/steps/finish`, `/v1/context/retrieve`, `/v1/branches/rollback`, `/v1/runs/{run_id}/complete`, `/v1/sessions/{session_id}/flush` (legacy path form), and `/v1/sessions/flush` (body form for arbitrary string session ids). Read endpoints: `GET /v1/runs/{run_id}/timeline|state-tree|profile|steps`, `/v1/access/{access_id}`, `/v1/replay/access/{access_id}`, `/v1/replay/runs/{run_id}`, `/v1/observability/summary`, `POST /v1/observability/reports`, `GET /v1/steps/{step_id}`, `/v1/memories`, `/v1/dashboard/tables`. Error mapping: `RunNotFoundError`/`StepNotFoundError`/missing → 404; observability `ValueError` → 400. `/health` is in `main.py:27` (outside router).
- **DI wiring:** `apps/api/app/api/deps.py:54` `AppState.startup()` builds `SqlRepository` + tri-state extraction provider + summarizer provider + `MemoryRuntime`; `get_runtime()`(:100) returns the singleton.
- **In-process usage reference (golden path):** `apps/api/app/demo/run_demo.py:42` `_seed_run()` = start\_run → start\_step → write\_event\* → finish\_step/rollback\_branch → start\_step(recovery) → retrieve\_context → inspect\_access. Benchmark runner mirrors it (`runner.py:114`).
- **Test convention:** `apps/api/tests/conftest.py:10-17` `repo`(InMemoryRepository)/`runtime`(`MemoryRuntime(repo, default_workspace_id="ws_test")`) fixtures; `asyncio_mode="auto"`; subpackages mirror `app/` layers.
- **Packaging:** root `pyproject.toml` still builds the core `memtrace` package from `apps/api/app`, and S0 now also declares `packages/python-sdk` as a uv workspace member with SDK pytest discovery and `pythonpath` wiring. `packages/python-sdk` exists; S4 now adds deterministic `examples/` smoke coverage.

## 4. Issues

### Issue S1 — Core `event_source` passthrough (behavior-preserving) ✅ Complete (2026-06-12)

**Goal:** let any caller stamp the entrypoint origin of an event. Default `None` ⇒ identical current behavior. **Done first** (tiny, unblocks later `event_source` assertions).

**Changes:**

- [x] `apps/api/app/runtime/models.py`: add `event_source: Optional[str] = None` to `WriteEventRequest` (after `extraction_mode`, before `metadata`).
- [x] `apps/api/app/runtime/memory_runtime.py` `write_event` (:236-253): pass `event_source=request.event_source` into the `AgentEvent(...)` constructor.
- [x] HTTP route `POST /v1/events` needs **no** change (it already forwards the full `WriteEventRequest`). ORM/SQL mapping already persists `event_source` (storage/orm.py:86, sql\_repository.py:79,93).

**RED tests** (`apps/api/tests/runtime/test_memory_runtime_trace.py` or a new `test_event_source.py`):

- [x] `test_write_event_stamps_event_source`: `write_event(WriteEventRequest(..., event_source="sdk"))` → returned `WriteEventResult.event.event_source == "sdk"` and `get_timeline(run_id)` shows it.
- [x] `test_write_event_event_source_defaults_none`: omitting it keeps `event.event_source is None` (no behavior drift).

**Verification:** `uv run --extra dev pytest apps/api/tests/runtime/test_memory_runtime_trace.py -q`; full `uv run --extra dev pytest -q` unchanged count + new tests.

**S1 verification (2026-06-12):** RED targeted test failed as expected (`None == "sdk"`), GREEN targeted tests passed (2 passed), runtime trace regression passed (13 passed), compile check passed, and full regression `uv run --extra dev pytest -q` passed (**256 passed**). S1 review found 0 P0/P1/P2 defects; report: `/tmp/mem-trace_s1_review/report.html`.

***

### Issue S0 — Packaging & workspace skeleton

**Goal:** stand up `packages/python-sdk` as a uv workspace member with empty-but-importable structure and wired test discovery. No runtime behavior yet.

**Changes:**

- [x] Root `pyproject.toml`: add `[tool.uv.workspace]` with `members = ["packages/python-sdk"]`. Keep root `[tool.uv] package = true`. Add `[tool.uv.sources] memtrace = { workspace = true }` so the SDK's `memtrace` dependency resolves to the local core package.
- [x] `packages/python-sdk/pyproject.toml`: new package — **depends on** **`memtrace`** **core by default** (review decision A: prioritize Pydantic isomorphism over a pure-HTTP minimal install; a separate `memtrace-contracts`/schema package is deferred):
  ```toml
  [project]
  name = "memtrace-sdk"
  version = "0.1.0"
  requires-python = ">=3.12"
  dependencies = ["memtrace", "pydantic>=2.9", "httpx>=0.27"]
  [project.optional-dependencies]
  langgraph = ["langgraph>=0.2"]
  dev = ["pytest>=8.3", "pytest-asyncio>=0.24"]
  [project.scripts]
  memtrace = "memtrace_sdk.cli:main"
  [build-system]
  requires = ["hatchling"]
  build-backend = "hatchling.build"
  [tool.hatch.build.targets.wheel]
  packages = ["src/memtrace_sdk"]
  ```
- [x] Scaffold `packages/python-sdk/src/memtrace_sdk/__init__.py` exporting public names (`MemTrace`, `Backend`, `InProcessBackend`, `HttpBackend`, `MemTraceError`, `NotFoundError`, `BadRequestError`). **S0 stub rule:** these must be **real placeholder symbols, not just docstring +** **`__all__`**, so `from memtrace_sdk import MemTrace` works before S2 replaces them. Minimum:
  - `errors.py`: real `class MemTraceError(Exception)`, `class NotFoundError(MemTraceError)`, `class BadRequestError(MemTraceError)`.
  - `backends.py`: `class Backend(Protocol): ...`, `class InProcessBackend: ...`, `class HttpBackend: ...` (empty bodies).
  - `client.py`: `class MemTrace: ...` (empty body).
  - `types.py`, `langgraph_adapter.py`: module docstring + `__all__` (no required symbols yet).
- [x] `cli.py` **must** ship a real `main` stub so the declared console script never crashes on import/execute before S5:
  ```python
  def main(argv: list[str] | None = None) -> int:
      raise SystemExit("memtrace CLI is not implemented yet (see SDK_ADAPTER_PLAN.md S5)")
  ```
- [x] Root `pyproject.toml` `[tool.pytest.ini_options]`: extend `testpaths += ["packages/python-sdk/tests"]` and `pythonpath += ["packages/python-sdk/src"]`. Keep `apps/api` entries. Also set `addopts = ["--import-mode=importlib"]` so the two `tests` packages (`apps/api/tests` and `packages/python-sdk/tests`) do not collide during full-suite collection.
- [x] `packages/python-sdk/tests/__init__.py` + a trivial `test_imports.py`.

**RED test:**

- [x] `test_imports.py::test_sdk_package_importable`: `import memtrace_sdk` and `from memtrace_sdk import MemTrace` succeed. (RED because the package/pythonpath does not exist yet.)

**Verification:** `uv sync` resolves the workspace; `uv run --package memtrace-sdk --extra dev pytest packages/python-sdk/tests/test_imports.py -q`. The console script (after S5) runs via `uv run --package memtrace-sdk memtrace ...`.

**S0 verification (2026-06-12):** RED `uv run pytest packages/python-sdk/tests/test_imports.py -q` failed with `ModuleNotFoundError: No module named 'memtrace_sdk'`; GREEN `uv run --package memtrace-sdk --extra dev pytest packages/python-sdk/tests/test_imports.py -q` passed (**1 passed**). `uv sync` resolved the workspace. `uv run --package memtrace-sdk python -c "import memtrace_sdk; ..."` imported all public stubs. CLI stub prints the S5 not-implemented message via `uv run --package memtrace-sdk memtrace`. Package build succeeds with `uv build --package memtrace-sdk`. Compile check `uv run --extra dev python -m compileall -q apps/api/app packages/python-sdk/src` passed. Full regression initially exposed a pytest collection collision between the two top-level `tests` packages, fixed with `--import-mode=importlib`; final `uv run --extra dev pytest -q` passed (**257 passed**). S0 review found no P0/P1/P2 defects.

***

### Issue S2a — Shared SDK contract + in-process backend ✅ Complete (2026-06-12)

**Goal:** the unified async `MemTrace` client + `Backend` Protocol + in-process backend, returning core Pydantic types.

**Changes:**

- [x] `packages/python-sdk/src/memtrace_sdk/errors.py`: `MemTraceError(Exception)`, `NotFoundError(MemTraceError)`, `BadRequestError(MemTraceError)`.
- [x] `types.py`: re-export the request/result/domain/enums from `app.runtime.models` (the `memtrace` core dependency guarantees they exist). Users get typed objects without importing `app.*` directly.
- [x] `backends.py` (in-process part):
  - `Backend` Protocol: async methods mirroring the runtime hot path + read models (start\_run, start\_step, write\_event, finish\_step, rollback\_branch, complete\_run, retrieve\_context, flush\_session, get\_timeline, get\_state\_tree, get\_steps, get\_profile, list\_memories, inspect\_access, replay\_access, replay\_run, observability\_summary, write\_observability\_report, dashboard\_tables).
  - `InProcessBackend(runtime: MemoryRuntime)` — direct `await runtime.<method>(...)`; `flush_session(session_id: str)` adapts the bare-str runtime signature. Convenience constructor `InProcessBackend.in_memory(**runtime_kwargs)` builds `MemoryRuntime(InMemoryRepository(), ...)` for zero-config local use.
  - **Missing-resource semantics (isomorphism with HTTP 404), scoped narrowly:** runtime methods that semantically represent missing singular resources are converted to `NotFoundError` in `InProcessBackend`: runtime `RunNotFoundError` / `StepNotFoundError` are mapped for lifecycle/retrieval calls, `inspect_access` / `replay_access` convert `None` results, and `replay_run` checks run existence to match the existing HTTP 404 route. Invalid observability report requests map `ValueError` to SDK `BadRequestError`, matching HTTP 400. Do **NOT** convert empty-list read models (`get_timeline`/`get_state_tree`/`get_steps`/`get_profile`/`list_memories`) into `NotFoundError`: those runtime methods return `[]` for a missing run (no existence check), and their HTTP routes return `[]` too, so an empty list is the correct isomorphic result.
- [x] `client.py`: `MemTrace(backend: Backend)` facade + convenience constructors `MemTrace.in_process(runtime=...)` / `MemTrace.in_memory(...)`. Each method is a thin `await self._backend.<m>(...)`. Stamp a default `event_source="sdk"` in `write_event` when the caller does not supply one.
- [x] `__init__.py`: export the public surface.

**RED/GREEN tests** (`packages/python-sdk/tests/test_inprocess_backend.py`):

- [x] Full golden-path sequence (start\_run → ... → retrieve\_context → inspect\_access) via `MemTrace.in_memory`, asserting structured context blocks + `event_source="sdk"`.
- [x] `test_inprocess_missing_access_raises_not_found`: `inspect_access`/`replay_access` on an unknown id raise `NotFoundError` (not return `None`).

**Verification:** `uv run --package memtrace-sdk --extra dev pytest packages/python-sdk/tests/test_inprocess_backend.py -q`.

**S2a verification (2026-06-12):** RED `uv run --package memtrace-sdk --extra dev pytest packages/python-sdk/tests/test_inprocess_backend.py -q` failed during collection with `ImportError: cannot import name 'EventRole' from 'memtrace_sdk.types'`, proving the missing shared type contract. GREEN targeted S2a tests passed after review hardening (**10 passed**) covering the SDK golden path, default `event_source="sdk"`, explicit event-source preservation, existing-runtime wrapping, backend-only source preservation, `InProcessBackend.in_memory(...)`, missing-access / missing-run lifecycle `NotFoundError`, `replay_run` missing-run HTTP-aligned `NotFoundError`, observability-report `BadRequestError`, and empty-list read preservation. SDK package tests passed (**11 passed**). Compile check `uv run --extra dev python -m compileall -q apps/api/app packages/python-sdk/src` passed. Full regression `uv run --extra dev pytest -q` passed (**267 passed**).

***

### Issue S2b — HTTP backend + missing `/v1/runs/{run_id}/steps` route + isomorphism

**Goal:** the HTTP backend, the one missing read route it needs, and the headline "same runtime, two entrypoints" isomorphism proof.

**Changes:**

- [x] **Add missing route** `apps/api/app/api/routes.py`: `GET /v1/runs/{run_id}/steps` → `rt.get_steps(run_id)`, `response_model=list[AgentStep]`. `MemoryRuntime.get_steps` already exists (memory\_runtime.py:769); only the route is missing. **Missing-run rule (follow existing run-level read routes):** like `timeline`/`state-tree`/`profile` (routes.py:115-127), this route returns the runtime list result directly — a missing run yields an **empty list, NOT 404**. `get_steps` (=`list_steps`, memory\_runtime.py:769-770) performs no existence check. Do not add a 404 here unless all run-level read routes are changed consistently; isomorphism tests must assert `[]` for a missing run, not 404.
- [x] `backends.py` (HTTP part): `HttpBackend(base_url, *, api_key=None, client: httpx.AsyncClient | None = None, timeout=...)`:
  - [x] Mirrors every `/v1` endpoint listed in §3 (including the existing `/v1/steps/{step_id}` and the new `/v1/runs/{run_id}/steps`).
  - [x] Request bodies via `model_dump(mode="json")` (because `_Base` uses `use_enum_values=False`).
  - [x] **Response parsing:** single models via `Model.model_validate(resp.json())`; **list responses via** **`pydantic.TypeAdapter(list[Model]).validate_python(resp.json())`** (timeline/state-tree/profile/memories/steps are all list-typed).
  - [x] Error mapping: HTTP 404 → `NotFoundError`, 400 → `BadRequestError`, other 4xx/5xx → `MemTraceError`.
  - [x] **`api_key`** **convention:** if provided, send header `Authorization: Bearer <api_key>`. The current server has no auth and ignores it; this keeps the client forward-compatible (do not invent `X-API-Key`).
  - [x] **Lifecycle:** own-vs-injected client: `self._owns_client = client is None`; `async def aclose(self)` closes only an owned client; `__aenter__`/`__aexit__` support `async with`. `MemTrace` exposes `aclose()` / async-context delegation.
- [x] `client.py`: add `MemTrace.http(base_url=..., api_key=..., client=...)` constructor.

**RED/GREEN tests** (`packages/python-sdk/tests/`):

- [x] `test_http_backend.py`: golden-path sequence via `MemTrace.http` over `httpx.ASGITransport(app=app)`. **Must not run the FastAPI lifespan /** **`AppState.startup`** **path** (main.py:18 → deps.py:54 builds a real `SqlRepository` and would touch Postgres). Concretely: `from app.main import app` and `from app.api.deps import get_runtime`, then `app.dependency_overrides[get_runtime] = lambda: MemoryRuntime(InMemoryRepository(), default_workspace_id="ws_test")`; build `httpx.ASGITransport(app=app)` directly (do **not** wrap in a `LifespanManager`); clear with `app.dependency_overrides.clear()` in teardown. Assert 404 → `NotFoundError` (missing access), 400 → `BadRequestError` (unsafe observability report dir), and `aclose()` closes an owned client.
- [x] `test_backend_isomorphism.py`: run an identical scripted sequence through both backends sharing one in-memory runtime (HTTP via `dependency_overrides` pointing at the same runtime instance) and assert equal `MemoryContext` block types/order, equal `get_steps`/timeline shape, **equal** **`[]`** **for a missing-run** **`get_steps`** (not 404), and equal missing-access behavior (both raise `NotFoundError`).

**Verification:** `uv run --package memtrace-sdk --extra dev pytest packages/python-sdk/tests/test_http_backend.py packages/python-sdk/tests/test_backend_isomorphism.py -q`; full `uv run --extra dev pytest -q` (new steps-route test in `apps/api/tests/api/`).

**S2b verification (2026-06-12):** RED targeted tests failed on missing `MemTrace.http`, missing `HttpBackend` constructor, and missing `/v1/runs/{run_id}/steps` route (6 failed). GREEN targeted S2b tests passed: `uv run --package memtrace-sdk --extra dev pytest packages/python-sdk/tests/test_http_backend.py packages/python-sdk/tests/test_backend_isomorphism.py apps/api/tests/api/test_steps_route.py -q` -> **6 passed**. Post-review hardening tightened backend-isomorphism coverage to share one `MemoryRuntime` across `MemTrace.in_process(...)` and ASGITransport HTTP, compare all list-shaped read responses (`timeline`, `state-tree`, `steps`, `profile`, `memories`), and include the existing single-step `/v1/steps/{step_id}` route in the SDK contract. SDK suite passed (**15 passed**), steps-route API tests passed (**2 passed**), and compile check `uv run --extra dev python -m compileall -q apps/api/app packages/python-sdk/src` passed. Full regression verification is recorded in `.ai/PROJECT_STATE.md`.

***

### Issue S3 — LangGraph adapter ✅ Complete (2026-06-12)

**Goal:** drive MemTrace from LangGraph node lifecycle per architecture §9.2, without hard-depending on langgraph.

**Changes:**

- [x] `packages/python-sdk/src/memtrace_sdk/langgraph_adapter.py`:
  - `MemTraceLangGraphAdapter(client: MemTrace, *, run_id, workspace_id=None, event_source="langgraph_adapter")`.
  - `async before_node(node_name, query, *, task_intent=None, strategy=...) -> (step, MemoryContext)`: `start_step(intent=node_name)` then `retrieve_context(...)`; returns context for prompt injection.
  - `async after_node(step_id, *, content, event_type=..., tool_name=None, status=None) -> tuple[WriteEventResult, FinishStepResult]`: `write_event(..., event_source=self._event_source)` then `finish_step(status=completed)`. **Return both** so callers can read the finish-stage `working_state` memory + final step status (`FinishStepResult` carries `step`/`state_node`/`created_memory_ids`, memory\_runtime.py:311-315); returning only `WriteEventResult` would hide them.
  - `async on_error(step_id, *, error_message) -> RollbackResult`: `write_event(event_type=error, status="failed", event_source=self._event_source)`, `finish_step(status=failed)`, then `rollback_branch(reason=error_message)`.
  - All adapter-written events stamp `event_source="langgraph_adapter"` (the constructor default).
  - Optional thin `wrap_node(fn)` helper that composes before/after/on\_error around an async callable for convenience.
  - Import guard: a module-level `try: import langgraph` is **not** required for the hooks (they only use the SDK client). If/when a true graph-compilation helper is added it must guard import and raise a clear `MemTraceError("install memtrace-sdk[langgraph]")`.
- [x] `test_before_after_node_traces_through_runtime`: drive a fake 2-node loop via the adapter over `InProcessBackend`; assert steps/events created, `event_source=="langgraph_adapter"`, `after_node` returns `(WriteEventResult, FinishStepResult)` with `finish.step.status == completed`, retrieved context returned.
- [x] `test_on_error_isolates_failed_branch_from_positive_context`: a failing node triggers `on_error`; assert the step is failed/rolled back and `rollback_branch` ran. **Assertions match the I3 negative-evidence model, not "failed evidence fully excluded":** the failed branch must NOT appear in positive context blocks; a *safe* failure may appear ONLY as `avoided_attempts` / `source="negative_evidence"` blocks; an *unsafe* failure may appear ONLY as a sanitized notice (no raw command). `RetrievalController.trace` builds negative evidence from all gate outcomes (controller.py:278) and passes it to the packer (controller.py:289), so a blanket-exclusion assertion would contradict the completed I3 work.
- [x] `test_wrap_node_records_success_and_failure_lifecycle`: optional helper wraps async node callables, injects `memtrace_step`/`memtrace_context` into mutable dict state, records successful outputs, and rolls back failures while preserving `event_source="langgraph_adapter"`.
- [x] `test_langgraph_optional_import_guard` was not added because S3 does not add a true graph-compilation helper and the hooks do not import langgraph.

**Verification:** `uv run --package memtrace-sdk --extra dev pytest packages/python-sdk/tests/test_langgraph_adapter.py -q`.

**S3 verification (2026-06-12):** RED `uv run --package memtrace-sdk --extra dev pytest packages/python-sdk/tests/test_langgraph_adapter.py -q` failed with 3 expected failures on missing `MemTraceLangGraphAdapter`. GREEN targeted S3 tests passed (**3 passed**). SDK package suite passed (**18 passed**) after exporting `MemTraceLangGraphAdapter` from `memtrace_sdk.__all__`. Compile check `uv run --extra dev python -m compileall -q apps/api/app packages/python-sdk/src` passed. Full regression `uv run --extra dev pytest -q` passed (**276 passed**). Detailed post-review found no P0/P1/P2 S3 defects; follow-up doc sync corrected this plan's historical current-state wording now that S0-S3 are complete.

***

### Issue S4 — Examples (custom loop + langgraph) ✅ Complete (2026-06-12)

**Goal:** runnable, copy-pasteable proof that arbitrary loops integrate.

**Changes:**

- [x] `examples/simple_agent/main.py`: a self-contained custom agent loop using `MemTrace.in_memory`. Reproduce the demo's Bun-vs-Node failed-branch-isolation scenario through the SDK; print the contamination contrast (baseline vs variant\_2). **Do not import the private** **`run_demo._decide_action`** — write a tiny local deterministic `decide_action(ctx)` in the example so it does not couple to demo internals, e.g. filter out `type=="avoided_attempts"` / `source=="negative_evidence"` blocks before deciding the action (this also showcases I3: an npm-failure appearing as negative evidence does NOT make the agent retry npm).
- [x] `examples/langgraph_adapter/main.py`: a minimal langgraph graph wired via `MemTraceLangGraphAdapter`. Top-level guard: if `import langgraph` fails, print an actionable skip message and exit 0 (so CI/smoke never breaks).
- [x] `examples/README.md`: how to run each, expected output, which backend each uses.

**Tests:**

- [x] `packages/python-sdk/tests/test_examples_smoke.py`: import + run `examples/simple_agent/main.py:main()` (in-process, deterministic) and assert it produces the contamination contrast; for the langgraph example, assert it either runs or cleanly skips when langgraph is absent. (Use `runpy`/import; keep deterministic, no network.)

**Verification:** `uv run --package memtrace-sdk python examples/simple_agent/main.py`; `uv run --package memtrace-sdk --extra dev pytest packages/python-sdk/tests/test_examples_smoke.py -q`.

**S4 verification (2026-06-12):** RED `uv run --package memtrace-sdk --extra dev pytest packages/python-sdk/tests/test_examples_smoke.py -q` failed with missing `examples/simple_agent/main.py` and `examples/langgraph_adapter/main.py`. GREEN targeted examples smoke passed (**2 passed**). Manual smoke `uv run --package memtrace-sdk python examples/simple_agent/main.py && uv run --package memtrace-sdk python examples/langgraph_adapter/main.py` printed the expected baseline `npm test` vs variant\_2 `bun test` contrast and a clean LangGraph-not-installed skip. SDK package tests passed (**20 passed**), compile check passed, full regression passed (**278 passed**), and deterministic benchmark/reproducibility passed with `acceptance.passed=true (10/10 checks true)`.

***

### Issue S5 — CLI entrypoint (third of three entrypoints) ✅ Complete (2026-06-12)

**Goal:** a thin `memtrace` CLI over the same SDK client. **Backend policy is the key design point:** a default-in-process CLI would silently lose state across commands, because each invocation is a separate process and a fresh `InMemoryRepository` cannot see the run created by a prior command.

**Changes:**

- [x] `packages/python-sdk/src/memtrace_sdk/cli.py`: `argparse`-based `main(argv=None) -> int`.
  - **Backend policy:**
    - **Operational commands** (`start-run`, `start-step`, `write-event`, `retrieve`, `timeline`, `state-tree`, `inspect-access`, `report`): **require** **`--http URL`** (a persistent server). They MUST NOT default to a throwaway in-memory runtime; error clearly if no `--http` is given. (A future `--database-url` SqlRepository mode for local persistence is deferred.)
    - **One-shot commands** (`demo`): support `--in-process` (in-memory, runs the full simple\_agent scenario in a single process) OR `--http URL`.
  - Global flags: `--http URL`, `--workspace-id`, `--api-key`, `--json` output.
  - All commands build a `MemTrace` client and `asyncio.run` the call; print results as JSON via `model_dump(mode="json")`. Map `NotFoundError`/`BadRequestError`/`MemTraceError` to a non-zero exit + stderr message.
  - **`event_source`** **rule:** CLI-generated write events (the `write-event` subcommand and any `demo`-generated events) MUST pass `event_source="cli"` explicitly; otherwise `MemTrace.write_event` would stamp its `"sdk"` default and mislabel the entrypoint.
- [x] `[project.scripts] memtrace = "memtrace_sdk.cli:main"` already declared in S0; S5 replaced the S0 stub with the real implementation.

**RED/GREEN tests** (`packages/python-sdk/tests/test_cli.py`):

- [x] `test_cli_demo_in_process`: `main(["demo", "--in-process"])` runs end-to-end and returns 0, printing the contamination contrast.
- [x] `test_cli_demo_http_runs_against_persistent_server`: `main(["--http", "http://test", "demo"])` runs the one-shot demo over an ASGITransport-backed persistent runtime.
- [x] `test_cli_operational_command_requires_http`: `main(["start-run", ...])` without `--http` returns a non-zero exit with an actionable message (no silent in-memory run).
- [x] `test_cli_retrieve_outputs_json` (over `--http` against an ASGITransport-backed client, via dependency\_overrides): a scripted run then `retrieve` prints valid JSON with `context_blocks`.
- [x] `test_cli_http_404_nonzero_exit`: a missing-resource HTTP call maps to a non-zero exit + error message.
- [x] `test_cli_write_event_stamps_cli_event_source`: `write-event` over the HTTP backend persists `event_source="cli"` rather than the SDK default.

**Verification:** `uv run --package memtrace-sdk memtrace demo --in-process`; `uv run --package memtrace-sdk --extra dev pytest packages/python-sdk/tests/test_cli.py -q`.

**S5 verification (2026-06-12):** RED `uv run --package memtrace-sdk --extra dev pytest packages/python-sdk/tests/test_cli.py -q` failed with 4 expected failures on the S0 not-implemented CLI stub. GREEN targeted S5 tests passed after implementation and event-source / HTTP-demo coverage expansion (**6 passed**). Manual CLI smoke `uv run --package memtrace-sdk memtrace demo --in-process` printed the expected baseline `npm test` vs variant\_2 `bun test` contrast. Compile check `uv run --extra dev python -m compileall -q apps/api/app packages/python-sdk/src examples` passed. SDK package suite `uv run --package memtrace-sdk --extra dev pytest packages/python-sdk/tests -q` passed (**26 passed**). Full regression `uv run --extra dev pytest -q` passed (**284 passed**).

***

### Issue S6 — Docs & project-memory sync ✅ Complete (2026-06-12)

**Goal:** make the three entrypoints discoverable and mark the phase complete.

**Changes:**

- [x] `docs/design/ROADMAP.md`: tick §6 Python SDK + LangGraph Adapter + examples + CLI items; update appendix step 6 to ✅; note TS SDK / OTel / MCP / IDE remain deferred.
- [x] `README.md`: add a "Three entrypoints (Python SDK / HTTP / CLI)" section with a short SDK quickstart, the langgraph adapter snippet, and CLI usage; link `examples/`.
- [x] `.ai/PROJECT_STATE.md`: record S0-S6 implemented + verification; set next recommended action to ROADMAP §7 (6-strategy benchmark) or §10/§11 (Provider Registry / Key Ontology).
- [x] `.ai/IMPLEMENTATION_PLAN.md`: reflect Phase 3.5 complete.
- [x] `AGENTS.md`: update the "Next priority" line.
- [x] Mark all Issues in this plan complete with verification notes.

**S6 review/fix (2026-06-12):** Detailed S6 review checked code invariants and doc-memory consistency. One P2 HTTP/in-process isomorphism gap was found and fixed: path-sensitive `session_id` values such as `tenant/session` now flush through a body-based `POST /v1/sessions/flush` endpoint used by `HttpBackend.flush_session(...)`, while the legacy path route remains. Coverage was added to `test_http_backend.py` and `test_backend_isomorphism.py`.

**S6 verification (2026-06-12):** README documents the three entrypoints (Python SDK, HTTP backend, CLI) and links examples; ROADMAP appendix step 6 and this plan are marked complete; `.ai/PROJECT_STATE.md`, `.ai/REQUIREMENTS.md`, `.ai/IMPLEMENTATION_PLAN.md`, `.ai/OPEN_QUESTIONS.md`, and `AGENTS.md` no longer point next work at S6. Final verification commands/results are recorded in `.ai/PROJECT_STATE.md`.

## 5. Key files

**Create**

- `packages/python-sdk/pyproject.toml`
- `packages/python-sdk/src/memtrace_sdk/{__init__,client,backends,types,errors,langgraph_adapter,cli}.py`
- `packages/python-sdk/tests/{__init__,test_imports,test_inprocess_backend,test_http_backend,test_backend_isomorphism,test_langgraph_adapter,test_examples_smoke,test_cli}.py`
- `examples/simple_agent/main.py`, `examples/langgraph_adapter/main.py`, `examples/README.md`

**Modify**

- `pyproject.toml` (root): `[tool.uv.workspace] members`, `[tool.uv.sources] memtrace = {workspace=true}`, pytest `testpaths`/`pythonpath`.
- `apps/api/app/runtime/models.py`: `WriteEventRequest.event_source` (S1).
- `apps/api/app/runtime/memory_runtime.py`: `write_event` passthrough (S1).
- `apps/api/app/api/routes.py`: add `GET /v1/runs/{run_id}/steps` (S2b) and body-based `POST /v1/sessions/flush` for HTTP-safe arbitrary session ids (S6 review hardening).
- `apps/api/tests/api/`: add a steps-route test (S2b).
- `README.md`, `docs/design/ROADMAP.md`, `AGENTS.md`, `.ai/PROJECT_STATE.md`, `.ai/IMPLEMENTATION_PLAN.md`.

## 6. Dependency order

S1 → S0 → S2a (needs S0+S1) → S2b (needs S2a) → S3 (needs S2a) → S4 (needs S2+S3) → S5 (needs S2) → S6 (needs S0-S5).

## 7. Verification (end-to-end)

- Per Issue: TDD RED→GREEN, targeted `uv run --extra dev pytest <files> -q`.
- SDK isomorphism: in-process and HTTP backends pass the same scripted assertions, including identical missing-resource (`NotFoundError`) behavior (`test_backend_isomorphism.py`).
- Adapter: before/after/on\_error produce correct trace + `event_source="langgraph_adapter"`; failed branch stays out of positive context but safe failures may surface as `avoided_attempts`/negative evidence (I3 model).
- Examples smoke: `examples/simple_agent` prints contamination contrast; langgraph example skips cleanly without the extra.
- CLI: `memtrace demo --in-process` returns 0; operational commands require `--http` (no silent in-memory state loss); JSON output valid.
- No regression: `uv run --extra dev pytest -q` (S6 final baseline recorded in `.ai/PROJECT_STATE.md`).
- Deterministic benchmark not regressed: `uv run python -m app.benchmark.runner --output-dir reports && bash scripts/reproduce.sh` → `acceptance.passed=true (10/10 checks true)`.
- Workspace resolves: `uv sync` succeeds with the new member.

## 8. Risks & constraints

- **Cross-cutting invariants (ROADMAP §1, must hold):** ① SDK/adapter/CLI add **no** new retrieval path and never bypass the lifecycle filter `_RETRIEVABLE_STATUSES` — everything flows through `MemoryRuntime`/`/v1`; ② pg16 image switch needs `docker-compose down -v`; ③ profiler sub-ms phases reading 0ms is expected.
- **Enum serialization:** `_Base` keeps enum instances; HTTP transport must `model_dump(mode="json")` to avoid sending enum objects.
- **`flush_session`** **transport shape:** runtime takes `session_id: str`; HTTP has a legacy path route plus a body-based `/v1/sessions/flush` route. `HttpBackend.flush_session(...)` must use the body route so arbitrary string ids (including `/`) stay isomorphic with in-process.
- **Type isomorphism over minimal install (review decision A):** `memtrace-sdk` depends on the core `memtrace` package by default so both backends return the **same** Pydantic types. A pure-HTTP minimal install (without core) via a `memtrace-contracts` schema package is deferred — the headline value here is behavioral isomorphism, not install footprint.
- **Missing-resource isomorphism:** runtime `inspect_access`/`replay_access` return `None` (memory\_runtime.py:807,827) and HTTP maps that to 404; `InProcessBackend` MUST raise `NotFoundError` so the two backends do not diverge on missing resources.
- **HTTP test must not hit Postgres:** `app.main:app` lifespan calls `AppState.startup()` which builds a real `SqlRepository` (main.py:18, deps.py:54). SDK HTTP tests MUST override `get_runtime` with an in-memory runtime via `app.dependency_overrides` (and clear it in teardown), not rely on the real lifespan.
- **Missing** **`get_steps`** **route:** `MemoryRuntime.get_steps` exists (memory\_runtime.py:769) but `GET /v1/runs/{run_id}/steps` does not exist in routes.py — S2b adds it; without it the HTTP backend cannot implement `get_steps`.
- **Optional langgraph:** never import langgraph at module top level of code paths exercised by the default test suite; guard and give actionable errors.
- **Settings global:** compaction config is read via `get_settings()` inside `MemoryRuntime`; SDK cannot override it per-instance — documented, not refactored here.

## 9. Implementation invariants (read before coding — prevents drift)

- The SDK is a **thin transport-agnostic facade**; no business logic, no retrieval/gate/packing logic lives in the SDK. All decisions stay in `MemoryRuntime`.
- Both backends MUST return the **same Pydantic types** (core `memtrace` is a hard SDK dependency). Isomorphism — including missing-resource `NotFoundError` — is a tested guarantee, not a hope.
- `event_source` defaults: SDK → `"sdk"`, adapter → `"langgraph_adapter"`, CLI → `"cli"` (override allowed). Omission upstream stays `None`.
- Examples and CLI `demo` are **deterministic** (in-memory repo, no network, default providers) so they can be smoke-tested in CI. Operational CLI commands require `--http` and must not silently spin up a throwaway in-memory runtime.
- The SDK `cli.py` ships a real `main` stub from S0 so the declared console script never crashes before S5.
- `HttpBackend` parses list responses with `pydantic.TypeAdapter(list[Model]).validate_python(...)`, single responses with `Model.model_validate(...)`. `api_key`, if set, is sent as `Authorization: Bearer <key>` (server currently ignores it; forward-compatible).
- The new `GET /v1/runs/{run_id}/steps` route follows existing run-level read routes: it returns the runtime list directly; a missing run yields `[]`, not 404. Both backends and the isomorphism test must assert `[]`.
- `HttpBackend.flush_session(...)` uses body JSON (`FlushRequest`) instead of interpolating `session_id` into the path; do not regress to a path-only call because `StartRunRequest.session_id` is an arbitrary string.
- Do not add a real OTel/telemetry implementation; keep `core/telemetry.py` absent or a no-op placeholder.
