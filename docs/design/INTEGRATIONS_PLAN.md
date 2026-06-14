# TypeScript SDK, MCP, and IDE Integrations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` (recommended) or `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add external integration entrypoints that let TypeScript applications, MCP-capable agents, and IDE workflows consume MemTrace without bypassing HTTP/SDK/runtime semantics.

**Architecture:** Integrations are intentionally thin clients over the stable `/v1` HTTP contract. The TypeScript SDK owns request/response typing and error mapping; the MCP server calls the TypeScript SDK; IDE adoption starts with MCP configuration templates before any dedicated extension package. No integration package may import Python runtime code, access the database directly, or reimplement retrieval/gate/context-packing logic.

**Tech Stack:** Bun workspace, TypeScript, fetch-based HTTP client, MCP SDK/server package, mocked fetch tests, optional service smoke tests, existing Python FastAPI service as the authoritative runtime.

---

## 0. Source-Verified Decisions

- The Python SDK already exposes in-process and HTTP backends around the same `MemoryRuntime` semantic boundary; integrations should mirror the HTTP surface rather than create a second runtime path.
- Current API routes include stable core operations: `POST /v1/runs`, `POST /v1/steps/start`, `POST /v1/events`, `POST /v1/context/retrieve`, `GET /v1/access/{access_id}`, lifecycle/read APIs, replay/report/dashboard surfaces, and Phase 4 memory version/conflict APIs.
- Phase 4 governance is implemented in the current HTTP contract: `/v1` routes depend on `require_api_key`, resource reads resolve workspace ownership before authorization, quota checks can return 429, unauthorized/missing-workspace requests can return 401/403, and FastAPI validation can return 422 detail arrays. TS SDK 401/403/429 plus 400/422 bad-request mapping and tests are first-release requirements, not future readiness.
- `FlushSession` uses a JSON body route (`POST /v1/sessions/flush`) for arbitrary session ids; TS SDK must not interpolate arbitrary `session_id` into path-only routes. Authorized non-wildcard principals require `workspace_id` as a query parameter for session flush.
- Phase 4 async extraction is part of the current event-write contract: `ExtractionMode` includes `sync`, `buffered`, `async`, `sync_flush`, `lazy`, and `no_extract`; `WriteEventResult` includes `buffered`, `queued`, `task_id`, and `warnings`.
- Phase 4 memory governance/observability APIs are current routes and should be covered by the expanded TS SDK before MCP work: `GET /v1/memories/{memory_id}/versions` and `GET /v1/memory-conflicts?workspace_id=...`.
- The project has no JS workspace yet and project memory says to prefer Bun rather than npm/pnpm/yarn lockfiles.
- Use stable workspace package names from the start, even before publishing: `@memtrace/sdk` for the TypeScript SDK and `@memtrace/mcp-server` for the MCP server.

## 1. Non-Goals and Ordering

- I7 and Phase 4 HTTP/governance contracts are now stable enough for this slice; keep the integration plan aligned with current source routes rather than older pre-Phase-4 assumptions.
- Do not create a full VS Code extension first. Start with MCP config templates and command-line/server smoke tests.
- Do not put examples in new README files unless explicitly accepted during implementation closeout; prefer root README sections and small source examples.
- Do not add JS checks to `scripts/reproduce.sh` unless they are deterministic, fast, and do not require a running external service. Prefer a separate `scripts/smoke-integrations.sh` for optional integration smoke.
- Do not duplicate memory semantics in TypeScript or MCP.

---

## 2. Stream INT-A — TypeScript SDK

### INT-A1 Bun Workspace and Minimal Core Client

**Status (2026-06-14):** ✅ complete. Implemented Bun workspace, `@memtrace/sdk`, strict TypeScript config, core DTOs/client/errors, mocked tests, and typecheck. Verification used temporary Bun via `npm exec --yes --package bun -- bun ...` because Bun is not globally installed in this environment.

