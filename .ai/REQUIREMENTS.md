# Requirements

## Current Task

P2 is feature-complete (6/6 mvp.md §2.3 slices, incl. the config-gated LLM extraction pipeline) and committed. Phase 3-A backend observability is complete. **Context Compaction (ROADMAP §9) is complete through C5 plus C6/I7 retained-negative metadata closeout**, per `docs/design/CONTEXT_COMPACTION_PLAN.md`. **Failure-aware Negative Memory Injection I1-I7 are complete**, per `docs/design/FAILURE_AWARE_NEGATIVE_MEMORY_PLAN.md` and `docs/design/I7_COMPACTION_NEGATIVE_RETENTION_PLAN.md`. **Phase 3.5 SDK/LangGraph adapter/CLI is complete through S6**, per `docs/design/SDK_ADAPTER_PLAN.md`. **ROADMAP §7 "完整 6 策略对比 + benchmark 落库" is complete through Task 11**, with six strategies, eval-table persistence, dashboard surfacing, and reproducibility closeout; I7 has since expanded the deterministic benchmark to **13 cases × 6 strategies = 78 rows** and `acceptance.passed=true (13/13 checks true)`. **ROADMAP §13 Security & Consistency Hardening is complete through H18, post-review hardened, and verified with full regression**. **ROADMAP §10 Provider Registry + §11 Controlled Memory Key Ontology is complete through P10**: provider factory/DI, runtime registry injection, retrieval-policy-v2 provider snapshots, AccessInspection flat policy fields, runtime/retrieval embedding provider fallback, repository backfill preservation, replay policy drift using public `RetrievalController.provider_snapshot`, controlled key ontology core, writer/resolver/runtime ontology migration, LLM extraction ontology normalization/prompt rendering, benchmark deterministic registry isolation, provider snapshot conformance, and final closeout are implemented. **Current implementation target:** Phase 4 async/lifecycle/governance via `docs/design/PHASE4_PLATFORM_PLAN.md`, starting with P4-A async foundation while preserving deterministic local/benchmark defaults.

### I7 Compaction Negative Retention Requirements (completed plan)

- Preserve failure-aware negative lessons through compaction metadata, replay, observability, reports, trace bundles, and benchmark acceptance without changing positive prompt-context semantics.
- Add `RetainedNegativeEvidence` as a dedicated safe metadata DTO derived only from `NegativeEvidence.safe_text`; do not read raw `MemoryItem.content` during retained conversion.
- Add `ContextCompactionLog.retained_negative_evidence` / `PendingCompactionLog.retained_negative_evidence` as a dedicated field; do not overload positive `retained_facts`.
- Persist the new field as JSONB with explicit PostgreSQL default `sa.text("'[]'::jsonb")`; SQL writes use `model_dump(mode="json")`, SQL reads use `RetainedNegativeEvidence.model_validate(...)`, and old `None`/missing rows map to `[]`.
- Set the I7 Alembic migration `down_revision` to the actual current head revision id from `migrations/versions`, not an inferred filename prefix.
- Keep `risk_kind` tolerant (`str | None`) or normalize known aliases without validation crashes.
- Packer retention only processes dropped standard negative-evidence prompt blocks where `block.type == "avoided_attempts"` **and** `block.source == "negative_evidence"`; retained metadata must never force the block into prompt context. Retained negative lookup must use `negative_by_memory_id` / `negative_by_state_reason`, not accepted-only `memory_by_id`, and `build_negative_evidence_block(...)` should preserve `source_state_node_id` via fallback provenance when `ev.provenance` is absent.
- Replay reads retained negative evidence directly from compaction logs, maps old rows to `[]`, and must not infer I7-era behavior from retrieval policy snapshots.
- Benchmark `case_13_compaction_retains_negative_lesson` verifies metadata retention, zero positive contamination, zero unsafe leakage, and unchanged task success from existing positive/project context; it does not imply retained metadata entered the prompt. ✅
- Closeout includes affected regression, compile, full pytest, deterministic benchmark, reproduce script, docs/.ai sync, and unsafe-marker checks over generated report outputs. ✅
- Do not include Phase 4 async/lifecycle/governance or TS/MCP/IDE integration work in this I7 slice; those are tracked separately in `docs/design/PHASE4_PLATFORM_PLAN.md` and `docs/design/INTEGRATIONS_PLAN.md`.
- **I7.1-I7.6 status (2026-06-14):** complete. The retained-negative DTO/conversion, dedicated compaction-log Pydantic field, SQL ORM JSONB column, Alembic migration `0007_i7_retained_negative_evidence`, SQL serialization/deserialization, I7.3 packer metadata retention for dropped standard `avoided_attempts` blocks, I7.4 replay/metrics/reports/trace-bundle surfacing, I7.5 benchmark `case_13_compaction_retains_negative_lesson`, dashboard benchmark-summary parity, and I7.6 closeout verification/docs sync are implemented. Current benchmark is 13 cases × 6 strategies = 78 rows and `bash scripts/reproduce.sh` reports `acceptance.passed=true (13/13 checks true)`.

