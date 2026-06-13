# Open Questions

## Document Conflicts

1. **MVP storage:** `architecture.md` recommends PostgreSQL + Elasticsearch for first stage, while `mvp.md` fixes MVP on PostgreSQL + pgvector and explicitly defers Elasticsearch.
2. **Neo4j timing:** `draft.md` describes Neo4j in the minimum final stack; `mvp.md` explicitly defers Neo4j from first implementation.
3. **API naming:** `draft.md` uses `commit_step`; `architecture.md` and `mvp.md` use `finish_step`.
4. **Dashboard timing:** `architecture.md` success criteria include dashboard views; `mvp.md` says CLI + JSON/Markdown reports are enough for first version.
5. **Phase labels:** `architecture.md` Phase 1 includes ES and LLM extraction; `mvp.md` P0/P1 narrows to deterministic write rules and pgvector.

## Remaining Implementation Questions

1. **pgvector restoration:** RESOLVED (2026-06-09, ADR-014). pgvector is restored on `pgvector/pgvector:pg16` with a `vector(256)` column + HNSW cosine index; retrieval is hybrid lexical + deterministic-vector cosine. Open follow-up: whether to replace the deterministic hashed embedding with a real embedding model (and how to keep benchmarks reproducible if so).
2. **Post-P2 implementation order:** RESOLVED (2026-06-13). P2, Phase 3-A, showcase/reproducibility baseline, Context Compaction C0-C5, Failure-aware Negative Memory Injection I1-I6, Phase 3.5 SDK/LangGraph adapter/CLI S0-S6, ROADMAP §7 6-strategy benchmark/eval persistence, ROADMAP §13 Security & Consistency Hardening H1-H18, and ROADMAP §10/§11 Provider Registry + Controlled Memory Key Ontology P1-P10 are complete. Provider Registry / Key Ontology now includes provider infrastructure, factory/DI, runtime/retrieval/replay embedding provider integration, key ontology/writer/resolver/LLM extraction migration, benchmark deterministic registry isolation, provider snapshot conformance, and closeout verification. Deterministic `variant_3` reflection-lite remains an explicit placeholder for the real §3.2 Reflection/Forgetting scheduler; I7 compaction negative retained is deferred.

3. **Auth model:** RESOLVED (2026-06-10, ADR-016; H3 implemented 2026-06-13). Lightweight Hosted-Demo Safety Mode now has a default-off token gate: local/dev/benchmark keep running with no auth by default, while `MEMTRACE_AUTH_ENABLED=true` makes `/v1` require Bearer or `X-API-Key` matching `MEMTRACE_API_KEY`. Full multi-tenant governance (API Key/JWT/workspace permissions, quotas, redaction/encryption state machine, admin conflict review) stays explicitly planned but is deferred to Phase 4 (ROADMAP §3.4) — a sequencing decision, not a descoping.
4. **Raw secret payloads:** RESOLVED (2026-06-10, ADR-017). Keep the default of never storing raw secrets. Any future `raw_payload_ref` must be encrypted at rest and default-off, gated behind the full redaction state machine in Phase 4 §3.4.

## Open During Provider Registry + Key Ontology Execution

- **Next roadmap after §10/§11:** not selected yet. Now that P10 closeout is complete, choose between deferred I7 compaction-negative retained facts, real Reflection/Forgetting scheduler, TypeScript/MCP/IDE integrations, or Phase 4 governance based on ROADMAP priority.
- **Provider factory / runtime embedding detail:** RESOLVED (2026-06-13). P3 created `providers/factory.py`, `deterministic_provider_registry(...)` registers the no-op judge contract, P4 completed runtime write/query embedding provider integration with deterministic fallback plus replay/policy snapshot alignment, P5-P7 completed key ontology and writer/resolver/LLM extraction migration, and P8/P10 completed benchmark deterministic registry/conformance plus final closeout. Final review hardened settings-derived embedding providers to the fixed 256-dim pgvector contract, package-manager correction semantics (`npm -> bun`), ontology schema coverage, and summarizer provider factory wiring.