**Files:**
- Create: `package.json`
- Create: `tsconfig.base.json`
- Create: `packages/ts-sdk/package.json`
- Create: `packages/ts-sdk/tsconfig.json`
- Create: `packages/ts-sdk/src/index.ts`
- Create: `packages/ts-sdk/src/client.ts`
- Create: `packages/ts-sdk/src/types.ts`
- Create: `packages/ts-sdk/src/errors.ts`
- Create: `packages/ts-sdk/test/client.test.ts`

- [x] **Step 1: Write RED workspace tests**
  - `bun test packages/ts-sdk/test/client.test.ts` should initially fail because package files do not exist.
  - Test package scripts: `bun test` and `bun run typecheck`.
  - Assert no `package-lock.json`, `pnpm-lock.yaml`, or `yarn.lock` is present after setup.

- [x] **Step 2: Add Bun workspace**
  - Root `package.json` declares workspaces `packages/ts-sdk` and, later, `packages/mcp-server`.
  - `packages/ts-sdk/package.json` uses the stable package name `@memtrace/sdk`; omit publish config until release policy is decided.
  - Use Bun lockfile generated by Bun; do not add npm/pnpm/yarn lockfiles.
  - Root `tsconfig.base.json` sets strict TypeScript defaults.

- [x] **Step 3: Define minimal type surface**
  - In `types.ts`, define request/response types for:
    - `StartRunRequest`, `AgentRun`
    - `StartStepRequest`, `AgentStep`
    - `WriteEventRequest`, `WriteEventResult`
    - `RetrievalRequest`, `MemoryContext`, `ContextBlock`
    - `AccessInspection`
    - `ExtractionMode` union: `"sync" | "buffered" | "async" | "sync_flush" | "lazy" | "no_extract"`
  - `WriteEventRequest.extraction_mode` is optional and uses current HTTP JSON names.
  - `WriteEventResult` includes `event`, `created_memory_ids`, `buffered`, `queued`, `task_id`, and `warnings`.
  - Keep fields aligned with current HTTP JSON names; unknown future fields should not break parsing.

- [x] **Step 4: Define error mapping**
  - `MemTraceError` base class includes `status`, `code`, and `responseBody`.
  - Error message extraction supports FastAPI's current `{"detail":"..."}` shape first, then common `error` / `message` string fields, then non-JSON raw response text, `statusText`, and a final fallback.
  - `NotFoundError` maps 404.
  - `BadRequestError` maps 400.
  - `ForbiddenError` maps current 401/403 authn/authz failures.
  - `RateLimitedError` maps current 429 quota failures.
  - Tests cover `{"detail":"workspace_id required"}` mapping to `ForbiddenError.message` and a non-JSON error response mapping to a useful raw-text/status message.

- [x] **Step 5: Implement core client methods**
  - First release methods only:
    - `startRun(req)` -> `POST /v1/runs`
    - `startStep(req)` -> `POST /v1/steps/start`
    - `writeEvent(req)` -> `POST /v1/events`
    - `retrieveContext(req)` -> `POST /v1/context/retrieve`
    - `inspectAccess(accessId)` -> `GET /v1/access/{access_id}`
  - Constructor accepts `baseUrl`, optional `apiKey`, optional custom `fetch`.
  - API key is sent as `Authorization: Bearer <apiKey>`.

- [x] **Step 6: Run minimal SDK tests**
  - Command: `bun test packages/ts-sdk/test/client.test.ts`
  - Command: `bun run typecheck`
  - Expected: all pass.

### INT-A2 Expanded HTTP Surface for Current Phase 4 Contract

**Status (2026-06-14):** ✅ complete. The SDK covers lifecycle/read/replay/observability/dashboard/memory version/conflict routes, path-authoritative `completeRun(runId, req)`, body-based workspace-aware `flushSession`, and 400/422/401/403/404/429 error mapping.

**Files:**
- Modify: `packages/ts-sdk/src/client.ts`
- Modify: `packages/ts-sdk/src/types.ts`
- Modify: `packages/ts-sdk/test/client.test.ts`
- Create: `packages/ts-sdk/test/errors.test.ts`

