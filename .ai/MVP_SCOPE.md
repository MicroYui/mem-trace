# MVP Scope

## Must Have

- MemoryRuntime facade with `start_run`, `start_step`, `write_event`, `finish_step`, `retrieve_context`, and minimal `rollback_branch`.
- Agent trace model for runs, steps, events, sequence numbers, tool calls/results, errors, and visibility/redaction metadata.
- Simplified execution state tree: `root`, `step`, `recovery`; no automatic subgoal inference.
- PostgreSQL source of truth with pgvector for MVP retrieval unless this storage conflict is resolved differently.
- Rule-based memory writer for deterministic demo memories: project constraints, working state, tool evidence, explicit correction, secret protection.
- State-aware retrieval and structured context blocks.
- Rule-based admission gate for workspace mismatch, deleted/quarantined status, secrets, failed/rolled-back branch, stale memory, and tool-sensitive/destructive/production risk flags.
- Minimal profiler for retrieval, gate, and context packing with candidate/accepted/rejected counts and latency.
- Demo agent/report for Bun vs Node.js plus failed-branch isolation.
- Access inspection endpoint or equivalent report showing candidates, gate decisions, context blocks, and profile.

## Should Have

- Active path context builder.
- Basic benchmark comparing no memory, vector-only memory, state-aware retrieval, and state-aware + gate.
- CLI/JSON/Markdown reporting before a full dashboard.
- Positive and negative project constraint packing into stable context text.
- Minimal workspace isolation tests.

## Explicitly Out of Scope for First Coding Slice / P0

- Full React dashboard, Sankey, graph visualization.
- Neo4j, Elasticsearch, Celery multi-queue, OpenTelemetry exporter.
- TypeScript SDK, MCP/IDE plugins.
- LLM extraction pipeline, complex reflection/forgetting scheduler, trained gate model.
- Full multi-tenant quota/admin system.
- Large document knowledge base, OCR/audio/multimodal ingestion, complete LoCoMo/MemoryArena benchmark.

## Assumptions

- P0 prioritizes the hot path over long-term lifecycle features.
- PostgreSQL is the durable source of truth; derived indexes are rebuildable when introduced.
- P0 can use deterministic regex/keyword memory writing instead of LLM extraction.
- Demo and benchmark can be CLI/report based before a UI exists.
- Failed/rolled-back branch memory must be visible for audit but excluded from prompt by default.

## MVP Acceptance Criteria

- FastAPI + PostgreSQL can start.
- API/service can create run/step, write events, and query timeline by `sequence_no`.
- `start_step`/`finish_step` creates and updates the simplified state tree.
- `rollback_branch` marks failed path rolled back and creates a recovery branch under the failed step's parent.
- At least project, working_state, and tool_evidence memories are written.
- `retrieve_context` returns structured context blocks and warnings.
- Gate rejects cross-workspace, deleted/quarantined, secret, failed-branch, rolled-back, stale, and configured risky memories.
- Profiler records retrieval/gate/context-packing latency and counts.
- Demo proves vector-only can admit failed memory while state-aware + gate rejects it and keeps Bun project constraints.

