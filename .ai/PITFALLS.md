# Pitfalls

## Risks

- Architecture breadth can consume the project before the state-aware memory loop works.
- LLM extraction can pollute memory and make tests nondeterministic if added too early.
- Multiple stores introduce consistency and deployment burden before the MVP proves value.
- A dashboard can hide weak runtime correctness.
- Benchmark claims will be weak unless vector-only and gated variants use identical seeded memory items.

## Likely Implementation Traps

- Attaching recovery nodes under failed nodes; recovery should attach to the failed node's parent.
- Sorting events only by `created_at`; use run-local `sequence_no`.
- Treating `branch_status` and lifecycle `status` as the same field.
- Letting failed/rolled-back memory enter prompt because semantic relevance is high.
- Making profiler writes part of the critical path.
- Physically deleting superseded or failed memories and losing provenance.
- Turning P0 regex memory writing into an unbounded NLP project.
- Adding Neo4j/ES/Celery before PostgreSQL-only correctness is proven.

## P0 Implementation Findings (encountered & handled)

- **Superseded/archived memory leaking into prompt.** Filtering only `deleted` at the candidate stage let user-corrected constraints (status `superseded`) survive and get injected when context-merge order happened to favor them. Fixed by an explicit `_RETRIEVABLE_STATUSES` allowlist (`active/pinned/conflicted/quarantined`) in the retrieval controller. Lesson: lifecycle `status` must be filtered at retrieval, not only relied on at merge time.
- **branch_status vs lifecycle status are two independent gates.** A memory can be `branch_status=completed` yet `status=superseded` (and vice versa). Both must be checked: branch validity in the gate, lifecycle validity at candidate selection. Confusing them silently injects stale data.
- **Single-filter retrieval path is fragile.** Lifecycle filtering currently lives only in the candidate stage. If a second retrieval path is added (e.g. pgvector KNN in P1), it must reapply the same `_RETRIEVABLE_STATUSES` filter or stale memory reappears.
- **Benchmark fairness depends on workspace isolation in the demo.** Sharing one workspace across strategies on the SQL backend accumulated duplicate candidates across runs and skewed counts. Fixed by per-strategy unique workspaces; keep seeded memory sets identical and isolated.
- **Profiler latency can read 0ms.** Sub-millisecond phases round to 0 in reports; this is expected for the in-memory path and not a measurement bug.

## P1 Implementation Findings (encountered & handled)

- **Benchmark case definitions are not enough without a runner.** `cases.py` and `evaluator.py` seed/evaluate data, but MVP requires actual JSON/Markdown report artifacts. Add/keep a runner that executes every case x strategy and writes `benchmark_report.md` + `benchmark_results.json`.
- **Benchmark reports are not the same as benchmark persistence.** If a reviewer asks for Task 14 persistence, ensure the runner can write `benchmark_cases` + `benchmark_results` via the repository; report files alone are not enough.
- **Generated benchmark reports are ignored.** `reports/` is intentionally ignored; when checking P1 completeness, run `python -m app.benchmark.runner --output-dir reports` rather than looking for tracked report files.
- **Active-path summaries must exclude failed progress.** The `active_path` context block should be built from nodes accepted by `active_path_node_ids`; otherwise rolled-back failed summaries can re-enter prompts as state context even when memory gate rejects failed-branch memories.
- **Basic dashboard tables should stay table-shaped.** P1 needs inspectable rows, not a full dashboard app. Keep `/v1/dashboard/tables` focused on runs/access/profile/benchmark rows and avoid React/UI scope creep before P2.
- **variant_1 sharing baseline_1's contamination rate is correct, not a bug.** mvp.md §10.1 defines variant_1 as state-aware rerank that only *downweights* failed branches (no hard reject). A downweighted failed memory can still pass top-k into context, so variant_1 may show the same `failed_branch_contamination_rate` as baseline_1; only variant_2 (hard+risk gate) drives it to 0. Do not "fix" variant_1 to reject — that would collapse it into variant_2.
- **cross_workspace_leakage is 0 for every strategy by construction.** Candidate retrieval is workspace-scoped, so even baseline_1 cannot pull another workspace's memory. This satisfies the §10.5 security invariant but means case_3 cannot show a baseline-vs-variant *quality* gap; it proves the permission filter, not a ranking improvement.
- **Encode §10.5 pass criteria as a runner self-check.** Metrics alone don't assert acceptance. The runner emits an `acceptance` block (criteria 1-3) asserted by a unit test; criteria 4-6 (project constraints, profiler fields, access inspection) are covered by existing unit tests, not the benchmark.
- **Keep `__init__.py` in every test package.** New `tests/benchmark/` and `tests/api/` initially lacked `__init__.py` while sibling packages had them; add them to match collection behavior.

