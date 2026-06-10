# Open Questions

## Document Conflicts

1. **MVP storage:** `architecture.md` recommends PostgreSQL + Elasticsearch for first stage, while `mvp.md` fixes MVP on PostgreSQL + pgvector and explicitly defers Elasticsearch.
2. **Neo4j timing:** `draft.md` describes Neo4j in the minimum final stack; `mvp.md` explicitly defers Neo4j from first implementation.
3. **API naming:** `draft.md` uses `commit_step`; `architecture.md` and `mvp.md` use `finish_step`.
4. **Dashboard timing:** `architecture.md` success criteria include dashboard views; `mvp.md` says CLI + JSON/Markdown reports are enough for first version.
5. **Phase labels:** `architecture.md` Phase 1 includes ES and LLM extraction; `mvp.md` P0/P1 narrows to deterministic write rules and pgvector.

## Remaining Implementation Questions

1. **pgvector restoration:** RESOLVED (2026-06-09, ADR-014). pgvector is restored on `pgvector/pgvector:pg16` with a `vector(256)` column + HNSW cosine index; retrieval is hybrid lexical + deterministic-vector cosine. Open follow-up: whether to replace the deterministic hashed embedding with a real embedding model (and how to keep benchmarks reproducible if so).
2. **P2 scope order:** RESOLVED (2026-06-10). P2 is complete (completed-run reuse/procedural memory, conflict resolver, candidate buffer, config-gated real LLM extraction, extended benchmark scenarios). Current remaining implementation order is tracked in `P3A_IMPLEMENTATION_PLAN.md` / `ROADMAP.md`; next slice is Phase 3-A Issue 3 (replay service + diff semantics).
3. **Auth model:** MVP still runs without full API-key/workspace auth. Decide whether P2 needs an API-key stub before any hosted demo.
4. **Raw secret payloads:** current implementation redacts persisted content and does not preserve original secret payloads. Decide whether future `raw_payload_ref` should ever store encrypted raw events.
