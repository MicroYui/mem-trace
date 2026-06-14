# R1-C1/R1-C2 Release Closeout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete R1 release readiness by adding the maintainer release checklist, running reproducibility closeout, and synchronizing roadmap/project memory so R1 is marked complete.

**Architecture:** This closeout changes documentation, release hygiene, and project-memory state only. It does not add runtime semantics, package publishing automation, JS build pipelines, or mandatory service dependencies. Verification uses existing public entrypoints: benchmark runner, reproduce script, release hygiene guard, Python tests, and Bun tests.

**Tech Stack:** Markdown docs, existing Python `uv` workspace, Bun workspace through temporary `npm exec --yes --package bun -- bun ...` when needed, deterministic benchmark/reproduce scripts, existing release-hygiene script.

---

### Task 1: Add the human release checklist

**Files:**
- Create: `docs/release-checklist.md`
- Modify: `README.md`

- [x] **Step 1: Create `docs/release-checklist.md`**

  Include these concrete release gates:

  ```markdown
  # MemTrace Release Checklist

  ## Scope and publish decision
  - Confirm whether this is a source-only release, a GitHub tag release, a PyPI release, an npm release, or a dry run.
  - Keep `packages/ts-sdk/package.json` and `packages/mcp-server/package.json` at `private: true` unless npm publication is explicitly approved.
  - Do not add `dist/`, bundler, declaration emit, or automatic publish workflow as part of R1.

  ## Required local verification
  - `uv run --extra dev python -m compileall -q apps/api/app packages/python-sdk/src examples`
  - `uv run --extra dev pytest -q`
  - `npm exec --yes --package bun -- bun run typecheck`
  - `npm exec --yes --package bun -- bun test`
  - `bash scripts/check-release-hygiene.sh`
  - `uv run python -m app.benchmark.runner --output-dir reports`
  - `bash scripts/reproduce.sh`

  ## Package metadata and dry-run checks
  - `uv build --out-dir /tmp/memtrace-build-root --package memtrace`
  - `uv build --out-dir /tmp/memtrace-build-sdk --package memtrace-sdk`
  - `npm exec --yes --package bun -- bun test packages/ts-sdk/test/package-shape.test.ts packages/mcp-server/test/package-shape.test.ts`

  ## Artifact and secret hygiene
  - `bash scripts/check-release-hygiene.sh` must pass before tagging or publishing.
  - Do not commit `node_modules/`, `*.tsbuildinfo`, npm/pnpm/yarn lockfiles, `*.tgz`, generated `reports/`, local database files, or tracked `.env` files.

  ## Rollback notes
  - If a GitHub tag is wrong and has not been published broadly, delete the local tag with `git tag -d <tag>` and the remote tag with `git push origin :refs/tags/<tag>`.
  - If a package upload fails before publication, fix metadata and rerun the dry-run/build checks.
  - If a package is already published, prefer publishing a corrected patch version rather than rewriting release history.
  ```

- [x] **Step 2: Link the checklist from README**

  Add `Release checklist` to the user-docs list without moving maintainer-only detail into the first-time quickstart.

- [x] **Step 3: Run release-hygiene guard after adding the checklist**

  Run: `bash scripts/check-release-hygiene.sh`

  Expected: `release hygiene checks passed`

### Task 2: Run closeout verification

**Files:**
- No source changes expected unless verification finds stale docs or broken commands.

- [x] **Step 1: Run deterministic benchmark**

  Run: `uv run python -m app.benchmark.runner --output-dir reports`

  Expected: command exits 0 and reports `acceptance.passed=true` with current global acceptance `13/13`.

- [x] **Step 2: Run reproducibility bundle**

  Run: `bash scripts/reproduce.sh`

  Expected: command exits 0 and prints `acceptance.passed=true (13/13 checks true)`.

- [x] **Step 3: Re-run release hygiene**

  Run: `bash scripts/check-release-hygiene.sh`

  Expected: `release hygiene checks passed`.

### Task 3: Mark R1 complete and sync project memory

**Files:**
- Modify: `docs/design/RELEASE_READINESS_PLAN.md`
- Modify: `docs/design/ROADMAP.md`
- Modify: `.ai/PROJECT_STATE.md`
- Modify: `.ai/REQUIREMENTS.md`
- Modify: `.ai/IMPLEMENTATION_PLAN.md`
- Modify: `.ai/OPEN_QUESTIONS.md`
- Modify: `.ai/PITFALLS.md` only if closeout uncovers a reusable release-readiness trap.

- [x] **Step 1: Update `docs/design/RELEASE_READINESS_PLAN.md`**

  Mark R1-C1 steps complete. Mark R1-C2 Step 3 and Step 5 complete with actual command outputs. Update acceptance criteria to state R1 is complete and next likely feature slice is OpenTelemetry/OpenInference exporter.

- [x] **Step 2: Update `docs/design/ROADMAP.md`**

  Change the R1 roadmap bullet from in-progress to complete. Add `docs/release-checklist.md` to the completed R1 description. Point the next recommended item to OpenTelemetry/OpenInference exporter.

- [x] **Step 3: Update `.ai` memory files**

  Record changed files, verification outputs, R1 complete state, and next recommended action. Ensure `.ai/IMPLEMENTATION_PLAN.md` no longer says R1-C1/C2 is pending.

- [x] **Step 4: Stale wording scan**

  Search for stale “R1-C1”, “R1-C2”, “current release-readiness work”, and global “12/12” acceptance wording. Keep historical slice counts only when clearly labeled historical; current global benchmark/reproduce acceptance must be `13/13`.

### Task 4: Final diff and summary

**Files:**
- No additional changes expected unless the diff exposes a missing closeout update.

- [x] **Step 1: Run final status/diff review**

  Run: `git status --short`

  Review that the new release checklist, R1 closeout plan, release plan, roadmap, and `.ai` memory changes are included.

- [x] **Step 2: Report verification evidence**

  Summarize exact commands and outputs. Do not claim completion without the benchmark, reproduce, and hygiene evidence.