### Provider Registry + Key Ontology Requirements (selected plan)

- Add a unified `ProviderRegistry` with stable non-secret `ProviderCapabilities` snapshots for extraction, embedding, summarizer, and contract-only judge providers. ✅ P1 base registry/snapshot layer complete for provider-only infrastructure.
- Keep deterministic behavior as the default: deterministic hash embedding and rule summarizer remain the no-env path; real providers are config-gated and degrade at runtime call sites.
- Add deterministic and OpenAI-compatible embedding providers without changing the pgvector column dimension (`embedding_vector` remains 256-dimensional) and without removing `stable_embedding(...)` or repository fallback backfill. ✅ P2 provider classes complete; ✅ P4 runtime/retrieval embedding provider integration complete while repository fallback backfill remains unchanged.
- Build providers through `providers/factory.py`; keep `providers/registry.py` dependency-light and free of settings/provider-implementation imports. ✅ P3 complete for factory/DI.
- Inject the registry into `MemoryRuntime` while preserving existing explicit `extraction_provider=` and `summarizer_provider=` arguments for compatibility during this slice. ✅ P3/P4 front-half complete for registry injection.
- Bump retrieval policy snapshots to `retrieval-policy-v2`; include only retrieval-relevant non-secret provider snapshots (`embedding`, `summarizer`) and reflect explicit provider overrides. Exclude `judge` from retrieval policy hashes. ✅ P4 complete for observability/policy metadata and runtime/retrieval embedding hot paths.
- Add `app.memory.key_ontology` as the single source for canonical keys, aliases, cardinality, default `MemoryType`/`MemoryScope`, free-form validation, prompt rendering, and candidate normalization. ✅ P5 complete.
- Migrate `writer`, `resolver`, and `llm_extractor` away from duplicated key/cardinality/prompt rules and into ontology-derived behavior. ✅ P6/P7 complete for writer/resolver/runtime identity and LLM extraction boundary.
- Normalize LLM extraction aliases; drop unknown non-free-form keys; allow only explicit safe free-form keys; reject secret-like or wildcard concrete free-form keys. ✅ P7 complete.
- Force deterministic provider registry inside the benchmark runner even when real-provider environment variables are set. ✅ P8 complete.
- Use TDD per plan task and update `.ai/PROJECT_STATE.md` plus `docs/design/ROADMAP.md` §10/§11 after each completed task. ✅ P10 closeout complete.

### Provider Registry + Key Ontology Progress Completed (P1/P2/P9/P3/P4/P5/P6/P7/P8/P10)

