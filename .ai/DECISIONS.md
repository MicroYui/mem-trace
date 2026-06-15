# Architecture Decisions

## Decision Log Template

```text
ID: ADR-XXX
Date: YYYY-MM-DD
Status: proposed | accepted | superseded
Context:
Decision:
Consequences:
Sources:
```

## Implied Decisions

### ADR-001: Project is Agent Memory Runtime, not a generic knowledge base

- **Date:** 2026-06-08
- **Status:** accepted by design docs
- **Decision:** Focus on Agent trace, state-aware retrieval, admission gate, and profiler rather than document ingestion/RAG breadth.
- **Sources:** `architecture.md`, `draft.md`, `mvp.md`.

### ADR-002: Use a MemoryRuntime facade as the public boundary

- **Date:** 2026-06-08
- **Status:** accepted by design docs
- **Decision:** External agents call runtime APIs instead of touching storage/indexes directly.
- **Sources:** `architecture.md`, `draft.md`, `mvp.md`.

### ADR-003: PostgreSQL is the source of truth

- **Date:** 2026-06-08
- **Status:** accepted by design docs
- **Decision:** Store traces, memory metadata, state, versions/logs, and profiler records durably in PostgreSQL; secondary indexes/projections are rebuildable.
- **Sources:** `architecture.md`, `mvp.md`.

### ADR-004: P0 uses explicit step events and simplified state tree

- **Date:** 2026-06-08
- **Status:** accepted by MVP plan
- **Decision:** Use `root -> step/recovery` with explicit `start_step` and `finish_step`; defer subgoal/summary/tool-call nodes.
- **Sources:** `mvp.md`, supported by `architecture.md` MVP generation rules.

### ADR-005: Admission gate is mandatory before prompt injection

- **Date:** 2026-06-08
- **Status:** accepted by design docs
- **Decision:** All retrieved memory candidates pass hard/risk/soft gate policies before context packing.
- **Sources:** `architecture.md`, `mvp.md`.

## P0 Implementation Decisions

### ADR-006: uv + apps/api monorepo layout

- **Date:** 2026-06-08
- **Status:** accepted
- **Context:** Needed a package manager and scaffold before writing code.
- **Decision:** Use `uv` for dependency management and an `apps/api/app/...` layout (runtime/memory/retrieval/storage/api/demo modules) so dashboard/SDK can be added as sibling apps later.
- **Consequences:** Tests run via `pythonpath = ["apps/api"]`; future apps live under `apps/`.

### ADR-007: Storage-agnostic Repository protocol with two backends

- **Date:** 2026-06-08
- **Status:** accepted
- **Context:** Need deterministic DB-free tests but PostgreSQL as source of truth.
- **Decision:** Define one async `Repository` protocol; provide `InMemoryRepository` (tests/demo) and `SqlRepository` (SQLAlchemy 2.0 async) implementing it. The `MemoryRuntime` facade depends only on the protocol.
- **Consequences:** Same runtime code path for both backends; verified identical behavior in tests and demo.

### ADR-008: P0 retrieval is deterministic lexical; embedding_vector stored as float[]

- **Date:** 2026-06-08
- **Status:** accepted (supersedes the pgvector assumption in mvp.md §4 for P0 only)
- **Context:** The pgvector Docker image was unreachable in this environment, and P0 benchmark value comes from state-awareness + gating, not BM25/vector recall quality.
- **Decision:** Use token-overlap lexical similarity with no external embedding provider; store `embedding_vector` as Postgres `float[]` instead of `pgvector.Vector`. The migration attempts `CREATE EXTENSION vector` best-effort.
- **Consequences:** No semantic KNN in P0; fully reproducible benchmarks. Re-enable pgvector by swapping the ORM column type and enabling the extension.

### ADR-009: Run-local sequence_no via transactional advisory lock

- **Date:** 2026-06-08
- **Status:** accepted
- **Context:** Events must be ordered by a strictly increasing run-local `sequence_no`, not `created_at`.
- **Decision:** In `SqlRepository.next_sequence_no`, take a per-run `pg_advisory_xact_lock(hashtext(run_id))` then `max(sequence_no)+1` within the transaction. In-memory uses a per-run counter.
- **Consequences:** Concurrent writers to the same run get gap-free monotonic sequence numbers; cross-run numbering is independent.

### ADR-010: Strategy modes encode the benchmark variants in the gate

- **Date:** 2026-06-08
- **Status:** accepted
- **Context:** Must prove gains come from state-awareness + gating over identical seeded memories.
- **Decision:** `GateConfig.for_strategy` maps `baseline_0/1`, `variant_1/2` to which layers run (baseline_1 = relevance only; variant_1 = state-aware rerank, failed-branch downweighted; variant_2 = full hard+risk+soft). Workspace-scoped candidate retrieval is the leakage filter; `workspace_mismatch` gate rule is defense-in-depth.
- **Consequences:** One retrieval pipeline serves all variants, ensuring fairness; demo shows baseline_1 contamination=1 vs variant_2=0.

### ADR-011: Lifecycle filtering of non-retrievable memory at candidate stage

- **Date:** 2026-06-09
- **Status:** accepted
- **Context:** Superseded/archived/dormant memory (e.g. a user-corrected project constraint) must never be injected, regardless of context-merge order.
- **Decision:** The retrieval controller admits only `active/pinned/conflicted/quarantined` statuses as candidates (`_RETRIEVABLE_STATUSES`); superseded/archived/dormant/deleted are excluded before scoring. This is a write-time lifecycle decision applied uniformly to all strategies, so it does not affect benchmark fairness.
- **Consequences:** Corrected constraints cannot leak; conflicted/quarantined remain visible so the gate can emit an auditable degrade/reject decision.

