# Requirements

## Current Task

Prepare, but do not yet implement, the first coding slice: **MemoryRuntime trace/state foundation**.

## Coding Readiness

- **Ready to write production code:** No.
- **Ready to plan the first slice:** Yes.

### Blocking Decisions Before Coding

1. **Package manager:** choose `uv`, Poetry, pip-tools, or plain pip.
2. **Initial scaffold:** choose `apps/api` monorepo-style layout or a simpler root-level Python package.
3. **First-slice boundary:** confirm service-layer-first is acceptable before HTTP endpoints and DB migrations.

### Non-Blocking for First Slice

- MVP storage conflict can be deferred if this slice uses an in-memory repository contract and no database migrations.
- Embedding provider, pgvector, Elasticsearch, dashboard, LLM extraction, auth, benchmark format, and secret raw-payload policy are not needed for this slice.

## Selected First Coding Task

Build the service-layer foundation for run/step/event/state-tree behavior:

- Define core request/result/domain models for `AgentRun`, `AgentStep`, `AgentEvent`, and `StateNode`.
- Define a `MemoryRuntime` interface with `start_run`, `start_step`, `write_event`, `finish_step`, and `rollback_branch`.
- Implement an in-memory repository/runtime sufficient to test deterministic state transitions.
- Prove event ordering with run-local `sequence_no`.
- Prove recovery nodes attach to the failed step's parent, not under the failed node.

## Why This Comes First

- It is the foundation for every later MVP feature: memory writing, retrieval, gate decisions, profiler, demo, and dashboard all depend on trustworthy trace/state semantics.
- It directly implements the highest-risk invariant identified in the design docs: failed branch isolation begins with correct state tree structure.
- It avoids premature storage, HTTP, LLM, dashboard, and retrieval complexity.

## Language and Framework

- **Language:** Python.
- **Runtime target:** Python 3.12 recommended.
- **Framework:** FastAPI is the intended API framework, but the first slice should be service-layer-first and not expose HTTP endpoints yet.
- **Data modeling:** Pydantic v2 recommended for request/result schemas once package manager is confirmed.
- **Testing:** pytest recommended once package manager is confirmed.

## Recommended Initial Directory Structure

Use this if the `apps/api` scaffold is confirmed:

```text
apps/
  api/
    app/
      __init__.py
      runtime/
        __init__.py
        models.py
        repository.py
        memory_runtime.py
        state_tree.py
    tests/
      runtime/
        test_memory_runtime_trace.py
        test_state_tree.py
pyproject.toml
```

If a simpler scaffold is chosen, keep the same module boundaries under a root-level `memtrace/` package.

## First Modules to Create

- `runtime/models.py`: enums and data models for runs, steps, events, state nodes, and runtime request/result objects.
- `runtime/repository.py`: repository protocol plus in-memory implementation for tests.
- `runtime/state_tree.py`: pure state transition helpers for root, step, finish, rollback, and recovery placement.
- `runtime/memory_runtime.py`: MemoryRuntime facade orchestrating repository and state tree operations.
- `tests/runtime/test_state_tree.py`: unit tests for state transitions and recovery placement.
- `tests/runtime/test_memory_runtime_trace.py`: service tests for run/step/event lifecycle and sequence numbers.

## Core Interface / Data Model Sketch

### Enums

- `RunStatus`: `running`, `completed`, `failed`, `cancelled`
- `StepStatus`: `active`, `completed`, `failed`, `cancelled`, `rolled_back`
- `StateNodeType`: `root`, `step`, `recovery`
- `StateNodeStatus`: `active`, `completed`, `failed`, `rolled_back`
- `EventRole`: `user`, `assistant`, `tool`, `system`, `runtime`
- `EventType`: `message`, `tool_call`, `tool_result`, `error`, `checkpoint`

### Core Models

- `AgentRun`: `run_id`, `workspace_id`, `session_id`, `task`, `status`, timestamps, metadata.
- `AgentStep`: `step_id`, `workspace_id`, `run_id`, `parent_step_id`, `recovery_from_step_id`, `state_node_id`, `intent`, `status`, timestamps, error, metadata.
- `AgentEvent`: `event_id`, `workspace_id`, `session_id`, `run_id`, `step_id`, `state_node_id`, `sequence_no`, `role`, `event_type`, `content`, `content_digest`, tool/status/token/latency metadata.
- `StateNode`: `node_id`, `workspace_id`, `run_id`, `parent_id`, `step_id`, `node_type`, `status`, `goal`, `summary`, `branch_reason`, `failure_reason`, `depth`, `path`, timestamps.

### Runtime Methods

- `start_run(request: StartRunRequest) -> AgentRun`
- `start_step(request: StartStepRequest) -> AgentStep`
- `write_event(event: WriteEventRequest) -> WriteEventResult`
- `finish_step(request: FinishStepRequest) -> FinishStepResult`
- `rollback_branch(request: RollbackRequest) -> RollbackResult`

## Tests to Write First

1. `test_start_run_creates_running_run_and_active_root_node`
2. `test_start_step_creates_active_step_node_under_root`
3. `test_write_event_assigns_monotonic_sequence_numbers_per_run`
4. `test_write_event_binds_event_to_step_and_state_node`
5. `test_finish_step_success_marks_step_and_state_node_completed`
6. `test_finish_step_failed_marks_step_and_state_node_failed`
7. `test_rollback_branch_marks_failed_step_rolled_back`
8. `test_recovery_step_attaches_to_failed_step_parent_not_failed_node`

## Acceptance Criteria

- All tests above pass.
- No production database, HTTP endpoint, retrieval, gate, profiler, memory writer, demo agent, or dashboard is introduced in this slice.
- Runtime assigns strictly increasing `sequence_no` values per run.
- Every event is bound to both `step_id` and `state_node_id`.
- `finish_step` keeps step and state node statuses consistent.
- Recovery state node is a sibling/replacement branch under the failed node's parent.

## Explicitly Out of Scope

- FastAPI routes.
- SQLAlchemy models and Alembic migrations.
- PostgreSQL, pgvector, Elasticsearch, Neo4j, Redis, Celery.
- Memory extraction/write pipeline.
- Retrieval controller, admission gate, context packing, profiler.
- Demo agent, benchmark reports, dashboard.
- Auth, API keys, multi-tenant quota, secret storage policy.

## Rollback / Simplification Path

- If package/scaffold remains undecided, reduce the slice to a pure Python design spike documented in `.ai/REQUIREMENTS.md` only.
- If Pydantic dependency is not confirmed, use stdlib `dataclasses` temporarily, but do not implement until this simplification is explicitly accepted.
- If repository layout is disputed, keep module names stable and move paths later.

## Standing Requirements From Design Docs

- Do not build a generic knowledge-base/RAG app as the main product.
- Treat memory as an Agent runtime component with trace, state, retrieval, gate, and profiler.
- Persist raw trace before derived memory extraction.
- Exclude failed/rolled-back branch memory from prompt context by default.
- Keep PostgreSQL as source of truth once persistence is introduced.
- Keep P0 deterministic and demo-oriented; defer LLM extraction, Neo4j, Celery, and full dashboard.

