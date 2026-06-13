# H15-H18 Security Hardening Closeout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete ROADMAP §13 H15-H18 by adding migration policy checks, redacted trace bundle export/validation, deterministic dogfood scenarios, and project-memory/docs closeout.

**Architecture:** Keep `MemoryRuntime` as the semantic boundary. Add a focused observability trace-bundle module that exports read-only, redacted DTO snapshots from repository data; add tests that freeze migration compatibility policy; add dogfood scripts that use the SDK/in-memory runtime without external services. H18 updates existing roadmap and `.ai` memory so resume points to the next slice after §13.

**Tech Stack:** Python 3.12, Pydantic v2, FastAPI route patterns already in repo, SQLAlchemy/Alembic migration files, pytest, uv workspace, existing `memtrace-sdk` facade.

---

## File Structure / Responsibility Map

- Modify `apps/api/tests/storage/test_migrations.py` for migration declaration/default/backfill policy tests and an optional PostgreSQL upgrade smoke guard.
- Add `apps/api/app/observability/trace_bundle.py` for `TraceBundle`, `TraceBundleValidation`, `export_run_bundle`, `export_access_bundle`, and `validate_bundle_schema`.
- Modify `apps/api/app/runtime/models.py` to expose stable DTOs only if the bundle models belong with shared API schemas; otherwise keep them in `trace_bundle.py`.
- Modify `apps/api/app/runtime/memory_runtime.py` to add thin facade methods `export_trace_bundle(...)`, `export_access_bundle(...)`, and `validate_trace_bundle(...)`.
- Add `apps/api/tests/observability/test_trace_bundle.py` for redaction, access/run filtering, schema validation, and no raw secret leakage.
- Add `examples/dogfood/coding_agent.py`, `examples/dogfood/multi_session_constraints.py`, and `examples/dogfood/destructive_failure.py` for deterministic CLI-friendly dogfood flows.
- Modify `packages/python-sdk/tests/test_examples_smoke.py` to smoke test dogfood scripts.
- Modify `scripts/reproduce.sh` only if smoke runtime remains deterministic and quick.
- Modify `docs/design/SECURITY_CONSISTENCY_HARDENING_PLAN.md`, `docs/design/ROADMAP.md`, `README.md`, `AGENTS.md`, `.ai/PROJECT_STATE.md`, `.ai/REQUIREMENTS.md`, `.ai/IMPLEMENTATION_PLAN.md`, `.ai/OPEN_QUESTIONS.md`, `.ai/DECISIONS.md`, and `.ai/PITFALLS.md` for closeout.

### Task 1: H15 migration compatibility policy

**Files:**
- Modify: `apps/api/tests/storage/test_migrations.py`
- Test: `apps/api/tests/storage/test_migrations.py`

- [x] **Step 1: Add always-on declaration tests**

Add helpers that iterate every `migrations/versions/*.py` file and assert revision metadata, `upgrade`, and `downgrade` exist.

- [x] **Step 2: Add non-null column policy test**

Scan migration source and fail any `op.add_column(... nullable=False ...)` without `server_default` or `op.execute` backfill in the same migration file.

- [x] **Step 3: Add optional PostgreSQL upgrade guard**

Add a skipped-by-default test that requires `MEMTRACE_TEST_DATABASE_URL`; when present, it runs Alembic `upgrade head` against the configured disposable database.

- [x] **Step 4: Verify H15**

Run `uv run --extra dev pytest apps/api/tests/storage/test_migrations.py -q`. Expected: all declaration tests pass and the live PostgreSQL upgrade test skips unless the env var is set.

### Task 2: H16 trace bundle export and schema validation

**Files:**
- Add: `apps/api/app/observability/trace_bundle.py`
- Modify: `apps/api/app/runtime/memory_runtime.py`
- Test: `apps/api/tests/observability/test_trace_bundle.py`

- [x] **Step 1: Write failing redaction test**

Create a test that writes an event containing `password is hunter2`, triggers memory extraction/retrieval, exports a run bundle with `redacted=True`, serializes it to JSON, and asserts `hunter2` is absent while `[REDACTED]` is present.

- [x] **Step 2: Implement bundle DTOs**

Implement `TraceBundle(schema_version="trace-bundle-v1", redacted=True, runs, steps, events, state_nodes, memories, access_logs, gate_logs, profile_events, compaction_logs)` and `TraceBundleValidation(schema_version, valid, counts, errors)`.

