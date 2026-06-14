# Open Questions

## Document Conflicts

1. **MVP storage:** `architecture.md` recommends PostgreSQL + Elasticsearch for first stage, while `mvp.md` fixes MVP on PostgreSQL + pgvector and explicitly defers Elasticsearch.
2. **Neo4j timing:** `draft.md` describes Neo4j in the minimum final stack; `mvp.md` explicitly defers Neo4j from first implementation.
3. **API naming:** `draft.md` uses `commit_step`; `architecture.md` and `mvp.md` use `finish_step`.
4. **Dashboard timing:** `architecture.md` success criteria include dashboard views; `mvp.md` says CLI + JSON/Markdown reports are enough for first version.
5. **Phase labels:** `architecture.md` Phase 1 includes ES and LLM extraction; `mvp.md` P0/P1 narrows to deterministic write rules and pgvector.

## Remaining Implementation Questions

1. **pgvector restoration:** RESOLVED (2026-06-09, ADR-014). pgvector is restored on `pgvector/pgvector:pg16` with a `vector(256)` column + HNSW cosine index; retrieval is hybrid lexical + deterministic-vector cosine. Open follow-up: whether to replace the deterministic hashed embedding with a real embedding model (and how to keep benchmarks reproducible if so).
2. **Post-P2 implementation order:** RESOLVED (2026-06-14). P2, Phase 3-A, showcase/reproducibility baseline, Context Compaction C0-C5 plus C6/I7 retained-negative metadata, Failure-aware Negative Memory Injection I1-I7, Phase 3.5 SDK/LangGraph adapter/CLI S0-S6, ROADMAP §7 6-strategy benchmark/eval persistence, ROADMAP §13 Security & Consistency Hardening H1-H18, ROADMAP §10/§11 Provider Registry + Controlled Memory Key Ontology P1-P10, Phase 4 async/lifecycle/governance P4-A/P4-B/P4-C/P4-D, integrations INT-A TypeScript SDK, integrations INT-B MCP Server, integrations INT-C MCP config templates / IDE thin-layer decision, R1 Release Readiness & Public Adoption, and OpenTelemetry/OpenInference exporter core slice are complete. Dedicated IDE package remains deferred until MCP adoption feedback shows editor-specific needs. Next roadmap target after OTel closeout is not yet selected.

3. **OpenTelemetry/OpenInference exporter scope:** RESOLVED (2026-06-14). Start with default-off OTLP/OpenInference core exporter: pure redacted semantic builders, noop/in-memory/JSONL/optional OTLP exporters, best-effort runtime hooks, and service-level read-only export/backfill. Runtime hooks must not synchronously perform network OTLP export; a minimal HTTP run export endpoint is implemented, while CLI telemetry export and richer access/backfill surfaces remain deferred. LangSmith/Phoenix/Langfuse vendor SDK bridges are deferred; they may consume OTLP/OpenInference output externally but are not direct dependencies in this slice.

3. **Auth model:** RESOLVED (2026-06-10, ADR-016; H3 implemented 2026-06-13). Lightweight Hosted-Demo Safety Mode now has a default-off token gate: local/dev/benchmark keep running with no auth by default, while `MEMTRACE_AUTH_ENABLED=true` makes `/v1` require Bearer or `X-API-Key` matching `MEMTRACE_API_KEY`. Full multi-tenant governance (API Key/JWT/workspace permissions, quotas, redaction/encryption state machine, admin conflict review) stays explicitly planned but is deferred to Phase 4 (ROADMAP §3.4) — a sequencing decision, not a descoping.
4. **Raw secret payloads:** RESOLVED (2026-06-10, ADR-017). Keep the default of never storing raw secrets. Any future `raw_payload_ref` must be encrypted at rest and default-off, gated behind the full redaction state machine in Phase 4 §3.4.

## Open During Provider Registry + Key Ontology Execution

- **Next roadmap after §10/§11:** RESOLVED (2026-06-14). **I7 compaction-negative retained facts** is complete through I7.6, **Phase 4 platform work is complete through P4-D4 and final P4-D review hardening**, and external integrations INT-A TypeScript SDK + INT-B MCP Server + INT-C MCP config templates are complete. Dedicated IDE extension package remains deferred until MCP adoption feedback exists.
- **Provider factory / runtime embedding detail:** RESOLVED (2026-06-13). P3 created `providers/factory.py`, `deterministic_provider_registry(...)` registers the no-op judge contract, P4 completed runtime write/query embedding provider integration with deterministic fallback plus replay/policy snapshot alignment, P5-P7 completed key ontology and writer/resolver/LLM extraction migration, and P8/P10 completed benchmark deterministic registry/conformance plus final closeout. Final review hardened settings-derived embedding providers to the fixed 256-dim pgvector contract, package-manager correction semantics (`npm -> bun`), ontology schema coverage, and summarizer provider factory wiring.
