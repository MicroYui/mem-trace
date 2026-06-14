# Release Readiness & Public Adoption Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` (recommended) or `executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the already-complete MemTrace core platform, Python SDK/CLI, TypeScript SDK, MCP server, and MCP config templates into a launch-ready open-source adoption path: a new user should understand the project, run a representative demo, connect through Python/HTTP/TypeScript/MCP, and verify reproducibility without reading internal design history.

**Architecture:** This slice does not add new memory algorithms or runtime semantics. It packages existing capabilities into user-facing docs, repeatable demos, package metadata, and CI/release checks. All examples and docs must route through existing public boundaries: Python SDK/CLI, `/v1` HTTP, `@memtrace/sdk`, and `@memtrace/mcp-server`. They must not import internal runtime modules from examples intended to represent external adoption, and they must not duplicate retrieval/gate/context-packing behavior.

**Tech Stack:** Markdown docs, existing Python `uv` workspace, Bun workspace, GitHub Actions, deterministic benchmark/reproduce scripts, existing Docker Compose files, FastAPI service, Python SDK/CLI, TypeScript SDK, MCP server.

---

## 0. Decision: Adopt This Recommendation

Adopt the GPT recommendation and select **R1 Release Readiness & Public Adoption** as the next roadmap target.

Reasons:

- The core system is already broad and deep: trace/state-aware runtime, context compaction, negative evidence, provider registry, controlled key ontology, Phase 4 async/lifecycle/governance, Python SDK/CLI/LangGraph adapter, TypeScript SDK, MCP server, and MCP config templates are complete.
- Remaining feature-heavy candidates such as Phase 5 advanced storage/retrieval, admin conflict workflow, and OpenTelemetry/OpenInference exporter are valuable, but they either increase system complexity or assume an adoption path already exists.
- The current highest-leverage gap is external comprehension and repeatable onboarding: users should be able to answer “what is MemTrace?”, “why not plain vector memory?”, “how do I run it?”, “how do I connect my agent/IDE?”, and “how do I reproduce the benchmark?” from the repository front door.

This plan intentionally comes before OpenTelemetry/OpenInference exporter. OTel remains the recommended next feature target after R1 because exporter value is highest once the project has a clear public onboarding path.

---

## 1. Source-Verified Current State

- Latest selected completed slice is TypeScript SDK + MCP integrations. `@memtrace/sdk` and `@memtrace/mcp-server` exist as Bun workspace packages and remain thin clients over `/v1`.
- Root JS workspace exists with Bun scripts:
  - `bun test packages/ts-sdk/test packages/mcp-server/test`
  - `tsc --noEmit -p tsconfig.json`
- `@memtrace/sdk` currently has minimal package metadata and is marked `private: true`.
- `@memtrace/mcp-server` currently has minimal package metadata, a `memtrace-mcp-server` bin entry, and is marked `private: true`.
- Python project metadata exists in `pyproject.toml`; Python SDK tests are included in root pytest discovery through `packages/python-sdk/tests`.
- MCP config templates already exist under `examples/mcp/` and are mirrored by exported `MCP_CONFIG_TEMPLATES`.
- Existing verification uses temporary Bun via `npm exec --yes --package bun -- bun ...` when Bun is not globally installed. R1 docs and CI should respect this environment reality.
- Governance, Redis/Celery, real LLM providers, optional HTTP smoke tests, and real Redis/Postgres integration tests are config-gated and must stay skipped/disabled by default in public quickstarts and CI unless explicitly enabled.

---

## 2. Non-Goals and Durable Invariants

- Do not add Phase 5 Elasticsearch/OpenSearch, Neo4j, graph retrieval, RRF, query planner, or multi-hop retrieval in this slice.
- Do not add OpenTelemetry/OpenInference exporter in R1; record it as the next likely feature slice after launch readiness.
- Do not build a React dashboard or dedicated IDE extension in this slice.
- Do not implement admin/manual conflict resolution workflow or new governance semantics in this slice.
- Do not publish npm or PyPI packages automatically from CI. R1 prepares metadata and dry-run/package checks; actual publishing remains an explicit maintainer action.
- Do not make Redis/Celery, real LLM providers, real external HTTP services, or live PostgreSQL integration tests mandatory for default CI.
- Do not add user-facing examples that bypass the public SDK/HTTP/MCP boundaries.
- Do not commit generated benchmark reports, `node_modules`, TypeScript build info, npm/pnpm/yarn lockfiles, or local service artifacts.

