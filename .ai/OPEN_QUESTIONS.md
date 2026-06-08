# Open Questions

## Document Conflicts

1. **MVP storage:** `architecture.md` recommends PostgreSQL + Elasticsearch for first stage, while `mvp.md` fixes MVP on PostgreSQL + pgvector and explicitly defers Elasticsearch.
2. **Neo4j timing:** `draft.md` describes Neo4j in the minimum final stack; `mvp.md` explicitly defers Neo4j from first implementation.
3. **API naming:** `draft.md` uses `commit_step`; `architecture.md` and `mvp.md` use `finish_step`.
4. **Dashboard timing:** `architecture.md` success criteria include dashboard views; `mvp.md` says CLI + JSON/Markdown reports are enough for first version.
5. **Phase labels:** `architecture.md` Phase 1 includes ES and LLM extraction; `mvp.md` P0/P1 narrows to deterministic write rules and pgvector.

## Missing Implementation Details

1. Exact Python package manager and dependency policy: uv, poetry, pip-tools, or plain pip?
2. Exact repository scaffold: monorepo `apps/api` now or simpler single `app/` package first?
3. Database migration tool confirmation: Alembic is implied but not explicitly confirmed for MVP.
4. Embedding provider/model for pgvector, or whether P0 can use lexical similarity only.
5. Auth model for P0: no auth, static workspace config, API key stub, or full API key table?
6. Whether P0 should expose HTTP endpoints immediately or start with service tests and CLI demo.
7. Demo agent LLM dependency: real LLM call, deterministic scripted loop, or both?
8. Secret redaction storage rule: should original raw payload ever be persisted behind `raw_payload_ref`?
9. Token counting library and context budget enforcement details.
10. Benchmark report format and location.

## Choices Needing Confirmation Before Coding

1. Confirm MVP storage: PostgreSQL + pgvector only, or PostgreSQL + Elasticsearch.
2. Confirm first scaffold and package manager.
3. Confirm first coding slice: data model/state runtime before retrieval/gate.
4. Confirm whether to build FastAPI endpoints in the first slice or keep service-layer first.
5. Confirm whether P0 demo should avoid external LLM calls for reproducibility.

