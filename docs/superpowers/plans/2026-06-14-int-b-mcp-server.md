# INT-B MCP Server Implementation Plan

**Status:** ✅ Completed on 2026-06-14. This file is retained as the historical execution plan for INT-B. INT-A, INT-B, and INT-C are now complete; current next work is selecting the next remaining ROADMAP target.

**Latest verification:** `npm exec --yes --package bun -- bun test packages/mcp-server/test/tools.test.ts` passed with **16 passed** after final cross-INT redaction hardening; package-local `cd packages/mcp-server && npm exec --yes --package bun -- bun test test` passed with **18 passed**; `npm exec --yes --package bun -- bun test` passed with **27 passed, 1 skipped**; `npm exec --yes --package bun -- bun run typecheck` passed.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the complete INT-B MCP server as a thin stdio MCP entrypoint over `@memtrace/sdk`.

**Architecture:** Add `@memtrace/mcp-server` as a Bun workspace package. Keep config loading, tool definitions/execution, and stdio server startup in separate files. All MemTrace calls go through `MemTraceClient`; MCP code never imports Python runtime, storage, database, retrieval, gate, or packer code.

**Tech Stack:** Bun workspace, TypeScript, `@modelcontextprotocol/sdk`, `@memtrace/sdk`, Bun test runner.

---

## File Structure

- Modify `package.json`: add `packages/mcp-server` to workspaces and include MCP tests in the root `test` script.
- Modify `tsconfig.json`: include MCP server source/tests.
- Create `packages/mcp-server/package.json`: package metadata, bin entry, dependency on `@memtrace/sdk` and MCP SDK.
- Create `packages/mcp-server/tsconfig.json`: package-level TS config.
- Create `packages/mcp-server/src/config.ts`: env parsing and config errors.
- Create `packages/mcp-server/src/tools.ts`: tool schemas, tool registry, handler execution, redaction, truncation, SDK error formatting.
- Create `packages/mcp-server/src/server.ts`: stdio MCP server wiring.
- Create `packages/mcp-server/src/index.ts`: public exports for tests and consumers.
- Create `packages/mcp-server/test/tools.test.ts`: full INT-B test coverage.
- Modify `docs/design/INTEGRATIONS_PLAN.md`: mark INT-B1/INT-B2 complete with verification notes.
- Modify `docs/design/ROADMAP.md`, `.ai/PROJECT_STATE.md`, `.ai/REQUIREMENTS.md`, `.ai/IMPLEMENTATION_PLAN.md`, `.ai/DECISIONS.md`, `.ai/PITFALLS.md`: sync current progress and next action.

---

## Task 1: Package Skeleton and RED Tests

**Files:**
- Modify: `package.json`
- Modify: `tsconfig.json`
- Create: `packages/mcp-server/package.json`
- Create: `packages/mcp-server/tsconfig.json`
- Create: `packages/mcp-server/test/tools.test.ts`

- [x] **Step 1: Add RED tests for tool registry, config, safety, and SDK calls**

Create tests that import `createMemTraceTools`, `loadMcpConfig`, and constants from files that do not exist yet. Mock the SDK client with methods matching `@memtrace/sdk`.

- [x] **Step 2: Run RED test**

Run: `npm exec --yes --package bun -- bun test packages/mcp-server/test/tools.test.ts`

Expected: fail because MCP server source files do not exist.

- [x] **Step 3: Add package skeleton**

Add the workspace package and include MCP paths in TypeScript config. Do not add npm/pnpm/yarn lockfiles.

- [x] **Step 4: Run RED test again**

Run: `npm exec --yes --package bun -- bun test packages/mcp-server/test/tools.test.ts`

Expected: fail because implementation exports are missing.

---

## Task 2: Config Loader

**Files:**
- Create: `packages/mcp-server/src/config.ts`
- Modify: `packages/mcp-server/test/tools.test.ts`