---

## 3. Stream R1-A — README, User Docs, and 5-Minute Demo Path

### R1-A0 Command Inventory Before README Rewrite

**Files:**
- Modify: `README.md` only after command inventory confirms the public command set
- Optional modify: existing example scripts only if inventory finds command drift

- [x] **Step 1: Inventory current commands before writing user-facing docs** ✅ Completed 2026-06-14. Confirmed CLI in-process and Python SDK examples emit stable `baseline_1 action: npm test`, `variant_2 action: bun test`, and `contamination eliminated: true` markers; TypeScript SDK example is a live HTTP client; MCP server/templates require a local HTTP service and repository-root path assumptions.
  - Confirm current CLI in-process demo command and stable stdout markers.
  - Confirm HTTP demo command, required service preconditions, and whether the command is default/no-network or optional/live-service.
  - Confirm TypeScript example command from the repository root and, if supported, package-local context.
  - Confirm MCP server command, Claude Code/Cursor template paths, and local-development path assumptions.

- [x] **Step 2: Classify commands by runtime requirement** ✅ Completed 2026-06-14. README/docs now classify CLI/Python demos and benchmark/reproduce as default/no-network, HTTP/TS/MCP paths as local-service or Docker/PostgreSQL-gated, Redis/Celery as optional, and real providers as external-provider optional.
  - Mark each command as one of: default/no-network, local service required, Docker/PostgreSQL required, Redis/Celery optional, live HTTP optional, or external provider optional.
  - README quickstarts may only present default/no-network commands as unconditional.
  - Commands requiring services or env vars must state their preconditions next to the command.

- [x] **Step 3: Record actual output markers** ✅ Completed 2026-06-14. README and `docs/getting-started.md` use the observed smoke-test markers and avoid unsupported “baseline contamination” wording.
  - Capture the current stable output markers used by CLI/example smoke tests.
  - Do not write README promises that overfit old wording such as a literal “baseline contamination” phrase unless that phrase is actually emitted and locked by tests.

### R1-A1 README as the Public Landing Page

**Files:**
- Modify: `README.md`

- [x] **Step 1: Restructure the README top half** ✅ Completed 2026-06-14. README now opens with a user-facing product statement, “Why not plain vector memory?”, and “What is implemented today?” rather than internal phase history.
  - Lead with a concise product statement: MemTrace is a trace-first, state-aware memory runtime for long-horizon agents.
  - Add a “Why not plain vector memory?” section that contrasts plain vector recall with state-aware retrieval, gate safety, negative evidence, and context compaction.
  - Add a “What is already implemented?” section summarizing core runtime, compaction, negative evidence, provider registry/key ontology, Phase 4 platform foundations, Python SDK/CLI/LangGraph, TypeScript SDK, MCP server, and templates.
  - Keep the tone user-facing; avoid dumping internal phase history in the top section.

- [x] **Step 2: Add quickstart paths** ✅ Completed 2026-06-14. README lists CLI/Python no-network demos, deterministic benchmark/reproduce, local HTTP service, CLI HTTP demo, TypeScript SDK example, and MCP server path with runtime requirements and observed markers.
  - Python in-process demo: `uv run --package memtrace-sdk memtrace demo --in-process`.
  - HTTP service path: start the API, then run the CLI HTTP demo.
  - TypeScript SDK example path using the existing Bun workspace and `examples/ts-simple-agent`.
  - MCP path for Claude Code/Cursor using checked-in templates and env placeholders.
  - Each path must state expected high-level output using actual stable markers discovered in R1-A0. Prefer wording like “representative failed-branch/state-aware-memory contrast” unless the exact marker is test-locked.

- [x] **Step 3: Add navigation to user docs** ✅ Completed 2026-06-14. README links the new getting-started, concepts, MCP, benchmark, and deployment docs; release checklist remains for R1-C.
  - Link to getting-started, concepts, MCP, benchmark, and deployment docs created in R1-A2; R1-C1 later added and linked the release checklist.
  - Keep internal design docs discoverable but not required for first-time users.

