#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

require_marker() {
  local output="$1"
  local marker="$2"
  if ! grep -Fq "$marker" <<<"$output"; then
    echo "error: expected marker not found: $marker" >&2
    exit 1
  fi
}

require_common_markers() {
  local output="$1"
  require_marker "$output" "baseline_1 action: npm test"
  require_marker "$output" "variant_2 action: bun test"
  require_marker "$(tr '[:upper:]' '[:lower:]' <<<"$output")" "contamination eliminated: true"
}

echo "==> Running canonical no-network CLI demo"
CLI_OUTPUT="$(uv run --package memtrace-sdk memtrace demo --in-process)"
printf '%s\n' "$CLI_OUTPUT"
require_common_markers "$CLI_OUTPUT"

echo "==> Running canonical no-network Python SDK example"
PY_OUTPUT="$(uv run --package memtrace-sdk python examples/simple_agent/main.py)"
printf '%s\n' "$PY_OUTPUT"
require_common_markers "$PY_OUTPUT"

if [[ -n "${MEMTRACE_SMOKE_HTTP_URL:-}" ]]; then
  echo "==> Running optional HTTP CLI demo against $MEMTRACE_SMOKE_HTTP_URL"
  HTTP_OUTPUT="$(uv run --package memtrace-sdk memtrace --http "$MEMTRACE_SMOKE_HTTP_URL" demo)"
  printf '%s\n' "$HTTP_OUTPUT"
  require_common_markers "$HTTP_OUTPUT"
else
  echo "==> Skipping optional HTTP smoke (set MEMTRACE_SMOKE_HTTP_URL to enable)"
fi

if [[ "${MEMTRACE_SMOKE_TS:-}" == "1" && -n "${MEMTRACE_BASE_URL:-}" ]]; then
  echo "==> Running optional TypeScript SDK smoke against $MEMTRACE_BASE_URL"
  read -r -a BUN_CMD_PARTS <<<"${BUN_CMD:-npm exec --yes --package bun -- bun}"
  "${BUN_CMD_PARTS[@]}" examples/ts-simple-agent/src/index.ts
else
  echo "==> Skipping optional TypeScript smoke (set MEMTRACE_SMOKE_TS=1 and MEMTRACE_BASE_URL to enable)"
fi

echo "release readiness smoke passed"