- [x] **Step 3: Implement redaction-first copies**

Copy repository objects and redact textual fields before returning: event `content`, memory `content`/`summary`/`value`, access `query`/`task_intent`, gate `reject_reason`, profile `operation`/`error_code`/metadata string values, compaction `summary_text`/retained facts/warnings, and nested dict/list string leaves.

- [x] **Step 4: Implement run/access exports**

`export_run_bundle(repo, run_id, redacted=True)` includes one run plus its steps/events/state nodes/run memories/access logs/gate logs/profile events/compaction logs. `export_access_bundle(repo, access_id, redacted=True)` includes the access log, related run, gate/profile/compaction logs, and memories referenced by gate logs.

- [x] **Step 5: Implement validation-only schema check**

`validate_bundle_schema(bundle_or_dict)` should parse `TraceBundle`, verify `schema_version == "trace-bundle-v1"`, return object counts, and not write to repositories.

- [x] **Step 6: Verify H16**

Run `uv run --extra dev pytest apps/api/tests/observability/test_trace_bundle.py -q`. Expected: all trace bundle tests pass.

### Task 3: H17 deterministic dogfood scenarios

**Files:**
- Add: `examples/dogfood/coding_agent.py`
- Add: `examples/dogfood/multi_session_constraints.py`
- Add: `examples/dogfood/destructive_failure.py`
- Modify: `packages/python-sdk/tests/test_examples_smoke.py`

- [x] **Step 1: Add smoke tests**

Add subprocess tests for each dogfood script. Assert stable, short stdout markers and assert raw unsafe content is absent from the destructive failure script.

- [x] **Step 2: Implement coding-agent recovery script**

Use `MemTrace.in_memory(...)` to model failed `npm test`, rollback/recovery, successful `bun test`, and later `variant_2` retrieval that emits a stable line such as `variant_2 avoids npm: true` and `recovery command: bun test`.

- [x] **Step 3: Implement multi-session constraint script**

Use one in-memory client/repository, write a session-1 project constraint such as `这个项目使用 Bun`, then start session 2 and retrieve it. Print `session_2_retrieved_project_runtime: Bun`.

- [x] **Step 4: Implement destructive failure script**

Record a failed destructive command memory, retrieve with `variant_2`, print `destructive_failure_sanitized: true`, and ensure raw `rm -rf` text is not printed.

- [x] **Step 5: Verify H17**

Run `uv run --package memtrace-sdk --extra dev pytest packages/python-sdk/tests/test_examples_smoke.py -q`. Expected: example smoke tests pass.

### Task 4: H18 documentation and project-memory closeout

**Files:**
- Modify: `docs/design/SECURITY_CONSISTENCY_HARDENING_PLAN.md`
- Modify: `docs/design/ROADMAP.md`
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `.ai/PROJECT_STATE.md`, `.ai/REQUIREMENTS.md`, `.ai/IMPLEMENTATION_PLAN.md`, `.ai/OPEN_QUESTIONS.md`, `.ai/DECISIONS.md`, `.ai/PITFALLS.md`

- [x] **Step 1: Mark H15-H18 complete**

Tick H15-H18 steps in the security hardening plan and update ROADMAP §13 to show the §13 slice complete.

- [x] **Step 2: Refresh next-action guidance**

Update resume-facing files so the next recommended work after §13 is Provider Registry (§10) / Controlled Memory Key Ontology (§11), while I7 remains deferred.

- [x] **Step 3: Record verification and pitfalls**

Record exact commands/pass counts and add pitfalls around migration declaration checks, bundle redaction defaults, validation-only imports, and dogfood scripts staying deterministic/no-network.

- [x] **Step 4: Final verification**

Run: `uv run --extra dev python -m compileall -q apps/api/app packages/python-sdk/src examples`; `uv run --extra dev pytest -q`; `uv run python -m app.benchmark.runner --output-dir reports`; and `bash scripts/reproduce.sh`. Expected: compile passes, full pytest passes, benchmark acceptance remains true, reproduce script passes.

## Self-Review

- Spec coverage: H15 migration policy, H16 redacted bundle export/validation, H17 dogfood scripts, and H18 docs/memory closeout each have a task and verification command.
- Placeholder scan: no TBD/TODO placeholders; each task has concrete file paths and expected verification.
- Type consistency: trace bundle functions are module-level helpers wrapped by `MemoryRuntime` facade methods; dogfood uses existing SDK in-memory API; migration tests operate on existing Alembic file layout.
