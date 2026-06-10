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

Status: complete (6/6), verified on 2026-06-10.

1. LLM extraction with schema validation and confidence/source-trust metadata. ✅ (config-gated pipeline + real OpenAI-compatible `LLMExtractionProvider`, live-verified against Volcengine Ark; degrades to rule writer on failure)
2. Candidate buffer, idle flush, and optional async worker. ✅ (in-process `candidate_buffer.py`; Redis-backed version deferred to ROADMAP §3.1)
3. Dedup/merge, simple conflict resolver, superseded memory handling. ✅ (write-path `resolver.resolve`; `superseded_by` lineage + migration `0003`; benchmark case 5)
4. Completed run summaries and procedural memory extraction. ✅ (cold-path `complete_run`; benchmark case 6)
5. Elasticsearch hybrid retrieval if pgvector limits become visible. ⏭ deferred — ROADMAP §4.
6. Neo4j provenance graph, richer dashboard, replay UI, OpenTelemetry integration. ⏭ deferred — ROADMAP §2/§4/§6.

## Next Coding Task

MVP (P0+P1+P2) is complete and committed. The selected next slice is
**Phase 3-A backend observability**, with the detailed implementation plan in
**`P3A_IMPLEMENTATION_PLAN.md`** at the repo root.

Implement `P3A_IMPLEMENTATION_PLAN.md` §11 issue-by-issue:

1. access fidelity + eval persistence schema; ✅ complete (2026-06-10)
2. side-effect-free retrieval trace pipeline; ✅ complete (2026-06-10)
3. replay service + diff semantics; ⬅ next
4. replay/observability APIs;
5. Quality/Safety metrics + profiler phase expansion;
6. dashboard table extension;
7. JSON/Markdown/HTML observability reports;
8. full regression, benchmark, and project-memory sync.

**Maintenance rule:** after completing each Issue, update `.ai/PROJECT_STATE.md`
and tick or annotate the corresponding `ROADMAP.md` checkbox/sub-checkbox.

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
