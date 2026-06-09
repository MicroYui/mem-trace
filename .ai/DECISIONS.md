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
