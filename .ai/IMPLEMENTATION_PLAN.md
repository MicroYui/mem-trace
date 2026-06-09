# Implementation Plan

## P0 Foundation

1. Create Python/FastAPI project skeleton only after confirming package manager and exact layout.
2. Add PostgreSQL/pgvector configuration and migrations for MVP tables.
3. Define Pydantic schemas and SQLAlchemy models for run/step/event/state/memory/access/gate/profile.
4. Implement MemoryRuntime facade with in-process service methods and HTTP endpoints.
5. Implement deterministic state tree transitions and `sequence_no` event ordering.
6. Add rule-based memory writer for the Bun/Node and tool-result demo cases.
7. Add rule-based admission gate and context block format.
8. Add minimal profiler and access inspection output.

## P1 MVP Differentiation

Status: implemented locally and verified on 2026-06-09.

1. Implement active path context builder. ✅
2. Add state-aware candidate scoring/reranking. ✅
3. Generalize failed/rolled-back branch isolation. ✅
4. Add benchmark cases for project preference, failed branch, workspace isolation, and tool safety. ✅
5. Produce JSON/Markdown demo and benchmark reports. ✅
6. Add basic table-style dashboard or API views only if the core path is stable. ✅ (`GET /v1/dashboard/tables`)

## P2 Advanced Features

1. LLM extraction with schema validation and confidence/source-trust metadata.
2. Candidate buffer, idle flush, and optional async worker.
3. Dedup/merge, simple conflict resolver, superseded memory handling.
4. Completed run summaries and procedural memory extraction.
5. Elasticsearch hybrid retrieval if pgvector limits become visible.
6. Neo4j provenance graph, richer dashboard, replay UI, OpenTelemetry integration.

## Suggested Next Coding Task

pgvector semantic retrieval is restored (hybrid lexical + deterministic-vector cosine on `pgvector/pgvector:pg16`). Review and commit those working-tree changes. Then select the next P2 slice: completed-run reuse/procedural memory, LLM extraction with schema validation, or extending P2 benchmark cases 5-8.

## Suggested Test Strategy

- Unit tests: state transitions, recovery parent placement, gate hard policies, memory write rules, context packing budget/order.
- Integration tests: run/step/event API flow, rollback excludes failed memory, workspace isolation, access/gate/profile logs.
- Golden demo tests: Bun vs Node.js failed branch case with expected context and gate decisions.
- Benchmark tests: compare vector-only versus state-aware + gate using identical seeded memories.

## Risks and Dependencies

- Need package manager and exact scaffold decision before production code.
- Storage choice conflict must be resolved: architecture suggests ES early; MVP narrows to PostgreSQL + pgvector.
- LLM extraction should not enter P0 hot path.
- Dashboard should not precede trace/state/gate correctness.
- Recovery tree semantics are easy to implement incorrectly.