### ADR-012: P1 benchmark reports are generated artifacts

- **Date:** 2026-06-09
- **Status:** accepted
- **Context:** P1 requires `benchmark_report.md` and `benchmark_results.json`, but benchmark outputs are reproducible and the repository already ignores `reports/`.
- **Decision:** Keep deterministic benchmark logic in source (`app/benchmark/cases.py`, `evaluator.py`, `runner.py`) and generate report artifacts with `python -m app.benchmark.runner --output-dir reports` instead of tracking generated report files.
- **Consequences:** Source control stays focused on executable benchmark definitions; reviewers can regenerate reports locally. Generated reports under `reports/` should not be treated as canonical source.

### ADR-013: P1 dashboard is a table API, not a frontend app

- **Date:** 2026-06-09
- **Status:** accepted
- **Context:** `mvp.md` asks for basic dashboard tables in P1 while explicitly deferring a full React dashboard.
- **Decision:** Implement `GET /v1/dashboard/tables` returning table-shaped runtime/profiler/benchmark data from the repository; do not add a frontend app yet.
- **Consequences:** P1 supports inspection and reportability without dashboard scope creep. A future UI can consume the same endpoint or replace it with richer paginated views.

### ADR-014: Restore pgvector semantic retrieval with deterministic hashed embeddings

