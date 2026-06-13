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

MVP (P0+P1+P2) is complete and committed. **Phase 3-A backend observability is complete (Issues 1-8, verified on 2026-06-10)**:

1. access fidelity + eval persistence schema; ✅ complete
2. side-effect-free retrieval trace pipeline; ✅ complete
3. replay service + diff semantics; ✅ complete
4. replay/observability APIs; ✅ complete
5. Quality/Safety metrics + profiler phase expansion; ✅ complete
6. dashboard table extension; ✅ complete
7. JSON/Markdown/HTML observability reports; ✅ complete
8. full regression, benchmark, and project-memory sync; ✅ complete (`uv run pytest -q` -> 145 passed; benchmark `acceptance.passed=true`)

The selected Context Compaction slice (ROADMAP §9) is complete through **C5**. Its Issue-by-Issue plan is `docs/design/CONTEXT_COMPACTION_PLAN.md`: C0 `PackResult`, C1 budget-aware `compacted_constraints` + `compaction_notice`, C2 durable `ContextCompactionLog` + observability/replay wiring, C3 rule/LLM `SummarizerProvider`, C4 config-gated rolling `history_summary`, and C5 retention-quality benchmark/report/replay/project-memory sync are implemented.

**Failure-aware Negative Memory Injection I1-I6 are complete** — Issue-by-Issue plan `docs/design/FAILURE_AWARE_NEGATIVE_MEMORY_PLAN.md`. I1-I6 cover gate three-way output, `NegativeEvidence` DTO/shared builder/packer `avoided_attempts`, controller hot-path wiring, inspect/replay/metrics sync, benchmark `case_10` safe + `case_11` sanitized destructive with evaluator positive/negative block split, and final docs/project-memory sync. That slice expanded the benchmark to 44 result rows and acceptance `variant_2_learns_from_failure_without_repeating` + `variant_2_sanitizes_destructive_failure_without_leakage`; existing `case_1..case_9` acceptance did not regress. I7 (compaction negative retained) is deferred.

**Phase 3.5 SDK/LangGraph adapter/CLI is complete** — Issue-by-Issue plan `docs/design/SDK_ADAPTER_PLAN.md`. **S1 Core `event_source` passthrough is complete and reviewed**: `WriteEventRequest.event_source` is accepted and `MemoryRuntime.write_event(...)` stamps `AgentEvent.event_source`, while omitted values preserve `None`. **S0 Packaging & workspace skeleton is complete**: `packages/python-sdk` is a uv workspace member with importable `memtrace_sdk` stubs, a CLI placeholder, and pytest discovery. **S2a Shared SDK contract + in-process backend is complete**: `memtrace_sdk.types` re-exports core runtime DTOs/enums; `Backend` Protocol and `InProcessBackend` cover the runtime hot path/read/observability surface; `MemTrace.in_process` / `MemTrace.in_memory` provide the unified client with default `event_source="sdk"`; missing singular resources map to SDK `NotFoundError`, invalid observability report requests map to `BadRequestError`, and empty-list reads remain `[]`. **S2b HTTP backend + missing `/v1/runs/{run_id}/steps` route + backend isomorphism is complete**: `HttpBackend` mirrors `/v1`, maps 404/400 to SDK errors, parses Pydantic models/lists, supports injected/owned `httpx.AsyncClient` lifecycle, and `MemTrace.http(...)` exposes the HTTP constructor. **S3 LangGraph adapter is complete**: `MemTraceLangGraphAdapter` provides `before_node` / `after_node` / `on_error` hooks and `wrap_node(...)` without hard-depending on langgraph, stamps `event_source="langgraph_adapter"`, and preserves negative-evidence semantics in failure tests. **S4 examples are complete**: `examples/simple_agent` demonstrates the SDK custom-loop Bun-vs-Node contrast, and `examples/langgraph_adapter` runs or skips cleanly when LangGraph is absent. **S5 CLI is complete**: the `memtrace` console script uses the SDK facade, requires `--http` for operational commands, supports one-shot `demo --in-process` / `demo --http`, emits JSON, maps SDK errors to exit codes, and stamps CLI writes as `event_source="cli"`. **S6 docs/project-memory finalization is complete**: README documents the Python SDK / HTTP / CLI three-entrypoint story, ROADMAP and `.ai` memory are synchronized, and S6 review fixed HTTP/in-process `flush_session` isomorphism for arbitrary string session ids. **ROADMAP §7 6-strategy benchmark expansion + eval-table persistence is also complete through Task 11** at `docs/design/SIX_STRATEGY_BENCHMARK_PLAN.md`. Heavy infra/advanced storage remain deferred.

## Selected Next Coding Task

**ROADMAP §13 Security & Consistency Hardening is complete through H18, using `docs/design/SECURITY_CONSISTENCY_HARDENING_PLAN.md` as the authoritative H1-H18 plan.** Final verification reached **397 passed, 1 skipped** plus benchmark/reproducibility `12/12` acceptance.

