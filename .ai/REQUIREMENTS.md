# Requirements

## Current Task

P2 is feature-complete (6/6 mvp.md §2.3 slices, incl. the config-gated LLM extraction pipeline) and committed. Phase 3-A backend observability is complete. **Context Compaction (ROADMAP §9) is complete through C5**, per `docs/design/CONTEXT_COMPACTION_PLAN.md`. **Failure-aware Negative Memory Injection I1-I6 are complete**, per `docs/design/FAILURE_AWARE_NEGATIVE_MEMORY_PLAN.md`: I1 gate three-way `accept / degrade / reject`; I2 runtime `NegativeEvidence` DTO + shared builder + packer `avoided_attempts`; I3 controller hot path negative-evidence injection; I4 inspect/replay/metrics sync; I5 benchmark/evaluator expansion with `case_10` safe failure learning + `case_11` sanitized destructive failure (36→44 benchmark result rows), explicit positive/negative block scoring, and acceptance `variant_2_learns_from_failure_without_repeating` + `variant_2_sanitizes_destructive_failure_without_leakage`; I6 docs/project-memory finalization. **Phase 3.5 SDK/LangGraph adapter/CLI is complete through S6**, per `docs/design/SDK_ADAPTER_PLAN.md`: S1 Core `event_source` passthrough, S0 Packaging & workspace skeleton, S2a Shared SDK contract + in-process backend, S2b HTTP backend + `/v1/runs/{run_id}/steps` route + backend isomorphism, S3 LangGraph adapter, S4 examples, S5 CLI, and S6 README/project-memory finalization are complete. S6 review also fixed HTTP/in-process `flush_session` isomorphism for arbitrary string `session_id` values by adding body-based `POST /v1/sessions/flush`. **ROADMAP §7 "完整 6 策略对比 + benchmark 落库" is complete through Task 11**, with the task-by-task plan at `docs/design/SIX_STRATEGY_BENCHMARK_PLAN.md`: `RetrievalStrategy` includes `long_context` and `variant_3`; exact six-strategy order/membership is guarded; `GateConfig` maps `long_context` to all-policies-off and `variant_3` to full `variant_2` gate/failure-learning plus `enable_reflection_rerank=True`; `RetrievalController` implements `long_context` include-all/unbounded budget and `variant_3` deterministic reflection-lite accepted-memory rerank; the benchmark runner snapshots/restores seed-time `access_count` before each strategy retrieval for fairness and uses an isolated workspace prefix for each persisted benchmark invocation so repeated `run_benchmark(..., repo=same_repo)` remains uncontaminated; `ALL_STRATEGIES` runs all six strategies; `case_12_reflection_retention` plus evaluator `reflection_retention_hit` expands the matrix to 12×6=72 with dashboard counts at 14 runs / 12 cases / 72 results; acceptance includes `variant_3_retains_high_value_memory_under_budget` and `long_context_shows_token_bloat` for 12/12 checks; benchmark runs persist into `eval_cases/eval_runs/eval_results` (reuse Phase 3-A schema, no migration) when a repository is supplied; dashboard benchmark summary surfaces `reflection_retention_hit_rate`; ROADMAP/README/project memory record that the future real Reflection/Forgetting scheduler must supersede deterministic reflection-lite. **Next implementation candidates:** ROADMAP §10 Provider Registry and §11 Controlled Memory Key Ontology. I7 compaction negative retained remains deferred.

Phase 3-A scope: Retrieval Replay, eval tables, Quality/Safety profiler metrics, expanded profiler phases, dashboard-table extension, and static JSON/Markdown/HTML observability reports. Use `docs/design/P3A_IMPLEMENTATION_PLAN.md` as the concrete implementation plan before touching code. **Issues 1-8 are complete**: access fidelity + eval persistence schema, side-effect-free retrieval trace pipeline, replay service + deterministic diff semantics, replay/observability APIs, Quality/Safety metrics + profiler phase expansion, dashboard table extension, JSON/Markdown/HTML observability reports, and full regression/benchmark/project-memory sync.

**Context Compaction (ROADMAP §9):** Issue-by-Issue plan lives at `docs/design/CONTEXT_COMPACTION_PLAN.md`. **C0, C1, C2, C3, C4, and C5 are complete**: `PackResult` + all `pack_context` callsite migrations landed behavior-preservingly; over-budget ordinary block drops now emit `compacted_constraints` + `compaction_notice` with protected-block truncation; budget compaction now persists durable `ContextCompactionLog` records surfaced through observability/replay; C3 adds the deterministic-rule plus config-gated OpenAI-compatible `SummarizerProvider` seam with validation/fallback; C4 adds config-gated in-flight rolling active-history summaries that inject protected `history_summary` blocks and persist `ContextCompactionLog(kind=history_summary)` without rerunning summarizers during replay; and C5 adds the retention-quality benchmark/report/replay loop (`case_9_over_budget_compaction`, compaction trigger/constraint retention/unsafe leakage/compression metrics, report Compaction section, replay drift coverage). The plan now also records deferred C6/I7 failure-aware negative retained facts as a future cross-feature design, with no current behavior change. Showcase assets (§12), Phase 3.5 SDK/LangGraph adapter/CLI (§6), and 6-strategy benchmark expansion/eval-table persistence (§7) are already done; remaining post-P3A priorities are provider/key-ontology work (§10/§11).

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
  memory/    writer.py, secrets.py, summarizer.py, resolver.py, candidate_buffer.py, llm_extractor.py
  retrieval/ similarity.py, gate.py, packer.py, profiler.py, controller.py
  benchmark/ cases.py, evaluator.py, runner.py
  storage/   orm.py, db.py, sql_repository.py
  api/       deps.py, routes.py
  demo/      run_demo.py
  config.py, main.py
apps/api/tests/   runtime/, memory/, retrieval/, benchmark/, api/, observability/, storage/ (full regression count changes as features land; see `.ai/PROJECT_STATE.md` latest verification)
migrations/       env.py, versions/0001_initial.py, versions/0002_pgvector.py, versions/0003_memory_superseded_by.py
```

## Standing Requirements From Design Docs

- Do not build a generic knowledge-base/RAG app as the main product.
- Treat memory as an Agent runtime component with trace, state, retrieval, gate, and profiler.
- Persist raw trace before derived memory extraction.
- Exclude failed/rolled-back/superseded branch memory from prompt context by default.
- Keep PostgreSQL as source of truth.
- Keep deterministic and demo-oriented through P1; defer LLM extraction, Neo4j, Celery, and full dashboard.
- Benchmark fairness: vector-only and gated variants must use identical seeded memory items.
