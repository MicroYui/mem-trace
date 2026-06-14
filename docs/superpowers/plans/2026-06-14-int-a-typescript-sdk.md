# INT-A TypeScript SDK Implementation Plan

**Status:** ✅ Completed on 2026-06-14. This file is retained as the historical execution plan for INT-A. INT-A, INT-B, and INT-C are now complete; current next work is selecting the next remaining ROADMAP target.

**Latest verification:** `npm exec --yes --package bun -- bun run typecheck` passed; `npm exec --yes --package bun -- bun test packages/ts-sdk/test` passed with **9 passed, 1 skipped** after the post-review 422 mapping follow-up; `uv run --extra dev pytest packages/python-sdk/tests/test_http_backend.py packages/python-sdk/tests/test_backend_isomorphism.py -q` passed with **13 passed**.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the complete INT-A TypeScript SDK loop for MemTrace.

**Architecture:** Add a Bun workspace with `@memtrace/sdk` as a strict TypeScript package. The SDK is a fetch-based thin client over FastAPI `/v1`, with DTO types, status-aware error mapping, deterministic mocked tests, and optional real-service smoke.

**Tech Stack:** Bun workspace, TypeScript, `bun:test`, fetch API, existing Python FastAPI runtime.

---

## File Map

- Root `package.json`: Bun workspace scripts for `test` and `typecheck`.
- Root `tsconfig.base.json` and `tsconfig.json`: shared strict TS settings and project reference.
- `packages/ts-sdk/package.json`: package metadata for `@memtrace/sdk`.
- `packages/ts-sdk/tsconfig.json`: package-specific compiler config.
- `packages/ts-sdk/src/types.ts`: structural DTOs for current `/v1` JSON contracts.
- `packages/ts-sdk/src/errors.ts`: SDK error classes and HTTP response parsing.
- `packages/ts-sdk/src/client.ts`: `MemTraceClient` and route/query/body helpers.
- `packages/ts-sdk/src/index.ts`: public exports.
- `packages/ts-sdk/test/*.test.ts`: mocked route/error/contract tests plus optional HTTP smoke.
- `.gitignore`: ignore JS dependency/build output directories.
- `docs/design/INTEGRATIONS_PLAN.md` and `.ai/*`: closeout progress updates.

## Tasks

### Task 1: Workspace and SDK Skeleton

- [x] Add root Bun workspace files and `@memtrace/sdk` package metadata.
- [x] Add strict TS configs.
- [x] Add empty SDK source/test files.
- [x] Verify absence of npm/pnpm/yarn lockfiles.

### Task 2: Types and Errors

- [x] Implement DTO unions/interfaces for core and Phase 4 route payloads.
- [x] Implement `MemTraceError`, `BadRequestError`, `NotFoundError`, `ForbiddenError`, and `RateLimitedError`.
- [x] Add mocked tests for FastAPI `detail`, validation detail arrays, JSON `message`, non-JSON body, 401/403 auth, 404, and 429.

### Task 3: Core and Expanded Client

- [x] Implement constructor options: `baseUrl`, optional `apiKey`, optional custom `fetch`.
- [x] Implement core INT-A1 methods: `startRun`, `startStep`, `writeEvent`, `retrieveContext`, `inspectAccess`.
- [x] Implement INT-A2 methods: finish/rollback/complete, timeline/state/profile/steps, body-based session flush, replay, observability, dashboard, memory list/version/conflict routes.
- [x] Add mocked tests for headers, paths, query strings, request bodies, path-authoritative complete-run behavior, and non-path-interpolated session ids.

### Task 4: Contract Smoke and Verification

- [x] Add mocked start-run/start-step/write/retrieve/inspect sequence smoke.
- [x] Add `MEMTRACE_TEST_HTTP_URL` gated real-service smoke.
- [x] Run `bun test packages/ts-sdk/test` and `bun run typecheck`.
- [x] Run Python SDK HTTP/isomorphism regression.

### Task 5: Closeout

- [x] Mark INT-A1/INT-A2/INT-A3 complete in `docs/design/INTEGRATIONS_PLAN.md`.
- [x] Update `.ai/PROJECT_STATE.md`, `.ai/REQUIREMENTS.md`, `.ai/IMPLEMENTATION_PLAN.md`, `.ai/OPEN_QUESTIONS.md`, and `.ai/PITFALLS.md` with current INT-A status and verification.
- [x] Report changed files, verification evidence, and any environment caveats.