**Current selected coding plan:** none selected after completing `docs/design/PROVIDER_REGISTRY_KEY_ONTOLOGY_PLAN.md` for ROADMAP §10 Provider Registry + §11 Controlled Memory Key Ontology through P10. Choose the next roadmap target before coding: deferred I7 compaction-negative retention, real Reflection/Forgetting scheduler, TypeScript/MCP/IDE integrations, or Phase 4 governance.

### Provider Registry + Key Ontology Task Index

1. **P1 Provider capability metadata and registry core:** ✅ complete for provider-only infrastructure. Added `apps/api/app/providers/base.py`, `registry.py`, public exports, and provider registry tests. Registry snapshots are deterministic and non-secret; metadata is recursively frozen/sanitized.
2. **P2 Embedding providers:** ✅ complete for provider-only infrastructure. Added `DeterministicHashEmbeddingProvider` wrapping `stable_embedding(...)` and `OpenAIEmbeddingProvider` with request-shape/dimension validation. Deterministic helper and 256-dim pgvector assumption are preserved.
3. **P3 Registry factory + DI:** ✅ complete. Added embedding settings, `providers/factory.py`, deterministic registry helper, settings-based registry builder for extraction/summarizer/embedding/judge, and FastAPI `deps.py` wiring while preserving summarizer/extraction fallback behavior.
4. **P4 Runtime/retrieval integration:** ✅ complete. `MemoryRuntime` accepts and stores optional `provider_registry`, caches `ProviderKind.embedding`, prepares internal write-path embeddings through `_prepare_embedding(...)` with deterministic fallback, and preserves repository-level `ensure_embedding(...)` backfill for direct seeded memories/tests/backfills. Runtime and retrieval reject provider vectors that are not finite 256-dimensional numeric lists before falling back. `RetrievalController` embeds query vectors through `_embed_query(...)` with deterministic fallback; retrieval-policy-v2 includes retrieval-relevant provider snapshots via `build_policy_snapshot(..., provider_snapshot=...)`; replay policy drift reconstruction uses public `RetrievalController.provider_snapshot`; `AccessInspection` exposes flat `policy_version/policy_hash/policy_snapshot`; `judge` is excluded; explicit `summarizer_provider=` overrides are reflected in policy snapshots.
5. **P5 Controlled Memory Key Ontology core:** ✅ complete. Added `memory/key_ontology.py` with canonical keys, aliases, cardinality, default type/scope, safe free-form validation, prompt rendering, and wildcard default inheritance.
6. **P6 Writer/resolver ontology migration:** ✅ complete. Runtime key constants and resolver single-valued semantics now derive from ontology; runtime active-memory matching/supersede paths use canonical identity for historical aliases.
7. **P7 LLM extraction ontology normalization:** ✅ complete. Added `free_form` candidate field, rendered `_SYSTEM_PROMPT` from ontology, normalized aliases, enforced ontology type/scope defaults, and dropped unsafe/unknown keys.
8. **P8 Benchmark deterministic registry + conformance:** ✅ complete. `benchmark.runner._run_case(...)` forces `deterministic_provider_registry()` in benchmark runtimes; tests cover real-provider env isolation, non-secret provider snapshots, and retrieval-relevant provider metadata.
9. **P9 JudgeProvider contract only:** ✅ complete. Added `JudgeProvider` protocol and `NoopJudgeProvider` with registry-ready metadata without changing evaluator/hot-path behavior; P3 now registers it in `deterministic_provider_registry(...)`.
10. **P10 Full regression + docs/project-memory closeout:** ✅ complete. Affected provider/ontology/runtime/replay/benchmark/conformance suite, compile, deterministic benchmark, reproduce script, full pytest, ROADMAP §10/§11, and `.ai` memory are synced. Final review hardening additionally fixed settings-derived embedding providers to the fixed 256-dim pgvector contract, package-manager correction semantics (`npm -> bun`), ontology schema coverage, and summarizer provider factory wiring.

### Required Verification Pattern

- Each task starts with targeted RED tests, then minimal implementation, targeted GREEN tests, and affected regression.
- P10 final commands from the plan: provider/ontology suite; runtime/retrieval/replay suite; benchmark/conformance/reproducibility guard; `compileall`; full `uv run --extra dev pytest -q`; deterministic benchmark; `bash scripts/reproduce.sh`.
- P1/P2/P9 provider-only slice, P3 factory/DI, P4 runtime/retrieval/replay provider integration, P5-P7 ontology/writer/resolver/LLM extraction migration, P8 benchmark deterministic registry/conformance, and P10 closeout followed this pattern and are complete. Latest P8/P10/final-review verification: RED provider-isolation test **1 failed / 1 passed / 22 deselected**, GREEN **2 passed, 22 deselected**; affected provider/benchmark/replay suite **70 passed**; strategy conformance provider snapshot suite **13 passed**; P10 closeout affected suite **312 passed**; final affected provider/ontology/runtime/retrieval/replay/benchmark/conformance suite **322 passed**; compile passed; deterministic benchmark passed; reproduce printed `acceptance.passed=true (12/12 checks true)`; full regression **460 passed, 1 skipped**. Current next actionable task is to select the next roadmap target.

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
