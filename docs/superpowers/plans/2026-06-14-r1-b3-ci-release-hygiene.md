# R1-B3 CI and Release Hygiene Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the default GitHub Actions CI matrix for R1-B3 and a tracked-file/docs hygiene guard for R1-C2 Step 4.

**Architecture:** Keep CI split into focused jobs: Python verification, Bun/TypeScript verification, and release hygiene. The hygiene script is a deterministic repository-root shell check that inspects only tracked files and docs/examples text, so it can run locally and in CI without external services.

**Tech Stack:** GitHub Actions, `uv`, Bun via `oven-sh/setup-bun`, Bash, Git tracked-file inspection.

---

## File Structure

- Create `.github/workflows/ci.yml`: default PR/push/manual CI with Python, JavaScript, and release-hygiene jobs. It must not require PostgreSQL, Redis, LLM/provider secrets, or a live HTTP service.
- Create `scripts/check-release-hygiene.sh`: tracked-file artifact guard plus docs/examples marker scan for obvious real secrets, bearer/sk tokens, unredacted raw payload references, and raw destructive production commands.
- Modify `docs/design/RELEASE_READINESS_PLAN.md`: mark R1-B3 and R1-C2 Step 4 implemented once the files and validation pass.

## Task 1: Add Release Hygiene Guard

**Files:**
- Create: `scripts/check-release-hygiene.sh`

- [x] **Step 1: Write the guard script**

Create `scripts/check-release-hygiene.sh` with:

```bash
#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

failures=0

report_failure() {
  local message="$1"
  printf 'error: %s\n' "$message" >&2
  failures=1
}

tracked_matches() {
  local pattern="$1"
  git ls-files | grep -E "$pattern" || true
}

forbidden_artifacts="(^|/)node_modules/|\.tsbuildinfo$|(^|/)package-lock\.json$|(^|/)pnpm-lock\.yaml$|(^|/)yarn\.lock$|\.tgz$|^reports/|(^|/)docker-data/|(^|/)postgres-data/|(^|/)redis-data/|(^|/)\.env$"
artifact_matches="$(tracked_matches "$forbidden_artifacts")"
if [[ -n "$artifact_matches" ]]; then
  report_failure "forbidden generated/local-service artifacts are tracked:"
  printf '%s\n' "$artifact_matches" >&2
fi

scan_paths=(README.md docs examples)
existing_scan_paths=()
for path in "${scan_paths[@]}"; do
  if [[ -e "$path" ]]; then
    existing_scan_paths+=("$path")
  fi
done

secret_pattern="(sk-[A-Za-z0-9_-]{12,}|Bearer[[:space:]]+[A-Za-z0-9._~+/-]{12,}|api[_-]?key[[:space:]]*[:=][[:space:]]*['\"]?[A-Za-z0-9._~+/-]{12,}|password[[:space:]]*[:=][[:space:]]*['\"]?[^[:space:]'\"]{6,})"
secret_matches="$(
  git grep -n -I -E -i "$secret_pattern" -- "${existing_scan_paths[@]}" ':!docs/design/*' ':!docs/superpowers/*' \
    | grep -Ev 'process\.env|your-|example-|placeholder|\$\{[A-Z0-9_]+\}' \
    || true
)"
if [[ -n "$secret_matches" ]]; then
  report_failure "possible real secret markers found in public docs/examples:"
  printf '%s\n' "$secret_matches" >&2
fi

raw_payload_pattern="raw_payload_ref[[:space:]]*[:=][[:space:]]*(['\"][^'\"]+['\"]|[^[:space:]#]+)"
raw_payload_matches="$(git grep -n -I -E "$raw_payload_pattern" -- "${existing_scan_paths[@]}" ':!docs/design/*' ':!docs/superpowers/*' || true)"
if [[ -n "$raw_payload_matches" ]]; then
  report_failure "unredacted raw_payload_ref values found:"
  printf '%s\n' "$raw_payload_matches" >&2
fi

destructive_matches="$(git grep -n -I -E 'rm[[:space:]]+-rf[[:space:]]+/(prod|production|var|etc|usr|home|root)(/|[[:space:]]|$)' -- "${existing_scan_paths[@]}" ':!docs/design/*' ':!docs/superpowers/*' || true)"
if [[ -n "$destructive_matches" ]]; then
  report_failure "raw destructive production command examples found:"
  printf '%s\n' "$destructive_matches" >&2
fi

if [[ "$failures" -ne 0 ]]; then
  exit 1
fi

echo "release hygiene checks passed"
```

- [x] **Step 2: Run the guard**

Run: `bash scripts/check-release-hygiene.sh`

Expected: `release hygiene checks passed`

## Task 2: Add Default GitHub Actions CI

**Files:**
- Create: `.github/workflows/ci.yml`

- [x] **Step 1: Write CI workflow**

Create `.github/workflows/ci.yml` with:

```yaml
name: CI

on:
  pull_request:
  push:
    branches: [main]
  workflow_dispatch:

jobs:
  python:
    name: Python compile and tests
    runs-on: ubuntu-latest
    steps:
      - name: Check out repository
        uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Compile Python sources
        run: uv run --extra dev python -m compileall -q apps/api/app packages/python-sdk/src examples

      - name: Run Python tests
        run: uv run --extra dev pytest -q

  javascript:
    name: Bun typecheck and tests
    runs-on: ubuntu-latest
    steps:
      - name: Check out repository
        uses: actions/checkout@v4

      - name: Set up Bun
        uses: oven-sh/setup-bun@v2
        with:
          bun-version: '1.3.14'

      - name: Install dependencies
        run: bun install --frozen-lockfile

      - name: Typecheck
        run: bun run typecheck

      - name: Run Bun tests
        run: bun test

  release-hygiene:
    name: Release hygiene
    runs-on: ubuntu-latest
    steps:
      - name: Check out repository
        uses: actions/checkout@v4

      - name: Run release hygiene guard
        run: bash scripts/check-release-hygiene.sh
```

- [x] **Step 2: Validate workflow shape locally**

Run: `bash scripts/check-release-hygiene.sh`

Expected: `release hygiene checks passed`

## Task 3: Update R1 Plan Tracking

**Files:**
- Modify: `docs/design/RELEASE_READINESS_PLAN.md`

- [x] **Step 1: Mark completed checkboxes and record implementation**

Update R1-B3 Step 1, Step 2, and R1-C2 Step 4 to checked. Keep R1-B3 Step 3 unchecked because no separate release-check workflow is added in this slice.

- [x] **Step 2: Re-run targeted validation**

Run: `bash scripts/check-release-hygiene.sh`

Expected: `release hygiene checks passed`

Run: `git status --short`

Expected: new `.github/workflows/ci.yml`, new `scripts/check-release-hygiene.sh`, and modified release plan appear alongside pre-existing R1 work.

## Self-Review

- Spec coverage: R1-B3 default CI is covered by Task 2; optional integrations stay gated because no service env vars are required. R1-C2 Step 4 tracked-file guard and docs/examples scan are covered by Task 1. Plan tracking is covered by Task 3.
- Placeholder scan: no TBD/TODO placeholders remain.
- Type consistency: all commands use existing project tools: `uv`, `bun`, `bash`, and `git`.
