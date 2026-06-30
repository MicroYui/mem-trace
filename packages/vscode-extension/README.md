# MemTrace VS Code Extension

A thin VS Code client for [MemTrace](../../README.md) — **not a reimplementation
of the runtime**. It calls the MemTrace `/v1` HTTP API through `@memtrace/sdk` and
renders the results in an editor output channel.

This completes the ROADMAP §6 "dedicated IDE extension" item as a thin layer over
`/v1`, alongside the already-shipped MCP server + MCP config templates. Editor
integrations stay thin over HTTP and never duplicate Python runtime semantics.

## Commands

| Command | Action |
|---------|--------|
| `MemTrace: Retrieve Context` | Retrieve gated context for a run + query |
| `MemTrace: Show Run Timeline` | List a run's trace events |
| `MemTrace: Inspect Access` | Show the candidate/gate/context breakdown for an access |

## Settings

- `memtrace.baseUrl` — MemTrace `/v1` service URL (default `http://localhost:8000`).
- `memtrace.apiKey` — optional bearer token. Prefer the `MEMTRACE_API_KEY`
  environment variable over storing secrets in settings; the extension reads the
  env var first.

## Build

This package is part of the Bun workspace but is excluded from the root `tsc`
typecheck because it requires `@types/vscode` + a VS Code extension host. To
develop it, install `@types/vscode` and open it in the VS Code Extension
Development Host. The package-shape test (`bun test packages/vscode-extension/test`)
validates the manifest without a VS Code runtime.
