# Open Questions

## Document Conflicts

1. **MVP storage:** `architecture.md` recommends PostgreSQL + Elasticsearch for first stage, while `mvp.md` fixes MVP on PostgreSQL + pgvector and explicitly defers Elasticsearch.
2. **Neo4j timing:** `draft.md` describes Neo4j in the minimum final stack; `mvp.md` explicitly defers Neo4j from first implementation.
3. **API naming:** `draft.md` uses `commit_step`; `architecture.md` and `mvp.md` use `finish_step`.
4. **Dashboard timing:** `architecture.md` success criteria include dashboard views; `mvp.md` says CLI + JSON/Markdown reports are enough for first version.
5. **Phase labels:** `architecture.md` Phase 1 includes ES and LLM extraction; `mvp.md` P0/P1 narrows to deterministic write rules and pgvector.

## Remaining Implementation Questions

1. **pgvector restoration:** keep lexical retrieval until a reliable pgvector image/provider is available, or implement optional pgvector KNN behind capability detection now?
2. **P2 scope order:** choose the next slice among completed-run reuse/procedural memory, LLM extraction, conflict resolution, or richer dashboard/replay UI.
3. **Auth model:** MVP still runs without full API-key/workspace auth. Decide whether P2 needs an API-key stub before any hosted demo.
4. **Raw secret payloads:** current implementation redacts persisted content and does not preserve original secret payloads. Decide whether future `raw_payload_ref` should ever store encrypted raw events.