- [x] **Step 4: Verify README commands are accurate** ✅ Completed 2026-06-14. Default/no-network demo commands and benchmark were run; service-dependent TypeScript/MCP/HTTP commands are documented with preconditions instead of unconditional pass claims.
  - Run every default quickstart command that does not require a persistent external service.
  - For commands requiring a running service, document the precondition and add an optional smoke command rather than claiming default pass.

### R1-A2 Thin User-Facing Docs

**Files:**
- Create: `docs/getting-started.md`
- Create: `docs/concepts.md`
- Create: `docs/mcp.md`
- Create: `docs/benchmark.md`
- Create: `docs/deployment.md`

- [x] **Step 1: Create `docs/getting-started.md`** ✅ Completed 2026-06-14. Covers prerequisites, in-process Python demo, local HTTP service, TypeScript SDK example, benchmark/reproduce, and troubleshooting for Bun/Docker/optional services.
  - Cover prerequisites: Python 3.12, uv, Docker Compose for PostgreSQL path, Bun or temporary Bun via `npm exec --yes --package bun -- bun`.
  - Provide three tracks: in-process Python demo, local HTTP service, TypeScript SDK example.
  - Include troubleshooting for missing Bun, Docker Compose command form, and optional service env vars.

- [x] **Step 2: Create `docs/concepts.md`** ✅ Completed 2026-06-14. Explains run/step/event, state tree, memory lifecycle, retrieval strategies, gate, negative evidence, compaction, provider/key ontology, lifecycle/version/conflict, governance defaults, and public boundaries.
  - Explain run, step, event, state tree, memory item, retrieval strategy, gate, negative evidence, context compaction, lifecycle signals, governance default-off behavior.
  - Keep it conceptual and user-facing; link to design docs only for deep internals.

- [x] **Step 3: Create `docs/mcp.md`** ✅ Completed 2026-06-14. Documents MCP tools, thin SDK/HTTP boundary, Claude Code/Cursor templates, placeholder handling, repository-root path assumptions, manual launch, and redacted/capped outputs.
  - Explain what the MCP server does and that it is a thin adapter over `@memtrace/sdk` and HTTP `/v1`.
  - Show Claude Code and Cursor template usage with `${MEMTRACE_BASE_URL}` / `${MEMTRACE_API_KEY}` placeholders.
  - Document local-development path assumptions for `packages/mcp-server/src/server.ts` and how users should replace it with an absolute path or installed command if their MCP client launches elsewhere.
  - State output redaction/capping behavior for replay/report tools.

- [x] **Step 4: Create `docs/benchmark.md`** ✅ Completed 2026-06-14. Documents six strategies, 13 benchmark cases, deterministic commands, and interpretation of acceptance, contamination, negative evidence, compaction, reflection-lite, and token overhead metrics.
  - Explain the six strategies and 13 benchmark cases at a user level.
  - Provide commands for deterministic benchmark and reproducibility script.
  - Explain how to interpret acceptance, contamination, negative evidence, compaction, and reflection-lite metrics.

- [x] **Step 5: Create `docs/deployment.md`** ✅ Completed 2026-06-14. Documents default-off local/dev posture, PostgreSQL path, optional Redis/Celery, auth/governance/quota, redaction/raw payload safety, provider configuration, client integration deployment, and release posture.
  - Document default local/dev posture: auth/governance/quota off unless enabled.
  - Document core PostgreSQL path and optional Redis/Celery dev compose path.
  - Document configuration safety: API keys, redaction, raw payload retention disabled by default, optional LLM/provider env vars.
  - Keep production guidance honest: this is launch readiness documentation, not an enterprise hardening guarantee.

### R1-A3 Demo Flow Consolidation

**Files:**
- Modify: `README.md`
- Modify: existing example scripts only if command drift is found
- Optional create: `scripts/smoke-release-readiness.sh`

