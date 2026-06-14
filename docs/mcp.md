# MCP Integration

`@memtrace/mcp-server` exposes MemTrace to MCP-capable agents and IDEs as a stdio server. It is a thin adapter over `@memtrace/sdk`, which is itself a thin HTTP client over MemTrace's `/v1` API.

## What the MCP server does

The server lets an MCP client:

- start runs and steps,
- write events,
- retrieve gated packed context,
- inspect access logs,
- finish steps,
- replay an access,
- generate observability reports.

Available tools:

- `memtrace_start_run`
- `memtrace_start_step`
- `memtrace_write_event`
- `memtrace_retrieve_context`
- `memtrace_inspect_access`
- `memtrace_finish_step`
- `memtrace_replay_access`
- `memtrace_report`

The MCP server does not import Python runtime or database modules. Runtime semantics remain on the server side: MCP → TypeScript SDK → HTTP `/v1` → `MemoryRuntime`.

## Runtime preconditions

The MCP server requires a running MemTrace HTTP service:

```bash
docker-compose up -d
until docker inspect --format='{{.State.Health.Status}}' memtrace-postgres | grep -q healthy; do sleep 1; done
uv run alembic upgrade head
uv run uvicorn app.main:app --app-dir apps/api --reload
```

Configure service location and optional API key in the MCP client environment:

```bash
export MEMTRACE_BASE_URL="http://127.0.0.1:8000"
export MEMTRACE_API_KEY="your-dev-token-if-auth-is-enabled"
```

If auth/governance is disabled, `MEMTRACE_API_KEY` can be left unset or empty.

## Claude Code-style template

Template file: [`examples/mcp/claude-code.json`](../examples/mcp/claude-code.json)

```json
{
  "mcpServers": {
    "memtrace": {
      "command": "bun",
      "args": ["packages/mcp-server/src/server.ts"],
      "env": {
        "MEMTRACE_BASE_URL": "${MEMTRACE_BASE_URL}",
        "MEMTRACE_API_KEY": "${MEMTRACE_API_KEY}"
      }
    }
  }
}
```

## Cursor-style template

Template file: [`examples/mcp/cursor.json`](../examples/mcp/cursor.json)

```json
{
  "mcpServers": {
    "memtrace": {
      "command": "bun",
      "args": ["packages/mcp-server/src/server.ts"],
      "env": {
        "MEMTRACE_BASE_URL": "${MEMTRACE_BASE_URL}",
        "MEMTRACE_API_KEY": "${MEMTRACE_API_KEY}"
      }
    }
  }
}
```

## Local-development path assumptions

The checked-in templates are local-development templates. They assume the MCP client launches the command from the repository root, where `packages/mcp-server/src/server.ts` exists, and that `bun` is available on the MCP client's `PATH`.

If your client launches from a different working directory, replace the relative path with an absolute path, for example:

```json
"args": ["/absolute/path/to/mem-trace/packages/mcp-server/src/server.ts"]
```

If Bun is not globally available to the MCP client, configure the client to use an absolute Bun executable path or an installed package command once publishing is explicitly approved. The manual `npm exec --yes --package bun -- bun ...` fallback is useful in a shell, but most MCP clients do not automatically run that fallback for `"command": "bun"` templates.

If you later install a packaged command, replace the template command/args with that installed command. R1 keeps both JS packages `private: true`; publishing is a separate maintainer decision.

If your MCP client does not expand `${...}` placeholders inside JSON, render or replace `MEMTRACE_BASE_URL` and `MEMTRACE_API_KEY` outside version control. Do not paste real secrets into checked-in config files.

## Running the server manually

From the repository root, with the HTTP service running:

```bash
MEMTRACE_BASE_URL=http://127.0.0.1:8000 \
npm exec --yes --package bun -- bun packages/mcp-server/src/server.ts
```

This starts a stdio server and waits for MCP protocol messages; it is usually launched by an MCP client rather than run directly by a human.

## Output safety

MCP tool output is an IDE/chat surface. The server redacts common secret-like keys and values, including API keys, bearer tokens, authorization headers, passwords, secret keys, id tokens, `*_token`, `*_secret`, and `*_credential` fields. Replay and report outputs are capped by default so large trace payloads are not dumped into chat context.

Server-side MemTrace redaction and gate policies still apply before MCP sees data. MCP redaction is an additional safety layer for integration output.
