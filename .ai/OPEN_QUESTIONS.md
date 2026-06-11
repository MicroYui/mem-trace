# Open Questions

## Document Conflicts

1. **MVP storage:** `architecture.md` recommends PostgreSQL + Elasticsearch for first stage, while `mvp.md` fixes MVP on PostgreSQL + pgvector and explicitly defers Elasticsearch.
2. **Neo4j timing:** `draft.md` describes Neo4j in the minimum final stack; `mvp.md` explicitly defers Neo4j from first implementation.
3. **API naming:** `draft.md` uses `commit_step`; `architecture.md` and `mvp.md` use `finish_step`.
4. **Dashboard timing:** `architecture.md` success criteria include dashboard views; `mvp.md` says CLI + JSON/Markdown reports are enough for first version.
5. **Phase labels:** `architecture.md` Phase 1 includes ES and LLM extraction; `mvp.md` P0/P1 narrows to deterministic write rules and pgvector.

## Remaining Implementation Questions

1. **pgvector restoration:** RESOLVED (2026-06-09, ADR-014). pgvector is restored on `pgvector/pgvector:pg16` with a `vector(256)` column + HNSW cosine index; retrieval is hybrid lexical + deterministic-vector cosine. Open follow-up: whether to replace the deterministic hashed embedding with a real embedding model (and how to keep benchmarks reproducible if so).
2. **Post-P2 implementation order:** RESOLVED (2026-06-12). P2 and Phase 3-A are complete, showcase/reproducibility baseline is complete, Context Compaction C0-C5 is complete per `docs/design/CONTEXT_COMPACTION_PLAN.md`, and Failure-aware Negative Memory Injection I1-I6 is complete per `docs/design/FAILURE_AWARE_NEGATIVE_MEMORY_PLAN.md`. Later priorities remain Phase 3.5 SDK/LangGraph adapter and 6-strategy benchmark expansion per `docs/design/ROADMAP.md`; I7 compaction negative retained is deferred.
3. **Auth model:** RESOLVED (2026-06-10, ADR-016). Before any hosted/public demo, do a lightweight Hosted-Demo Safety Mode (API-key stub + workspace-scoped demo token + no raw-secret persistence + demo reset + rate limit + read-only public reports). Full multi-tenant governance (API Key/JWT/workspace permissions, quotas, redaction/encryption state machine, admin conflict review) stays explicitly planned but is deferred to Phase 4 (ROADMAP §3.4) — a sequencing decision, not a descoping. Local/dev/benchmark keep running with no auth.
4. **Raw secret payloads:** RESOLVED (2026-06-10, ADR-017). Keep the default of never storing raw secrets. Any future `raw_payload_ref` must be encrypted at rest and default-off, gated behind the full redaction state machine in Phase 4 §3.4.