- **Date:** 2026-06-09
- **Status:** accepted (supersedes the P0 `float[]` workaround in ADR-007/decision notes)
- **Context:** P0 stored `embedding_vector` as `float[]` and retrieved lexically because the `pgvector/pgvector` image was unreachable. The image is now available locally (`pgvector/pgvector:pg16`), so the mvp.md §4 requirement (PostgreSQL + pgvector) can be met without giving up reproducibility or pulling in an external embedding provider.
- **Decision:**
  - Embeddings are deterministic, process-stable hashed bag-of-words vectors (`similarity.stable_embedding`, blake2b — not Python's salted `hash`), L2-normalized, dim 256. No external/LLM embedding provider, so benchmark/demo stay reproducible.
  - `memory_items.embedding_vector` is a `pgvector.Vector(256)` column (migration `0002_pgvector`: hard `CREATE EXTENSION vector`, type change, HNSW cosine index). The compose default image is now `pgvector/pgvector:pg16`.
  - Retrieval is hybrid: `RetrievalController._select_candidates` blends lexical overlap with vector cosine (`retrieval_vector_weight`, default 0.5) and falls back to lexical-only when vectors are absent/disabled (`retrieval_use_vector`).
  - Embeddings are backfilled at the single write chokepoint `Repository.add_memory` via `ensure_embedding`, so every stored memory (rule-written or test-seeded) is vector-searchable; benchmark fairness (identical seeded items per strategy) is preserved.
  - New protocol method `search_memories_by_vector`: InMemory uses Python cosine; SQL uses pgvector `<=>` cosine distance converted to a [0,1] similarity.
- **Consequences:** Semantic + lexical retrieval both contribute to relevance while all existing differentiation results hold (variant_2 contamination 0.0 < baseline_1 0.25; tool-sensitive blocked; zero cross-workspace leakage). PG15 volumes are incompatible with the pg16 image, so switching requires recreating the data volume (`docker-compose down -v`). Hashed embeddings are a similarity proxy, not true semantics; swapping in a real embedding model later only requires changing `stable_embedding` (keep determinism for benchmarks or gate it behind config).

## Post-P3-A Decisions (OPEN QUESTIONS resolved)

### ADR-015: Keep deterministic embedding as default; real embedding is an optional config-gated provider

- **Date:** 2026-06-10
- **Status:** accepted (resolves OPEN_QUESTIONS #1; refines ADR-014)
- **Context:** ADR-014 restored pgvector with deterministic hashed bag-of-words embeddings (blake2b, dim 256). These are a similarity proxy, not learned semantics. OPEN_QUESTIONS #1 asked whether to replace them with a real embedding model and how to keep benchmarks reproducible if so.
- **Decision:** The deterministic hashed embedding stays the **default** and remains the benchmark/demo baseline so results stay reproducible. A real embedding model is introduced only as an **optional, config-gated `EmbeddingProvider`** under the unified Provider Registry (ROADMAP §10), mirroring the proven `LLMExtractionProvider` pattern: deterministic fallback + config-gate enablement + failure degradation. Benchmarks always select the deterministic path (provider capability metadata declares determinism), so enabling a real embedding model never breaks reproducibility.
- **Consequences:** No change to current behavior until the provider is built. Implementation work moves to ROADMAP §10 (Provider Registry); §0 only records that the direction is now decided. Swapping in a real model touches `similarity.stable_embedding` / the new provider seam, not the retrieval pipeline.
- **Sources:** OPEN_QUESTIONS #1, PROJECT_STATE risk #1, ADR-014, ROADMAP §0 / §10.

### ADR-016: Lightweight Hosted-Demo Safety Mode first; full multi-tenant governance is planned but deferred to Phase 4

- **Date:** 2026-06-10
- **Status:** accepted (resolves OPEN_QUESTIONS #3)
- **Context:** The MVP runs without API-key/workspace auth. OPEN_QUESTIONS #3 asked whether a stub is needed before any hosted demo. There are two distinct scopes: a minimal safety layer to expose a public demo safely, versus full multi-tenant governance (RBAC, quotas, admin review).
- **Decision:** Before any hosted/public demo, implement a **lightweight Hosted-Demo Safety Mode** only: API-key stub + workspace-scoped demo token + no raw-secret persistence (see ADR-017) + demo reset + rate limit + read-only public reports. **Full multi-tenant governance** (API Key/JWT/workspace permission system with `api_keys` table, per-tenant quota/limiting, field-level redaction/encryption state machine, admin conflict-review workflow) **remains explicitly in the plan** but is deferred to Phase 4 (ROADMAP §3.4); it is a sequencing decision, not a descoping.
- **Consequences:** Local/dev/benchmark continue to run with no auth. The lightweight mode is a small, self-contained slice unblocking a public demo without pulling forward heavy governance. §3.4 stays on the roadmap with a clear dependency note.
- **Sources:** OPEN_QUESTIONS #3, MVP_SCOPE Out-of-Scope #5, ROADMAP §0 / §3.4.

### ADR-017: Secrets are not persisted in raw form by default; any future raw_payload_ref must be encrypted and off by default

- **Date:** 2026-06-10
- **Status:** accepted (resolves OPEN_QUESTIONS #4)
- **Context:** The current implementation redacts persisted content and does not preserve original secret payloads. OPEN_QUESTIONS #4 asked whether a future `raw_payload_ref` should ever store encrypted raw events.
- **Decision:** Keep the **default of never storing raw secrets**. If a `raw_payload_ref` capability is ever added, it **must be encrypted at rest and default-off**, and it is gated behind the full redaction state machine (`none/redacted/digest_only/blocked`) in Phase 4 §3.4. The lightweight Hosted-Demo Safety Mode (ADR-016) explicitly does not persist raw secrets.
- **Consequences:** No raw secret leakage risk in current or demo modes. Encrypted raw retention is a deliberate, opt-in, Phase 4 feature, not an implicit default.
- **Sources:** OPEN_QUESTIONS #4, architecture.md §6.2, ROADMAP §0 / §3.4.

### ADR-018: Failure learning uses a separate negative-evidence channel, not positive context injection

- **Date:** 2026-06-11
- **Status:** accepted; implemented through I7, including compaction-negative retained facts closeout (2026-06-14)
- **Context:** The current gate hard-rejects failed/rolled_back branch memories, which prevents contamination but also hides useful "what failed before" information from coding agents. Directly accepting failed memories would pollute positive context and replay/metrics currently treat `degrade` as accepted in multiple places.
- **Decision:** Implement Failure-aware Negative Memory Injection as a distinct warning-only channel. Safe failed/rolled_back memories may become `degrade` decisions and render as `avoided_attempts` blocks through a derived `NegativeEvidence` DTO. Destructive, secret, tool-sensitive, or production-env failures remain hard-rejected and only produce sanitized notices with fixed templates. `accepted` means only `accept/warn`; `degrade` is a separate channel. Controller, inspect, and replay must all use the shared `retrieval/negative_evidence.py` builder to avoid drift.
- **Consequences:** Existing positive-context semantics remain protected while variant_2 can learn from failures. I2 established the safe DTO/builder/packer boundary: packer consumes only `NegativeEvidence.safe_text`, and the shared builder re-checks unsafe flags even for drifted `degrade` inputs before emitting sanitized notices. I3 wires the controller hot path so safe failed lessons render as `avoided_attempts` and unsafe failed lessons render as sanitized notices without entering positive accepted context; profile/warnings count retained negative-evidence blocks so budget-dropped lessons are not reported as injected. I4 wires inspect/replay/metrics through the same semantics: degraded memories are not positive accepted context, replay original views rebuild negative evidence via the shared builder, missing source memories warn without reconstructing raw failed text, sanitized/degraded drift severity is explicit, and observability exposes explicit negative-evidence counters. I5 expands benchmark coverage from 36 to 44 runs with `case_10` safe failure learning and `case_11` sanitized destructive failure; evaluator/report/dashboard metrics explicitly split positive context from negative evidence, and acceptance verifies `variant_2_learns_from_failure_without_repeating` plus `variant_2_sanitizes_destructive_failure_without_leakage`. I6 finalized ROADMAP / compaction-plan cross-reference / `.ai` memory sync. I7 preserves dropped negative lessons as dedicated compaction metadata without mixing them into positive `retained_facts` or forcing prompt injection: it added `RetainedNegativeEvidence`, `to_retained_negative_evidence(...)`, `ContextCompactionLog.retained_negative_evidence` / `PendingCompactionLog.retained_negative_evidence`, SQL JSONB persistence, Alembic migration `0007_i7_retained_negative_evidence`, trace-bundle/report redaction, packer dropped-block metadata retention, replay/metrics/reports/dashboard surfacing, benchmark `case_13_compaction_retains_negative_lesson`, and acceptance `variant_2_retains_negative_lesson_under_compaction`.
- **Sources:** `docs/design/FAILURE_AWARE_NEGATIVE_MEMORY_PLAN.md`, `docs/design/ROADMAP.md` §9.1, `.ai/PROJECT_STATE.md` Next Recommended Action.

### ADR-019: Phase 3.5 exposes one runtime through SDK, HTTP, adapter, and CLI entrypoints

- **Date:** 2026-06-12
- **Status:** accepted; implemented through S6
- **Context:** Phase 3.5 needed to prove MemTrace is a pluggable agent-memory runtime rather than a bundled demo loop. The same state-aware retrieval, gate, context compaction, negative evidence, profiler, and replay semantics must be reachable from embedded Python loops, HTTP clients, LangGraph-style node lifecycle hooks, and shell workflows without duplicating business logic.
- **Decision:** Keep the Python SDK as a thin async facade over interchangeable backends. `memtrace-sdk` intentionally depends on the core `memtrace` package so in-process and HTTP backends return the same Pydantic DTOs/enums. The SDK facade stamps omitted event sources as `"sdk"`; LangGraph adapter and CLI explicitly stamp `"langgraph_adapter"` and `"cli"`. CLI operational commands require `--http` because separate shell invocations cannot share throwaway in-memory state; in-process mode is reserved for one-shot demos. HTTP transport uses JSON bodies for arbitrary string identifiers such as `session_id` when path interpolation would break backend isomorphism.
- **Consequences:** SDK, HTTP, LangGraph adapter, examples, and CLI share one runtime boundary and one testable behavior contract. Install footprint is heavier than a pure-HTTP schema-only SDK, but behavioral/type isomorphism is prioritized; a future `memtrace-contracts` package can revisit this. Future entrypoints (TS SDK, MCP, IDE plugins, telemetry exporters) must not bypass `MemoryRuntime` or introduce alternate retrieval/gate/packing paths.
- **Sources:** `docs/design/SDK_ADAPTER_PLAN.md`, `docs/design/ROADMAP.md` §6, `README.md` three-entrypoint section.

### ADR-020: Execute Security & Consistency Hardening before Provider Registry / Key Ontology

- **Date:** 2026-06-13
- **Status:** accepted; implemented through H18 and verified
- **Context:** After ROADMAP §7 Task 11, the next candidates were §10 Provider Registry and §11 Controlled Memory Key Ontology. A 2026-06-13 full six-module review fixed four immediate defects but left larger security/consistency findings in ROADMAP §1.1/§13: positive context redaction defense-in-depth, `variant_1` gate convergence, lightweight auth semantics, atomic event sequencing, timeout persistence, backend isomorphism, deterministic gate/replay ordering, ORM/migration alignment, token-budget precision, summarizer provenance validation, state-machine boundaries, benchmark fairness, policy snapshot, conformance suite, trace bundle, migration policy, and dogfood scenarios.
- **Decision:** Treat ROADMAP §13 Security & Consistency Hardening as the selected next target before starting §10/§11. Use `docs/design/SECURITY_CONSISTENCY_HARDENING_PLAN.md` as the authoritative H1-H18 implementation plan. Start with Batch A / H1-H3 security closure, then proceed through backend/data consistency, determinism/schema alignment, policy snapshot + conformance suite, precision/robustness, migration policy, trace bundle, dogfood harness, and docs/project-memory closeout.
- **Consequences:** Provider Registry and Controlled Memory Key Ontology were intentionally postponed until the runtime's existing promises were hardened; with H1-H18 complete, they are now the recommended next roadmap area. Batch A closed the first safety layer: prompt-context positive blocks are redacted defensively, `variant_1` can no longer bypass hard/risk safety policies, quarantined/secret/destructive/tool-sensitive memories are non-bypassable safety floors across strategies, and the existing SDK/CLI bearer-token path is backed by default-off `/v1` API auth. H4/H5/H6/H13 close backend error isomorphism, atomic event append, retrieval-timeout persistence, and state-machine corruption boundaries. H7-H10 close deterministic gate/replay ordering, compaction-index ORM/migration drift, retrieval policy snapshot/policy-drift classification, and conformance-suite coverage for strategy/backend/replay invariants. H11/H12/H14 close independent token-budget estimation/CJK truncation, structured summarizer provenance allow-set validation, and whole-memory benchmark fairness snapshot/restore. H15-H18 close migration compatibility policy, redacted trace bundle export/validation, deterministic dogfood harnesses, and docs/project-memory closeout. Full RBAC/JWT multi-tenant governance remains deferred to ROADMAP §3.4; H3 only implements default-off lightweight token auth per ADR-016.
- **Sources:** `docs/design/SECURITY_CONSISTENCY_HARDENING_PLAN.md`, `docs/design/ROADMAP.md` §1.1 / §13, `.ai/PROJECT_STATE.md` Current Goal.

### ADR-021: Provider Registry and Key Ontology complete the deterministic provider/key boundary

- **Date:** 2026-06-13
- **Status:** accepted and implemented through P10
- **Context:** After H1-H18, provider construction remains split across `api/deps.py`, direct provider classes, `stable_embedding(...)`, and retrieval policy hard-coded provider strings. Memory key semantics are duplicated between deterministic writer rules, resolver single-valued key sets, and LLM extraction prompt text, causing drift risk for aliases and controlled keys.
- **Decision:** Execute `docs/design/PROVIDER_REGISTRY_KEY_ONTOLOGY_PLAN.md` as the source plan for ROADMAP §10/§11. Add `app.providers` with dependency-light base/registry modules and a separate settings-aware factory; use non-secret capability metadata snapshots; keep deterministic provider defaults and explicit benchmark override; add deterministic and OpenAI-compatible embedding providers; include only retrieval-relevant provider snapshots in retrieval policy v2. Add `app.memory.key_ontology` as the code-defined single source of truth for canonical keys, aliases, cardinality, default type/scope, free-form validation, and prompt rendering; migrate writer/resolver/LLM extraction to import ontology behavior instead of duplicating rules. Represent judge only as a no-op contract/provider-family metadata in this slice.
- **Consequences:** Real providers can be enabled behind config without compromising deterministic tests/benchmarks. P1/P2/P9 establish the provider-only base: `ProviderCapabilities.snapshot()` freezes/sanitizes metadata, `ProviderRegistry` stays dependency-light, deterministic hash embedding wraps `stable_embedding(...)`, OpenAI-compatible embedding validates request/response dimensions without changing pgvector's 256-dim assumption, and `NoopJudgeProvider` represents the judge family without hot-path behavior. P3 adds settings-based provider construction and FastAPI/runtime registry injection; final review hardens this boundary so settings-derived embedding providers always use the fixed 256-dim pgvector contract even if `MEMTRACE_EMBEDDING_DIM` is configured differently. P4 makes policy drift aware of retrieval provider capabilities through `retrieval-policy-v2`, keeps non-retrieval `judge` out of retrieval policy hashes, routes runtime internal memory-write embeddings and retrieval query vectors through the embedding provider with deterministic 256-dim fallback, rejects non-finite provider vectors before storage/search, preserves repository-level `ensure_embedding(...)` backfill for direct seeded memories/tests/backfills, freezes retrieval provider snapshots with the cached provider lifecycle, reflects explicit summarizer overrides in policy snapshots, and makes replay policy-drift reconstruction use public `RetrievalController.provider_snapshot`. P5-P7 add `app.memory.key_ontology`, migrate writer/resolver/runtime identity to canonical key semantics, split package-manager facts from runtime facts including `npm -> bun` correction paths, promote same-value alias survivors to canonical keys, and enforce ontology normalization/default type-scope/free-form safety at the LLM extraction boundary. P8 forces `deterministic_provider_registry()` inside benchmark runtime construction and adds provider snapshot conformance so real-provider env vars cannot affect reproducibility. P10 closes the slice with affected regression, compile, full pytest, deterministic benchmark, reproduce script, ROADMAP, and `.ai` sync. The plan deliberately avoids pgvector dimension migration, storage-backed ontology administration, production LLM judge behavior, and broader governance.
- **Sources:** `docs/design/PROVIDER_REGISTRY_KEY_ONTOLOGY_PLAN.md`, `docs/design/ROADMAP.md` §10 / §11, ADR-015, ADR-020.

### ADR-022: Select integrations as the next post-Phase-4 roadmap slice

- **Date:** 2026-06-14
- **Status:** accepted
- **Context:** Phase 4 async/lifecycle/governance is complete through P4-D4 and final review hardening, with full regression and reproducibility passing. The remaining roadmap candidates were external integrations, admin/manual governance depth, advanced storage/retrieval, and UI/dashboard work.
- **Decision:** Use `docs/design/INTEGRATIONS_PLAN.md` as the selected next implementation plan and refresh it against source-verified Phase 4 routes/models before coding. Start with INT-A TypeScript SDK, specifically INT-A1 Bun workspace and minimal core HTTP client, then expand the HTTP surface/contract smoke before implementing the MCP server and IDE/MCP configuration templates. The TS SDK plan must treat 401/403/429, FastAPI `detail`/non-JSON error parsing, path-authoritative `completeRun(runId, req)`, workspace-scoped session flush, missing-workspace 403 handling for workspace-wide routes, full `ExtractionMode`, async write-result fields, and memory versions/conflicts as current contract requirements. Use stable package names `@memtrace/sdk` and `@memtrace/mcp-server` from the start.
- **Consequences:** Project memory should point future resume/implementation sessions at `docs/design/INTEGRATIONS_PLAN.md`. Integration code must remain a thin client layer over the stable `/v1` HTTP contract and must not import Python runtime modules, access storage directly, or reimplement retrieval, gate, context-packing, replay, governance, or memory semantics. MCP tools should call the TS SDK only and cap/sanitize replay/report output by default.
- **Sources:** `docs/design/INTEGRATIONS_PLAN.md`, `.ai/PROJECT_STATE.md`, `.ai/IMPLEMENTATION_PLAN.md`.

### ADR-023: TypeScript SDK is a thin fetch client over the Phase 4 HTTP contract

- **Date:** 2026-06-14
- **Status:** accepted and implemented through INT-A
- **Context:** After Phase 4, external JavaScript/TypeScript applications need a stable entrypoint without duplicating Python runtime behavior. The HTTP contract now includes governance, quota, async extraction, session flushing, and memory versions/conflicts.
- **Decision:** Implement `@memtrace/sdk` as a Bun-workspace TypeScript package with structural DTOs, a fetch-based `MemTraceClient`, and status-aware error classes. The SDK maps FastAPI `detail`/validation-detail/common JSON/non-JSON errors, including 400/422 bad requests, 401/403 authn/authz failures, 404 not found, and 429 quota failures; sends API keys as `Authorization: Bearer`; uses body JSON for arbitrary session flush ids; treats `completeRun(runId, req)` path id as authoritative; and covers current Phase 4 routes before MCP work. It deliberately avoids runtime schema-validation dependencies and any Python runtime/database imports.
- **Consequences:** MCP and IDE integrations can depend on `@memtrace/sdk` instead of reimplementing HTTP details. Future route additions should update `types.ts`, `client.ts`, and mocked path/error tests together. Bun is the intended JS workspace tool; `bun.lock` is expected and npm/pnpm/yarn lockfiles are not.
- **Sources:** `docs/design/INTEGRATIONS_PLAN.md` INT-A, `packages/ts-sdk/src/client.ts`, `packages/ts-sdk/src/errors.ts`, `packages/ts-sdk/src/types.ts`.

### ADR-024: MCP server is a thin stdio adapter over the TypeScript SDK

- **Date:** 2026-06-14
- **Status:** accepted and implemented through INT-B
- **Context:** MCP-capable agents and IDEs need a MemTrace entrypoint after the TS SDK, but integration code must not duplicate Python runtime, retrieval, gate, replay, report, governance, or storage semantics.
- **Decision:** Implement `@memtrace/mcp-server` as a Bun-workspace stdio MCP server. It loads `MEMTRACE_BASE_URL` and optional `MEMTRACE_API_KEY`, constructs `MemTraceClient`, and exposes only concise tools backed by SDK methods: `memtrace_start_run`, `memtrace_start_step`, `memtrace_write_event`, `memtrace_retrieve_context`, `memtrace_inspect_access`, `memtrace_finish_step`, `memtrace_replay_access`, and `memtrace_report`. Tool outputs are redacted, replay/report responses are capped at 8k characters by default, and tests assert the package source does not import Python runtime/database markers.
- **Consequences:** MCP/IDE workflows inherit HTTP/SDK error mapping and server-side semantics instead of adding another runtime path. Future MCP tools should be added only after output-safety review and should continue to use `@memtrace/sdk` as their MemTrace boundary. INT-B detailed review additionally hardened MCP text redaction for JSON-style secret-like keys (`password`, `api_key`, `access_token`, etc.) so replay/report summaries cannot leak values serialized through `JSON.stringify(...)`; made unknown-tool errors use the same redacted/capped output path; and restricted `MEMTRACE_BASE_URL` to HTTP(S) without embedded credentials. Cross-INT final review broadened redaction to parse whole JSON and redact common secret-bearing keys such as `authorization`, bare `token`, `client_secret`, `secret_key`, `id_token`, `*_token`, `*_secret`, and `*_credential`, while preserving non-secret budget fields. INT-C can now focus on MCP configuration templates rather than a dedicated IDE extension.
- **Sources:** `docs/design/INTEGRATIONS_PLAN.md` INT-B, `packages/mcp-server/src/tools.ts`, `packages/mcp-server/src/server.ts`, `packages/mcp-server/test/tools.test.ts`.

### ADR-025: IDE integration starts with MCP config templates, not a dedicated extension package

- **Date:** 2026-06-14
- **Status:** accepted and implemented through INT-C
- **Context:** After INT-A and INT-B, Claude Code / Cursor-style MCP clients can already reach MemTrace through `@memtrace/mcp-server`. A dedicated IDE package would add editor-specific packaging, command palette behavior, and UI maintenance before there is evidence that MCP-based usage is insufficient.
- **Decision:** Complete INT-C by shipping MCP configuration templates and documentation only. Add Claude Code and Cursor-style template fixtures under `examples/mcp/`, export the same structures from `@memtrace/mcp-server` for testability, and keep all config examples using `${MEMTRACE_BASE_URL}` and `${MEMTRACE_API_KEY}` placeholders rather than real secrets. Do not create `packages/ide/` in this slice.
- **Consequences:** IDE/agent users get copy-paste integration immediately while all runtime semantics still flow through MCP → TypeScript SDK → HTTP `/v1` → `MemoryRuntime`. Dedicated IDE extension work remains deferred until MCP adoption feedback identifies editor-specific needs. Future template changes should update `packages/mcp-server/src/templates.ts`, `examples/mcp/*.json`, README snippets, and `packages/mcp-server/test/config.test.ts` together.
- **Sources:** `docs/design/INTEGRATIONS_PLAN.md` INT-C, `README.md` MCP config snippets, `packages/mcp-server/src/templates.ts`, `packages/mcp-server/test/config.test.ts`.

### ADR-026: Select Release Readiness before the next feature-heavy roadmap slice

- **Date:** 2026-06-14
- **Status:** accepted; implemented through R1-C2
- **Context:** After Phase 4 and INT-A/INT-B/INT-C, MemTrace has substantial runtime/platform and integration capability: state-aware memory runtime, context compaction, failure-aware negative evidence, provider registry/key ontology, async/lifecycle/governance foundations, Python SDK/CLI/LangGraph adapter, TypeScript SDK, MCP server, MCP config templates, benchmark, replay, and reports. Remaining roadmap candidates such as OpenTelemetry/OpenInference exporter, advanced retrieval/storage, admin conflict workflow, and React dashboard are useful but either add new feature surfaces or assume public adoption paths already exist.
- **Decision:** Select `docs/design/RELEASE_READINESS_PLAN.md` as the next implementation plan. R1 focuses on public adoption readiness: command inventory, README/user-doc rewrite, 5-minute demo/smoke consolidation, package metadata and package-shape checks, CI, release-hygiene guards, release checklist, verification, and ROADMAP/`.ai` closeout. R1 must not add runtime retrieval/gate/context-packing semantics. It must keep JS packages `private: true` unless publication is explicitly approved, avoid introducing a `dist/` build pipeline by default, use `oven-sh/setup-bun` in CI while documenting local temporary-Bun fallback, and make service/provider-dependent paths opt-in.
- **Consequences:** R1 is now complete: public onboarding, user docs, smoke script, package metadata/package-shape checks, CI, release hygiene, release checklist, benchmark/reproduce closeout, and ROADMAP/`.ai` sync are in place. At R1 closeout, OpenTelemetry/OpenInference exporter became the recommended next feature slice; this historical recommendation has since been superseded by ADR-031 / OTel Segment 4 closeout. README/public docs must still avoid advertising LangSmith/Phoenix/Langfuse direct vendor support unless a separate bridge slice is completed. Phase 5 retrieval/storage, admin/manual governance workflow, React dashboard, dedicated IDE extension, and automatic npm/PyPI publishing remain out of scope until explicitly selected.
- **Sources:** `docs/design/RELEASE_READINESS_PLAN.md`, `.ai/PROJECT_STATE.md`, `.ai/IMPLEMENTATION_PLAN.md`, `.ai/OPEN_QUESTIONS.md`.

### ADR-027: Public docs classify quickstarts by runtime requirement

- **Date:** 2026-06-14
- **Status:** accepted; implemented through R1-A2
- **Context:** R1-A0 command inventory showed that MemTrace has both deterministic no-network entrypoints and service-dependent integration entrypoints. The CLI in-process demo and Python SDK example emit stable failed-branch contrast markers without Docker or a live server, while the TypeScript SDK example and MCP server are HTTP clients that require a running MemTrace service. Treating all examples as unconditional quickstarts would make first-time onboarding brittle.
- **Decision:** README and user docs must classify commands by runtime requirement. Only no-network commands may appear as unconditional first-run quickstarts. HTTP, TypeScript SDK, MCP, Docker/PostgreSQL, Redis/Celery, and real-provider paths must state preconditions next to the command. R1-A1/R1-A2 implement this with a README command table and dedicated getting-started/MCP/deployment docs.
- **Consequences:** Public onboarding is honest and reproducible: new users can run the CLI/Python demo immediately, while service-backed paths remain discoverable without overclaiming default pass behavior. Future release-readiness work should preserve these labels and keep optional smoke tests env-gated.
- **Sources:** `docs/design/RELEASE_READINESS_PLAN.md`, `README.md`, `docs/getting-started.md`, `docs/mcp.md`, `docs/deployment.md`.

### ADR-028: R1 package readiness uses private source-entry packages before publication

- **Date:** 2026-06-14
- **Status:** accepted; implemented through R1-B2
- **Context:** R1-B1/B2 prepares MemTrace for public adoption, but maintainers have not approved npm/PyPI publication or a JS build-output pipeline. The current TypeScript packages are Bun workspace packages consumed from source during local development, while Python packaging already uses the uv workspace and Hatchling.
- **Decision:** Keep `@memtrace/sdk` and `@memtrace/mcp-server` as `private: true` source-entry packages for R1. Add release-ready metadata, `exports`, explicit `files`, and package-shape tests, but do not introduce `dist/`, bundlers, declaration emit, or automatic publishing. For Python, update root and SDK metadata to describe the current platform/SDK and test README/license/URLs/classifiers plus the `memtrace` console script.
- **Consequences:** Package manifests become reviewable and launch-ready without creating an unsupported publication contract. R1-B3/R1-C can add CI/release hygiene around the same shape; actual package publishing remains a future explicit decision.
- **Sources:** `docs/design/RELEASE_READINESS_PLAN.md`, `packages/ts-sdk/package.json`, `packages/mcp-server/package.json`, `pyproject.toml`, `packages/python-sdk/pyproject.toml`.

### ADR-029: R1 default CI is deterministic and service-free by default

- **Date:** 2026-06-14
- **Status:** accepted; implemented through R1-B3 / R1-C2 Step 4
- **Context:** R1 needs CI and release hygiene for public adoption, but the repository has optional Postgres/Redis/LLM/live HTTP paths that should not be required for default PR checks. Local development may also contain untracked `node_modules/`, generated `reports/`, `dist/`, and TypeScript build-info files that should not break hygiene checks unless they are tracked.
- **Decision:** Add a default GitHub Actions workflow with separate Python, Bun, and release-hygiene jobs. Python CI runs uv compileall and full pytest; JS CI uses `oven-sh/setup-bun` and runs Bun typecheck/tests; hygiene runs `scripts/check-release-hygiene.sh`. The hygiene guard checks tracked files via `git ls-files` for generated/local artifacts and scans only public docs/examples for obvious real secret/destructive/raw-payload markers, excluding internal design/superpowers plans that intentionally contain synthetic fixtures.
- **Consequences:** PR CI verifies the default deterministic path without requiring service credentials or external infrastructure. Release hygiene catches accidentally tracked artifacts and public-doc leaks while avoiding false positives from local untracked outputs and internal test/design fixtures. Full benchmark/reproduce was completed in R1-C2 closeout and remains a maintainer release-checklist command rather than a mandatory default PR workflow.
- **Sources:** `.github/workflows/ci.yml`, `scripts/check-release-hygiene.sh`, `docs/design/RELEASE_READINESS_PLAN.md` R1-B3 / R1-C2 Step 4.

### ADR-030: R1 release checklist is manual and non-publishing by default

- **Date:** 2026-06-14
- **Status:** accepted; implemented through R1-C1/R1-C2
- **Context:** R1 prepares MemTrace for public adoption, but maintainers have not approved automatic PyPI/npm publishing or a JavaScript build-output pipeline. Release readiness needs a concrete maintainer checklist without turning package metadata work into irreversible publication automation.
- **Decision:** Add `docs/release-checklist.md` as a manual maintainer checklist covering release scope selection, required verification, Python/JS package dry-run checks, artifact and secret hygiene, tagging notes, explicit publish decision gates, and rollback guidance. Keep `@memtrace/sdk` and `@memtrace/mcp-server` private by default; no automatic package publishing, `dist/` build pipeline, bundler, or declaration-emission workflow is added in R1.
- **Consequences:** Maintainers have a repeatable release process while publication remains an explicit future decision. Release closeout can verify benchmark/reproduce and hygiene without creating package registry side effects.
- **Sources:** `docs/release-checklist.md`, `README.md`, `docs/design/RELEASE_READINESS_PLAN.md` R1-C1/R1-C2.

### ADR-031: OpenTelemetry/OpenInference exporter starts as a default-off projection, not vendor-specific runtime logic

- **Date:** 2026-06-14
- **Status:** accepted; implemented through Segment 4 closeout
- **Context:** After R1, MemTrace has public onboarding, replay/report observability, SDK/MCP integration, provider/key ontology, governance, and reproducible benchmark coverage. The next recommended roadmap item is OpenTelemetry/OpenInference export so users can send MemTrace runtime evidence to external observability tools. Because telemetry is an egress surface and default quickstarts/CI must remain deterministic, directly adding LangSmith/Phoenix/Langfuse SDKs or always-on network export would increase dependency and leakage risk.
- **Decision:** Implement `docs/design/OTEL_OPENINFERENCE_EXPORTER_PLAN.md` as a default-off OTLP/OpenInference core exporter. The exporter is a read-only projection over MemTrace DTOs and persisted records: pure semantic builders create redacted spans/events, a pluggable exporter protocol supports noop/in-memory/JSONL/optional OTLP sinks, and `TelemetryService` provides best-effort runtime hooks plus a minimal read-only run export API. Runtime hooks may build/enqueue spans but must not synchronously perform network OTLP export; OTLP delivery must use OTel SDK batching or an internal best-effort queue. `memtrace.*` attributes are the stable contract, while OpenInference-compatible keys are emitted only where safe as a compatibility layer. Vendor-specific LangSmith/Phoenix/Langfuse bridges are deferred; they may consume OTLP/OpenInference output externally but are not direct dependencies in this slice.
- **Consequences:** Telemetry does not become a second source of truth and cannot change retrieval/gate/context-packing/benchmark semantics. Default local/dev/CI/reproduce behavior remains service-free and network-free. Segment 1 locks a stricter egress contract: `TelemetrySpan`/`TelemetryEvent` attributes exclude `None`, raw-content-like metadata keys (`prompt`, `query`, `content`, `raw_context`, `messages`, `context_blocks`, etc.) are redacted, benign token metric spellings are preserved, and optional-run-id builders fall back to stable record ids rather than a shared `unknown` trace. Segment 2 adds default-off exporter sinks and factory/service boundaries. Segment 3 wires runtime hooks after authoritative persistence, adds a minimal read-only `POST /v1/telemetry/export/runs/{run_id}` endpoint that returns counts/warnings only, and documents JSONL/OTLP usage plus vendor non-goals. Segment 3 detailed-review hardening keeps runtime hooks fail-open even when a fail-closed service is injected, avoids duplicate run/step lifecycle span ids, and applies existing `report_export` quota to the HTTP export surface. Segment 4 closeout verified targeted telemetry/runtime/API, affected runtime/API/observability, compileall, full pytest, benchmark/reproduce, release hygiene, and diff checks. CLI telemetry-export and richer access/backfill surfaces remain deferred. Future vendor bridges can be added behind the same exporter boundary after a separate bridge design.
- **Sources:** `docs/design/OTEL_OPENINFERENCE_EXPORTER_PLAN.md`, `docs/design/ROADMAP.md` §6, `.ai/PROJECT_STATE.md`, `.ai/IMPLEMENTATION_PLAN.md`.

### ADR-032: Keep static dashboard and RRF commits, but correct their boundaries

- **Date:** 2026-06-15
- **Status:** accepted
- **Context:** Two recent commits added a built-in `/v1/dashboard/ui` HTML viewer and an opt-in RRF retrieval mode. Neither changed default benchmark/reproduce semantics, but the naming and roadmap wording could imply that the full Phase 3-B React/TypeScript dashboard or Phase 5 advanced retrieval program had started.
- **Decision:** Do not revert the commits. Keep `/v1/dashboard/ui` as a built-in read-only static dashboard UI over existing read-only APIs, and keep RRF as a dependency-free, default-off Phase 5 micro-slice over the existing lexical + pgvector signals. Add boundaries: `MEMTRACE_RETRIEVAL_FUSION` validates only `linear` / `rrf`; vector-disabled RRF requests fall back to linear policy snapshots; tests lock exact RRF rank-sum behavior; ROADMAP/README/project memory explicitly state that React/TS `apps/web`, ES/OpenSearch, Neo4j, graph retrieval, task-intent ranking profiles, and broader Phase 5 remain future/trigger-gated work.
- **Consequences:** The usable work remains available without rewriting history, while future sessions should not treat the static HTML viewer as Phase 3-B completion or the RRF micro-slice as authorization to continue Phase 5 by default.
- **Sources:** `README.md`, `docs/design/ROADMAP.md`, `apps/api/app/config.py`, `apps/api/app/retrieval/controller.py`, `apps/api/tests/retrieval/test_retrieval_fusion.py`.
