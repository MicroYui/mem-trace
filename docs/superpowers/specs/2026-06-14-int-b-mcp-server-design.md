# INT-B MCP Server Design

## Scope

Implement `docs/design/INTEGRATIONS_PLAN.md` Stream INT-B in full: INT-B1 minimal MCP tools and INT-B2 second-wave tools. The MCP server is a thin TypeScript entrypoint over `@memtrace/sdk`; it must not import Python runtime, storage, database, retrieval, gate, or context-packing modules.

## Architecture

- Add workspace package `@memtrace/mcp-server` under `packages/mcp-server`.
- Keep package boundaries small:
  - `config.ts`: read and validate `MEMTRACE_BASE_URL`; read optional `MEMTRACE_API_KEY`; never include secrets in errors.
  - `tools.ts`: define tool schemas, dependency-injected tool handlers, output formatting, truncation, and redaction.
  - `server.ts`: wire tools into an MCP stdio server and create `MemTraceClient` from env config.
  - `index.ts`: package exports for tests and downstream consumers.
- The only MemTrace integration dependency is `@memtrace/sdk`.

## Tools

First wave:

- `memtrace_start_run` -> `MemTraceClient.startRun`
- `memtrace_start_step` -> `MemTraceClient.startStep`
- `memtrace_write_event` -> `MemTraceClient.writeEvent`
- `memtrace_retrieve_context` -> `MemTraceClient.retrieveContext`
- `memtrace_inspect_access` -> `MemTraceClient.inspectAccess`

Second wave:

- `memtrace_finish_step` -> `MemTraceClient.finishStep`
- `memtrace_replay_access` -> `MemTraceClient.replayAccess`
- `memtrace_report` -> `MemTraceClient.writeObservabilityReport`

## Output and Safety

- Tool responses return concise MCP text payloads with key ids, counts, status, warnings, and small summaries.
- Replay/report output is capped at 8k characters by default. Truncated responses explicitly say they were truncated.
- Redaction is applied to all text before returning to the MCP client. Redaction covers bearer tokens, authorization headers, API-key phrases, OpenAI-style `sk-...` tokens, password-like values, raw payload refs, destructive command examples, and production path markers.
- SDK errors are mapped into user-facing text containing error class, status, code, and redacted message only.

## Testing

- Add Bun tests with mocked SDK clients.
- Assert all eight tool names exist, schemas are present, and handlers call the expected SDK methods.
- Assert missing `MEMTRACE_BASE_URL` returns a clear config error.
- Assert API keys and unsafe markers are absent from error and replay/report outputs.
- Assert long replay/report outputs are capped at 8k characters.
- Assert MCP package source does not contain Python runtime/database import markers.

## Verification

Run:

```bash
npm exec --yes --package bun -- bun test packages/mcp-server/test/tools.test.ts
npm exec --yes --package bun -- bun run typecheck
npm exec --yes --package bun -- bun test packages/ts-sdk/test
```

Only `bun.lock` may be updated; npm/pnpm/yarn lockfiles must not be introduced.