- [x] **Step 1: Add RED tests for expanded methods**
  - Methods:
    - `finishStep(req)` -> `POST /v1/steps/finish`
    - `rollbackBranch(req)` -> `POST /v1/branches/rollback`
    - `completeRun(runId, req)` -> `POST /v1/runs/{run_id}/complete`
    - `getTimeline(runId)` -> `GET /v1/runs/{run_id}/timeline`
    - `getStateTree(runId)` -> `GET /v1/runs/{run_id}/state-tree`
    - `getSteps(runId)` -> `GET /v1/runs/{run_id}/steps`
    - `getStep(stepId)` -> `GET /v1/steps/{step_id}`
    - `getProfile(runId)` -> `GET /v1/runs/{run_id}/profile`
    - `flushSession(sessionId, options?: { workspaceId?: string })` -> `POST /v1/sessions/flush` with JSON body and optional `workspace_id` query
    - `replayAccess(accessId)` -> `GET /v1/replay/access/{access_id}`
    - `replayRun(runId)` -> `GET /v1/replay/runs/{run_id}`
    - `observabilitySummary(params?)` -> `GET /v1/observability/summary`
    - `dashboardTables(workspaceId?)` -> `GET /v1/dashboard/tables`
    - `writeObservabilityReport(req)` -> `POST /v1/observability/reports`
    - `listMemories(params?)` -> `GET /v1/memories`
    - `listMemoryVersions(memoryId)` -> `GET /v1/memories/{memory_id}/versions`
    - `listMemoryConflicts(params)` -> `GET /v1/memory-conflicts?workspace_id=...` with optional `memory_id` and `status`
  - Assert 400/422/404/401/403/429 mapping with mocked fetch responses.
  - Assert `completeRun(runId, req)` always uses the path `runId` as authoritative; a body `run_id`, if present, must not be interpolated independently or used to build a different path.
  - Assert `flushSession` never path-interpolates arbitrary session ids, handles session ids containing `/`, includes `workspace_id` as query when provided, and maps authorized missing-workspace 403 to `ForbiddenError`.
  - Assert workspace-wide optional methods map missing-workspace 403 to `ForbiddenError` under authorized non-wildcard principals: `dashboardTables()`, `listMemories({})`, and `observabilitySummary({})`.

- [x] **Step 2: Implement expanded methods**
  - Keep path interpolation only for server-generated ids (`run_id`, `step_id`, `access_id`).
  - For `completeRun`, use `runId` from the method parameter for the path; send the request body as data only and do not derive the path from `req.run_id`.
  - Use JSON body for arbitrary `sessionId` flush; use optional `workspace_id` query for Phase 4 authorized flush semantics.
  - Preserve optional `workspaceId` parameters for anonymous/default-off convenience, while documenting that auth-enabled non-wildcard calls need workspace ids for workspace-wide summary/list/dashboard routes or the server returns 403.
  - Do not add client-side memory/gate semantics.
  - Add Phase 4 DTOs needed by the expanded surface: `MemoryItem`, `MemoryVersionRecord`, `MemoryConflictRecord`, `ReplayRetrievalResult`, `RunReplayResult`, `ObservabilitySummary`, `ObservabilityReportRequest`, `ObservabilityReportResult`, `DashboardTables`, `FinishStep*`, `Rollback*`, and `CompleteRun*`.

- [x] **Step 3: Verify**
  - Command: `bun test packages/ts-sdk/test`
  - Command: `bun run typecheck`
  - Expected: all pass.

### INT-A3 Cross-Language Contract Smoke

**Status (2026-06-14):** ✅ complete. Added mocked deterministic contract smoke, an environment-gated optional real-service smoke, and a minimal `examples/ts-simple-agent/src/index.ts` example.

**Files:**
- Create: `examples/ts-simple-agent/src/index.ts`
- Create: `packages/ts-sdk/test/contract.test.ts`
- Optional script: `scripts/smoke-integrations.sh`

- [x] **Step 1: Add mocked deterministic contract smoke**
  - Use mocked fetch by default so CI does not require a running API service.
  - Assert a simple sequence can be represented: start run, start step, write event, retrieve context, inspect access.