- [x] **Step 1: Inventory current demo commands** ✅ Completed 2026-06-14. Reused R1-A0 command inventory and kept CLI/Python as the no-network canonical path; HTTP and TypeScript remain optional env-gated smoke paths.
  - Reuse the R1-A0 command inventory rather than repeating discovery from scratch.
  - Re-check only commands that changed during README/docs/package metadata work.
  - Keep command classifications consistent with R1-A0: default/no-network vs service/env-gated.

- [x] **Step 2: Add one canonical “5-minute demo” flow** ✅ Completed 2026-06-14. Added `scripts/smoke-release-readiness.sh`, which orchestrates existing CLI and Python SDK demos and verifies stable markers without requiring network services by default.
  - Prefer documenting existing commands over adding new code.
  - If existing commands are scattered or too hard to validate, add a small deterministic smoke script that only orchestrates existing commands and does not require network services by default.
  - The flow should demonstrate the core value with the current stable output markers: a representative failed-branch/state-aware-memory contrast where MemTrace avoids reusing unsafe or stale failed-branch context.

- [x] **Step 3: Add smoke coverage for documented demo commands** ✅ Completed 2026-06-14. `packages/python-sdk/tests/test_examples_smoke.py` now runs the smoke script and asserts `baseline_1 action`, `variant_2 action`, `contamination eliminated`, and `release readiness smoke passed` markers.
  - Post-review hardening: README's compact quickstart table now links to the full Local HTTP and Docker section instead of showing a one-line Docker/PostgreSQL command that skipped the required health wait.
  - Full-regression hardening: README now also preserves the underlying deterministic reproducibility entrypoints (`app.demo.run_demo`, benchmark runner, observability reports) and replay API snippet required by integration tests.
  - Test or script should verify command availability and stable output markers.
  - Keep optional HTTP/MCP live-service smoke gated by env vars.

---

## 4. Stream R1-B — Package Metadata, Release Hygiene, and CI Matrix

### R1-B1 TypeScript Package Publishing Readiness

**Files:**
- Modify: `packages/ts-sdk/package.json`
- Modify: `packages/mcp-server/package.json`
- Optional create/modify: package-level README files only if root README links are insufficient for package consumers

- [x] **Step 1: Add non-publishing metadata** ✅ Completed 2026-06-14. Added descriptions, Apache-2.0 license, repository/homepage/bugs URLs, keywords, source-entry `exports`, and explicit `files` to `@memtrace/sdk` and `@memtrace/mcp-server`.
  - Add `description`, `license`, `repository`, `homepage`, `bugs`, and `keywords` to both packages.
  - Add `exports` and `files` so eventual package contents are explicit.
  - Preserve current runtime entrypoints and TypeScript source layout.
  - R1 package metadata must not introduce a `dist/` build, bundler, `tsup`, declaration emit pipeline, or package layout migration unless that is explicitly selected as a separate publish-readiness task. The default R1 shape is source-entry package metadata plus package-shape validation.

- [x] **Step 2: Decide package privacy behavior for R1** ✅ Completed 2026-06-14. Both JS packages remain `private: true`; R1 prepares metadata and package-shape checks without enabling publication.
  - Default plan: keep `private: true` during R1 unless the maintainer explicitly chooses npm publication.
  - Even while private, metadata should be release-ready and package checks should validate intended shape.

- [x] **Step 3: Add package dry-run checks where feasible** ✅ Completed 2026-06-14. Added package-shape Bun tests for both packages, asserting metadata, source-entry exports/files, MCP bin shape, and absence of generated/test/lockfile packaging entries.
  - For Bun workspace packages, add a deterministic package-shape check that does not require publishing credentials.
  - Ensure no secrets, generated artifacts, test-only fixtures, or internal Python runtime code are packaged as public JS package contents.

### R1-B2 Python Package Metadata and CLI Readiness Check

**Files:**
- Modify: `pyproject.toml`
- Modify: `packages/python-sdk/pyproject.toml` if present and needed
- Modify: README/docs references as needed

- [x] **Step 1: Review Python packaging metadata** ✅ Completed 2026-06-14. Root `memtrace` and workspace `memtrace-sdk` metadata now describe the current platform/SDK instead of P0-only state and include Apache-2.0 license, README, project URLs, and classifiers.
  - Post-review hardening: `uv build --package memtrace-sdk` exposed that `readme = "../../README.md"` is not build-safe for the SDK package; the SDK now uses inline PEP 621 readme metadata and metadata tests lock the shape.
  - Ensure project/package descriptions no longer describe only the P0 MVP if the package now represents the broader current system.
  - Add/verify license, repository URLs, classifiers, and console script metadata.
  - Keep Python SDK packaging aligned with the existing uv workspace setup.