## Environment Pitfalls

- **pgvector restored (2026-06-09).** The `pgvector/pgvector:pg16` image is now available, so semantic retrieval is back: `embedding_vector` is `vector(256)` with an HNSW cosine index. Pitfalls learned: (1) PG15 data volumes are incompatible with the pg16 image — switching requires `docker-compose down -v` (destructive, recreates the volume); (2) this env has standalone `docker-compose` only (the `docker compose` subcommand errors out); (3) alembic must run from the repo root (where `alembic.ini` lives) with `PYTHONPATH=apps/api` so `app.*` imports resolve; (4) embeddings MUST use a process-stable hash (blake2b), not Python's salted built-in `hash`, or persisted vectors won't match query vectors across processes.

## Over-Engineering Warnings

- Defer multimodal ingestion, full knowledge graph, complex reflection, trained gate, and enterprise governance.
- Prefer JSON/Markdown report over full dashboard until gate/state workflow is stable.
- Keep P0 memory types and rules small enough to test exhaustively.
- Do not implement generic RAG features unless they support agent runtime behavior.

## Testing Pitfalls

- Testing only happy-path retrieval; include failed branch, stale, secret, workspace mismatch, and tool-sensitive cases.
- Using LLM generation as the only evaluator; also test context pollution before generation.
- Forgetting negative project constraints (`should not use Node.js`) when packing positive constraints (`uses Bun`).
- Not verifying gate logs for every candidate, including rejections.
- Not checking profiler does not block or fail the main request.
- Context compaction tests must cover protected-block budget pressure: if a protected block consumes the full budget while ordinary blocks are dropped, the packer must still make room for a real `compaction_notice` block (not merely set `PackResult.notice`). Also verify config knobs are wired through every pack_context callsite (hot path, inspect, replay), not only declared in `Settings`.
- Durable compaction logs must be written only after `MemoryAccessLog.access_id` exists. Keep the `PendingCompactionLog -> RetrievalPipelineTrace.pending_compaction_logs -> RetrievalController._persist_trace -> ContextCompactionLog` path single-sourced; do not add second write sites in packer, runtime, replay, or reports.
- C3 summarizer provider validation is intentionally conservative: LLM retained facts must be drawn from structured `must_retain_facts` and must cover every required full identity (`key/value/source_memory_id/provenance.run_id/provenance.step_id/provenance.event_id/provenance.state_node_id`), not only key/value. Do not parse free-form block text as allowed facts because negated/stale/risky text can contain `key=value` strings. Recompute `post_tokens` locally (never trust LLM token counts), require top-level source id sets to be preserved, reject invented or misbound source ids/provenance, and make any HTTP/JSON/schema/validation failure fall back to `RuleSummarizerProvider` with `provider=fallback_rule`. When sorting/deduping retained facts, normalize nullable provenance fields for ordering; Python cannot compare `None` and `str`. C4 replay now reads persisted `history_summary` compaction logs and must never rerun the provider. C4 has two filter sets: raw active-path events skip failed/rolled_back nodes, redacted secrets, and risky tool results; retained `MemoryItem` facts still require retrievable lifecycle status, active branch, non-stale, non-secret, non-risky provenance.
