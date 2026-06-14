# R1-A3/B1/B2 Release Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete R1-A3 demo-flow consolidation plus R1-B1 TypeScript package readiness and R1-B2 Python package/CLI readiness without changing MemTrace runtime semantics.

**Architecture:** Add one deterministic release-readiness smoke script that orchestrates existing no-network public demos and verifies stable markers. Add package-shape tests for JS packages and metadata/readiness tests for Python packaging/CLI, then make package metadata explicit while keeping packages private and source-entry based. Update user docs, roadmap, release plan, and `.ai` memory to keep resume/project recovery aligned.

**Tech Stack:** Bash, Python pytest, Bun test, TypeScript package metadata, uv workspace, existing CLI/example commands, Markdown docs.

---

### Task 1: R1-A3 Canonical Demo Smoke

**Files:**
- Create: `scripts/smoke-release-readiness.sh`
- Modify: `README.md`
- Modify: `docs/getting-started.md`
- Test: `packages/python-sdk/tests/test_examples_smoke.py`

- [ ] **Step 1: Write failing test**

Add a pytest test that runs `bash scripts/smoke-release-readiness.sh` and asserts it prints the stable no-network markers:

```python
def test_release_readiness_smoke_script_runs_canonical_no_network_demo() -> None:
    result = subprocess.run(
        ["bash", "scripts/smoke-release-readiness.sh"],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )

    output = result.stdout.lower()
    assert "baseline_1 action: npm test" in result.stdout
    assert "variant_2 action: bun test" in result.stdout
    assert "contamination eliminated: true" in output
    assert "release readiness smoke passed" in output
```

- [ ] **Step 2: Verify RED**

Run:

```bash
uv run --package memtrace-sdk --extra dev pytest packages/python-sdk/tests/test_examples_smoke.py::test_release_readiness_smoke_script_runs_canonical_no_network_demo -q
```

Expected: fail because `scripts/smoke-release-readiness.sh` does not exist.

- [ ] **Step 3: Implement script**

Create `scripts/smoke-release-readiness.sh` with `set -euo pipefail`. It should:

1. Run `uv run --package memtrace-sdk memtrace demo --in-process`, capture output, and require the three stable markers.
2. Run `uv run --package memtrace-sdk python examples/simple_agent/main.py`, capture output, and require the same markers.
3. If `MEMTRACE_SMOKE_HTTP_URL` is set, run `uv run --package memtrace-sdk memtrace --http "$MEMTRACE_SMOKE_HTTP_URL" demo`; otherwise print that HTTP smoke is skipped.
4. If both `MEMTRACE_SMOKE_TS=1` and `MEMTRACE_BASE_URL` are set, run the TypeScript example through `${BUN_CMD:-npm exec --yes --package bun -- bun}`; otherwise print that TypeScript smoke is skipped.
5. Print `release readiness smoke passed`.

- [ ] **Step 4: Verify GREEN**

Run the same targeted pytest command. Expected: pass.

- [ ] **Step 5: Document canonical flow**

Update README and `docs/getting-started.md` so the 5-minute demo points to `scripts/smoke-release-readiness.sh` as the canonical no-network smoke, while keeping HTTP/TS/MCP service-dependent paths explicitly gated.

### Task 2: R1-B1 TypeScript Package Shape

**Files:**
- Modify: `packages/ts-sdk/package.json`
- Modify: `packages/mcp-server/package.json`
- Test: `packages/ts-sdk/test/package-shape.test.ts`
- Test: `packages/mcp-server/test/package-shape.test.ts`

- [ ] **Step 1: Write failing package-shape tests**

Add Bun tests that read each package's `package.json` and assert:

- `private` remains `true`.
- `description`, `license`, `repository.url`, `homepage`, `bugs.url`, and `keywords` are present.
- `exports` points at source entrypoints (`./src/index.ts`; MCP server also exposes `./server`).
- `files` includes `src` and excludes generated/publish-unsafe entries such as `dist`, `node_modules`, `test`, `*.tsbuildinfo`, and lockfiles.
- MCP `bin.memtrace-mcp-server` remains `./src/server.ts`.

- [ ] **Step 2: Verify RED**

Run:

```bash
npm exec --yes --package bun -- bun test packages/ts-sdk/test/package-shape.test.ts packages/mcp-server/test/package-shape.test.ts
```

Expected: fail on missing metadata/exports/files.

- [ ] **Step 3: Add metadata**

Update both package manifests with release-ready non-publishing metadata, preserving `private: true` and avoiding `dist`/build tooling. Use repository `git+https://github.com/MicroYui/mem-trace.git`, homepage `https://github.com/MicroYui/mem-trace#readme`, bugs URL `https://github.com/MicroYui/mem-trace/issues`, and `Apache-2.0` license.

- [ ] **Step 4: Verify GREEN**

Run the package-shape tests, then root `bun run typecheck` and `bun test` through temporary Bun.

### Task 3: R1-B2 Python Package and CLI Readiness

**Files:**
- Modify: `pyproject.toml`
- Modify: `packages/python-sdk/pyproject.toml`
- Test: `packages/python-sdk/tests/test_package_metadata.py`
- Existing Test: `packages/python-sdk/tests/test_cli.py`

- [ ] **Step 1: Write failing metadata tests**

Create `test_package_metadata.py` using `tomllib` to assert root `memtrace` and `packages/python-sdk` package metadata have non-P0-only descriptions, `Apache-2.0` license, repository/homepage/bugs URLs, useful classifiers, and the `memtrace` console script points to `memtrace_sdk.cli:main`.

- [ ] **Step 2: Verify RED**

Run:

```bash
uv run --package memtrace-sdk --extra dev pytest packages/python-sdk/tests/test_package_metadata.py -q
```

Expected: fail because package metadata is incomplete/stale.

- [ ] **Step 3: Update Python metadata**

Update root and Python SDK `pyproject.toml` metadata. Keep uv workspace wiring unchanged and keep the console script entrypoint unchanged.

- [ ] **Step 4: Verify CLI readiness**

Run:

```bash
uv run --package memtrace-sdk --extra dev pytest packages/python-sdk/tests/test_package_metadata.py packages/python-sdk/tests/test_cli.py -q
uv run --package memtrace-sdk memtrace demo --in-process
```

Expected: metadata tests and CLI tests pass, and demo prints stable markers.

### Task 4: Docs and Project Memory Closeout

**Files:**
- Modify: `docs/design/RELEASE_READINESS_PLAN.md`
- Modify: `docs/design/ROADMAP.md`
- Modify: `.ai/PROJECT_STATE.md`
- Modify: `.ai/REQUIREMENTS.md`
- Modify: `.ai/IMPLEMENTATION_PLAN.md`
- Modify: `.ai/PITFALLS.md`

- [ ] **Step 1: Mark R1-A3/B1/B2 complete**

Record implemented files, verification commands, and next action as R1-B3 CI matrix.

- [ ] **Step 2: Run final verification**

Run targeted Python tests, targeted Bun package-shape tests, root Bun typecheck/test, release-readiness smoke script, and CLI demo. If feasible, run benchmark acceptance.

- [ ] **Step 3: Keep generated artifacts untracked**

Check `git status --short` and ensure generated reports, `node_modules`, tsbuildinfo, and npm/pnpm/yarn lockfiles are not tracked.

## Self-Review

- Spec coverage: R1-A3 is covered by Task 1; R1-B1 by Task 2; R1-B2 by Task 3; docs/memory closeout by Task 4.
- Placeholder scan: no `TBD` or open implementation placeholders remain.
- Type consistency: script path, package metadata keys, and test commands match the existing uv/Bun workspace layout.