- [x] **Step 2: Verify CLI entrypoints and examples** ✅ Completed 2026-06-14. Metadata tests plus existing CLI readiness tests pass, and `uv run --package memtrace-sdk memtrace demo --in-process` prints the stable failed-branch contrast markers.
  - Confirm `uv run --package memtrace-sdk memtrace demo --in-process` works from a clean checkout with dev dependencies.
  - Confirm operational commands still require `--http` and docs do not imply cross-process in-memory persistence.

### R1-B3 GitHub Actions Verification Matrix

**Files:**
- Create: `.github/workflows/ci.yml`
- Optional create: `.github/workflows/release-check.yml`
- Optional create/modify: `scripts/smoke-release-readiness.sh`

- [x] **Step 1: Add default CI workflow** ✅ Completed 2026-06-14. Added `.github/workflows/ci.yml` with separate Python, Bun/TypeScript, and release-hygiene jobs. Python installs uv and runs compileall plus full pytest; JS uses `oven-sh/setup-bun@v2` with Bun 1.3.14, `bun install --frozen-lockfile`, typecheck, and tests; hygiene runs `scripts/check-release-hygiene.sh`.
  - Python job:
    - Install uv.
    - Run `uv run --extra dev python -m compileall -q apps/api/app packages/python-sdk/src examples`.
    - Run `uv run --extra dev pytest -q`.
  - JS job:
    - Use `oven-sh/setup-bun` in CI so the CI strategy is deterministic.
    - Run `bun run typecheck`.
    - Run `bun test`.
  - Local docs may still mention the current fallback for machines without global Bun: `npm exec --yes --package bun -- bun ...`.
  - Reproducibility job or step:
    - Run deterministic benchmark smoke if runtime is acceptable in CI.
    - Run `bash scripts/reproduce.sh` if wall-clock runtime is acceptable; otherwise keep full reproduce as a scheduled/manual workflow and run a lighter benchmark smoke on PRs.

- [x] **Step 2: Keep optional integration checks gated** ✅ Completed 2026-06-14. Default CI does not require `MEMTRACE_TEST_DATABASE_URL`, `MEMTRACE_TEST_REDIS_URL`, LLM/provider credentials, `MEMTRACE_BASE_URL`, or a live HTTP service; live/service-dependent smoke remains outside default CI.
  - Do not require `MEMTRACE_TEST_DATABASE_URL`, `MEMTRACE_TEST_REDIS_URL`, real LLM provider env vars, or live HTTP service env vars for default PR CI.
  - Optional smoke tests may be added behind env vars and should skip clearly when unset.

- [x] **Step 3: Add release-check workflow if useful** ✅ Closed 2026-06-14 without adding a separate workflow.
  - Closed in R1-C1/R1-C2: no separate release-check workflow was added because the default CI already covers package-shape tests through `bun test`, release hygiene through the dedicated job, and the human release checklist documents heavier benchmark/reproduce and package dry-run commands.
  - Run package metadata/package-shape checks.
  - Run docs link/command smoke if lightweight.
  - Do not publish artifacts automatically.

---

## 5. Stream R1-C — Release Checklist, Verification, and Project Memory Sync

### R1-C1 Release Checklist

**Files:**
- Create: `docs/release-checklist.md`
- Modify: `README.md`

- [x] **Step 1: Add human release checklist** ✅ Completed 2026-06-14. Added `docs/release-checklist.md` with release scope selection, required local verification commands, Python/JS package dry-run checks, artifact/secret hygiene, tagging notes, explicit publish decision gates, and rollback guidance.
  - Include pre-release verification commands.
  - Include package metadata checks.
  - Include generated artifact cleanup checks.
  - Include npm/PyPI publish decision gates, but do not automate publishing.
  - Include rollback notes for failed package/release attempts.

