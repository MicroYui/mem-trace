# Requirements

## Current Task

P2 is feature-complete (6/6 mvp.md §2.3 slices, incl. the config-gated LLM extraction pipeline) and committed. Phase 3-A backend observability is complete. **Context Compaction (ROADMAP §9) is complete through C5**, per `docs/design/CONTEXT_COMPACTION_PLAN.md`. **Failure-aware Negative Memory Injection I1-I6 are complete**, per `docs/design/FAILURE_AWARE_NEGATIVE_MEMORY_PLAN.md`. **Phase 3.5 SDK/LangGraph adapter/CLI is complete through S6**, per `docs/design/SDK_ADAPTER_PLAN.md`. **ROADMAP §7 "完整 6 策略对比 + benchmark 落库" is complete through Task 11**, with six strategies, 12 cases × 6 strategies = 72 rows, eval-table persistence, dashboard surfacing, and reproducibility closeout. A full six-module code review (2026-06-13) fixed four security/consistency defects; **ROADMAP §13 Security & Consistency Hardening is now complete through H18, post-review hardened, and verified with full regression**: H1-H3 security closure; H4 backend error isomorphism; H5 atomic event sequence allocation+insert with SQL uniqueness aligned to `uq_event_run_seq`; H6 unified retrieval-timeout persistence; H7 deterministic gate-log/replay tie-breaks; H8 ORM/migration compaction-index alignment; H9 retrieval policy snapshot + policy drift classification; H10 runtime conformance suite; H11 independent token estimation + CJK-safe truncation + token-estimator policy snapshot; H12 summarizer provenance validation with exact top-level source preservation across LLM/rule fallback; H13 explicit side-effect-free state-machine boundary errors; H14 whole-memory benchmark snapshot/restore with created/missing-memory guards; H15 migration compatibility policy tests; H16 redacted trace bundle export/validation; H17 deterministic dogfood harnesses; H18 docs/project-memory closeout. Post-review fixes also redacted compacted retained-fact keys, made auth reject non-ASCII invalid credentials with 403, closed cross-run step/run isolation gaps, added deterministic candidate tie-breaks, extended trace-bundle event-field redaction, and made summarizer top-level source preservation exact. Latest full regression: `uv run --extra dev pytest -q` -> **397 passed, 1 skipped**; benchmark/reproducibility remain `acceptance.passed=true (12/12 checks true)`. **Current selected implementation target:** next recommended area is ROADMAP §10 Provider Registry + §11 Controlled Memory Key Ontology, unless explicitly selecting deferred I7 compaction negative retained facts first.

Phase 3-A scope: Retrieval Replay, eval tables, Quality/Safety profiler metrics, expanded profiler phases, dashboard-table extension, and static JSON/Markdown/HTML observability reports. Use `docs/design/P3A_IMPLEMENTATION_PLAN.md` as the concrete implementation plan before touching code. **Issues 1-8 are complete**: access fidelity + eval persistence schema, side-effect-free retrieval trace pipeline, replay service + deterministic diff semantics, replay/observability APIs, Quality/Safety metrics + profiler phase expansion, dashboard table extension, JSON/Markdown/HTML observability reports, and full regression/benchmark/project-memory sync.

**Context Compaction (ROADMAP §9):** Issue-by-Issue plan lives at `docs/design/CONTEXT_COMPACTION_PLAN.md`. **C0, C1, C2, C3, C4, and C5 are complete**: `PackResult` + all `pack_context` callsite migrations landed behavior-preservingly; over-budget ordinary block drops now emit `compacted_constraints` + `compaction_notice` with protected-block truncation; budget compaction now persists durable `ContextCompactionLog` records surfaced through observability/replay; C3 adds the deterministic-rule plus config-gated OpenAI-compatible `SummarizerProvider` seam with validation/fallback; C4 adds config-gated in-flight rolling active-history summaries that inject protected `history_summary` blocks and persist `ContextCompactionLog(kind=history_summary)` without rerunning summarizers during replay; and C5 adds the retention-quality benchmark/report/replay loop (`case_9_over_budget_compaction`, compaction trigger/constraint retention/unsafe leakage/compression metrics, report Compaction section, replay drift coverage). The plan now also records deferred C6/I7 failure-aware negative retained facts as a future cross-feature design, with no current behavior change. Showcase assets (§12), Phase 3.5 SDK/LangGraph adapter/CLI (§6), 6-strategy benchmark expansion/eval-table persistence (§7), and Security & Consistency Hardening (§13) are already done; the active post-P3A priority can now move to provider/key-ontology work (§10/§11).

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