- [x] **Step 2: Add optional real-service smoke**
  - Gate real HTTP smoke behind `MEMTRACE_TEST_HTTP_URL`.
  - If env var is missing, test skips with a clear message.
  - Do not add this to `scripts/reproduce.sh` unless the service is started deterministically inside the script.

- [x] **Step 3: Verify Python remains unchanged**
  - Command: `uv run --extra dev pytest packages/python-sdk/tests/test_http_backend.py packages/python-sdk/tests/test_backend_isomorphism.py -q`
  - Expected: Python SDK behavior still passes.

---

## 3. Stream INT-B — MCP Server

### INT-B1 Minimal MCP Tools Over TS SDK

**Status (2026-06-14):** ✅ complete. Added `@memtrace/mcp-server` with env-based config, stdio MCP server wiring, five first-wave tools over the TS SDK, concise/redacted outputs, and tests proving tool schemas, SDK method dispatch, and no Python runtime/database imports.

**Files:**
- Create: `packages/mcp-server/package.json`
- Create: `packages/mcp-server/tsconfig.json`
- Create: `packages/mcp-server/src/server.ts`
- Create: `packages/mcp-server/src/tools.ts`
- Create: `packages/mcp-server/src/config.ts`
- Create: `packages/mcp-server/test/tools.test.ts`

- [x] **Step 1: Write RED MCP tool tests**
  - Mock the TS SDK client.
  - Assert tool schemas exist for first release:
    - `memtrace_start_run`
    - `memtrace_start_step`
    - `memtrace_write_event`
    - `memtrace_retrieve_context`
    - `memtrace_inspect_access`
  - Assert tools call TS SDK methods and never import Python runtime/database modules.

- [x] **Step 2: Implement config**
  - Require explicit `MEMTRACE_BASE_URL`.
  - Support `MEMTRACE_API_KEY` env var.
  - Refuse startup when base URL is missing, returning a clear configuration error.
  - `packages/mcp-server/package.json` uses the stable package name `@memtrace/mcp-server` and imports the TS SDK as `@memtrace/sdk`.

- [x] **Step 3: Implement tools**
  - Keep result payloads concise by default.
  - Redact tool error output and never echo API keys.
  - Use SDK error classes for user-facing error messages.

- [x] **Step 4: Verify**
  - Command: `bun test packages/mcp-server/test/tools.test.ts`
  - Command: `bun run typecheck`
  - Expected: all pass.

### INT-B2 Expanded MCP Tools After Output Safety Review

**Status (2026-06-14):** ✅ complete and detailed-review hardened. Added second-wave MCP tools `memtrace_finish_step`, `memtrace_replay_access`, and `memtrace_report`; replay/report output is capped at 8k characters by default and all success/error text is redacted for raw auth headers, API keys, raw payload refs, destructive commands, production path markers, password-like values, and JSON-style secret-like key/value pairs. Detailed review also made unknown-tool errors use the same redacted/capped path, restricted `MEMTRACE_BASE_URL` to HTTP(S) without embedded credentials, and made MCP source-boundary tests cwd-stable. Root README now includes MCP configuration snippets using environment variables.

**Files:**
- Modify: `packages/mcp-server/src/tools.ts`
- Modify: `packages/mcp-server/test/tools.test.ts`
- Modify: root `README.md`

- [x] **Step 1: Add RED tests for second-wave tools**
  - Add tools:
    - `memtrace_finish_step`
    - `memtrace_replay_access`
    - `memtrace_report`
  - Assert long outputs are summarized or paginated in tool response metadata.
  - Assert replay/report tool response text is capped at 8k characters by default; full payloads require explicit report export paths or metadata references.
  - Assert report/replay tools preserve redaction and do not include raw unsafe failed commands, raw API keys, raw `Authorization` headers, raw `raw_payload_ref` values, or unsafe markers such as `rm -rf`, `/prod`, `sk-`, and `password`.

- [x] **Step 2: Implement second-wave tools**
  - Use TS SDK methods only.
  - Require explicit user input for report export directory if the tool writes files.
  - Keep all retrieval/replay semantics on the server side.