- [x] **Step 2: Link checklist from README** ✅ Completed 2026-06-14. README user-doc navigation now links the maintainer release checklist while keeping the first-time quickstart focused on no-network onboarding.
  - Make it visible to maintainers without putting maintainer-only detail in the first-time user path.

### R1-C2 Verification Closeout

**Files:**
- Modify: `docs/design/ROADMAP.md`
- Modify: `.ai/PROJECT_STATE.md`
- Modify: `.ai/REQUIREMENTS.md`
- Modify: `.ai/IMPLEMENTATION_PLAN.md`
- Modify: `.ai/OPEN_QUESTIONS.md` if the next target decision changes
- Modify: `.ai/PITFALLS.md` if new release-readiness traps are found

- [x] **Step 1: Run Python verification** ✅ Completed 2026-06-14 during R1-B3 review. `uv run --extra dev python -m compileall -q apps/api/app packages/python-sdk/src examples` passed and `uv run --extra dev pytest -q` -> **607 passed, 2 skipped**.
  - `uv run --extra dev python -m compileall -q apps/api/app packages/python-sdk/src examples`
  - `uv run --extra dev pytest -q`

- [x] **Step 2: Run JS verification** ✅ Completed 2026-06-14 during R1-B3 review. `npm exec --yes --package bun -- bun run typecheck` passed and `npm exec --yes --package bun -- bun test` -> **31 passed, 1 skipped**.
  - Preferred when Bun is installed: `bun run typecheck` and `bun test`.
  - Fallback in environments without global Bun: `npm exec --yes --package bun -- bun run typecheck` and `npm exec --yes --package bun -- bun test`.

- [x] **Step 3: Run reproducibility checks** ✅ Completed 2026-06-14. `uv run python -m app.benchmark.runner --output-dir reports` exited 0 and generated `reports/benchmark_results.json` with `acceptance.passed=true` and 13 true checks. `bash scripts/reproduce.sh` exited 0 and printed `acceptance.passed=true (13/13 checks true)`.
  - `uv run python -m app.benchmark.runner --output-dir reports`
  - `bash scripts/reproduce.sh`
  - Verify acceptance remains `13/13` unless benchmark case count intentionally changes.

- [x] **Step 4: Run release hygiene checks** ✅ Completed 2026-06-14. Added `scripts/check-release-hygiene.sh` and wired it into CI. The guard checks tracked forbidden artifacts and scans public docs/examples for obvious real secrets, bearer/sk tokens, unredacted `raw_payload_ref` values, and raw destructive production commands while allowing explicit placeholders and env-var references. Local verification `bash -n scripts/check-release-hygiene.sh` passed and `bash scripts/check-release-hygiene.sh` prints `release hygiene checks passed`.
  - Add or run an explicit tracked-file guard. Preferred implementation: `scripts/check-release-hygiene.sh`.
  - The guard should fail if tracked files match forbidden artifact patterns such as `node_modules`, `*.tsbuildinfo`, `package-lock.json`, `pnpm-lock.yaml`, `yarn.lock`, `*.tgz`, generated `reports/` outputs, or local service artifacts.
  - At minimum, the guard must cover the equivalent of `git ls-files | grep -E '(^|/)node_modules/|\.tsbuildinfo$|(^|/)package-lock\.json$|(^|/)pnpm-lock\.yaml$|(^|/)yarn\.lock$|\.tgz$|^reports/'` and fail on any match.
  - Confirm docs/examples do not contain real API keys, bearer tokens, `sk-` tokens, passwords, raw destructive production commands, or unredacted `raw_payload_ref` values.

- [x] **Step 5: Sync roadmap and project memory** ✅ Completed 2026-06-14. `docs/design/ROADMAP.md`, this plan, and `.ai` project memory now mark R1 complete and point the next recommended feature slice to OpenTelemetry/OpenInference exporter unless adoption feedback reprioritizes maintenance scheduler completion, admin workflow, or advanced retrieval/storage. Final closeout verification after sync: `git diff --check` passed; `uv run --extra dev pytest -q` -> **607 passed, 2 skipped**; `npm exec --yes --package bun -- bun run typecheck` passed; `npm exec --yes --package bun -- bun test` -> **31 passed, 1 skipped**.
  - Mark R1 complete in `docs/design/ROADMAP.md` after implementation and verification pass.
  - Update `.ai/PROJECT_STATE.md` with changed files, verification output, and next recommended target.
  - Update `.ai/IMPLEMENTATION_PLAN.md` to make the next selected or candidate target clear.
  - Recommended next target after R1: OpenTelemetry/OpenInference exporter, unless real adoption feedback points more strongly to admin workflow, maintenance scheduler completion, or advanced retrieval/storage.