- [x] **Step 1: Implement `McpConfigError` and `loadMcpConfig`**

`loadMcpConfig(env)` requires `MEMTRACE_BASE_URL`, accepts optional `MEMTRACE_API_KEY`, trims whitespace, validates URL parseability, and never returns or prints secrets in thrown messages.

- [x] **Step 2: Verify config tests**

Run: `npm exec --yes --package bun -- bun test packages/mcp-server/test/tools.test.ts -t config`

Expected: config tests pass.

---

## Task 3: Tool Registry and Concise Safe Outputs

**Files:**
- Create: `packages/mcp-server/src/tools.ts`
- Create: `packages/mcp-server/src/index.ts`
- Modify: `packages/mcp-server/test/tools.test.ts`

- [x] **Step 1: Define tool names and input schemas**

Implement eight tools: `memtrace_start_run`, `memtrace_start_step`, `memtrace_write_event`, `memtrace_retrieve_context`, `memtrace_inspect_access`, `memtrace_finish_step`, `memtrace_replay_access`, and `memtrace_report`.

- [x] **Step 2: Implement dependency-injected handlers**

Each handler calls exactly one SDK method and formats a concise redacted text response.

- [x] **Step 3: Implement redaction and 8k truncation**

Apply redaction to all success/error output. Cap replay/report text to `MAX_TOOL_TEXT_CHARS = 8000` and include a truncation notice.

- [x] **Step 4: Verify tool tests**

Run: `npm exec --yes --package bun -- bun test packages/mcp-server/test/tools.test.ts`

Expected: all MCP tool tests pass.

---

## Task 4: stdio MCP Server Entrypoint

**Files:**
- Create: `packages/mcp-server/src/server.ts`
- Modify: `packages/mcp-server/src/index.ts`

- [x] **Step 1: Wire MCP stdio server**

Create a `Server` from `@modelcontextprotocol/sdk/server/index.js`, connect it to `StdioServerTransport`, register list/call tool handlers from `createMemTraceTools`, and construct `MemTraceClient` from `loadMcpConfig()`.

- [x] **Step 2: Keep startup side effects explicit**

Only start the stdio server when the module is executed as the bin entry; exports remain testable without starting stdio.

- [x] **Step 3: Typecheck**

Run: `npm exec --yes --package bun -- bun run typecheck`

Expected: TypeScript passes.

---

## Task 5: Verification and Project Memory Sync

**Files:**
- Modify: `docs/design/INTEGRATIONS_PLAN.md`
- Modify: `docs/design/ROADMAP.md`
- Modify: `.ai/PROJECT_STATE.md`
- Modify: `.ai/REQUIREMENTS.md`
- Modify: `.ai/IMPLEMENTATION_PLAN.md`
- Modify: `.ai/DECISIONS.md`
- Modify: `.ai/PITFALLS.md`

- [x] **Step 1: Run verification**

Run:

```bash
npm exec --yes --package bun -- bun test packages/mcp-server/test/tools.test.ts
npm exec --yes --package bun -- bun run typecheck
npm exec --yes --package bun -- bun test packages/ts-sdk/test
```

Expected: MCP tests pass, root typecheck passes, TS SDK tests still pass.

- [x] **Step 2: Sync plan/docs/project memory**

Mark INT-B1 and INT-B2 complete. Historical next action was INT-C1 MCP config templates; INT-C is now complete, so the current next recommended action is selecting the next remaining ROADMAP target.

- [x] **Step 3: Confirm no forbidden lockfiles**

Check that `package-lock.json`, `pnpm-lock.yaml`, and `yarn.lock` are absent.

---

## Self-Review

- Spec coverage: all INT-B1 tools, INT-B2 tools, config, redaction, truncation, SDK-only boundary, and verification are covered.
- Placeholder scan: no open-ended placeholder steps remain.
- Type consistency: tool names and SDK method names match existing `packages/ts-sdk/src/client.ts` exports.
