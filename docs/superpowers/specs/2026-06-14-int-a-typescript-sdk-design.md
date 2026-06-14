# INT-A TypeScript SDK Design

## Goal

Implement INT-A as a complete TypeScript SDK slice for MemTrace: a Bun workspace package named `@memtrace/sdk`, a typed fetch-based HTTP client, first-release Phase 4 route coverage, deterministic mock tests, optional real-service smoke, and project-memory closeout.

## Scope

Included:

- Bun workspace at the repository root.
- `packages/ts-sdk` with strict TypeScript sources and tests.
- Thin HTTP client over `/v1`; no Python runtime imports and no duplicated retrieval, gate, context packing, governance, or redaction semantics.
- Error mapping for FastAPI `detail`, validation detail arrays, common JSON error/message fields, non-JSON bodies, and current 400/422/401/403/404/429 statuses.
- Current Phase 4 HTTP contract coverage, including async extraction fields, path-authoritative `completeRun(runId, req)`, body-based `flushSession(sessionId, { workspaceId })`, workspace-wide 403 handling, memory versions, and memory conflicts.

Excluded:

- MCP server and IDE templates.
- Runtime response schema validation libraries such as zod.
- Publishing metadata and release automation.

## Architecture

The SDK is a thin TypeScript facade over the existing FastAPI `/v1` contract. `types.ts` defines structural DTOs aligned with current JSON field names while allowing forward-compatible additional fields. `client.ts` owns path/query/body construction and API-key headers. `errors.ts` owns response parsing and status-to-error-class mapping.

Tests use mocked `fetch` by default so CI does not need a running API. A separate contract smoke file represents the start-run/start-step/write/retrieve/inspect flow with mocked responses and includes an environment-gated real HTTP smoke for `MEMTRACE_TEST_HTTP_URL`.

## Verification

- `bun test packages/ts-sdk/test`
- `bun run typecheck`
- `uv run --extra dev pytest packages/python-sdk/tests/test_http_backend.py packages/python-sdk/tests/test_backend_isomorphism.py -q`

Because this environment may not have Bun installed globally, verification can use a temporary Bun binary via `npm exec --yes --package bun -- bun ...`; the repository still remains a Bun workspace and must not add npm/pnpm/yarn lockfiles.