---

## 6. Suggested Implementation Order

1. **Segment 1 — Command inventory + README + user docs:** R1-A0, R1-A1, and R1-A2. Inventory comes first so docs reflect real commands and stable output markers.
2. **Segment 2 — Demo/smoke + package metadata:** R1-A3, R1-B1, and R1-B2. Keep package metadata release-ready while preserving `private: true` unless publication is explicitly approved.
3. **Segment 3 — CI + release hygiene:** R1-B3 plus the tracked-file guard from R1-C2. CI uses `oven-sh/setup-bun`; local docs keep the temporary Bun fallback.
4. **Segment 4 — Release checklist + full verification + closeout:** R1-C1 and R1-C2, including ROADMAP and `.ai` memory sync.

Avoid combining all streams into one large unreviewable change. The natural commit/slice boundaries are:

- Docs and quickstart story.
- Demo/smoke command hardening.
- Package metadata/release hygiene.
- CI workflows.
- Closeout verification and project-memory sync.

---

## 7. Acceptance Criteria

R1 is complete (2026-06-14) because all of the following are true:

- A first-time reader can understand MemTrace’s positioning and why it differs from plain vector memory from the top of `README.md`.
- README links to concise user-facing docs for getting started, concepts, MCP, benchmark, deployment, and release checklist.
- At least one default no-network demo path runs from a clean checkout and demonstrates MemTrace’s core value.
- TypeScript SDK and MCP server packages have release-ready metadata and explicit package shape, even if `private: true` remains in place.
- CI runs Python tests/compile checks and Bun typecheck/tests without requiring real Redis, real LLM providers, live PostgreSQL integration DB, or live HTTP services by default.
- Benchmark/reproducibility commands still pass with `13/13` acceptance unless a future task intentionally changes the benchmark suite.
- ROADMAP and `.ai` project memory identify R1 as the selected/completed target and name the next recommended target.

---

## 8. Risks and Mitigations

- **Risk: Docs drift from actual commands.** Mitigation: add smoke tests/scripts for documented default commands and keep optional-service commands clearly labeled.
- **Risk: Release metadata implies packages are published when they are not.** Mitigation: keep `private: true` unless publication is explicitly approved; document “publishing readiness” separately from “published package”.
- **Risk: CI becomes too slow or environment-heavy.** Mitigation: keep live Redis/Postgres/LLM/service tests gated; use fast deterministic tests on PRs and move heavier reproduce checks to scheduled/manual workflow if needed.
- **Risk: User docs duplicate internal design docs and become stale.** Mitigation: keep user docs thin, concept-focused, and link to design docs for deep implementation detail.
- **Risk: Demo overclaims general benchmark results.** Mitigation: phrase the 5-minute demo as a representative failure-branch/state-aware-memory demonstration, not a complete substitute for benchmark/reproduce.
- **Risk: Roadmap wording promises unimplemented integrations.** Mitigation: mention OpenTelemetry/OpenInference only as a likely future slice in roadmap/planning sections; do not advertise LangSmith/Phoenix/Langfuse support as available in the README top-level user path until an exporter exists.

---

## 9. Post-R1 Candidate Ordering

Recommended order after R1:

1. **OpenTelemetry / OpenInference exporter** — strongest next fit for agent-runtime observability after adoption docs exist.
2. **Maintenance Scheduler Completion** — finish `dedup_memory`, `conflict_scan`, `reindex_memory`, and unify summarize/procedural scheduling.
3. **Admin / Manual Governance Workflow** — deeper conflict resolution and tenant/admin workflows after real usage feedback.
4. **Advanced Retrieval / Storage Phase 5** — Elasticsearch/OpenSearch, Neo4j, RRF, query planner, and multi-hop retrieval only once benchmark/use cases prove the need.