- `app.providers.base` now defines `ProviderKind`, `ProviderCapabilities`, and an `EmbeddingProvider` protocol. Capability snapshots are deterministic, metadata is recursively frozen, and key/value secret-like metadata is removed before snapshotting.
- `app.providers.registry` now defines the dependency-light `ProviderRegistry`; `app.providers.factory` now owns settings-based construction and deterministic registry helpers.
- `app.providers.embedding` now defines `DeterministicHashEmbeddingProvider` and `OpenAIEmbeddingProvider`; `stable_embedding(...)` remains the deterministic primitive and pgvector dimension remains unchanged. `MemoryRuntime._prepare_embedding(...)` and `RetrievalController._embed_query(...)` use the embedding provider first and fall back to `stable_embedding(...)` on failure; `Repository.add_memory(...)` still performs deterministic `ensure_embedding(...)` backfill for direct seeded memories/tests/backfills.
- `app.providers.judge` now defines the contract-only `JudgeProvider` and `NoopJudgeProvider`; no evaluator/hot-path behavior changed.
- `app.memory.key_ontology` now defines canonical memory key specs, aliases (`project.pkg_manager` -> `project.package_manager`, `project.js_runtime` -> `project.runtime`), single/multi cardinality, default memory type/scope, safe free-form validation, and stable LLM prompt rendering.
- `writer`, `resolver`, and `MemoryRuntime` now use ontology constants/cardinality/canonical identity instead of duplicated raw-key semantics; historical alias rows participate in conflict/supersede matching with canonical incoming keys, package-manager facts (`npm/pnpm/yarn`, and correction paths such as `npm -> bun`) no longer overwrite runtime facts, and same-value alias survivors are promoted to canonical keys.
- `llm_extractor` now exposes `ExtractionCandidate.free_form`, renders its system prompt from ontology, canonicalizes alias keys in `build_results(...)`, drops unknown non-free-form keys, rejects unsafe free-form keys, and applies ontology default type/scope to controlled, wildcard, and arbitrary safe free-form specs.
- `benchmark.runner._run_case(...)` now injects `deterministic_provider_registry()` for every benchmark runtime, so real extraction/summarizer/embedding env vars cannot affect reproducibility; conformance asserts access policy provider snapshots are non-secret, contain only `embedding`/`summarizer`, and exclude `judge` from retrieval policy hashes.
- Current verified commands: P8 RED/GREEN completed; affected provider/benchmark/replay suite -> **70 passed**; strategy conformance provider snapshot suite -> **13 passed**; P10 closeout affected provider/ontology/runtime/retrieval/replay/benchmark/conformance suite -> **312 passed**. Final review hardening fixed settings-derived embedding providers to the fixed 256-dim pgvector contract, package-manager correction semantics (`npm -> bun`), ontology schema coverage, and summarizer provider factory wiring; final affected suite -> **322 passed**; compile `uv run --extra dev python -m compileall -q apps/api/app packages/python-sdk/src examples` -> passed; deterministic benchmark passed; `bash scripts/reproduce.sh` printed `acceptance.passed=true (12/12 checks true)`; full `uv run --extra dev pytest -q` -> **460 passed, 1 skipped**.

Phase 3-A scope: Retrieval Replay, eval tables, Quality/Safety profiler metrics, expanded profiler phases, dashboard-table extension, and static JSON/Markdown/HTML observability reports. Use `docs/design/P3A_IMPLEMENTATION_PLAN.md` as the concrete implementation plan before touching code. **Issues 1-8 are complete**: access fidelity + eval persistence schema, side-effect-free retrieval trace pipeline, replay service + deterministic diff semantics, replay/observability APIs, Quality/Safety metrics + profiler phase expansion, dashboard table extension, JSON/Markdown/HTML observability reports, and full regression/benchmark/project-memory sync.

**Context Compaction (ROADMAP §9):** Issue-by-Issue plan lives at `docs/design/CONTEXT_COMPACTION_PLAN.md`. **C0, C1, C2, C3, C4, C5, and C6/I7 are complete**: `PackResult` + all `pack_context` callsite migrations landed behavior-preservingly; over-budget ordinary block drops now emit `compacted_constraints` + `compaction_notice` with protected-block truncation; budget compaction now persists durable `ContextCompactionLog` records surfaced through observability/replay; C3 adds the deterministic-rule plus config-gated OpenAI-compatible `SummarizerProvider` seam with validation/fallback; C4 adds config-gated in-flight rolling active-history summaries that inject protected `history_summary` blocks and persist `ContextCompactionLog(kind=history_summary)` without rerunning summarizers during replay; C5 adds the retention-quality benchmark/report/replay loop (`case_9_over_budget_compaction`, compaction trigger/constraint retention/unsafe leakage/compression metrics, report Compaction section, replay drift coverage); and C6/I7 preserves dropped negative lessons as separate retained metadata without changing prompt semantics. Showcase assets (§12), Phase 3.5 SDK/LangGraph adapter/CLI (§6), 6-strategy benchmark expansion/eval-table persistence (§7), Security & Consistency Hardening (§13), Provider Registry / Controlled Memory Key Ontology (§10/§11), and I7 are already done.

**Context Compaction maintenance rule:** after completing each Issue in `docs/design/CONTEXT_COMPACTION_PLAN.md` §4, update `.ai/PROJECT_STATE.md` and tick or annotate the corresponding `docs/design/ROADMAP.md` / `docs/design/CONTEXT_COMPACTION_PLAN.md` checkbox/sub-checkbox.

## Coding Readiness

- **P0 production code:** Done and verified (45 pytest passing at P0; demo proves contamination elimination).
- **P1 production code:** Done and verified locally (50 pytest passing; benchmark report with §10.5 acceptance self-check generated; benchmark persistence and dashboard tables covered).