- [x] **Step 3: Add config examples in root README**
  - Add Claude Code/Cursor-style MCP config snippets using env vars.
  - Do not create `examples/mcp/README.md` unless implementation closeout explicitly accepts a separate example doc.

---

## 4. Stream INT-C — IDE Integration Thin Layer

### INT-C1 MCP Config Templates Before Extension Package

**Status (2026-06-14):** ✅ complete. Added Claude Code and Cursor-style JSON templates under `examples/mcp/`, package-exported template fixtures in `@memtrace/mcp-server`, README copy-paste snippets, and Bun tests proving templates use `MEMTRACE_BASE_URL` / `MEMTRACE_API_KEY` placeholders with no real secrets.

**Files:**
- Modify: `README.md`
- Create: `examples/mcp/claude-code.json`, `examples/mcp/cursor.json`
- Test: `packages/mcp-server/test/config.test.ts`

- [x] **Step 1: Add config template tests**
  - Assert templates use env vars for `MEMTRACE_BASE_URL` and `MEMTRACE_API_KEY`.
  - Assert templates do not contain real secrets. A documented local default such as `http://127.0.0.1:8000` is acceptable, but real tokens must be represented by environment-variable placeholders.

- [x] **Step 2: Add documentation/templates**
  - Provide copy-paste MCP config snippets for Claude Code and Cursor-style clients.
  - Keep docs clear that MCP uses the HTTP API through the TS SDK.

### INT-C2 Decide Dedicated IDE Package Only After MCP Adoption

**Status (2026-06-14):** ✅ complete as a scope decision. No `packages/ide/` package is created in this slice; dedicated IDE work remains deferred until MCP usage provides adoption feedback and concrete editor-specific requirements.

**Files:**
- Create only if selected after MCP review: `packages/ide/`
- Test: package-specific smoke tests if created

- [x] **Step 1: Scope decision checkpoint**
  - Prefer command palette wrappers around MCP tools before building a full VS Code extension.
  - If selected, IDE package exposes only: start run, record event, retrieve context, inspect/replay access, export redacted bundle.

- [x] **Step 2: Enforce semantic boundary**
  - IDE layer calls MCP/TS SDK only.
  - IDE layer must not implement retrieval, gate, packing, summarization, auth, or redaction logic.

---

## 5. Verification and Closeout

### After INT-A

- Command: `bun test packages/ts-sdk/test`
- Command: `bun run typecheck`
- Command: `uv run --extra dev pytest packages/python-sdk/tests/test_http_backend.py packages/python-sdk/tests/test_backend_isomorphism.py -q`
- Expected: TS SDK tests pass and Python SDK remains stable.

### After INT-B

- Command: `bun test packages/mcp-server/test`
- Command: `bun run typecheck`
- Expected: MCP server tests pass without a running API service.

### After INT-C

- Command: `bun test`
- Command: `bun run typecheck`
- Observed on 2026-06-14 with temporary Bun: `npm exec --yes --package bun -- bun test` -> passed; `npm exec --yes --package bun -- bun run typecheck` -> passed.
- Optional command when API service is available: `MEMTRACE_TEST_HTTP_URL=http://127.0.0.1:8000 bash scripts/smoke-integrations.sh`

### Final docs and project memory

- Update `docs/design/ROADMAP.md` after each integration stream.
- Update `.ai/PROJECT_STATE.md`, `.ai/REQUIREMENTS.md`, `.ai/IMPLEMENTATION_PLAN.md`, `.ai/OPEN_QUESTIONS.md`, and `.ai/PITFALLS.md`.
- Add pitfalls for: Bun-only lockfiles, arbitrary session id body flush, MCP output redaction, and avoiding runtime/database imports from integrations.

---

## 6. Self-Review Checklist

- [x] TS SDK first release is scoped to core methods; replay/report/dashboard are second wave.
- [x] MCP first release is scoped to core tools; replay/report are second wave after output safety review.
- [x] IDE work starts with MCP templates before any extension package.
- [x] All integration layers consume HTTP/SDK semantics and do not bypass `MemoryRuntime`.
- [x] Bun is the only JS package-manager path described.
- [x] Tests are deterministic by default and real-service smoke is explicitly gated.