## P0 Outcome (Done)

The full P0 hot path from `mvp.md` is implemented:

- MemoryRuntime facade: `start_run`, `start_step`, `write_event`, `finish_step`, `rollback_branch`, `retrieve_context`, plus read models and `inspect_access`.
- Execution state tree (`root -> step/recovery`) with correct recovery placement and `failure_reason` preserved across rollback.
- Run-local monotonic `sequence_no`; every event bound to `step_id` + `state_node_id`.
- Rule-based memory writer (project +/- constraints, explicit correction supersede, tool_evidence, working_state) + secret redaction.
- Lexical retrieval, three-layer admission gate (hard/risk/soft), structured context packer, phase-aware profiler (retrieval/gate/context_packing).
- PostgreSQL source of truth via SQLAlchemy 2.0 async + Alembic; in-memory repo for tests; same `Repository` protocol for both.
- FastAPI endpoints for all `mvp.md` §3.1 routes + `/health`.
- Deterministic Bun-vs-Node demo emitting `reports/demo_report.{md,json}`.

P0 acceptance criteria in `mvp.md` §13 are satisfied; see `.ai/PROJECT_STATE.md` for the verification snapshot.

## P1 Outcome (Done Locally)

Per `mvp.md` §2.2 and §10, the P1 scope is now implemented:

- Active-path context builder and `active_path` context block.
- Generalized failed/rolled-back branch isolation through active-path filtering and `variant_2` gate rejection.
- The 4 required benchmark cases: project preference, failed branch isolation, workspace isolation, tool-call safety.
- `benchmark_report.md` and `benchmark_results.json` generated by `python -m app.benchmark.runner --output-dir reports` with metrics from `mvp.md` §10.2.
- Benchmark cases/results can be persisted through the repository into `benchmark_cases` and `benchmark_results` tables.
- Basic dashboard table API is exposed at `GET /v1/dashboard/tables`.
- P1 benchmark acceptance observed: `variant_2.failed_branch_contamination_rate=0.0`, `baseline_1.failed_branch_contamination_rate=0.25`, `cross_workspace_leakage_rate=0.0`, `tool_sensitive_blocked_rate=1.0`.
- pgvector semantic retrieval is restored (`pgvector/pgvector:pg16`): hybrid lexical + deterministic-vector cosine, `vector(256)` column with an HNSW index (migration `0002_pgvector`).

### P1 Non-Goals

- No LLM extraction pipeline, dedup/merge, conflict resolver (P2).
- No Neo4j, Elasticsearch, Celery, React dashboard, TypeScript SDK (deferred).

## Implemented Module Map

```text
apps/api/app/
  runtime/   models.py, repository.py, state_tree.py, memory_runtime.py
  memory/    writer.py, secrets.py, summarizer.py, summarizer_provider.py, resolver.py, candidate_buffer.py, llm_extractor.py
  retrieval/ similarity.py, gate.py, packer.py, profiler.py, controller.py, negative_evidence.py, policy.py
  benchmark/ cases.py, evaluator.py, runner.py
  observability/ metrics.py, replay.py, reports.py
  storage/   orm.py, db.py, sql_repository.py
  api/       deps.py, routes.py
  demo/      run_demo.py
  config.py, main.py
apps/api/tests/   runtime/, memory/, retrieval/, benchmark/, api/, observability/, storage/, conformance/ (full regression count changes as features land; see `.ai/PROJECT_STATE.md` latest verification)
migrations/       env.py, versions/0001_initial.py, versions/0002_pgvector.py, versions/0003_memory_superseded_by.py, versions/0004_phase3a_observability.py, versions/0005_context_compaction.py, versions/0006_security_consistency_hardening.py
packages/python-sdk/   src/memtrace_sdk/ (SDK facade/backends/CLI/LangGraph adapter) and tests/
```

## Standing Requirements From Design Docs

- Do not build a generic knowledge-base/RAG app as the main product.
- Treat memory as an Agent runtime component with trace, state, retrieval, gate, and profiler.
- Persist raw trace before derived memory extraction.
- Exclude failed/rolled-back/superseded branch memory from prompt context by default.
- Keep PostgreSQL as source of truth.
- Keep deterministic and demo-oriented through P1; defer LLM extraction, Neo4j, Celery, and full dashboard.
- Benchmark fairness: vector-only and gated variants must use identical seeded memory items.
