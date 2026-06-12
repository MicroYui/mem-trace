# Project State

- **Current state:** P0 + P1 complete; **P2 complete (6/6)** and committed. **Phase 3-A is complete (Issues 1-8)**. **Showcase assets + reproducibility baseline are complete**. **Context Compaction C0-C5 are complete**. **Failure-aware Negative Memory Injection I1-I6 are complete** and I7 compaction negative retained remains deferred. **Phase 3.5 SDK/LangGraph adapter/CLI is complete through S6** per `docs/design/SDK_ADAPTER_PLAN.md`. **ROADMAP §7 "完整 6 策略对比 + benchmark 落库" is complete through Task 11 full regression/reproducibility/project-memory sync.**
- **Last updated:** 2026-06-12 (Completed detailed Task 11 review and hardening. The review found and fixed one P1 repeatability defect: persisted `run_benchmark(..., repo=same_repo)` invocations reused fixed `bench_ws_{index}` workspaces, so the second run could read prior-run memories and fail acceptance; `run_benchmark` now uses an isolated workspace prefix per persisted invocation. Final six-strategy review also fixed two P2 edge defects: `long_context` no longer relies on a fixed `1_000_000` token sentinel and instead expands to the exact pre-compaction budget only when needed, and replay original-view reconstruction now applies the same `variant_3` reflection-lite rerank as the hot path. The repeatability test now compares deterministic summary fields while excluding timing-only latency fields. Stale next-action references in `.ai/REQUIREMENTS.md`, `docs/design/ROADMAP.md`, `README.md`, and the plan background wording were refreshed; `.ai/PITFALLS.md` records the workspace-isolation, long-context sentinel, replay-rerank, and latency-summary traps. Verification after final fixes: `uv run --extra dev pytest apps/api/tests/retrieval/test_retrieval_flow.py::test_long_context_preserves_scope_lifecycle_logs_and_unbounded_budget apps/api/tests/observability/test_replay.py::test_variant_3_replay_reconstructs_reflection_reranked_context -q` -> **2 passed**; `uv run --extra dev pytest apps/api/tests/retrieval/ apps/api/tests/observability/test_replay.py -q` -> **100 passed**; `uv run --extra dev pytest apps/api/tests/benchmark/test_runner.py apps/api/tests/api/test_dashboard.py apps/api/tests/runtime/test_models_strategy.py -q` -> **24 passed**; `uv run --extra dev python -m compileall -q apps/api/app && uv run --extra dev pytest -q` -> **305 passed**; `uv run python -m app.benchmark.runner --output-dir reports && bash scripts/reproduce.sh` -> `acceptance.passed=true (12/12 checks true)`; six-strategy report-shape check printed `OK {'baseline_0': 0.0, 'long_context': 44.1667, 'baseline_1': 25.4167, 'variant_1': 25.4167, 'variant_2': 26.8333, 'variant_3': 26.5}`. Next candidates are ROADMAP §10/§11 Provider Registry / Controlled Memory Key Ontology; deterministic reflection-lite remains a placeholder to be superseded by the real §3.2 Reflection/Forgetting scheduler.)

## Doc Reorg (2026-06-10)

- The five top-level design/plan docs were moved into `docs/design/`: `docs/design/architecture.md`, `docs/design/draft.md`, `docs/design/mvp.md`, `docs/design/P3A_IMPLEMENTATION_PLAN.md`, `docs/design/ROADMAP.md` (via `git mv`, history preserved).
- `README.md`, `AGENTS.md`, and `CLAUDE.md` stay at the repo root.
- All path-style index references were updated: `AGENTS.md`, `README.md`, the moved docs' internal links, `.ai/` memory files, and both skill mirrors (`.agents/skills/` + `.claude/skills/`: `sync-design-docs`, `review-agent-architecture`, `resume-project`).
- Source `.py` "section citation" comments (e.g. `mvp.md §5.2`) were intentionally left unchanged — they cite a doc name + section, not a file path.

## Current Goal

Post-P3A **Context Compaction (ROADMAP §9)** is complete through C5 and **Failure-aware Negative Memory Injection** is complete through I6. I7 (compaction negative retained) remains deferred.

**Completed slice:** ROADMAP §7 **6-strategy benchmark expansion + eval-table persistence** (`docs/design/SIX_STRATEGY_BENCHMARK_PLAN.md`) is complete through Task 11. `RetrievalStrategy` exposes `long_context` and `variant_3`; `GateConfig` exposes the strategy config contract; controller `long_context` performs include-all candidate stuffing with dynamically unbounded packing (expanding to exact pre-compaction tokens when needed, not a fixed sentinel); the benchmark runner restores seed-time `access_count` before each strategy for fairness; controller `variant_3` applies deterministic reflection-lite accepted-memory rerank and persists the rerank score in gate logs so replay reuses the original ordering; benchmark `ALL_STRATEGIES` runs in six-strategy order; `case_12_reflection_retention` expands the matrix to 12×6=72 with a real `variant_3` retention contrast; Task 7 surfaces reflection/token-bloat metrics in summary/Markdown/acceptance; Task 8 persists every benchmark run into `eval_cases` / `eval_runs` / `eval_results` when a repo is supplied; Task 9 surfaces `reflection_retention_hit_rate` through the dashboard benchmark summary; Task 10 updates ROADMAP/README/plan docs; Task 11 verifies full regression/reproducibility/report shape. **Next candidates:** ROADMAP §10/§11 Provider Registry / Controlled Memory Key Ontology.

## Implemented (ROADMAP §7 Six-Strategy Benchmark Task 11 — full regression/reproducibility/project-memory sync — 2026-06-12)

- **Full closeout:** ROADMAP §7 is now complete through Task 11. The deterministic six-strategy benchmark is locked at `baseline_0`, `long_context`, `baseline_1`, `variant_1`, `variant_2`, `variant_3` with 12 cases × 6 strategies = 72 result/access rows and 14 seeded runs.
- **Reflection-lite verification:** `variant_3`'s deterministic reflection-lite retention rerank remains a deliberate placeholder over accepted memories; `case_12_reflection_retention` proves it retains the high-retention marker where `variant_2` drops it, and ROADMAP §3.2 records that the real Reflection/Forgetting scheduler must later supersede this placeholder.
- **Fairness, replay, and persistence:** the benchmark runner's seed-time `access_count` snapshot/restore keeps strategy comparisons order-independent. Task 11 review additionally hardened persisted benchmark repeatability: `run_benchmark(..., repo=repo)` now uses an isolated workspace prefix per invocation so prior benchmark memories in the same repository cannot pollute later candidate sets, while still persisting stable `eval_cases` plus one `eval_run` and 72 `eval_results` per invocation without a migration. Final review hardening also made `long_context` dynamically expand to the exact pre-compaction budget if a fixed request budget would drop blocks, and made `variant_3` persist its reflection-lite rerank score in `MemoryGateLog.final_score` so replay original-view reconstruction can reuse the original ordering without recomputing retention from later-mutated memory state.
- **Acceptance and report shape:** benchmark acceptance now has 12/12 checks, including `variant_3_retains_high_value_memory_under_budget` and `long_context_shows_token_bloat`; `long_context` has the largest average memory-token overhead in the generated report.
- **Project-memory sync:** current state and next-action guidance now point beyond §7 to ROADMAP §10/§11 Provider Registry / Controlled Memory Key Ontology. Detailed review refreshed stale README/ROADMAP/REQUIREMENTS wording and recorded the repeatability trap in `.ai/PITFALLS.md`. I7 compaction negative retained remains deferred independently.

## Latest Verification (2026-06-12 ROADMAP §7 Task 11)

- Compile + full regression: `uv run --extra dev python -m compileall -q apps/api/app && uv run --extra dev pytest -q` -> **305 passed**.
- Deterministic benchmark + reproducibility: `uv run python -m app.benchmark.runner --output-dir reports && bash scripts/reproduce.sh` -> passed; printed `acceptance.passed=true (12/12 checks true)`.
- Report-shape check: `uv run python - <<'PY' ...` over `reports/benchmark_results.json` -> `OK {'baseline_0': 0.0, 'long_context': 44.1667, 'baseline_1': 25.4167, 'variant_1': 25.4167, 'variant_2': 26.8333, 'variant_3': 26.5}` with exact six-strategy order, 72 results, and both new acceptance checks true.
- Review hardening RED/GREEN: `uv run --extra dev pytest apps/api/tests/benchmark/test_runner.py::test_run_benchmark_eval_persistence_is_repeatable -q` failed before the isolated workspace-prefix fix (`second["acceptance"]["passed"] is False`), then passed after the fix; the test now compares deterministic summary fields while excluding timing-only latency fields. Additional RED/GREEN hardening covered `long_context` dynamic unbounded budget and `variant_3` replay rerank reconstruction: `uv run --extra dev pytest apps/api/tests/retrieval/test_retrieval_flow.py::test_long_context_preserves_scope_lifecycle_logs_and_unbounded_budget apps/api/tests/observability/test_replay.py::test_variant_3_replay_reconstructs_reflection_reranked_context -q` failed before the fixes, then passed after them. Benchmark/dashboard/strategy suite: `uv run --extra dev pytest apps/api/tests/benchmark/test_runner.py apps/api/tests/api/test_dashboard.py apps/api/tests/runtime/test_models_strategy.py -q` -> **24 passed**; retrieval+replay suite -> **100 passed**.

## Implemented (ROADMAP §7 Six-Strategy Benchmark Task 10 — docs/ROADMAP reflection-lite supersede note — 2026-06-12)

- **ROADMAP §7 completion:** `docs/design/ROADMAP.md` now marks the full 6-strategy comparison and benchmark eval-table persistence items complete, recording the strategy mapping `baseline_0` / `long_context` / `baseline_1` / `variant_1` / `variant_2` / `variant_3` and the `eval_runs` / `eval_cases` / `eval_results` persistence reuse of the Phase 3-A eval schema.
- **Reflection-lite supersede note:** ROADMAP §3.2 now explicitly states that `variant_3`'s deterministic reflection-lite `retention_score` is only a placeholder over accepted memories and must be replaced by the real Reflection/Forgetting scheduler's `retention_score / reflection_priority` once that slice lands.
- **README strategy docs:** `README.md` now lists all six deterministic benchmark strategies and describes `long_context` as same trace/gate logging path with policies disabled + effectively unbounded budget, while `variant_3` is documented as state-aware + gate + deterministic reflection-lite.
- **README benchmark coverage:** Task 10 review fixed the adjacent README coverage sentence so it no longer stops at compaction; it now includes safe failure learning (`case_10`), sanitized destructive-failure handling (`case_11`), and reflection-retention under a tight budget (`case_12_reflection_retention`).
- **Appendix next-action accuracy:** Task 10 review fixed ROADMAP appendix wording so §7 is described as function/docs complete but still awaiting Task 11 reproducibility closeout before switching to §10/§11.
- **Plan tracking:** `docs/design/SIX_STRATEGY_BENCHMARK_PLAN.md` marks Task 10 Steps 1-5 complete with the observed README command-guard verification result.
- **Review/memory refresh:** Detailed Task 10 review found no remaining P0/P1/P2 defects after the README coverage sentence and ROADMAP appendix next-action fixes. `.ai/PITFALLS.md` now records the doc-closeout trap that README strategy lists and benchmark coverage prose must be updated together.

## Latest Verification (2026-06-12 ROADMAP §7 Task 10)

- README command guard: `uv run --extra dev pytest apps/api/tests/integration/test_reproducibility.py -q` -> **4 passed**.
- Post-review README command guard: `uv run --extra dev pytest apps/api/tests/integration/test_reproducibility.py -q` -> **4 passed**.

## Implemented (ROADMAP §7 Six-Strategy Benchmark Task 9 — dashboard reflection summary — 2026-06-12)

- **Dashboard summary metric:** `apps/api/app/runtime/memory_runtime.py` now adds `reflection_retention_hit_rate` to `_benchmark_summary_from_records(...)`, using only rows with `reflection_retention_hit_present` so dashboard aggregation matches `apps/api/app/benchmark/runner.py`.
- **Dashboard/API coverage:** `apps/api/tests/api/test_dashboard.py::test_dashboard_tables_endpoint_exposes_benchmark_and_runtime_rows` now asserts dashboard/report parity for the new field and the concrete `variant_3` reflection-retention success value.
- **Plan tracking:** `docs/design/SIX_STRATEGY_BENCHMARK_PLAN.md` marks Task 9 Steps 1-3 complete.
- **Final review:** Detailed Task 9 review found no P0/P1/P2 defects after checking dashboard/runner summary parity, present-flag-gated aggregation, response schema compatibility, test strength, and memory freshness. Report: `/tmp/mem-trace_task9_final_review/report.html` / `/tmp/mem-trace_task9_final_review/report.md`.

## Latest Verification (2026-06-12 ROADMAP §7 Task 9)

- RED: `uv run --extra dev pytest apps/api/tests/api/test_dashboard.py::test_dashboard_tables_endpoint_exposes_benchmark_and_runtime_rows -q` -> failed as expected with `KeyError: 'reflection_retention_hit_rate'`.
- GREEN targeted: same command after dashboard summary implementation -> **1 passed**.
- Dashboard suite: `uv run --extra dev pytest apps/api/tests/api/test_dashboard.py -q` -> **3 passed**.
- Affected benchmark+dashboard suite: `uv run --extra dev pytest apps/api/tests/benchmark/test_runner.py apps/api/tests/api/test_dashboard.py -q` -> **23 passed**.
- Compile check: `uv run --extra dev python -m compileall -q apps/api/app/runtime/memory_runtime.py` -> passed.
- Final focused review: checked metric-name parity with runner summary, present-flag filtering, dashboard JSON shape, test coverage, plan status, and project-memory freshness; result **0 P0 / 0 P1 / 0 P2**. Report: `/tmp/mem-trace_task9_final_review/report.html` / `/tmp/mem-trace_task9_final_review/report.md`.

## Implemented (ROADMAP §7 Six-Strategy Benchmark Task 8 — eval-table persistence — 2026-06-12)

- **Eval run persistence:** `apps/api/app/benchmark/runner.py` adds `_persist_eval_records(...)` and calls it after computing summary/acceptance, so `run_benchmark(..., repo=repo)` writes one completed `EvalRunRecord` with `finished_at` and config containing strategy order, summary, and acceptance verdict.
- **Eval cases/results:** The runner upserts one `EvalCaseRecord` per benchmark case (`tags=["benchmark"]`) and writes one `EvalResultRecord` per case/strategy row with `passed=True`; task-quality remains in `metrics["task_success"]`, and overall benchmark pass/fail remains in `EvalRunRecord.config["acceptance"]["passed"]`.
- **Repeatability:** Case rows are stable across repeated benchmark runs, while each run appends a fresh eval run and 72 result rows.
- **Coverage:** `apps/api/tests/benchmark/test_runner.py::test_run_benchmark_persists_eval_records` locks the eval run/case/result shape and `case_12` reflection metric persistence; `test_run_benchmark_eval_persistence_is_repeatable` locks stable cases plus appended runs/results.
- **Plan tracking:** `docs/design/SIX_STRATEGY_BENCHMARK_PLAN.md` marks Task 8 Steps 1-5 complete.
- **Final review:** Detailed Task 8 review found no P0/P1/P2 defects after checking eval write shape, payload/config consistency, repeatability/upsert semantics, dashboard/schema compatibility, and stale memory references.

## Latest Verification (2026-06-12 ROADMAP §7 Task 8)

- RED: `uv run --extra dev pytest apps/api/tests/benchmark/test_runner.py::test_run_benchmark_persists_eval_records apps/api/tests/benchmark/test_runner.py::test_run_benchmark_eval_persistence_is_repeatable -q` -> **2 failed** as expected with `len(eval_cases) == 0`.
- GREEN targeted: same command after `_persist_eval_records(...)` implementation -> **2 passed**.
- Benchmark runner regression: `uv run --extra dev pytest apps/api/tests/benchmark/test_runner.py -q` -> **20 passed**.
- Compile check: `uv run --extra dev python -m compileall -q apps/api/app/benchmark/runner.py` -> passed.
- Affected suite: `uv run --extra dev pytest apps/api/tests/benchmark/test_runner.py apps/api/tests/api/test_dashboard.py apps/api/tests/observability/test_eval_records.py -q` -> **27 passed**.
- Benchmark sanity: `uv run python -m app.benchmark.runner --output-dir reports` -> passed.
- Focused review report: `/tmp/mem-trace_task8_review/report.html` / `/tmp/mem-trace_task8_review/report.md`; result **0 P0 / 0 P1 / 0 P2**.

## Implemented (ROADMAP §7 Six-Strategy Benchmark Task 7 — reflection/token-bloat acceptance — 2026-06-12)

- **Summary metric:** `apps/api/app/benchmark/runner.py` now summarizes `reflection_retention_hit` as `reflection_retention_hit_rate`, gated by `reflection_retention_hit_present` so only `case_12` contributes.
- **Report/JSON exposure:** `_METRIC_FIELDS` includes `reflection_retention_hit`, and the Markdown summary now describes all six strategies and includes a `reflection_retention_hit_rate` column alongside token overhead.
- **Acceptance checks:** `_acceptance(...)` now verifies `variant_3_retains_high_value_memory_under_budget` using both summary rates and explicit `case_12` row metrics, and verifies `long_context_shows_token_bloat` by requiring `long_context` to have the maximum average memory-token overhead and exceed `variant_2`.
- **Coverage:** `apps/api/tests/benchmark/test_runner.py::test_acceptance_includes_reflection_and_long_context_checks` locks both new acceptance checks, `variant_3`/`variant_2` reflection contrast, and the long-context overhead invariant. Review-hardening tests also require a real `variant_2` comparator and `case_12` present rows so partial summaries cannot make the new checks pass accidentally.
- **Plan tracking:** `docs/design/SIX_STRATEGY_BENCHMARK_PLAN.md` marks Task 7 Steps 1-7 complete.
- **Final review:** Detailed review found no remaining P0/P1/P2 defects after updating the Task 7 plan snippet to match the hardened comparator-required acceptance logic.

## Latest Verification (2026-06-12 ROADMAP §7 Task 7)

- RED: `uv run --extra dev pytest apps/api/tests/benchmark/test_runner.py::test_acceptance_includes_reflection_and_long_context_checks -q` -> failed as expected with `KeyError: 'variant_3_retains_high_value_memory_under_budget'`.
- GREEN targeted: same command after runner summary/report/acceptance implementation -> **1 passed**.
- Review hardening RED/GREEN: targeted negative pair initially failed on `test_long_context_token_bloat_acceptance_requires_variant_2_comparator` (`True is False`) before requiring an explicit `variant_2` comparator, then passed -> **2 passed**.
- Benchmark runner regression: `uv run --extra dev pytest apps/api/tests/benchmark/test_runner.py -q` -> **18 passed**.
- Compile check: `uv run --extra dev python -m compileall -q apps/api/app/benchmark/runner.py` -> passed.
- Affected suite: `uv run --extra dev pytest apps/api/tests/benchmark/test_runner.py apps/api/tests/api/test_dashboard.py -q` -> **21 passed**.
- Benchmark sanity: `uv run python -m app.benchmark.runner --output-dir reports && uv run python - <<'PY' ...` -> printed `OK {'baseline_0': 0.0, 'long_context': 44.1667, 'baseline_1': 25.4167, 'variant_1': 25.4167, 'variant_2': 26.8333, 'variant_3': 26.5}`.

## Implemented (ROADMAP §7 Six-Strategy Benchmark Task 6 — `case_12_reflection_retention` — 2026-06-12)

- **New benchmark case:** `apps/api/app/benchmark/cases.py` adds `case_12_reflection_retention`, seeding one frequently used high-retention episodic memory (`RETAIN-CRITICAL-FACT`, `access_count=10`) plus six higher-relevance low-retention noise memories.
- **Reflection metric:** `apps/api/app/benchmark/evaluator.py` adds `reflection_retention_hit` and `reflection_retention_hit_present`, scored when `reflection_case=True` and the configured marker reaches context.
- **Runner wiring:** `apps/api/app/benchmark/runner.py` passes `reflection_marker` and `reflection_case` from `SeedResult.extra` into `evaluate_case(...)`.
- **Matrix counts:** benchmark/report persistence assertions now expect 12 cases × 6 strategies = 72 result/access rows; dashboard table assertions now expect 14 seeded runs, 12 benchmark cases, and 72 benchmark results/accesses.
- **Fixture tuning:** `case_12` uses `token_budget=32` so protected active-state/path plus compaction notice still leave enough ordinary-budget room for exactly the intended contrast: `variant_2` drops the high-retention marker, while `variant_3` keeps it. Production rerank logic was not changed.
- **Plan tracking:** `docs/design/SIX_STRATEGY_BENCHMARK_PLAN.md` marks Task 6 Steps 1-9 complete.

## Latest Verification (2026-06-12 ROADMAP §7 Task 6)

- RED: `uv run --extra dev pytest apps/api/tests/benchmark/test_runner.py::test_evaluator_scores_reflection_retention_hit_from_marker_presence -q` -> failed as expected with `TypeError: evaluate_case() got an unexpected keyword argument 'reflection_marker'`.
- GREEN targeted: same command after evaluator metric implementation -> **1 passed**.
- Case persistence/contrast guard: `uv run --extra dev pytest apps/api/tests/benchmark/test_runner.py::test_run_benchmark_persists_cases_and_results -q` -> **1 passed**.
- Affected suite: `uv run --extra dev pytest apps/api/tests/benchmark/test_runner.py apps/api/tests/api/test_dashboard.py -q` -> **18 passed**.
- Benchmark sanity: `uv run python -m app.benchmark.runner --output-dir reports && uv run python - <<'PY' ...` -> printed `variant_2 0 variant_3 1` and `OK: reflection contrast holds`.

## Implemented (ROADMAP §7 Six-Strategy Benchmark Task 5 — benchmark strategy expansion — 2026-06-12)

- **Six-strategy runner order:** `apps/api/app/benchmark/cases.py` expands `ALL_STRATEGIES` to `baseline_0`, `long_context`, `baseline_1`, `variant_1`, `variant_2`, `variant_3`.
- **Interim count updates:** Benchmark/report persistence assertions now expect 66 rows for 11 cases × 6 strategies. Dashboard table assertions now expect 66 access rows and 66 benchmark-result rows while retaining 13 runs and 11 cases until Task 6.
- **Coverage:** `apps/api/tests/benchmark/test_runner.py::test_all_strategies_uses_six_strategy_benchmark_order` locks the benchmark-layer order so future report/acceptance code cannot silently drift.
- **Plan tracking:** `docs/design/SIX_STRATEGY_BENCHMARK_PLAN.md` marks Task 5 Steps 1-3 complete.

## Latest Verification (2026-06-12 ROADMAP §7 Task 5)

- RED: `uv run --extra dev pytest apps/api/tests/benchmark/test_runner.py::test_all_strategies_uses_six_strategy_benchmark_order -q` -> failed as expected because `ALL_STRATEGIES` was still `baseline_0`, `baseline_1`, `variant_1`, `variant_2`.
- GREEN targeted: same command after expanding `ALL_STRATEGIES` -> **1 passed**.
- Affected suite: `uv run --extra dev pytest apps/api/tests/benchmark/test_runner.py apps/api/tests/api/test_dashboard.py -q` -> **17 passed**.
- Detailed review: checked Task 5 code, tests, dashboard counts, existing acceptance, and project-memory consistency; result **0 P0 / 0 P1 / 0 P2** remaining defects. Reports: `/tmp/mem-trace_task5_review/report.html` / `/tmp/mem-trace_task5_review/report.md`.

## Implemented (ROADMAP §7 Six-Strategy Benchmark Task 4b — `variant_3` reflection-lite accepted-memory rerank — 2026-06-12)

- **Retention helper:** `apps/api/app/retrieval/controller.py` now exposes module-level `retention_score(mem)`, a deterministic placeholder for ROADMAP §3.2 Reflection/Forgetting that blends clamped trust, clamped freshness, and clamped usage frequency (`access_count / 10`).
- **Reflection-aware accepted sort:** `RetrievalController.trace(...)` keeps the old `final_score` sort for all existing strategies, but when `GateConfig.enable_reflection_rerank=True` (`variant_3`) it sorts accepted positive memories by `0.5 * final_score + 0.5 * retention_score(memory)` before packing.
- **Scope preserved:** the rerank only changes accepted-memory order before packing. The packer still owns protected/project/type ordering, so protected state and project constraints are not overridden by reflection-lite.
- **Coverage:** `apps/api/tests/retrieval/test_retrieval_flow.py::test_variant_3_retains_high_retention_memory_where_variant_2_drops_it` uses fresh repos per strategy and a tight budget to prove `variant_2` drops a high-access-count marker while `variant_3` retains it.
- **Plan tracking:** `docs/design/SIX_STRATEGY_BENCHMARK_PLAN.md` marks Task 4b Steps 1-5 complete.

## Latest Verification (2026-06-12 ROADMAP §7 Task 4b)

- RED: `uv run --extra dev pytest apps/api/tests/retrieval/test_retrieval_flow.py::test_variant_3_retains_high_retention_memory_where_variant_2_drops_it -q` -> failed as expected because `variant_3` sorted like `variant_2` and did not include `retain-critical-fact`.
- GREEN targeted: same command after implementation and fixture budget tuning -> **1 passed**.
- Review hardening RED/GREEN: `uv run --extra dev pytest apps/api/tests/retrieval/test_retrieval_flow.py::test_retention_score_clamps_out_of_range_memory_signals -q` failed before clamping (`1.55 != 1.0`), then passed after adding `_clamp01(...)`.
- Compile check: `uv run --extra dev python -m compileall -q apps/api/app/retrieval/controller.py` -> passed.
- Retrieval regression: `uv run --extra dev pytest apps/api/tests/retrieval/ -q` -> **85 passed**.
- Detailed review: checked `variant_3` gate/state parity with `variant_2`, accepted-only rerank, negative-evidence separation, `retention_score` bounds/determinism, packer protected/project ordering, benchmark/test order independence, and `.ai`/plan memory sync. Result: **0 P0 / 0 P1 / 0 P2** remaining defects. Report: `/tmp/mem-trace_task4b_review/report.html` / `/tmp/mem-trace_task4b_review/report.md`.

## Implemented (ROADMAP §7 Six-Strategy Benchmark Task 4a — benchmark access-count isolation — 2026-06-12)

- **Seed-time snapshot:** `apps/api/app/benchmark/runner.py` now captures every seeded memory's `access_count` for the case workspace immediately after `case.seed(...)`.
- **Per-strategy restore:** `_run_case(...)` restores that snapshot before each strategy retrieval, isolating benchmark variants from `_bump_access_counts(...)` side effects produced by earlier strategies in the same case.
- **Task-order invariant unlocked:** Task 4b can now implement `variant_3` reflection-lite using `access_count` without making its benchmark result order-dependent.
- **Coverage:** `apps/api/tests/benchmark/test_runner.py::test_snapshot_restore_resets_access_counts` directly verifies snapshot/restore semantics over the repository boundary; `test_run_case_restores_access_counts_before_each_strategy` proves `_run_case(...)` invokes the restore before each strategy retrieval.
- **Plan tracking:** `docs/design/SIX_STRATEGY_BENCHMARK_PLAN.md` marks Task 4a Steps 1-5 complete.

## Latest Verification (2026-06-12 ROADMAP §7 Task 4a)

- RED: `uv run --extra dev pytest apps/api/tests/benchmark/test_runner.py::test_snapshot_restore_resets_access_counts -q` -> failed during collection with `ImportError: cannot import name '_restore_access_counts'`, as expected before helper implementation.
- GREEN targeted: same command after implementation -> **1 passed**; review-hardening targeted pair -> **2 passed**.
- Compile check: `uv run --extra dev python -m compileall -q apps/api/app/benchmark/runner.py` -> passed.
- Benchmark regression: `uv run --extra dev pytest apps/api/tests/benchmark/test_runner.py -q` -> **13 passed**.
- Detailed Task 4a review: checked snapshot/restore placement, workspace scoping, repository copy/update semantics, retrieval `_bump_access_counts` side effect boundaries, cross-workspace case behavior, performance of per-strategy restore scans, and test coverage. Initial review found two P2 issues (restore should be workspace-scoped; helper-only coverage did not prove `_run_case` orchestration). Both were fixed, then issue-validator rechecked the final implementation and found **no remaining defects**. Report: `/tmp/mem-trace_task4a_final_review/report.html`.

## Implemented (ROADMAP §7 Six-Strategy Benchmark Task 3 — long_context controller behavior — 2026-06-12)

- **Include-all candidate selection:** `apps/api/app/retrieval/controller.py` now passes `include_all=True` for `RetrievalStrategy.long_context`, so `_select_candidates(...)` includes every retrievable workspace memory even when relevance is 0 and returns all scored candidates instead of truncating to `top_k`.
- **Unbounded budget baseline:** `trace(...)` dynamically expands the effective token budget for `long_context` to the exact pre-compaction size when a requested budget would drop blocks, preserving the normal gate/packer/logging path while preventing budget drops so §7 can measure token bloat without relying on a fixed sentinel.
- **Safety invariants preserved:** Workspace scoping and `_RETRIEVABLE_STATUSES` lifecycle filtering still apply before `long_context` stuffing; this is not a separate bypass path.
- **Coverage:** `apps/api/tests/retrieval/test_retrieval_flow.py` asserts `top_k=1` still limits `baseline_1` to the most relevant block while `long_context` includes the off-topic pottery memory and reports higher accepted/actual-token counts. Review hardening also asserts `long_context` preserves workspace isolation, lifecycle filtering, access/gate/profile persistence, and no budget drops under `token_budget=1`.
- **Plan tracking:** `docs/design/SIX_STRATEGY_BENCHMARK_PLAN.md` marks Task 3 Steps 1-6 complete.

## Latest Verification (2026-06-12 ROADMAP §7 Task 3)

- RED: `uv run --extra dev pytest apps/api/tests/retrieval/test_retrieval_flow.py::test_long_context_includes_all_memories_while_top_k_limits_baseline_1 -q` -> failed as expected because `long_context` was still `top_k=1` limited and omitted `pottery`.
- GREEN targeted: same command after implementation -> **1 passed**.
- Review hardening targeted: `uv run --extra dev pytest apps/api/tests/retrieval/test_retrieval_flow.py::test_long_context_preserves_scope_lifecycle_logs_and_unbounded_budget -q` -> **1 passed**.
- Retrieval regression: `uv run --extra dev pytest apps/api/tests/retrieval/ -q` -> **83 passed**.
- Strategy/gate/flow regression: `uv run --extra dev pytest apps/api/tests/runtime/test_models_strategy.py apps/api/tests/retrieval/test_gate.py apps/api/tests/retrieval/test_retrieval_flow.py -q` -> **67 passed**.
- Compile check: `uv run --extra dev python -m compileall -q apps/api/app/retrieval/controller.py` -> passed.

## Implemented (ROADMAP §7 Six-Strategy Benchmark Task 2 — gate config — 2026-06-12)

- **Long-context gate contract:** `apps/api/app/retrieval/gate.py` maps `RetrievalStrategy.long_context` to the baseline all-policies-off gate config: no hard/risk policy, no state match, failed/rolled_back admitted, failure learning disabled, and reflection rerank disabled. The actual include-all/unbounded-budget controller behavior is now implemented by Task 3 above.
- **Variant-3 gate contract:** `RetrievalStrategy.variant_3` now keeps `variant_2`'s full gate/failure-learning behavior and sets `enable_reflection_rerank=True`, ready for Task 4b controller consumption after Task 4a fairness isolation lands.
- **Coverage:** `apps/api/tests/retrieval/test_gate.py` asserts `long_context` matches the all-policies-off contract, `variant_3` is `variant_2` plus reflection rerank, and no other strategy enables `enable_reflection_rerank`.
- **Plan tracking:** `docs/design/SIX_STRATEGY_BENCHMARK_PLAN.md` marks Task 2 Steps 1-4 complete.

## Latest Verification (2026-06-12 ROADMAP §7 Task 2)

- RED: `uv run --extra dev pytest apps/api/tests/retrieval/test_gate.py -k "long_context or variant_3 or reflection_rerank" -q` -> failed as expected because `long_context` fell through to the default hard-policy config, `variant_3` did not enable failure learning, and `enable_reflection_rerank` was missing.
- GREEN targeted: same command after implementation -> **3 passed**.
- Review hardening: generalized the existing failure-learning strategy matrix in `apps/api/tests/retrieval/test_gate.py` to include `long_context=False` and `variant_3=True`, replacing stale "variant_2-only" wording with "full gate strategies".
- Detailed Task 2 review: checked plan conformance, strategy config semantics, forward compatibility of the unused `enable_reflection_rerank` flag, downstream controller impact, stale memory references, and test coverage. No P0/P1/P2 defects found.
- Compile check: `uv run --extra dev python -m compileall -q apps/api/app/retrieval/gate.py apps/api/app/runtime/models.py` -> passed.
- Gate regression after review hardening: `uv run --extra dev pytest apps/api/tests/retrieval/test_gate.py -q` -> **34 passed**.
- Task 1+2 + retrieval-flow regression: `uv run --extra dev pytest apps/api/tests/retrieval/test_gate.py apps/api/tests/runtime/test_models_strategy.py apps/api/tests/retrieval/test_retrieval_flow.py -q` -> **65 passed**.

## Implemented (ROADMAP §7 Six-Strategy Benchmark Task 1 — strategy enum — 2026-06-12)

- **Enum expansion:** `apps/api/app/runtime/models.py` now declares six benchmark strategy enum values in ROADMAP §7 order: `baseline_0`, `long_context`, `baseline_1`, `variant_1`, `variant_2`, `variant_3`.
- **Intent documentation:** The enum docstring documents the layered comparison sequence: no-memory -> long-context -> vector -> state-aware -> +gate -> +reflection.
- **Coverage:** `apps/api/tests/runtime/test_models_strategy.py` asserts both exact enum order and exact set membership so future drift is visible early.
- **Plan hygiene:** `docs/design/SIX_STRATEGY_BENCHMARK_PLAN.md` now marks Task 1 Steps 1-4 complete and no longer contains per-task add/commit instructions.

## Latest Verification (2026-06-12 ROADMAP §7 Task 1)

- RED: `uv run --extra dev pytest apps/api/tests/runtime/test_models_strategy.py -q` -> failed as expected because `long_context` / `variant_3` were missing.
- GREEN: `uv run --extra dev pytest apps/api/tests/runtime/test_models_strategy.py -q` -> **1 passed**.
- Compile check: `uv run --extra dev python -m compileall -q apps/api/app/runtime/models.py` -> passed.
- Detailed Task 1 review: checked plan conformance, enum serialization values, ordering, downstream compatibility, and test coverage. No P0/P1/P2 defects found for Task 1 scope. Historical note: Task 1 only made `long_context` / `variant_3` parseable; `long_context` behavior is now implemented by Task 3, while `variant_3` reflection behavior remains pending Task 4b.

**Completed slice:** Phase 3.5 **Python SDK + LangGraph Adapter + CLI** (`docs/design/SDK_ADAPTER_PLAN.md`) is complete through S6. S1 lets callers stamp event entrypoint origin via `WriteEventRequest.event_source`, preserving `None` by default for existing callers. S0 makes `packages/python-sdk` an importable uv workspace package with pytest discovery. S2a/S2b provide isomorphic in-process and HTTP SDK backends over `MemoryRuntime` / `/v1`, including `/v1/runs/{run_id}/steps` and body-based `/v1/sessions/flush` for arbitrary session ids. S3 provides LangGraph-style lifecycle hooks and wrapper without hard-depending on langgraph. S4 adds runnable custom-loop and LangGraph-adapter examples. S5 provides the `memtrace` CLI with safe HTTP-default operational semantics. S6 finalizes README, ROADMAP, this plan, and `.ai` project memory.

## Implemented (Phase 3.5 SDK/LangGraph Adapter S6 — docs/project-memory sync + review hardening — 2026-06-12)

- **README three-entrypoint docs:** `README.md` now has a “Three entrypoints: Python SDK / HTTP / CLI” section with SDK quickstart, HTTP backend constructor, LangGraph adapter snippet, CLI usage, and links to `examples/README.md`, `examples/simple_agent`, and `examples/langgraph_adapter`.
- **Plan/roadmap finalization:** `docs/design/SDK_ADAPTER_PLAN.md` marks S6 complete and records the review hardening; `docs/design/ROADMAP.md` appendix step 6 now marks Phase 3.5 complete and points next candidates to §7 / §10 / §11 while keeping TS SDK, OTel, MCP, IDE plugins, Go/Rust collectors deferred.
- **Project-memory sync:** `AGENTS.md`, `.ai/REQUIREMENTS.md`, `.ai/IMPLEMENTATION_PLAN.md`, `.ai/OPEN_QUESTIONS.md`, `.ai/DECISIONS.md`, and `.ai/PITFALLS.md` are updated so new sessions no longer treat S6 as pending. ADR-019 records the durable SDK/HTTP/adapter/CLI entrypoint decision.
- **Review hardening:** Detailed code review found one P2 backend-isomorphism defect: `flush_session("tenant/session")` worked in-process but HTTP path interpolation would 404. `apps/api/app/api/routes.py` now exposes body-based `POST /v1/sessions/flush` with `FlushRequest`; `HttpBackend.flush_session(...)` uses that endpoint; tests cover path-sensitive session ids and shared-runtime backend isomorphism.

## Latest Verification (2026-06-12 Phase 3.5 S6)

- Detailed S6 code review: checked `event_source`, HTTP/in-process isomorphism, CLI `--http` policy, LangGraph optional dependency, and steps-route missing-run `[]`. Found and fixed the single P2 `flush_session` path-sensitive session-id issue described above.
- Documentation consistency review: found stale S6-next references in `SDK_ADAPTER_PLAN`, `ROADMAP`, `README`, `AGENTS.md`, `.ai/PROJECT_STATE.md`, `.ai/REQUIREMENTS.md`, `.ai/IMPLEMENTATION_PLAN.md`, and `.ai/OPEN_QUESTIONS.md`; all were updated.
- Targeted post-fix verification: `uv run --package memtrace-sdk --extra dev pytest packages/python-sdk/tests/test_http_backend.py packages/python-sdk/tests/test_backend_isomorphism.py apps/api/tests/api/test_steps_route.py -q` -> **7 passed**.
- SDK package regression: `uv run --package memtrace-sdk --extra dev pytest packages/python-sdk/tests -q` -> **27 passed**.
- Compile check: `uv run --extra dev python -m compileall -q apps/api/app packages/python-sdk/src examples` -> passed.
- Full regression: `uv run --extra dev pytest -q` -> **285 passed**.
- Deterministic benchmark + reproducibility: `uv run python -m app.benchmark.runner --output-dir reports && bash scripts/reproduce.sh` -> **acceptance.passed=true (10/10 checks true)**.

## Implemented (Phase 3.5 SDK/LangGraph Adapter S5 — CLI — 2026-06-12)

- **CLI entrypoint:** `packages/python-sdk/src/memtrace_sdk/cli.py` now implements the declared `memtrace` console script with `argparse` and `main(argv=None) -> int`.
- **Backend policy:** operational commands (`start-run`, `start-step`, `write-event`, `retrieve`, `timeline`, `state-tree`, `inspect-access`, `report`) require `--http URL` so separate CLI invocations do not silently use a fresh in-memory runtime and lose state. `demo` is explicitly one-shot and supports `--in-process` or `--http`.
- **Command surface:** global `--http`, `--workspace-id`, `--api-key`, and `--json` are supported. Command results are serialized through the SDK/core Pydantic DTOs via `model_dump(mode="json")` where applicable.
- **Entrypoint stamping:** CLI-generated events from `write-event` and demo seeding pass `event_source="cli"` explicitly rather than inheriting the SDK facade's default `"sdk"` label.
- **Error handling:** `NotFoundError`, `BadRequestError`, and generic `MemTraceError` map to non-zero exit codes and actionable stderr messages.
- **Coverage:** `packages/python-sdk/tests/test_cli.py` covers in-process demo, HTTP-backed demo over a persistent ASGITransport runtime, operational command `--http` enforcement, ASGITransport-backed JSON retrieve, missing access 404/non-zero exit, and CLI `event_source` stamping.

## Latest Verification (2026-06-12 Phase 3.5 S5)

- RED: `uv run --package memtrace-sdk --extra dev pytest packages/python-sdk/tests/test_cli.py -q` -> **4 failed** on the S0 not-implemented CLI stub.
- GREEN targeted S5: same command after implementation + event-source / HTTP-demo coverage -> **6 passed**.
- Manual CLI smoke: `uv run --package memtrace-sdk memtrace demo --in-process` -> printed `baseline_1 action: npm test`, `variant_2 action: bun test`, `contamination eliminated: true`.
- SDK package tests: `uv run --package memtrace-sdk --extra dev pytest packages/python-sdk/tests -q` -> **26 passed**.
- Compile check: `uv run --extra dev python -m compileall -q apps/api/app packages/python-sdk/src examples` -> passed.
- Full regression: `uv run --extra dev pytest -q` -> **284 passed**.
- Detailed S5 review: CLI implementation was checked against `docs/design/SDK_ADAPTER_PLAN.md` S5 requirements and the bits-code-guard review dimensions (logic, business semantics, security, robustness, performance, quality). No P0/P1/P2 implementation defects were found. One stale `.ai/PROJECT_STATE.md` tail recommendation still saying to implement S5 was corrected to S6 docs/project-memory finalization.

## Implemented (Phase 3.5 SDK/LangGraph Adapter S4 — examples — 2026-06-12)

- **Custom-loop example:** `examples/simple_agent/main.py` uses `MemTrace.in_memory(...)` only through the public SDK facade to seed the canonical Bun-vs-Node failed-branch isolation scenario, retrieve with `baseline_1` and `variant_2`, and print the contamination contrast (`npm test` vs `bun test`). Its local `decide_action(...)` deliberately excludes `avoided_attempts` / `source="negative_evidence"` blocks from positive action choice so I3 negative evidence does not make the agent retry the failed npm path.
- **LangGraph example:** `examples/langgraph_adapter/main.py` builds a minimal graph around `MemTraceLangGraphAdapter.wrap_node(...)` when `langgraph` is installed, and otherwise prints an actionable `pip install memtrace-sdk[langgraph]` skip message and exits successfully.
- **Example README:** `examples/README.md` documents both commands, expected output, backend choice, and the clean LangGraph skip behavior.
- **Smoke coverage:** `packages/python-sdk/tests/test_examples_smoke.py` imports and awaits both example `main()` functions, asserting the simple-agent contrast and either LangGraph execution with `event_source="langgraph_adapter"` or a deterministic skip.

## Latest Verification (2026-06-12 Phase 3.5 S4)

- RED: `uv run --package memtrace-sdk --extra dev pytest packages/python-sdk/tests/test_examples_smoke.py -q` -> **2 failed** on missing `examples/simple_agent/main.py` and `examples/langgraph_adapter/main.py`.
- GREEN targeted S4: same command -> **2 passed**.
- Manual examples smoke: `uv run --package memtrace-sdk python examples/simple_agent/main.py && uv run --package memtrace-sdk python examples/langgraph_adapter/main.py` -> printed `baseline_1 action: npm test`, `variant_2 action: bun test`, `contamination eliminated: true`, and the clean LangGraph-not-installed skip message.
- SDK package tests: `uv run --package memtrace-sdk --extra dev pytest packages/python-sdk/tests -q` -> **20 passed**.
- Compile check: `uv run --extra dev python -m compileall -q apps/api/app packages/python-sdk/src examples` -> passed.
- Full regression: `uv run --extra dev pytest -q` -> **278 passed**.
- Deterministic benchmark + reproducibility: `uv run python -m app.benchmark.runner --output-dir reports && bash scripts/reproduce.sh` -> **acceptance.passed=true (10/10 checks true)**.
- Detailed S4 review: examples implementation and project-memory sync were rechecked against `docs/design/SDK_ADAPTER_PLAN.md` S4 requirements; no Critical / Important / Minor implementation defects were found. One stale `.ai/OPEN_QUESTIONS.md` reference still pointing to S4 as next was corrected to S5 CLI.

## Implemented (Phase 3.5 SDK/LangGraph Adapter S3 — lifecycle hooks — 2026-06-12)

- **Adapter hooks:** `memtrace_sdk.langgraph_adapter.MemTraceLangGraphAdapter` exposes `before_node(node_name, query, ...)`, `after_node(step_id, content=..., ...)`, and `on_error(step_id, error_message=...)` over the existing `MemTrace` facade, so it works with in-process and HTTP backends.
- **Trace semantics:** `before_node` starts a runtime step and retrieves a `MemoryContext`; `after_node` writes node output with `event_source="langgraph_adapter"` and finishes the step as completed, returning both `WriteEventResult` and `FinishStepResult`; `on_error` writes an error event, finishes failed, then calls `rollback_branch(...)`.
- **Optional wrapper:** `wrap_node(...)` composes before/after/on_error around an async callable and injects `memtrace_step` / `memtrace_context` into mutable dict state for prompt construction.
- **No hard LangGraph dependency:** S3 hooks do not import langgraph, so `memtrace-sdk` remains usable without the optional extra until a future true graph-compilation helper needs it.
- **Tests:** `packages/python-sdk/tests/test_langgraph_adapter.py` covers successful lifecycle tracing and event-source stamping, rollback behavior with positive-context isolation that allows only I3 `avoided_attempts` / `source="negative_evidence"` failure lessons, and wrapper success/failure behavior. `test_imports.py` now includes the public `MemTraceLangGraphAdapter` export.

## Latest Verification (2026-06-12 Phase 3.5 S3)

- RED: `uv run --package memtrace-sdk --extra dev pytest packages/python-sdk/tests/test_langgraph_adapter.py -q` -> **3 failed** on missing `MemTraceLangGraphAdapter`.
- GREEN targeted S3: same command -> **3 passed**.
- SDK package tests: `uv run --package memtrace-sdk --extra dev pytest packages/python-sdk/tests -q` -> **18 passed**.
- Compile check: `uv run --extra dev python -m compileall -q apps/api/app packages/python-sdk/src` -> passed.
- Full regression: `uv run --extra dev pytest -q` -> **276 passed**.
- Detailed S3 review: no P0/P1/P2 defects found in `MemTraceLangGraphAdapter`, public export, S3 tests, or memory sync; stale historical wording in `docs/design/SDK_ADAPTER_PLAN.md` §0/§1/§3 was corrected and the LangGraph adapter testing pitfall was recorded in `.ai/PITFALLS.md`.

## Implemented (Phase 3.5 SDK/LangGraph Adapter S2b — HTTP backend + route/isomorphism — 2026-06-12)

- **Missing HTTP read route:** `GET /v1/runs/{run_id}/steps` now returns `list[AgentStep]` via `MemoryRuntime.get_steps(run_id)`, matching existing run-level read endpoints by returning `[]` for missing runs instead of 404.
- **HTTP backend:** `memtrace_sdk.backends.HttpBackend` mirrors the current `/v1` surface: run/step/event lifecycle, retrieval, flush, timeline/state/steps/profile/memories, single-step reads, inspect/replay, observability summary/report, and dashboard tables.
- **HTTP contract details:** request bodies use `model_dump(mode="json")`; single responses parse with `Model.model_validate(...)`; list responses parse with `TypeAdapter(list[Model])`; HTTP 404 maps to SDK `NotFoundError`, 400 maps to `BadRequestError`, and other HTTP errors map to `MemTraceError`; optional `api_key` sends `Authorization: Bearer ...`.
- **Lifecycle + facade:** `HttpBackend` supports owned vs injected `httpx.AsyncClient`; `aclose()` closes only owned clients; async context manager support is wired through both backend and `MemTrace`; `MemTrace.http(...)` constructs the HTTP client facade.
- **Tests:** `packages/python-sdk/tests/test_http_backend.py` covers HTTP golden path, single-step reads, error mapping, and lifecycle; `packages/python-sdk/tests/test_backend_isomorphism.py` proves shared-runtime in-process vs HTTP shape equivalence, cross-backend read/write visibility, single-step 404 equivalence, all list-shaped read responses, and missing-run `get_steps == []`; `apps/api/tests/api/test_steps_route.py` covers the route directly.

## Latest Verification (2026-06-12 Phase 3.5 S2b)

- RED: `uv run --package memtrace-sdk --extra dev pytest packages/python-sdk/tests/test_http_backend.py packages/python-sdk/tests/test_backend_isomorphism.py apps/api/tests/api/test_steps_route.py -q` -> **6 failed** on missing `MemTrace.http`, missing `HttpBackend` constructor, and missing `/v1/runs/{run_id}/steps` route.
- GREEN targeted S2b: same command -> **6 passed**.
- Review hardening: tightened `test_backend_isomorphism.py` to use one shared `MemoryRuntime` behind both `MemTrace.in_process(...)` and ASGITransport HTTP, to compare `timeline`, `state-tree`, `steps`, `profile`, and `memories` list parsing across backends, and to cover existing `/v1/steps/{step_id}` through SDK `get_step`.
- SDK package tests: `uv run --package memtrace-sdk --extra dev pytest packages/python-sdk/tests -q` -> **15 passed**.
- API steps route: `uv run --extra dev pytest apps/api/tests/api/test_steps_route.py -q` -> **2 passed**.
- Compile check: `uv run --extra dev python -m compileall -q apps/api/app packages/python-sdk/src` -> passed.
- Full regression: `uv run --extra dev pytest -q` -> **273 passed**.

## Implemented (Phase 3.5 SDK/LangGraph Adapter S2a — Shared SDK contract + in-process backend — 2026-06-12)

- **Shared SDK contract:** `packages/python-sdk/src/memtrace_sdk/types.py` re-exports the core runtime request/result/domain DTOs and enums from `app.runtime.models`, keeping SDK users off private `app.*` imports while preserving a single Pydantic schema vocabulary.
- **Backend Protocol:** `memtrace_sdk.backends.Backend` now mirrors the runtime hot path plus read/observability methods: run/step/event lifecycle, retrieval, flush, timeline/state/steps/profile/memories, inspect/replay, observability summary/report, and dashboard tables.
- **In-process backend:** `InProcessBackend(runtime)` directly wraps `MemoryRuntime`, adapts `flush_session(session_id: str)`, provides `InProcessBackend.in_memory(**runtime_kwargs)`, maps runtime missing-resource errors plus missing `inspect_access`/`replay_access`/`replay_run` to SDK `NotFoundError`, maps invalid observability report requests to `BadRequestError`, and preserves `[]` for empty-list reads such as missing-run `get_steps`.
- **Unified client:** `MemTrace(backend)` forwards calls to any backend; `MemTrace.in_process(runtime)` and `MemTrace.in_memory(...)` provide convenient constructors; `write_event(...)` stamps `event_source="sdk"` only when the caller omitted an explicit source.
- **Tests:** `packages/python-sdk/tests/test_inprocess_backend.py` covers SDK golden path, structured retrieved context, inspect access, default SDK event source, explicit source preservation, backend-direct source preservation, existing-runtime wrapping, backend in-memory construction, missing-resource `NotFoundError`, observability-report `BadRequestError`, and empty-list read preservation.

## Latest Verification (2026-06-12 Phase 3.5 S2a)

- RED: `uv run --package memtrace-sdk --extra dev pytest packages/python-sdk/tests/test_inprocess_backend.py -q` -> failed during collection with `ImportError: cannot import name 'EventRole' from 'memtrace_sdk.types'`, proving the missing shared type contract.
- GREEN after review hardening: `uv run --package memtrace-sdk --extra dev pytest packages/python-sdk/tests/test_inprocess_backend.py -q` -> **10 passed**.
- SDK package tests: `uv run --package memtrace-sdk --extra dev pytest packages/python-sdk/tests -q` -> **11 passed**.
- Compile check: `uv run --extra dev python -m compileall -q apps/api/app packages/python-sdk/src` -> passed.
- Full regression: `uv run --extra dev pytest -q` -> **267 passed**.

## Implemented (Phase 3.5 SDK/LangGraph Adapter S0 — Packaging & workspace skeleton — 2026-06-12)

- **Workspace wiring:** root `pyproject.toml` now declares `packages/python-sdk` as a uv workspace member and maps `memtrace` to the local workspace package for SDK dependency resolution.
- **SDK package skeleton:** `packages/python-sdk/pyproject.toml` defines `memtrace-sdk` with `memtrace`, `pydantic`, and `httpx` dependencies, optional `langgraph` / `dev` extras, and the future `memtrace` console script.
- **Importable public stubs:** `memtrace_sdk` exports real placeholder symbols (`MemTrace`, `Backend`, `InProcessBackend`, `HttpBackend`, `MemTraceError`, `NotFoundError`, `BadRequestError`) so S2 can replace behavior without changing import paths.
- **CLI stub:** `memtrace_sdk.cli.main(...)` exists and raises a clear not-implemented message until S5 supplies the real CLI.
- **Pytest discovery:** SDK tests are part of the root suite; pytest uses importlib import mode to avoid collision between `apps/api/tests` and `packages/python-sdk/tests` packages.

## Latest Verification (2026-06-12 Phase 3.5 S0)

- RED: `uv run pytest packages/python-sdk/tests/test_imports.py -q` -> failed with `ModuleNotFoundError: No module named 'memtrace_sdk'`.
- GREEN: `uv run --package memtrace-sdk --extra dev pytest packages/python-sdk/tests/test_imports.py -q` -> **1 passed**.
- Workspace resolution: `uv sync` -> resolved workspace successfully.
- Import smoke: `uv run --package memtrace-sdk python -c "import memtrace_sdk; from memtrace_sdk import ..."` -> imported all public stubs.
- CLI stub smoke: `uv run --package memtrace-sdk memtrace` -> prints `memtrace CLI is not implemented yet (see SDK_ADAPTER_PLAN.md S5)`.
- Package build: `uv build --package memtrace-sdk` -> built `memtrace_sdk-0.1.0.tar.gz` and `memtrace_sdk-0.1.0-py3-none-any.whl` (local `dist/` artifacts removed after verification).
- Compile check: `uv run --extra dev python -m compileall -q apps/api/app packages/python-sdk/src` -> passed.
- Review: S0-focused review found no P0/P1/P2 defects; the only discovered pitfall was the already-fixed duplicate top-level `tests` package collection collision, now documented in `.ai/PITFALLS.md`.
- Full regression: first run found pytest collection collision for duplicate top-level `tests` packages; after `--import-mode=importlib`, `uv run --extra dev pytest -q` -> **257 passed**.

## Implemented (Phase 3.5 SDK/LangGraph Adapter S1 — event_source passthrough — 2026-06-12)

- **Request contract:** `WriteEventRequest` now exposes optional `event_source`, matching the already-persisted `AgentEvent.event_source` / ORM / SQL mapping contract.
- **Runtime passthrough:** `MemoryRuntime.write_event(...)` passes `request.event_source` into the created `AgentEvent`, so in-process and HTTP callers can stamp entrypoint origin without route changes.
- **Compatibility:** omitting `event_source` keeps `AgentEvent.event_source is None`, preserving existing behavior for all current demos, benchmarks, tests, and API callers.
- **S1 review:** diff-only review covered `apps/api/app/runtime/models.py` and `apps/api/app/runtime/memory_runtime.py`; no P0/P1/P2 defects found. Report: `/tmp/mem-trace_s1_review/report.html`.

## Latest Verification (2026-06-12 Phase 3.5 S1)

- RED: `uv run --extra dev pytest apps/api/tests/runtime/test_memory_runtime_trace.py::test_write_event_stamps_event_source apps/api/tests/runtime/test_memory_runtime_trace.py::test_write_event_event_source_defaults_none -q` -> **1 failed / 1 passed**, expected failure `None == "sdk"`.
- GREEN: same targeted command -> **2 passed**.
- Runtime trace regression: `uv run --extra dev pytest apps/api/tests/runtime/test_memory_runtime_trace.py -q` -> **13 passed**.
- Compile check: `uv run python -m compileall -q apps/api/app` -> passed.
- Full regression: `uv run --extra dev pytest -q` -> **256 passed**.

## Implemented (Failure-aware Negative Memory Injection I6 — doc sync/finalization — 2026-06-12)

- **Design-doc finalization:** `docs/design/FAILURE_AWARE_NEGATIVE_MEMORY_PLAN.md` now marks I1-I6 complete and records I6 verification. `docs/design/ROADMAP.md` §9.1 now marks the Failure-aware first batch complete and moves the active next-priority marker to Phase 3.5 SDK/LangGraph adapter / 6-strategy benchmark expansion.
- **Compaction cross-reference:** `docs/design/CONTEXT_COMPACTION_PLAN.md` now documents deferred C6/I7 failure-aware negative retained facts as a future cross-feature design, explicitly preserving current C0-C5 behavior.
- **Project-memory sync:** `AGENTS.md`, `.ai/PROJECT_STATE.md`, `.ai/REQUIREMENTS.md`, `.ai/IMPLEMENTATION_PLAN.md`, and `.ai/DECISIONS.md` are updated so new sessions no longer treat I6 as pending.
- **Review follow-up:** `.ai/OPEN_QUESTIONS.md` now records Failure-aware I1-I6 in the resolved Post-P2 order, `docs/design/CONTEXT_COMPACTION_PLAN.md` distinguishes historical C5 `8/8` from current global `10/10` acceptance, and `.ai/PITFALLS.md` records the acceptance-count drift trap.
- **Security review hardening:** explicit `RiskFlags.contains_secret` now hard-rejects as `secret` even for completed/active memories; `safe_observability_content(...)` uses explicit secret metadata/reject reasons before regex fallback; replay candidate key/value metadata is hidden for sanitized/unsafe/secret candidates to prevent raw failed command/secret leakage through observability payloads.
- **I7 still deferred:** this review added security hardening for existing failure-aware behavior only; I7 remains deferred because it touches compaction persisted snapshots and replay semantics.

## Latest Verification (2026-06-12 Failure-aware I6)

- Stale-reference check: no old I6-pending / I1-I5-only state references remain.
- Full implementation review found and fixed three security gaps: completed/active `contains_secret` memories were not hard-rejected, explicit secret metadata was not always honored by safe observability rendering, and replay candidate key/value metadata could leak raw unsafe failed command markers even when `content` was sanitized.
- TDD RED reproduced all three gaps, then targeted GREEN passed: `uv run pytest apps/api/tests/retrieval/test_gate.py::test_hard_reject_contains_secret_flag_even_when_completed -q`; `uv run pytest apps/api/tests/retrieval/test_packer_negative.py::test_safe_observability_content_honors_explicit_secret_metadata_without_regex_match apps/api/tests/retrieval/test_packer_negative.py::test_safe_observability_content_honors_contains_secret_flag_without_regex_match -q`; `uv run pytest apps/api/tests/observability/test_replay.py::test_replay_sanitizes_original_and_replayed_candidate_views_for_sanitized_failure -q`.
- Failure-aware related regression: `uv run python -m compileall -q apps/api/app && uv run pytest apps/api/tests/retrieval/test_gate.py apps/api/tests/retrieval/test_packer_negative.py apps/api/tests/retrieval/test_retrieval_flow.py apps/api/tests/observability/test_replay.py apps/api/tests/observability/test_metrics.py apps/api/tests/benchmark/test_runner.py apps/api/tests/api/test_dashboard.py -q` -> **103 passed**.
- Full regression: `uv run pytest -q` -> **254 passed**.
- Deterministic benchmark + reproducibility: `uv run python -m app.benchmark.runner --output-dir reports && bash scripts/reproduce.sh` -> **acceptance.passed=true (10/10 checks true)**.
- Review scope generation: bits-code-guard diff filter over `HEAD` produced 26 changed files, 11 runtime review files, and untracked `negative_evidence.py` / `test_packer_negative.py` / failure-aware plan were manually included as context. Report: `/tmp/mem-trace_failure_aware_review/report.html`.

## Implemented (Failure-aware Negative Memory Injection I5 — benchmark/evaluator expansion — 2026-06-11)

- **Benchmark cases:** `case_10_avoid_repeating_failed_attempt` proves safe failed npm attempts are retained as `avoided_attempts` negative evidence while final action remains `bun test`; `case_11_sanitized_failed_destructive_attempt` proves destructive rolled-back failures render only sanitized negative notices without raw `git push --force` / `rm -rf` leakage.
- **Evaluator split:** benchmark action/contamination now use only positive blocks; negative lesson retention and unsafe negative leakage are scored only from `avoided_attempts` / `source=negative_evidence` blocks.
- **Metrics + acceptance:** `CaseMetrics`, JSON/Markdown reports, persisted benchmark results, runner summary, and dashboard benchmark summary now expose present-gated failure-learning rates. Acceptance now has 10 checks including `variant_2_learns_from_failure_without_repeating` and `variant_2_sanitizes_destructive_failure_without_leakage`; total deterministic benchmark rows are 11 cases × 4 strategies = 44.
- **Review hardening:** I5 review fixed acceptance robustness by requiring the concrete case row and corresponding `*_present` flag for zero-rate / present-gated checks, so missing benchmark rows cannot make `cross_workspace_leakage_rate=0`, `positive_contamination_rate=0`, or `unsafe_negative_leakage_rate=0` pass vacuously. The tail `Next Recommended Action` was also updated from stale I5 guidance to I6.

## Latest Verification (2026-06-11 Failure-aware I5)

- RED observed before implementation: I5 tests failed because benchmark still had 9 cases / 36 results, `evaluate_case` did not accept negative-evidence scoring parameters, and acceptance lacked the two new checks.
- I5 targeted GREEN: `uv run pytest apps/api/tests/benchmark/test_runner.py::test_evaluator_keeps_negative_evidence_out_of_positive_contamination_and_action apps/api/tests/benchmark/test_runner.py::test_evaluator_scores_sanitized_negative_notice_without_raw_marker_leakage apps/api/tests/benchmark/test_runner.py::test_run_benchmark_writes_markdown_and_json_reports apps/api/tests/benchmark/test_runner.py::test_run_benchmark_meets_mvp_acceptance apps/api/tests/benchmark/test_runner.py::test_run_benchmark_persists_cases_and_results apps/api/tests/api/test_dashboard.py::test_dashboard_tables_endpoint_exposes_benchmark_and_runtime_rows -q` -> **6 passed**.
- Related regression: `uv run pytest apps/api/tests/retrieval/test_packer_negative.py apps/api/tests/retrieval/test_gate.py apps/api/tests/retrieval/test_retrieval_flow.py apps/api/tests/observability/test_replay.py apps/api/tests/observability/test_metrics.py apps/api/tests/benchmark/test_runner.py apps/api/tests/api/test_dashboard.py -q` -> **98 passed**.
- Compile check: `uv run python -m compileall -q apps/api/app` -> passed.
- Full regression: `uv run pytest -q` -> **249 passed**.
- Deterministic benchmark: `uv run python -m app.benchmark.runner --output-dir reports`; `reports/benchmark_results.json` -> **11 cases / 44 results**, `acceptance.passed=true` with **10/10** checks true.
- Review hardening targeted tests: `uv run pytest apps/api/tests/benchmark/test_runner.py::test_acceptance_requires_present_rows_for_failure_learning_checks apps/api/tests/benchmark/test_runner.py::test_acceptance_requires_present_rows_for_zero_leakage_checks -q` -> **2 passed**.
- Post-review benchmark/dashboard regression: `uv run pytest apps/api/tests/benchmark/test_runner.py apps/api/tests/api/test_dashboard.py -q` -> **14 passed**.
- Post-review related regression: `uv run pytest apps/api/tests/retrieval/test_packer_negative.py apps/api/tests/retrieval/test_gate.py apps/api/tests/retrieval/test_retrieval_flow.py apps/api/tests/observability/test_replay.py apps/api/tests/observability/test_metrics.py apps/api/tests/benchmark/test_runner.py apps/api/tests/api/test_dashboard.py -q` -> **100 passed**.
- Post-review full regression: `uv run pytest -q` -> **251 passed**.
- Post-review reproducibility: `uv run python -m app.benchmark.runner --output-dir reports && bash scripts/reproduce.sh` -> **acceptance.passed=true (10/10 checks true)**.

## Implemented (Failure-aware Negative Memory Injection I4 — inspect/replay/metrics sync — 2026-06-11)

- **Inspect access reconstruction:** `MemoryRuntime.inspect_access(...)` now treats only `accept/warn` as positive accepted memories, rebuilds `GateOutcome` snapshots from persisted gate logs, calls the shared `build_negative_evidence(...)`, and passes `negative_evidence` into `pack_context(...)` so inspected context blocks match the hot path instead of packing degraded failed memories as positive `tool_evidence`.
- **Replay original-view reconstruction:** `RetrievalReplayService._build_original_view(...)` reconstructs negative evidence through the shared builder, excludes `degrade` from positive accepted memories, passes negative evidence into packer, and emits a deterministic warning when the source memory needed for raw failed-attempt reconstruction is missing rather than trying to recover raw text from gate logs.
- **Replay severity semantics:** drift severity now treats `reject(*_sanitized) -> accept/degrade` as critical, `degrade -> accept/warn` as critical, and loss of negative evidence (`degrade -> reject`) as warning.
- **Observability metrics:** `ObservabilitySummary` and access/replay metrics now expose `degraded_negative_evidence_count`, `sanitized_failure_notice_count`, and `negative_evidence_block_count`; `degrade` remains excluded from positive `failed_branch_injected` semantics. `negative_evidence_block_count` follows rebuilt/visible block semantics rather than raw gate-log sum, so source-state dedupe and `max_blocks` truncation are reflected.
- **Review hardening:** post-I4 review fixed sanitized/unsafe raw content leaking through inspect/replay candidate views, added inspect warnings for missing negative-evidence source memories, tightened replay severity coverage for `reject(sanitized)->degrade`, added positive-context non-contamination assertions for replay, and clarified metrics/doc semantics for builder-deduped negative-evidence block counts.

## Latest Verification (2026-06-11 Failure-aware I4)

- RED observed before implementation: inspect_access I4 test failed with `tool_evidence` vs `avoided_attempts`; replay I4 tests failed because original reconstruction lacked `avoided_attempts`, sanitized reject drift was not critical, and missing source memories produced no negative-evidence warning; metrics I4 test failed with missing `degraded_negative_evidence_count`.
- I4 targeted GREEN after review hardening: `uv run pytest apps/api/tests/retrieval/test_retrieval_flow.py::test_inspect_access_unchanged_after_pack_result_refactor apps/api/tests/retrieval/test_retrieval_flow.py::test_variant_2_sanitizes_unsafe_failed_branch_negative_evidence apps/api/tests/retrieval/test_retrieval_flow.py::test_inspect_access_warns_without_raw_negative_evidence_when_source_memory_missing apps/api/tests/observability/test_replay.py::test_replay_reconstructs_negative_evidence_without_false_context_drift apps/api/tests/observability/test_replay.py::test_replay_sanitizes_original_and_replayed_candidate_views_for_sanitized_failure apps/api/tests/observability/test_replay.py::test_replay_marks_sanitized_reject_to_accept_as_critical apps/api/tests/observability/test_replay.py::test_replay_marks_sanitized_reject_to_degrade_as_critical apps/api/tests/observability/test_replay.py::test_replay_warns_without_raw_negative_evidence_when_source_memory_missing apps/api/tests/observability/test_metrics.py::test_negative_evidence_metrics_are_explicit_and_not_positive_injection apps/api/tests/observability/test_metrics.py::test_negative_evidence_block_count_uses_builder_dedupe_not_gate_count -q` -> **10 passed**.
- Related regression: `uv run pytest apps/api/tests/retrieval/test_packer_negative.py apps/api/tests/retrieval/test_gate.py apps/api/tests/retrieval/test_retrieval_flow.py apps/api/tests/retrieval/test_retrieval_trace.py apps/api/tests/observability/test_replay.py apps/api/tests/observability/test_metrics.py -q` -> **90 passed**.
- Compile check: `uv run python -m compileall -q apps/api/app` -> passed.
- Full regression: `uv run pytest -q` -> **248 passed**.
- Deterministic benchmark: `uv run python -m app.benchmark.runner --output-dir reports`; `reports/benchmark_results.json` -> `acceptance.passed=true` with existing **8/8** checks true.

## Implemented (Failure-aware Negative Memory Injection I3 — controller hot-path wiring — 2026-06-11)

- **Controller hot path:** `RetrievalController.trace(...)` now calls `build_negative_evidence(outcomes, memories_by_id, max_blocks=3)` with all gate outcomes, passes the resulting `NegativeEvidence` list into `pack_context(...)`, and keeps positive accepted memories restricted to `accept/warn` outcomes.
- **Count closure + profile metadata:** access counts remain schema-compatible (`candidate_count == accepted_count + rejected_count`, with `degrade` in not-positively-accepted/rejected). Gate/profile metadata records `degraded_count` and `hard_rejected_count`; context-packing metadata records retained `negative_evidence_count` / retained `sanitized_negative_evidence_count` plus `built_negative_evidence_count` / `dropped_negative_evidence_count`, so budget-dropped negative evidence is not reported as injected.
- **Warnings:** retrieval warnings distinguish safe failed/rolled-back lessons (`failed-branch memories injected as negative evidence`) from unsafe sanitized failures (`unsafe failed-branch memories were redacted into sanitized safety notices`).
- **Positive/negative evaluation split:** demo and benchmark contamination/action helpers now ignore `type="avoided_attempts"` / `source="negative_evidence"` blocks when judging positive context contamination or deciding final action, preserving existing acceptance semantics now that safe negative evidence intentionally contains failed npm text.
- **Compatibility bridge before I4:** legacy observability/replay `failed_branch_rejected` metrics count `*_degraded` / `*_sanitized` failure reasons as failed-branch exclusions so existing reports remain meaningful; replay `_ACCEPTED_DECISIONS` no longer treats `degrade` as positive accepted. Full inspect/replay original-view negative-evidence reconstruction and new explicit negative-evidence metrics remain I4.

## Latest Verification (2026-06-11 Failure-aware I3)

- RED observed before implementation: new controller tests failed because hot-path contexts had no `avoided_attempts` blocks.
- I3 targeted GREEN: `uv run pytest apps/api/tests/retrieval/test_retrieval_flow.py::test_variant_2_injects_safe_failed_branch_as_negative_evidence apps/api/tests/retrieval/test_retrieval_flow.py::test_variant_2_sanitizes_unsafe_failed_branch_negative_evidence -q` -> **2 passed**.
- Related retrieval regression: `uv run pytest apps/api/tests/retrieval/test_packer_negative.py apps/api/tests/retrieval/test_gate.py apps/api/tests/retrieval/test_retrieval_flow.py apps/api/tests/retrieval/test_retrieval_trace.py -q` -> **66 passed / 1 xfailed**. The xfail documents the known I4 gap: `inspect_access` reconstructs positive context without the shared negative-evidence builder.
- Full regression: `uv run pytest -q` -> **238 passed / 1 xfailed**.
- Compile check: `uv run python -m compileall -q apps/api/app` -> passed.
- Deterministic benchmark: `uv run python -m app.benchmark.runner --output-dir reports`; `reports/benchmark_results.json` -> `acceptance.passed=true` with existing **8/8** checks true and `variant_2.failed_branch_contamination_rate=0.0 < baseline_1=0.1111`.
- Final I3 review: bits-code-guard scoped review found two issues (replay `_ACCEPTED_DECISIONS` still included `degrade`; controller counted built rather than retained negative evidence for profile/warnings under budget pressure). Both were fixed, then an independent final reviewer pass found **0 P0 / 0 P1 / 0 P2** defects. Non-blocking I4 follow-up remains: inspect_access/replay original views should reconstruct `avoided_attempts` through the shared builder and metrics should expose explicit negative-evidence counters.

## Implemented (Failure-aware Negative Memory Injection I2 — NegativeEvidence builder + packer avoided_attempts — 2026-06-11)

- **Runtime DTO:** `NegativeEvidence` is now part of the runtime model vocabulary with source memory/state ids, memory type, branch status, mode (`raw_failed_attempt` / `sanitized_risk_notice`), risk kind, reason, safe text, and id-only provenance.
- **Shared builder:** `app.retrieval.negative_evidence.build_negative_evidence(...)` is the single construction path for controller/inspect/replay follow-ups. It accepts all `GateOutcome` values plus `memories_by_id`, derives raw negative evidence from `degrade`, derives sanitized notices from `*_sanitized` rejects, applies secret redaction fallback, re-checks unsafe flags even if a drifted input outcome says `degrade`, enforces risk-kind priority (`secret > destructive > tool_sensitive > unknown`), dedupes by `source_state_node_id` with `tool_evidence > working_state` priority, and truncates via `max_blocks`.
- **Packer rendering:** `pack_context(..., negative_evidence=None)` now accepts already-safe `NegativeEvidence` items and renders ordinary `avoided_attempts` blocks. Raw failed attempts receive the explicit `do NOT re-execute` negative-evidence frame; sanitized notices render only fixed safe templates. `avoided_attempts` sorts after project memory/constraints and before tool evidence, and is intentionally not protected so budget pressure can drop it before protected context.
- **Plan sync:** `docs/design/FAILURE_AWARE_NEGATIVE_MEMORY_PLAN.md` I2 checkboxes are ticked; `docs/design/ROADMAP.md` §9.1 marks the packer `avoided_attempts` block complete and notes controller/inspect/replay wiring remains I3-I4.

## Latest Verification (2026-06-11 Failure-aware I2)

- RED observed before implementation: `uv run pytest apps/api/tests/retrieval/test_packer_negative.py -q` failed during collection with `ModuleNotFoundError: No module named 'app.retrieval.negative_evidence'`.
- I2 targeted GREEN after review hardening: `uv run pytest apps/api/tests/retrieval/test_packer_negative.py apps/api/tests/retrieval/test_gate.py -q` -> **35 passed**.
- Compile check: `uv run python -m compileall -q apps/api/app` -> passed.
- Known follow-up before full retrieval regression: `uv run pytest apps/api/tests/retrieval/test_packer_negative.py apps/api/tests/retrieval/test_gate.py apps/api/tests/retrieval/test_retrieval_flow.py -q` currently reports **59 passed / 3 expected failures** because I3-I4 are not implemented yet: controller does not yet pass `negative_evidence` into `pack_context`, warnings/count/profile metadata are not updated, and inspect_access still needs accepted/degraded decision sync.

**Maintenance rule:** after completing meaningful work, update this file with current progress/verification and tick or annotate the corresponding `docs/design/ROADMAP.md` checkbox/sub-checkbox. Do not leave progress only in chat history.

## Implemented (Failure-aware Negative Memory Injection I1 — gate three-way + safe/unsafe split — 2026-06-11)

- **Gate config switch:** `GateConfig.enable_failure_learning` defaults to `False`; `GateConfig.for_strategy(...)` enables it only for `variant_2`, while `baseline_0`, `baseline_1`, and `variant_1` keep failure learning disabled.
- **Three-way gate semantics:** `GateOutcome.accepted` now means positive context only (`accept` / `warn`), and `GateOutcome.degraded` identifies `degrade` decisions for the future negative-evidence channel.
- **Safe vs unsafe failed split:** with failure learning enabled, safe `failed` / `rolled_back` memories now return `decision=degrade` with `failed_branch_degraded` / `rolled_back_degraded`; unsafe failed memories (`secret`, `contains_secret`, `destructive_command`, `tool_sensitive`, or `production_env`) remain hard `reject` with `failed_branch_sanitized` / `rolled_back_sanitized`. Default config still hard-rejects failed branches with the previous `failed_branch` / `rolled_back` reasons.
- **Review hardening:** post-implementation review fixed the `baseline_0` config contract so failure learning is enabled only for `variant_2`, and expanded I1 tests to cover `baseline_0`, `contains_secret`, and unsafe `rolled_back` sanitized behavior.
- **Plan sync:** `docs/design/FAILURE_AWARE_NEGATIVE_MEMORY_PLAN.md` I1 checkboxes are ticked; `docs/design/ROADMAP.md` §9.1 marks Gate three-way output complete and notes that packer/controller/replay/metrics wiring remains I2-I4.

## Latest Verification (2026-06-11 Failure-aware I1)

- RED observed before implementation: `uv run pytest apps/api/tests/retrieval/test_gate.py -q` failed on missing `GateConfig.enable_failure_learning` and missing `GateOutcome.degraded` / `degrade` behavior (5 failed, 9 passed).
- I1 targeted GREEN: `uv run pytest apps/api/tests/retrieval/test_gate.py -q` -> **28 passed** after review hardening.
- Compile check: `uv run python -m compileall -q apps/api/app` -> passed.
- Known follow-up before full retrieval regression: `uv run pytest apps/api/tests/retrieval/test_gate.py apps/api/tests/retrieval/test_retrieval_flow.py -q` currently has expected downstream failures because I3-I4 are not implemented yet: the controller does not pass `NegativeEvidence`/`avoided_attempts` into the hot path, and inspect/replay/metrics still need their accepted/degraded decision sync per the plan.

## Implemented (Context Compaction C0 — PackResult refactor — 2026-06-11)

- **Structured pack result:** `app.retrieval.packer.PackResult` now wraps packed blocks, used tokens, and `pre_compaction_tokens`, with C1-ready empty/default fields for `dropped_blocks`, `notice`, and `retained_constraints`.
- **Behavior-preserving callsite migration:** `pack_context(...)` returns `PackResult`; the hot-path trace in `RetrievalController`, `MemoryRuntime.inspect_access`, replay original-view reconstruction, and direct packer tests all consume `.blocks` / `.used` explicitly. No tuple compatibility shim was kept.
- **C0 plan sync:** `docs/design/CONTEXT_COMPACTION_PLAN.md` C0 checkboxes are ticked. ROADMAP §9 remains unchecked for C1+ because user-visible compaction behavior is not implemented yet.

## Latest Verification (2026-06-11 Context Compaction C0)

- RED observed before implementation: C0 tests failed on missing `PackResult` import and tuple return lacking `.blocks`.
- Targeted C0 packer tests: `uv run pytest apps/api/tests/retrieval/test_retrieval_flow.py::test_pack_context_emits_dynamic_key_project_memory apps/api/tests/retrieval/test_retrieval_flow.py::test_pack_result_preserves_existing_behavior_when_no_truncation apps/api/tests/retrieval/test_retrieval_flow.py::test_pack_result_reports_pre_compaction_tokens_when_truncated apps/api/tests/retrieval/test_retrieval_flow.py::test_inspect_access_unchanged_after_pack_result_refactor -q` -> **4 passed**.
- Retrieval + replay regression: `uv run pytest apps/api/tests/retrieval/test_retrieval_flow.py apps/api/tests/observability/test_replay.py -q` -> **23 passed**.
- Full regression: `uv run pytest -q` -> **152 passed**.
- C0 re-review (2026-06-11): bits-code-guard scoped review covered 4 production files (`packer.py`, `controller.py`, `memory_runtime.py`, `replay.py`) and found **0 defects**. A prior reviewer note identified a weak test assertion for `pre_compaction_tokens`; the test was strengthened to independently compute the all-candidate token total via an ample-budget pack.
- Final verification after re-review and memory sync: `uv run python -m compileall -q apps/api/app`; `uv run pytest apps/api/tests/retrieval/test_retrieval_flow.py apps/api/tests/observability/test_replay.py -q` -> **23 passed**; `uv run pytest -q` -> **152 passed**.

## Implemented (Context Compaction C1 — budget-aware packer compensation — 2026-06-11)

- **Default-on over-budget compensation:** `pack_context` now splits protected vs ordinary blocks, preserves protected blocks by deterministic truncation instead of silent drop, and records dropped ordinary blocks in `PackResult.dropped_blocks`.
- **Retained key=value facts:** added shared `RetainedFact` model and pure packer helpers to extract retained facts from dropped blocks via `MemoryItem.key/value` (not rendered text parsing), whitelist `project.*` / `endpoint.*` / `profile.*` / `procedure.*`, and render `compacted_constraints` blocks under the token budget.
- **Audit notice:** over-budget packing emits a reserved `compaction_notice` block (`kind=budget_notice`) and keeps `PackResult.notice` populated when ordinary blocks are dropped.
- **Controller observability surface:** `RetrievalController.trace` writes `pre_compaction_tokens`, `actual_tokens`, `dropped_count`, `compression_ratio`, `notice_kind`, retained constraints, and dropped block snapshots into the `context_packing` profile metadata; returned contexts include `context budget exceeded: omitted N blocks` warnings when applicable. Durable compaction logs were added in the subsequent C2 slice.
- **Safety guard:** failed/rolled_back/stale/secret/tool-sensitive content still cannot enter compaction because C1 only compacts already gate-accepted blocks; regression coverage asserts failed-branch memories are absent from dropped/retained compaction outputs.
- **Review hardening:** post-implementation review found and fixed two C1 edge bugs: the configured `compaction_notice_reserve_tokens` was not wired into `pack_context`, and a protected block could consume the full budget so `PackResult.notice` was set while no `compaction_notice` block appeared. The hot path, access inspection, and replay reconstruction now pass the configured reserve; packer truncates earlier packed blocks as needed so the notice is present in returned blocks when ordinary blocks are dropped.

## Latest Verification (2026-06-11 Context Compaction C1)

- RED observed before implementation: new C1 tests failed on missing `compacted_constraints`, missing `compaction_notice`, and missing context budget warning/profile metadata.
- Targeted C1 tests: `uv run pytest apps/api/tests/retrieval/test_retrieval_flow.py::<C1 tests> -q` -> **11 passed** after adding review-regression coverage for custom reserve wiring and protected-full-budget notice emission.
- Retrieval + replay regression: `uv run pytest apps/api/tests/retrieval/test_retrieval_flow.py apps/api/tests/observability/test_replay.py -q` -> **34 passed**.
- Compile + full regression + deterministic benchmark: `uv run python -m compileall -q apps/api/app && uv run pytest -q && uv run python -m app.benchmark.runner --output-dir reports` -> **163 passed**, benchmark `acceptance.passed=true` with **7/7** checks true.

## Implemented (Context Compaction C2 — durable compaction logs + observability/replay wiring — 2026-06-11)

- **Durable compaction record:** added `CompactionKind`, `CompactionProvider`, `ContextCompactionLog`, and internal `PendingCompactionLog`; `budget_notice` compaction records now capture per-event `pre_tokens`, `post_tokens`, dropped block count, compression ratio, retained facts, source memory/event/state ids, warnings, and summary text.
- **Repository + SQL persistence:** `Repository` / `InMemoryRepository` now expose `add_compaction_log` and `list_compaction_logs(access_id=..., run_id=..., workspace_id=...)`; SQL adds `ContextCompactionORM`, mappings, and Alembic migration `0005_context_compaction.py` after `0004_phase3a_observability`.
- **Single persistence path:** `PackResult.pending_compaction_logs` flows into `RetrievalPipelineTrace.pending_compaction_logs`; `RetrievalController._persist_trace` materializes every pending record only after the `MemoryAccessLog.access_id` exists, avoiding split-brain writes.
- **Observability metrics:** `build_access_observability_metrics` and `build_observability_summary` now load compaction logs and expose `compaction_trigger_rate`, `avg_compression_ratio`, `total_dropped_blocks`, `history_summary_count`, plus strategy-level compaction aggregates.
- **Replay wiring:** access replay payloads include persisted `compaction_logs`; replay compares persisted vs replayed `budget_notice` dropped counts and emits deterministic `compaction_drift` warnings when they diverge. Replay still performs no writes and does not rerun summarizers.
- **Review hardening:** post-implementation review found a provenance gap where non-retained dropped blocks (e.g. episodic/tool evidence) did not contribute source event/state ids to the durable log; fixed by collecting provenance from all dropped block/memory inputs, with regression coverage for the episodic source id.

## Latest Verification (2026-06-11 Context Compaction C2)

- RED observed before implementation: C2 tests failed on missing `CompactionKind` / `ContextCompactionLog` imports and missing migration/model/repository plumbing.
- Targeted C2 tests: `uv run pytest apps/api/tests/storage/test_migrations.py apps/api/tests/observability/test_compaction_log.py apps/api/tests/observability/test_metrics.py::test_access_metrics_cover_all_quality_safety_signals apps/api/tests/observability/test_metrics.py::test_summary_filters_and_by_strategy_rates apps/api/tests/observability/test_replay.py::test_replay_detects_compaction_drift_when_dropped_count_changes -q` -> **10 passed**.
- Observability/replay/report regression: `uv run python -m compileall -q apps/api/app && uv run pytest apps/api/tests/observability/test_metrics.py apps/api/tests/observability/test_replay.py apps/api/tests/observability/test_compaction_log.py apps/api/tests/storage/test_migrations.py apps/api/tests/api/test_observability.py apps/api/tests/observability/test_reports.py -q` -> **34 passed**.
- Post-review targeted regression: `uv run python -m compileall -q apps/api/app && uv run pytest apps/api/tests/observability/test_compaction_log.py apps/api/tests/observability/test_metrics.py apps/api/tests/observability/test_replay.py apps/api/tests/storage/test_migrations.py -q` -> **19 passed**; issue-validator re-review found **0 defects**.
- Full regression: `uv run pytest -q` -> **169 passed**.
- Deterministic benchmark: `uv run python -m app.benchmark.runner --output-dir reports`; `reports/benchmark_results.json` -> `acceptance.passed=true` with **7/7** checks true.

## Implemented (Context Compaction C3 — SummarizerProvider rule/LLM dual path — 2026-06-11)

- **Provider seam:** added `app.memory.summarizer_provider` with `SummarizeRequest`, `SummarizeResult`, async `SummarizerProvider` Protocol, and `SummarizerValidationError`.
- **Deterministic fallback:** `RuleSummarizerProvider` is the default and renders summaries from structured `RetainedFact` inputs, enforces `summary_budget_tokens` with deterministic truncation, and never raises.
- **OpenAI-compatible LLM path:** `LLMSummarizerProvider` calls `/chat/completions` with a fixed compaction prompt, `temperature=0`, optional `response_format=json_object`, markdown-fence tolerance, and schema parsing. HTTP/JSON/schema/validation failures raise for runtime fallback.
- **Conservative validation:** LLM retained facts must be drawn from structured `must_retain_facts` and must cover all required fact identities; invented retained facts, dropped identities, or provenance drift raise `SummarizerValidationError`. Provider validation also recomputes `post_tokens` locally before enforcing budget, requires top-level source ids to preserve the request's full source-id sets, rejects invented/misbound retained-fact memory/run/step/event/state provenance, and deliberately does not parse free-form block text as allowed key=value facts (so negated/risky mentions such as "do not use project.runtime=npm" are not accepted as retained facts).
- **Config + DI:** added `compaction_enabled`, `llm_summarizer_enabled`, `compaction_history_token_threshold`, `compaction_summary_budget_tokens`, and `compaction_timeout_ms`; FastAPI deps now wire a deterministic rule provider by default, an LLM provider only when enabled with `MEMTRACE_LLM_API_KEY`, and rule fallback with a warning when enabled without a key.
- **Runtime fallback helper:** `MemoryRuntime` accepts a `summarizer_provider` and exposes `_summarize(request, deadline_ms=...)`, guarded by `asyncio.wait_for`; timeout/failure logs and falls back to `RuleSummarizerProvider` with `provider=fallback_rule` for future C4 compaction logs.

## Latest Verification (2026-06-11 Context Compaction C3)

- RED observed before implementation: C3 tests failed on missing `app.memory.summarizer_provider` and missing `_build_summarizer_provider` import from `app.api.deps`.
- Targeted C3 tests: `uv run pytest apps/api/tests/memory/test_summarizer_provider.py apps/api/tests/runtime/test_summarizer_fallback.py -q` -> **19 passed**.
- Related regression: `uv run python -m compileall -q apps/api/app && uv run pytest apps/api/tests/memory apps/api/tests/runtime/test_summarizer_fallback.py apps/api/tests/runtime/test_llm_extraction_flow.py apps/api/tests/api/test_observability.py -q` -> **69 passed**.
- Full regression: `uv run pytest -q` -> **188 passed**.
- Deterministic benchmark: `uv run python -m app.benchmark.runner --output-dir reports`; `reports/benchmark_results.json` -> `acceptance.passed=true` with **7/7** checks true.
- Final C3 review: bits-code-guard scoped review plus two independent read-only reviewer passes covered provider schema, rule/LLM path, DI, runtime fallback, validation/provenance, default benchmark behavior, and tests. Review-discovered issues were fixed with RED/GREEN tests: LLM cannot omit top-level source ids, cannot misbind a retained fact to another allowed source, cannot drop same-key/value required identities, and rule fallback no longer crashes when sorting mixed `None`/string provenance identities. Final reviewer pass found **0 Critical / 0 Important / 0 Minor** issues.

## Implemented (Context Compaction C4 — in-flight rolling history summary — 2026-06-11)

- **Config-gated rolling fold:** `MemoryRuntime.retrieve_context` now checks `compaction_enabled` before retrieval; when active-path event history exceeds `compaction_history_token_threshold`, it summarizes safe active-path history into a protected `history_summary` prelude block.
- **Safety filters:** raw history assembly includes only active-path nodes and skips failed/rolled_back nodes, redacted secret events, and risky/destructive tool results. Retained `MemoryItem` facts additionally require retrievable lifecycle status, non-failed branch status, non-stale expiry, non-secret sensitivity, and non-risky flags.
- **Single compaction-log persistence path preserved:** C4 creates access-id-less `PendingCompactionLog(kind=history_summary)` records and passes them into `RetrievalController.retrieve_with_prelude`; successful retrievals materialize them only in `_persist_trace` after the `MemoryAccessLog.access_id` exists, sharing the C2 path with `budget_notice` logs. If retrieval itself times out after a history fold was prepared, the timeout access is persisted for inspectability but the prepared `history_summary` log is intentionally not materialized because no summary block was returned.
- **Protected context injection:** `pack_context` accepts `prelude_blocks`; `history_summary` participates in the protected tier and is truncated rather than silently dropped under tiny budgets.
- **Replay stability:** replay reconstructs `history_summary` prelude blocks from persisted `ContextCompactionLog` rows and passes corresponding pending snapshots into the side-effect-free trace, so replay never reruns the summarizer provider.
- **Degradation:** the full history-fold attempt (state/event/memory scans plus provider call) is bounded by `compaction_timeout_ms`; timeout/error logs a warning, adds `history compaction skipped: <reason>` to retrieval warnings, and proceeds with normal retrieval/no-fold instead of returning an empty context.

## Latest Verification (2026-06-11 Context Compaction C4)

- RED observed before implementation: new C4 tests failed on missing `history_summary` block/log persistence/replay behavior and missing skip warnings.
- Targeted C4 tests: `uv run pytest apps/api/tests/runtime/test_context_compaction.py -q` -> **14 passed** after review hardening for failed tool results, destructive tool calls, quarantined/source-less retained facts, whole-fold timeout coverage, and retrieval-timeout access persistence without logging a summary that was not returned.
- C4 related regression: `uv run pytest apps/api/tests/runtime/test_context_compaction.py apps/api/tests/runtime/test_summarizer_fallback.py apps/api/tests/memory/test_summarizer_provider.py apps/api/tests/observability/test_compaction_log.py apps/api/tests/observability/test_replay.py apps/api/tests/retrieval/test_retrieval_flow.py -q` -> **71 passed**.
- Compile + full regression + deterministic benchmark: `uv run python -m compileall -q apps/api/app && uv run pytest -q && uv run python -m app.benchmark.runner --output-dir reports` -> **202 passed**; `reports/benchmark_results.json` -> `acceptance.passed=true` with **7/7** checks true.

## Implemented (Context Compaction C5 — benchmark/report/replay/project-memory sync — 2026-06-11)

- **Retention-quality benchmark:** added `case_9_over_budget_compaction`, which forces tiny-budget packing over mixed project/endpoint/episodic memories and includes rolled-back, stale, secret, and destructive negative samples.
- **Benchmark metrics + acceptance:** evaluator/runner now expose `compaction_trigger_rate`, `constraint_retention_hit_rate`, `unsafe_compaction_leakage_rate`, and `avg_compression_ratio`; benchmark acceptance adds `variant_2_retains_constraints_under_compaction` and result counts update to 9 cases × 4 strategies = 36.
- **Reports + dashboard:** JSON/Markdown/HTML observability reports now include a Compaction section with per-access kind/provider/pre/post/dropped/retained facts; dashboard benchmark summaries include the new compaction rates.
- **Replay coverage:** added an end-to-end drift test where a persisted over-budget compaction access is replayed after source memories change, producing deterministic `compaction_drift` on dropped count.
- **Docs sync:** `README.md`, `docs/design/ROADMAP.md`, `docs/design/CONTEXT_COMPACTION_PLAN.md`, and `.ai/` project memory now mark the C5 loop complete.
- **Final review hardening:** C5 review fixed retention scoring to read durable `ContextCompactionLog.retained_facts`, strengthened compaction acceptance to require an actual trigger, made the no-memory-baseline check case-8-specific, present-gated cross-workspace benchmark leakage, filtered compaction logs by access workspace/run in benchmark/metrics/replay/reports, escaped Markdown report content, aligned observability `workspace_leakage` with accepted-context leakage semantics, and made case_9 unsafe negative samples query-relevant enough to prove gate/compaction safety.

## Latest Verification (2026-06-11 Context Compaction C5)

- RED observed before implementation: C5 tests failed on missing case 9 / 36-result benchmark output, missing compaction summary fields and acceptance check, missing report `compactions` section, and stale dashboard counts.
- Targeted C5 GREEN: `uv run pytest apps/api/tests/benchmark/test_runner.py apps/api/tests/observability/test_reports.py::test_report_includes_compaction_section_with_retained_facts apps/api/tests/api/test_dashboard.py::test_dashboard_tables_endpoint_exposes_benchmark_and_runtime_rows -q` -> **5 passed**.
- Replay C5 GREEN: `uv run pytest apps/api/tests/observability/test_replay.py::test_replay_detects_compaction_drift_when_dropped_count_changes apps/api/tests/observability/test_replay.py::test_replay_detects_compaction_drift_from_persisted_over_budget_access -q` -> **2 passed**.
- C5 related regression: `uv run python -m compileall -q apps/api/app && uv run pytest apps/api/tests/benchmark/test_runner.py apps/api/tests/observability/test_reports.py apps/api/tests/observability/test_replay.py apps/api/tests/observability/test_metrics.py apps/api/tests/api/test_dashboard.py -q` -> **33 passed**.
- Full regression: `uv run python -m compileall -q apps/api/app && uv run pytest -q` -> **210 passed**.
- Deterministic benchmark: `uv run python -m app.benchmark.runner --output-dir reports`; `reports/benchmark_results.json` -> `acceptance.passed=true` with **8/8** checks true, including `variant_2_retains_constraints_under_compaction=true`; `variant_2` summary includes `compaction_trigger_rate=1.0`, `constraint_retention_hit_rate=1.0`, `unsafe_compaction_leakage_rate=0.0`, and `avg_compression_ratio=0.0738`.
- Reproducibility script: `./scripts/reproduce.sh` -> passed, printed `acceptance.passed=true (8/8 checks true)`.

## Planned (Phase 3-A — Retrieval Replay & Observability — 2026-06-10)

- **Plan file:** `docs/design/P3A_IMPLEMENTATION_PLAN.md`.
- **Scope:** `GET /v1/replay/access/{access_id}`, `GET /v1/replay/runs/{run_id}`, observability summary API, side-effect-free retrieval trace/replay service, `MemoryAccessLog.top_k`, eval tables (`eval_cases`, `eval_runs`, `eval_results`), Quality/Safety metrics, expanded `ProfilePhase`, dashboard table extension, and generated `reports/observability_report.{json,md,html}`.
- **Non-goals:** no React dashboard, no Celery/Redis, no ES/Neo4j replay, no LLM judge, no hosted auth, and no immutable historical candidate snapshots in the first slice.
- **Execution:** implement `docs/design/P3A_IMPLEMENTATION_PLAN.md` §11 issue-by-issue; run targeted tests per issue; final verification requires `uv run pytest -q` and deterministic benchmark acceptance.

## Implemented (Phase 3-A Issue 1 — access fidelity + eval persistence — 2026-06-10)

- **Access fidelity:** `MemoryAccessLog.top_k: int = 10` added and persisted through hot-path retrieval, in-memory repository, SQL ORM/repository mappings, and migration default/backfill (`migrations/versions/0004_phase3a_observability.py`).
- **Eval persistence schema:** added `EvalCaseRecord`, `EvalRunRecord`, `EvalResultRecord`; repository protocol methods; `InMemoryRepository` and `SqlRepository` add/list/update support; SQL ORM tables `eval_cases`, `eval_runs`, `eval_results` with planned indexes.
- **Dashboard table extension (Issue 1 scope):** `DashboardTables` now exposes `eval_cases`, `eval_runs`, and `eval_results`; workspace-filtered dashboard calls filter eval results through the matching eval runs to avoid cross-workspace result leakage. `observability_summary` remains for later Phase 3-A Issues.
- **Plan/backlog sync:** `docs/design/P3A_IMPLEMENTATION_PLAN.md` Issue 1 checkboxes are ticked; `docs/design/ROADMAP.md` Phase 3-A eval-table item is ticked.

## Latest Verification (2026-06-10 Phase 3-A Issue 1)

- TDD RED for missing eval/top_k schema: `uv run pytest apps/api/tests/observability/test_eval_records.py apps/api/tests/storage/test_migrations.py -q` initially failed on missing `EvalCaseRecord` / `EvalCaseORM`.
- Additional RED for workspace filtering: `uv run pytest apps/api/tests/observability/test_eval_records.py::test_dashboard_tables_filters_eval_results_by_workspace -q` failed because `eval_results` included another workspace's result; fixed by filtering results through workspace-scoped eval runs.
- Targeted regression: `uv run pytest apps/api/tests/observability/test_eval_records.py apps/api/tests/storage/test_migrations.py apps/api/tests/api/test_dashboard.py apps/api/tests/retrieval/test_retrieval_flow.py -q` -> **20 passed**.
- Review: spec compliance PASS; code quality APPROVED after the workspace-filtering fix.

## Implemented (Phase 3-A Issue 2 — side-effect-free retrieval trace pipeline — 2026-06-10)

- **Trace structures:** `RetrievalCandidateTrace` captures each candidate memory plus lexical/vector/relevance/state-match score components; `RetrievalPipelineTrace` captures the in-memory access record, active state/path, candidates, gate outcomes, accepted memories, packed context blocks, warnings, token usage, and per-phase profile summaries.
- **Side-effect-free pipeline:** `RetrievalController.trace(...)` now runs candidate selection -> gate -> context packing without creating access/gate/profile rows and without mutating `MemoryItem.access_count`. It preserves request fidelity, including `access_record.top_k = request.top_k`.
- **Hot-path refactor:** `_retrieve_impl` now calls `trace(...)`, then `_persist_trace(...)`, then `_bump_access_counts(...)`, and returns the same `MemoryContext` shape as before. Timeout behavior still wraps only `retrieve(...)`, so future replay can call `trace(...)` directly without the hot-path timeout/persistence side effects.
- **Candidate scoring fidelity:** `_select_candidates` now retains lexical and vector component scores while preserving the existing blended relevance formula and project-constraint fallback behavior.
- **Plan/backlog sync:** `docs/design/P3A_IMPLEMENTATION_PLAN.md` Issue 2 checkboxes and related acceptance items are ticked; `docs/design/ROADMAP.md` Phase 3-A Retrieval Replay item is annotated that the trace-pipeline prerequisite is complete while replay service/API remain pending.

## Latest Verification (2026-06-10 Phase 3-A Issue 2)

- TDD RED for missing trace pipeline: `uv run pytest apps/api/tests/retrieval/test_retrieval_trace.py -q` failed on `AttributeError: 'RetrievalController' object has no attribute 'trace'`.
- Targeted regression: `uv run pytest apps/api/tests/retrieval/test_retrieval_trace.py apps/api/tests/retrieval/test_retrieval_flow.py -q` -> **16 passed**.
- Full regression: `uv run pytest -q` -> **118 passed**.
- Deterministic benchmark: `uv run python -m app.benchmark.runner --output-dir reports`; generated `reports/benchmark_results.json` with `acceptance.passed=true`.

## Implemented (Phase 3-A Issue 3 — replay service + diff semantics — 2026-06-10)

- **Replay models:** added public replay response models (`ReplayCandidateView`, `ReplayGateDecisionView`, `ReplayDiffItem`, `ReplayRetrievalResult`, `RunReplayResult`) for access-level and run-level replay payloads.
- **Replay service:** added `app.observability.replay.RetrievalReplayService`, which loads original `MemoryAccessLog` + `MemoryGateLog` evidence, reconstructs the original candidate/gate/context view, reruns `RetrievalController.trace(...)` with the original request parameters, and returns original/replayed views, warnings, access metrics, and stable-sorted diffs.
- **Diff semantics:** implemented candidate added/removed/order drift, relevance/final/state score drift, decision/reject-reason drift, context block added/removed/order drift, token usage drift, and missing memory/run/step integrity diffs. Severity ordering is deterministic (`critical` before `warning` before `info`); dangerous rejected→accepted drifts are critical, accepted→rejected/order/score/token drifts are warnings.
- **No-side-effect guarantee:** replay calls the side-effect-free trace pipeline directly and does not create access/gate/profile rows, does not flush buffered extraction, and does not mutate `MemoryItem.access_count`.
- **Runtime facade:** `MemoryRuntime.replay_access(access_id)` and `MemoryRuntime.replay_run(run_id)` now expose the service for Issue 4 API wiring.
- **Plan/backlog sync:** `docs/design/P3A_IMPLEMENTATION_PLAN.md` Issue 3 checkboxes and replay acceptance items are ticked/annotated; `docs/design/ROADMAP.md` Phase 3-A Retrieval Replay item is annotated that service + diff semantics are complete while HTTP APIs remain pending.

## Latest Verification (2026-06-10 Phase 3-A Issue 3)

- TDD RED for missing replay facade/service: `uv run --extra dev pytest apps/api/tests/observability/test_replay.py -q` initially failed on `AttributeError: 'MemoryRuntime' object has no attribute 'replay_access'` / `replay_run`.
- Targeted regression: `uv run --extra dev pytest apps/api/tests/observability/test_replay.py apps/api/tests/retrieval/test_retrieval_trace.py apps/api/tests/retrieval/test_retrieval_flow.py -q` -> **23 passed**.
- Full regression: `uv run --extra dev pytest -q` -> **125 passed**.

## Implemented (Phase 3-A Issue 4 — replay/observability APIs — 2026-06-10)

- **Replay APIs:** added `GET /v1/replay/access/{access_id}` returning `ReplayRetrievalResult` and `GET /v1/replay/runs/{run_id}` returning `RunReplayResult`, both backed by the existing side-effect-free replay service/runtime facade.
- **HTTP error semantics:** missing access maps to `404 access not found`; missing original run maps to `404 run not found`; run-level replay validates the run exists before replaying its accesses.
- **Observability summary API:** added `GET /v1/observability/summary?workspace_id=&run_id=` returning `ObservabilitySummary` with deterministic counters from persisted access/gate logs. Workspace leakage is counted from all candidate memories represented by gate logs (not only accepted memories), matching the Phase 3-A metric semantics. This is the minimal Issue 4 endpoint wiring; Issue 5 remains responsible for profiler phase expansion and broader Quality/Safety metric hardening.
- **Tests:** added `apps/api/tests/api/test_observability.py` covering replay access/run endpoints, 404 mappings, and the summary endpoint.
- **Plan/backlog sync:** `docs/design/P3A_IMPLEMENTATION_PLAN.md` Issue 4 checkboxes are ticked; `docs/design/ROADMAP.md` Phase 3-A Retrieval Replay is marked complete because HTTP APIs are now wired.

## Latest Verification (2026-06-10 Phase 3-A Issue 4)

- TDD RED for missing API routes: `uv run pytest apps/api/tests/api/test_observability.py -q` -> **6 failed** with route-level `404 Not Found` before implementation.
- Targeted regression: `uv run pytest apps/api/tests/api/test_observability.py apps/api/tests/observability/test_replay.py apps/api/tests/api/test_dashboard.py -q` -> **15 passed**.
- Full regression: `uv run pytest -q` -> **132 passed**.

## Implemented (Phase 3-A Issue 5 — Quality/Safety metrics + profiler phase expansion — 2026-06-10)

- **Profiler phase expansion:** `ProfilePhase` now preserves existing `retrieval`, `gate`, and `context_packing` values and adds architecture-aligned `ingestion`, `construction`, `rerank`, `generation`, `maintenance`, `quality`, and `safety` values.
- **Access-level metrics helper:** `app.observability.metrics.build_access_observability_metrics(...)` is public via `__all__` and computes candidate/accepted/rejected counts, tokens/latency, failed-branch rejection/injection, stale rejection/injection, tool-sensitive/destructive blocking, risk blocking, workspace mismatch/leakage, and superseded injection from persisted access/gate records plus candidate/accepted memory views.
- **Summary hardening:** `build_observability_summary(repo, workspace_id=None, run_id=None)` uses the access-level helper, supports workspace/run filters, aggregates totals, and exposes P3-A §7.3 `by_strategy` averages/rates.
- **Read-only guarantee:** `MemoryRuntime.observability_summary(...)` remains a read facade over persisted logs and does not create fake `quality` / `safety` `ProfileEvent` rows.
- **Plan/backlog sync:** `docs/design/P3A_IMPLEMENTATION_PLAN.md` Issue 5 checkboxes are ticked; `docs/design/ROADMAP.md` Phase 3-A Quality/Safety and phase-aware profiler items are marked complete with P3-A semantics.

## Latest Verification (2026-06-10 Phase 3-A Issue 5)

- TDD RED: `uv run pytest apps/api/tests/observability/test_metrics.py -q` failed as expected on missing expanded `ProfilePhase` values and missing `build_access_observability_metrics(...)`.
- Targeted regression: `uv run pytest apps/api/tests/observability/test_metrics.py apps/api/tests/api/test_observability.py -q` -> **11 passed**.
- Full regression: `uv run pytest -q` -> **136 passed**.
- Deterministic benchmark: `uv run python -m app.benchmark.runner --output-dir reports`; generated `reports/benchmark_results.json` with `acceptance.passed=true`.

## Implemented (Phase 3-A Issue 6 — dashboard table extension — 2026-06-10)

- **Dashboard model:** `DashboardTables` now includes `observability_summary: ObservabilitySummary | None` while preserving `runs`, `accesses`, `profile_events`, `benchmark_cases`, `benchmark_results`, `eval_cases`, `eval_runs`, `eval_results`, and `benchmark_summary`.
- **Runtime wiring:** `MemoryRuntime.dashboard_tables(workspace_id=...)` now computes `build_observability_summary(...)` with the same workspace filter as the dashboard request; eval result workspace filtering through scoped eval runs remains intact.
- **Tests:** dashboard API coverage asserts eval rows and workspace-scoped observability summary are present without changing existing benchmark row counts; eval-record tests were updated now that Issue 6 owns the summary field.
- **Plan/backlog sync:** `docs/design/P3A_IMPLEMENTATION_PLAN.md` Issue 6 checkboxes and acceptance item are ticked; `docs/design/ROADMAP.md` minimal dashboard item is annotated that table API extension is complete and static reports remain Issue 7.

## Latest Verification (2026-06-10 Phase 3-A Issue 6)

- TDD RED: `uv run --extra dev pytest apps/api/tests/api/test_dashboard.py -q` failed as expected on missing `observability_summary` in the dashboard payload.
- Targeted regression: `uv run --extra dev pytest apps/api/tests/api/test_dashboard.py apps/api/tests/api/test_observability.py apps/api/tests/observability/test_eval_records.py apps/api/tests/observability/test_metrics.py -q` -> **17 passed**.
- Full regression: `uv run --extra dev pytest -q` -> **137 passed**.
- Deterministic benchmark: `uv run --extra dev python -m app.benchmark.runner --output-dir reports`; generated `reports/benchmark_results.json` with `acceptance.passed=true`.

## Implemented (Phase 3-A Issue 7 — JSON/Markdown/HTML observability reports — 2026-06-10)

- **Report models:** `ObservabilityReportRequest` and `ObservabilityReportResult` added to the runtime API model vocabulary.
- **Report writer:** `app.observability.reports.write_observability_report(...)` writes deterministic `observability_report.json`, `observability_report.md`, and `observability_report.html` artifacts under a safe `reports/`-scoped output directory. JSON includes summary, access rows, per-access metrics, critical drift counts, context block counts, and optional replay payloads. Markdown includes Summary, Strategy Breakdown, Quality Signals, Safety Signals, Slowest Accesses, Replay Drift, and Access Details with concrete replay access commands. HTML is a single static inline-CSS file with summary cards, strategy table, quality/safety table, replay drift table, and per-access `<details>` sections; no external JS/CDN is used.
- **Runtime/API/CLI wiring:** `MemoryRuntime.write_observability_report(...)` exposes the writer, `POST /v1/observability/reports` returns generated paths plus summary, and `uv run python -m app.observability.reports --output-dir reports` writes an in-memory empty report fixture for local smoke checks. Unsafe output directories (absolute paths, `..`, or paths outside `reports/`) map to HTTP 400.
- **Read-only diagnostics:** report generation reads persisted access/gate logs and uses `RetrievalReplayService` for optional side-effect-free replay; it does not create access/gate/profile rows and does not mutate memory access counters.
- **Plan/backlog sync:** `docs/design/P3A_IMPLEMENTATION_PLAN.md` Issue 7 checkboxes are ticked; `docs/design/ROADMAP.md` minimal dashboard/static report item is marked complete.

## Latest Verification (2026-06-10 Phase 3-A Issue 7)

- TDD RED: `uv run pytest apps/api/tests/observability/test_reports.py -q` failed as expected on missing `app.observability.reports`.
- Additional RED for the module entrypoint: `uv run pytest apps/api/tests/observability/test_reports.py::test_reports_module_entrypoint_writes_empty_report -q` failed before the CLI wrote reports.
- Security review found unsafe symlink edge cases; RED tests reproduced `reports -> outside` and `reports -> reports` symlink-loop behavior before the fix. `_safe_output_dir(...)` now rejects existing symlink path components and converts unsafe resolution failures into `ValueError`, so API maps them to HTTP 400.
- Targeted GREEN: `uv run pytest apps/api/tests/observability/test_reports.py apps/api/tests/api/test_observability.py -q` -> **15 passed**.
- Observability regression: `uv run pytest apps/api/tests/observability/test_reports.py apps/api/tests/api/test_observability.py apps/api/tests/api/test_dashboard.py apps/api/tests/observability/test_metrics.py apps/api/tests/observability/test_replay.py -q` -> **25 passed**.
- Code review: issue-validator reviewed report generation, API wiring, safety checks, and tests; **0 defects** found.

## Implemented (Phase 3-A Issue 8 — full regression, benchmark, and project-memory sync — 2026-06-10)

- **Full regression:** `uv run pytest -q` -> **145 passed** after Issue 7 report/API/CLI/symlink-safety implementation.
- **Deterministic benchmark:** `uv run python -m app.benchmark.runner --output-dir reports`; `reports/benchmark_results.json` has `acceptance.passed=true` and all 7 checks true (`variant_2_contamination_below_baseline_1`, zero cross-workspace leakage, tool-sensitive block, procedural reuse, superseded exclusion, stale exclusion, no-memory baseline failure recovery).
- **Generated artifacts:** benchmark and observability report artifacts remain under ignored `reports/`; they are reproducible outputs and are not source-controlled.
- **Plan/backlog sync:** `docs/design/P3A_IMPLEMENTATION_PLAN.md` acceptance checklist and Issue 8 checkboxes are ticked; `.ai/REQUIREMENTS.md`, `.ai/IMPLEMENTATION_PLAN.md`, and `docs/design/ROADMAP.md` now show Phase 3-A complete and point to post-P3A priorities.

## Latest Verification (2026-06-10 Phase 3-A complete)

- `uv run pytest apps/api/tests/observability/test_reports.py::test_reports_module_entrypoint_writes_empty_report -q` -> **1 passed**.
- `uv run pytest apps/api/tests/observability/test_reports.py::test_report_writer_rejects_symlink_loop_as_value_error apps/api/tests/observability/test_reports.py::test_report_writer_rejects_reports_symlink -q` -> **2 passed**.
- `uv run pytest apps/api/tests/observability/test_reports.py apps/api/tests/api/test_observability.py -q` -> **15 passed**.
- `uv run pytest -q` -> **145 passed**.
- `uv run python -m app.benchmark.runner --output-dir reports`; `reports/benchmark_results.json` -> `acceptance.passed=true`.

## Implemented (showcase assets + reproducibility baseline — 2026-06-10)

- **README showcase:** added a top-level README with product positioning, Mermaid architecture diagram, deterministic quickstart, report guide, API/observability endpoints, PostgreSQL mode, optional real-LLM bench, and roadmap pointer.
- **Reproducibility scripts:** added `scripts/reproduce.sh` for database-free deterministic demo/benchmark/observability report generation and benchmark acceptance checking; added `scripts/smoke.sh` for full local smoke verification.
- **Regression coverage:** added integration tests that generate demo/benchmark reports into a temporary directory, assert benchmark `acceptance.passed=true`, verify observability report entrypoint output, and guard README command drift.
- **Showcase narrative:** added `docs/blog/why-agent-memory-is-not-just-rag.md`, covering failed-branch isolation, workspace isolation, stale rejection, tool safety, state-aware retrieval, gate policy, replay, and profiler evidence.
- **Local hygiene:** `.superpowers/` is ignored; generated `reports/` remain ignored and reproducible.

## Latest Verification (2026-06-10 showcase/reproducibility)

- `uv run pytest apps/api/tests/integration/test_reproducibility.py -q` -> **4 passed**.
- `./scripts/reproduce.sh` -> **passed**, generated demo/benchmark/observability reports and printed `acceptance.passed=true (7/7 checks true)`.
- `uv run pytest -q` -> **149 passed**.
- `uv run python -m app.benchmark.runner --output-dir reports`; `reports/benchmark_results.json` -> `acceptance.passed=true` with all 7 checks true.

## Implemented (real-LLM validation bench + fixes — 2026-06-10)

- **`app/benchmark/llm_bench.py` (new, manual/opt-in, NOT in CI):** drives the real `LLMExtractionProvider` against a configured OpenAI-compatible endpoint. **8 scenarios**: `memory_override`, `scale_retrieval`, `llm_vs_rule`, `nl_extraction`, plus `failed_branch_isolation` (rollback excludes failed npm branch), `workspace_isolation` (other-workspace deno never leaks), `stale_rejection` (expired memory dropped by risk gate), `tool_safety` (destructive `git push --force` blocked). Memory is written via the real LLM extraction path; isolation/rejection comes from the runtime (rollback / workspace-scoped retrieval / risk gate). **Multi-endpoint portability comparison** via `MEMTRACE_LLM_BENCH_ENDPOINTS` (JSON list of `{name,api_key,base_url,model,...}`); single endpoint via standard `MEMTRACE_LLM_*`. Requires a live key; surfaces errors instead of silently degrading. Writes `reports/llm_bench_report.{json,md}` (per-endpoint sections). Run: `MEMTRACE_LLM_API_KEY=... uv run python -m app.benchmark.llm_bench`.
- **Fix 1 — packer dropped dynamic-key project memories (`app/retrieval/packer.py`):** `pack_context` previously skipped ALL `MemoryType.project` items (via `proj_ids`) while only merging `project.runtime`/`project.runtime.excluded` into the constraint block, so LLM-extracted keys like `project.database`/`project.cache_layer` were retrieved (accepted by the gate) but silently never packed into any context block. Now only the runtime/excluded keys are merged; every other project memory is emitted as its own `project_memory` block (using `summary` or `content`). Added `test_pack_context_emits_dynamic_key_project_memory`.
- **Fix 2 — LLM key instability broke conflict resolution (`app/memory/llm_extractor.py` `_SYSTEM_PROMPT`):** the model assigned different keys to the same concept (npm/pnpm → `project.package_manager`, but bun → `project.runtime`), so the resolver (key-based) never reconciled them and both stayed active. The system prompt now defines a controlled key vocabulary (runtime/package-manager → always `project.runtime`; language/database/test_framework/formatting), requires reusing the same key per concept across turns, and to set `supersede=true` when a choice changes.

## Latest Verification (2026-06-10 real-LLM bench + fixes)

- `uv run pytest -q` -> **109 passed** (was 98; +11 incl. packer dynamic-key test).
- Deterministic benchmark: `acceptance.passed=true` (unchanged; packer fix keeps runtime merge + adds non-runtime project blocks).
- **Live bench (Volcengine Ark deepseek):** all **8 scenarios PASS** — memory_override (active `project.runtime=['bun']`, npm fully retired, pnpm only as exclusion), scale_retrieval (13 memories, 4/4 probes hit, budget respected), llm_vs_rule (LLM extracts where rule writer can't, e.g. ruff/TypeScript), nl_extraction (3/3 colloquial inputs incl. English + indirect Chinese), failed_branch_isolation (rolled-back npm branch not recalled, bun kept), workspace_isolation (other-workspace deno never leaks), stale_rejection (expired `/v1/old-users` dropped), tool_safety (`git push --force` blocked).

## Implemented (real LLM extraction provider — 2026-06-10)

- **Async provider Protocol (`app/memory/llm_extractor.py`):** `ExtractionProvider.extract` is now `async def`. `FakeExtractionProvider.extract` made async (logic unchanged); it is now the *fallback* when LLM extraction is enabled without an API key (no longer a "swap later" placeholder).
- **`LLMExtractionProvider` (new, `llm_extractor.py`):** calls an OpenAI-compatible `{base_url}/chat/completions` via `httpx.AsyncClient` with a fixed system prompt (`_SYSTEM_PROMPT`) constraining output to the `ExtractionCandidate` schema (`temperature=0`). `response_format=json_object` is **opt-in** (`use_json_response_format`, default off) because some endpoints (e.g. Volcengine Ark deepseek) return 400 for it. Responses are passed through `_strip_code_fences` before `json.loads` to tolerate ```json fences. Accepts an injected `httpx.AsyncClient` for testing. `_extract_candidate_list` accepts either a bare array or `{"candidates": [...]}`. Individually-invalid items are dropped (`_validate`); empty content skips the call; any HTTP/JSON failure raises (caught upstream). `ExtractionCandidate.confidence` is bound to `[0,1]` via `Field(ge=0, le=1)` (architecture.md §11.4 hardening). `__all__` updated.
- **Config (`app/config.py`):** new `llm_api_key=""`, `llm_base_url="https://api.openai.com/v1"`, `llm_model="gpt-4o-mini"`, `llm_timeout_ms=8000`, `llm_max_tokens=512`, `llm_use_json_response_format=False` (all `MEMTRACE_` prefixed).
- **Runtime (`app/runtime/memory_runtime.py`):** `_extract_user_message` is now async and wraps the provider call in try/except — on any exception it logs a warning and falls back to `writer.write_from_user_message` (no memory lost, architecture.md §12). `_apply_write_rules` awaits it. Module logger added.
- **DI (`app/api/deps.py`):** wires `LLMExtractionProvider` when `llm_extraction_enabled` AND `llm_api_key` set (passing `use_json_response_format`); enabled-but-no-key logs a warning and falls back to `FakeExtractionProvider`; default `None`.
- **Dependency (`pyproject.toml`):** `httpx>=0.27` promoted from dev to runtime dependency.
- **Tests:** new `tests/memory/test_llm_provider.py` (httpx `MockTransport`: candidate-array parsing, request shape/auth, response_format omitted-by-default + sent-when-enabled, markdown-fence stripping, invalid-item dropping, extra-field ignoring, out-of-range confidence dropping, empty-content skip, HTTP 500 raises, invalid-JSON raises). Updated `tests/runtime/test_llm_extraction_flow.py` (`_RecordingProvider.extract` async; new `_FailingProvider` + `test_provider_failure_falls_back_to_rule_writer`) and `tests/memory/test_llm_extractor.py` (fake provider awaited).

## Latest Verification (2026-06-10 real LLM extraction)

- `uv run pytest -q` -> **108 passed** (was 98; +10 provider/fallback/hardening tests).
- Benchmark: `acceptance.passed=true` with all 7 checks true (default-off path unchanged; LLM provider only wires when enabled + key present).
- Code review (issue-validator): async consistency, fallback covers all LLM exceptions without memory loss, secret skipped before provider, schema hardening + forward-ref runtime-safe, httpx both paths correct, config/injection three-branch correct, no import/cycle/type issues. No functional bugs.
- **Live verification (Volcengine Ark, deepseek model):** real extraction returns `project.runtime=bun` + `project.runtime.excluded=npm, node.js`; full `MemoryRuntime` path persists `project.package_manager=pnpm` as active; bad-key (401) correctly degrades to the rule writer and still writes `project.runtime=bun` (no memory lost). Found + fixed two real-endpoint issues during this run: response_format=json_object rejected (made opt-in) and JSON-in-fences tolerance.

## Implemented (MVP audit fixes — 2026-06-09)

- **Retrieval hot-path timeout (mvp.md §11 / §12.3):** `RetrievalController.retrieve` now wraps `_retrieve_impl` in `asyncio.wait_for(timeout=settings.retrieval_timeout_ms/1000)`; on `TimeoutError` it degrades to an empty `MemoryContext` with a "timed out" warning instead of blocking. `retrieval_timeout_ms` was previously a dead config (`controller.py`).
- **Rollback memory-flip degenerate branch (`memory_runtime.py` `rollback_branch`):** memories are now flipped via a single `affected_node_ids` set; when the step's node is missing but its id is known it is still targeted, and matching never falls back to a `None` source-node id (which previously could either skip the flip entirely or wrongly match every memory lacking a source node). Removed the redundant `== step.state_node_id` or-clause.
- **Recovery parent dangling reference (`memory_runtime.py` `start_step` + new `StateTreeError`):** if a failed node has a `parent_id` that cannot be resolved, recovery no longer silently reattaches to root (which would misplace it in a multi-level tree); it raises `StateTreeError`. Root-level steps (no parent) still legitimately attach to root.
- **Access inspection candidates vs gate_decisions (`memory_runtime.py` `inspect_access`):** `candidates` is now the retrieval-input view ranked by `relevance_score`; `gate_decisions` stays the gate-output view in processing order. Both cover the same memory set but expose distinct orderings/intent (mvp.md §3.2).
- **Tests:** `tests/runtime/test_memory_runtime_trace.py` (dangling-parent recovery raises `StateTreeError`) and `tests/retrieval/test_retrieval_flow.py` (candidates ranked by relevance + cover same set as gate_decisions; retrieve times out to empty context with warning).

## Latest Verification (2026-06-09 MVP audit + fixes)

- `uv run pytest -q` -> **98 passed** (was 95; +3 audit-fix tests).
- Benchmark: **8 cases / 32 results**, `acceptance.passed=true` (deterministic path unchanged).
- Demo re-verified: baseline_1 contamination=1, variant_2 contamination=0, contamination_eliminated=True.
- Audit result: all 15 mvp.md §13 acceptance items ✅; §3.1 endpoints 12/12; §4 entities + 12 ORM tables covered; Alembic chain 0001→0002→0003 intact.

## Implemented (P2 — LLM extraction pipeline)

- **`app/memory/llm_extractor.py`** (new, pure + storage-agnostic): `ExtractionCandidate` (fixed Pydantic schema, `extra="ignore"` per architecture.md §11.4), `ExtractionProvider` Protocol, deterministic `FakeExtractionProvider` (wraps the writer rules so output is identical to the rule-based path), and `build_results(event, candidates) -> list[MemoryWriteResult]` (validates + drops invalid candidates, stable `(scope, key, value)` sort, builds `MemoryItem` with provenance + risk flags, emits `supersede_keys` when `supersede=True`).
- **Config** (`app/config.py`): `llm_extraction_enabled: bool = False` (env `MEMTRACE_LLM_EXTRACTION_ENABLED`).
- **Runtime** (`app/runtime/memory_runtime.py`): `__init__` takes keyword-only `extraction_provider: Optional[ExtractionProvider] = None`; new `_extract_user_message` helper branches (provider when injected, else `writer.write_from_user_message`); `_apply_write_rules` calls it. Tool_result / working_state / summarizer paths unchanged. Buffered/idle-flush path reuses `_apply_write_rules`, so the provider works under deferred extraction too.
- **DI** (`app/api/deps.py`): injects `FakeExtractionProvider()` when enabled, else `None` (TODO marker for a real LLM client).
- **Secret safety:** secret events are redacted and skip the whole extraction branch in `write_event` before any provider is consulted (verified by test).
- **Tests:** `tests/memory/test_llm_extractor.py` (pure-function: schema validation, invalid/extra-field dropping, provenance, supersede_keys, deterministic ordering) and `tests/runtime/test_llm_extraction_flow.py` (provider path persists via resolver, no-provider keeps rule-based, resolver dedup, secret skips provider, provider works under buffered flush).

## Latest Verification (2026-06-09 P2 LLM extraction)

- `uv run pytest -q` -> **95 passed** (was 84; +11 extractor/flow tests).
- Benchmark: **8 cases / 32 results**, `acceptance.passed=true` (default-off path unchanged).
- Demo re-verified: baseline_1 contamination=1, variant_2 contamination=0, contamination_eliminated=True.
- Enabled-path manual check: `MemoryRuntime(..., extraction_provider=FakeExtractionProvider())` writing "这个项目使用 Bun" produces `project.runtime=bun` via the resolver.

## Implemented (P2 — benchmark cases 7-8)

- **Case 7 `case_7_stale_rejection`** (`app/benchmark/cases.py`): seeds an expired (`expires_at` in the past) high-relevance `episodic` memory pointing at a legacy endpoint `/v1/old-users`, plus a Bun constraint. The query asks which endpoint to call. Returns `stale_markers` in `SeedResult.extra`.
- **Case 8 `case_8_no_memory_baseline`** (`app/benchmark/cases.py`): seeds only the Bun constraint; baseline_0 (no memory) returns `unknown` (task fails), state-aware strategies recall Bun and succeed.
- **Evaluator** (`app/benchmark/evaluator.py`): `stale_memory_injection` is now really computed (was hardcoded 0) — a memory whose `stale_markers` appear in any context block counts as injected. Added `stale_memory_injection_present` so the rate is averaged only over cases that seed stale memory (mirrors the `tool_sensitive_present` / `procedural_reuse_present` convention, incl. baseline_0 present=1/inj=0).
- **Runner** (`app/benchmark/runner.py`): passes `stale_markers` through; `stale_memory_injection_rate` now filtered by `_present`; two new acceptance checks: `variant_2_excludes_stale_memory` (variant_2 rate 0 AND baseline_1 rate > 0) and `variant_2_succeeds_where_no_memory_baseline_fails` (variant_2 task_success_rate > baseline_0).
- **Tests:** `tests/benchmark/test_runner.py` (6→8 cases, 24→32 results, two new acceptance asserts) and `tests/api/test_dashboard.py` (runs 8→10, accesses 24→32, cases 6→8, results 24→32).

## Latest Verification (2026-06-09 P2 cases 7-8)

- `uv run pytest -q` -> **84 passed** (test count unchanged; benchmark/dashboard counts updated in place).
- Benchmark: **8 cases / 32 results**; `acceptance.passed=true` with all 7 checks true. Case 7 per-strategy stale_injection: baseline_1=1, variant_1=1, variant_2=0. Case 8 task_success: baseline_0=0, variant_2=1. variant_2 overall task_success_rate=1.0, baseline_0=0.0.
- Demo re-verified: baseline_1 contamination=1, variant_2 contamination=0, contamination_eliminated=True.

## Implemented (P2 — candidate buffer / idle flush)

- **`ExtractionMode` enum** (`sync` / `buffered`) in `app/runtime/models.py`; `WriteEventRequest.extraction_mode` per-request override (sync_flush for explicit corrections); `WriteEventResult.buffered` flag; new `FlushRequest`/`FlushResult` models.
- **`CandidateBuffer`** `app/memory/candidate_buffer.py`: pure, deterministic, in-process, session-keyed FIFO of candidate events (append/pending/size/total_size/drain/sessions). Ephemeral — only holds event ids/copies; raw events already persisted to PG, so no DB table/migration is needed. Falls back to `run_id` grouping when an event has no session.
- **Runtime wiring** `MemoryRuntime` (`app/runtime/memory_runtime.py`): constructor takes `extraction_mode` (default `sync`) + owns a `CandidateBuffer`. `write_event` buffers non-secret events in buffered mode (honoring per-request `sync` override); secrets are never buffered. New public `flush_session()` (drains + replays `_apply_write_rules` in write order, so dedup/conflict resolution stays order-correct; idempotent). Lazy `_flush_session` hooked into `retrieve_context`, `finish_step`, `rollback_branch`, and `complete_run` so deferred extraction is materialized before reads/summaries/branch-isolation.
- **Failed-branch isolation parity:** `rollback_branch` flushes the session *before* flipping branch memories. Without this, a buffered branch's tool-evidence would stay pending and a later flush would resurrect it as a completed-branch memory; flushing first lets rollback flip it to `rolled_back`, keeping buffered-mode isolation identical to sync mode.
- **Config/wiring**: `Settings.extraction_mode` (`app/config.py`, default `sync`); `deps.py` injects `ExtractionMode(settings.extraction_mode)` into the runtime.
- **HTTP**: `POST /v1/sessions/{session_id}/flush` -> `FlushResult` (`app/api/routes.py`).
- **Tests:** `tests/memory/test_candidate_buffer.py` (pure buffer: grouping, order-preserving pending, drain empties + idempotent, unknown session, session→run fallback) and `tests/runtime/test_candidate_buffer_flush.py` (buffered defers extraction but persists raw event, explicit flush extracts, flush idempotent, lazy flush on retrieve_context / finish_step, per-request sync override, secret not buffered, buffered conflict resolves in write order with lineage, rollback-before-flush isolates buffered branch memory).

## Latest Verification (2026-06-09 P2 candidate buffer)

- `uv run pytest -q` -> **84 passed** (was 70; +14 buffer/flush tests incl. rollback isolation).
- Benchmark `acceptance.passed=true` (default `sync` mode unchanged; buffer is opt-in).
- Demo re-verified: baseline_1 contamination=1, variant_2 contamination=0, contamination_eliminated=True (sync default path intact).
- No new DB migration required (buffer is ephemeral; raw events remain the durable source of truth in PG).
- Correctness review note: in-process buffer is single-process and not shared across workers; acceptable for the deterministic MVP (raw events are durable in PG; architecture.md defers the Redis-backed buffer to post-P2).

## Implemented (P2 — dedup/merge + conflict resolver)

- **`superseded_by` lineage column** added: `MemoryItem.superseded_by` (`app/runtime/models.py`), `MemoryORM.superseded_by` (`app/storage/orm.py`), `_mem_to_orm`/`_mem_from_orm` mappings (`app/storage/sql_repository.py`), and migration `0003_memory_superseded_by` (down_revision `0002_pgvector`).
- **Resolver** `app/memory/resolver.py`: pure, deterministic, no-LLM. `resolve(incoming, existing_active) -> ResolveResult(add, updates)`. Same value (normalized) → dedup/merge into the strongest representative (union `source_event_ids`, max scores), retire other duplicates to `superseded`. Different value on a single-valued key (`project.runtime`) → conflict resolved by `trust_score` then `updated_at`; loser `superseded` with `superseded_by`=winner; a genuine tie marks both `conflicted` (gate degrades). Multi-valued keys (`project.runtime.excluded`) coexist.
- **Runtime hook** `MemoryRuntime._apply_write_rules` (`app/runtime/memory_runtime.py`): user-message memories now flow through `_resolve_and_persist` / `_same_identity_actives`; the existing explicit-correction `_supersede_keys` path is preserved and runs first. The resolver never rewrites `content`, so embeddings never go stale.
- **Benchmark** P2 case 5 (`case_5_explicit_correction`): user states Node then states Bun (conflicting positive prefs); the older Node preference is superseded at write time and never recalled. New evaluator metric `superseded_injection` (+`superseded_injection_present`) + summary `superseded_injection_rate` + acceptance check `variant_2_excludes_superseded_memory`.
- **Tests:** `tests/memory/test_resolver.py` (pure-function: dedup-merge, duplicate supersede, trust/recency conflict, tie→conflicted, multi-valued coexist, lineage) and `tests/runtime/test_dedup_merge.py` (dedup to one active, conflict supersede + lineage, superseded not recalled, idempotency). Updated benchmark/dashboard counts (now 6 cases / 24 results / 8 runs / 24 accesses).

## Latest Verification (2026-06-09 P2 dedup/merge)

- `uv run pytest -q` -> **70 passed** (was 59; +11 resolver/dedup tests, benchmark/dashboard counts updated).
- Benchmark `acceptance.passed=true` with new check `variant_2_excludes_superseded_memory=true`; case 5 per-strategy `superseded_injection=0` for all strategies (resolver retires the loser at write time, so it is strategy-independent).
- Migration chain validated: `0003_memory_superseded_by` down_revision `0002_pgvector`, upgrade/downgrade callable.

## Implemented (P2 — completed-run reuse / procedural memory)

- **MemoryType.procedural** added (`app/runtime/models.py`); `CompleteRunRequest`/`CompleteRunResult` request/result models added.
- **Summarizer** `app/memory/summarizer.py`: pure, deterministic, no-LLM. `build_run_summary` emits an episodic completed-run summary (active-path progress) and, for successful runs only, a procedural memory distilling the successful approach (positive project constraint + successful non-risky tool evidence on the active path). Failed/rolled-back branches and tool-sensitive/destructive evidence are never distilled.
- **Runtime** `MemoryRuntime.complete_run` (cold path, not on hot retrieve path): marks run completed, runs the summarizer, persists memories, and supersedes prior same-(run-scoped-)key summaries so re-running is idempotent. Stable keys `run.summary.<run_id>` / `procedure.<run_id>`.
- **Packer** maps `MemoryType.procedural` to the reserved `procedural` block (mvp.md §8 ordering).
- **HTTP** `POST /v1/runs/{run_id}/complete` (path param is authoritative; request body `run_id` optional).
- **Failed-branch isolation extended to summaries:** a failed run's episodic summary is written with `branch_status=failed` (not `completed`), so it is never recalled as a successful path.
- **Benchmark** P2 case 6 (`case_6_completed_run_reuse`): first run fixes a pytest suite and is completed (procedural extracted); a second similar run recalls it. New evaluator metric `procedural_reuse_hit` + summary `procedural_reuse_hit_rate` + acceptance check `variant_2_reuses_procedural_memory`.
- **Tests:** `tests/runtime/test_completed_run_reuse.py` (episodic+procedural write, failed-run produces no procedural, idempotency, later-run recall). Updated benchmark/dashboard counts (now 5 cases / 20 results / 7 runs).

## Latest Verification (2026-06-09 P2)

- `uv run pytest -q` -> **59 passed** (was 55; +4 procedural tests, benchmark/dashboard counts updated).
- Benchmark `acceptance.passed=true` with new check `variant_2_reuses_procedural_memory=true`; case 6 per-strategy: baseline_0 hit=0 (no memory), baseline_1/variant_1/variant_2 hit=1.
- Demo unchanged: baseline_1 contamination=1 (`npm test`), variant_2 contamination=0 (`bun test`), contamination_eliminated=True.

## Latest Verification (2026-06-09 full audit)

A full P0/P1 logic + mvp.md conformance audit was performed:
- `uv run pytest -q` -> **50 passed** (supersedes earlier 49; one additional test present).
- Benchmark runner -> `acceptance.passed=true`: variant_2 failed_branch_contamination_rate=0.0 < baseline_1=0.25; cross_workspace_leakage_rate=0.0; tool_sensitive_blocked_rate=1.0; task_success_rate=1.0.
- Demo -> baseline_1 contamination=1 (`npm test`), variant_2 contamination=0 (`bun test`), contamination_eliminated=True; state tree shows recovery attached under root (not under failed step) with failure_reason preserved.
- mvp.md §13 P0 checklist verified item-by-item against code; mvp.md §2.2/§10 P1 scope verified. No logic defects found.

## Resolved Blocking Decisions

1. **Package manager / scaffold:** `uv` + `apps/api/app/...` monorepo layout.
2. **Storage:** PostgreSQL source of truth via SQLAlchemy 2.0 async + Alembic (docker-compose). **pgvector semantic retrieval is now restored** (`pgvector/pgvector:pg16`): `embedding_vector` is a `Vector(256)` column with an HNSW cosine index (migration `0002_pgvector`); retrieval is hybrid lexical + deterministic-vector cosine. Compose defaults to `pgvector/pgvector:pg16`, overridable via `MEMTRACE_PG_IMAGE`.
3. **Retrieval similarity:** hybrid — lexical token overlap blended with deterministic hashed-embedding cosine (no external embedding provider; reproducible).
4. **Demo:** deterministic scripted loop, no external LLM.

(See `.ai/DECISIONS.md` ADR-006..014 for rationale.)

## Implemented (P0)

- **Runtime core:** `app/runtime/` models/enums, repository protocol + `InMemoryRepository`, pure `state_tree` helpers, `MemoryRuntime` facade (start_run/start_step/write_event/finish_step/rollback_branch/retrieve_context + read models + inspect_access).
- **Memory writer:** `app/memory/` rule-based writer (project +/- constraints, correction supersede, tool_evidence, working_state) + secret redaction.
- **Retrieval:** `app/retrieval/` lexical similarity, 3-layer gate (hard/risk/soft), context packer, profiler; strategy modes baseline_0/1, variant_1/2.
- **Storage:** `app/storage/` SQLAlchemy ORM (all MVP tables) + `SqlRepository`; Alembic migration `0001_initial`.
- **HTTP:** `app/api/` + `app/main.py` — all mvp.md §3.1 endpoints + `/health`.
- **Demo:** `app/demo/run_demo.py` -> `reports/demo_report.{md,json}` (in-memory or `--sql`).

## Implemented (P1)

- **Active path builder:** `active_path_chain` derives an ordered active progress chain excluding failed/rolled-back branches; context packing emits an `active_path` block after `active_state`.
- **State-aware retrieval plumbing:** retrieval now passes active-path data through controller and access inspection; existing strategy modes still compare `baseline_0`, `baseline_1`, `variant_1`, and `variant_2` on identical candidates.
- **Benchmark package:** `app/benchmark/` contains deterministic case seeders and rule evaluator for the four required cases: project preference, failed branch isolation, workspace isolation, and tool-call safety.
- **Benchmark runner/report/persistence:** `python -m app.benchmark.runner --output-dir reports` writes ignored generated artifacts `reports/benchmark_report.md` / `reports/benchmark_results.json`; when passed a repository it also persists `benchmark_cases` and `benchmark_results` rows.
- **Acceptance self-check:** the runner encodes mvp.md §10.5 criteria 1-3 in an `acceptance` block (variant_2 contamination < baseline_1, zero cross-workspace leakage, tool-sensitive blocked) surfaced in both JSON and Markdown; criteria 4-6 are covered by unit tests.
- **Dashboard tables:** `GET /v1/dashboard/tables` exposes table-shaped runs, access logs, profile events, benchmark cases/results, and benchmark summary for P1 inspection.
- **Tests:** benchmark runner/persistence/acceptance and dashboard table coverage added under `apps/api/tests/benchmark/` and `apps/api/tests/api/` (with `__init__.py` for both, matching other test packages).

## Verification Done

- `uv run pytest -q` -> **45 passed**.
- Demo (both backends): baseline_1 contamination=1 (`npm test`), variant_2 contamination=0 (`bun test`), contamination_eliminated=True.
- API smoke-tested via httpx ASGI on live Postgres; `alembic upgrade head` succeeds.
- P1 latest local verification: `uv run pytest -q` -> **50 passed**.
- P1 benchmark: `uv run python -m app.benchmark.runner --output-dir reports` generated JSON/Markdown reports with an `acceptance.passed=true` block. Summary: `variant_2.failed_branch_contamination_rate=0.0 < baseline_1=0.25`, `variant_2.cross_workspace_leakage_rate=0.0`, `variant_2.tool_sensitive_blocked_rate=1.0`, `variant_2.task_success_rate=1.0`.
- SQL backend re-verified on live Postgres: benchmark persists 4 cases + 16 results and `dashboard_tables()` returns them with a per-strategy summary.
- Targeted P1 gap tests passed: benchmark persistence stores 4 cases + 16 results; `/v1/dashboard/tables` returns benchmark/dashboard table rows and summary.
- pgvector restoration verified (2026-06-09): `uv run pytest -q` -> **55 passed** (added embedding stability / cosine / in-memory vector KNN tests). Recreated the data volume on `pgvector/pgvector:pg16`, `alembic upgrade head` ran `0001` + `0002_pgvector` (extension + `vector(256)` column + HNSW index confirmed via psql). SQL-backend demo: baseline_1 contamination=1, variant_2 contamination=0, contamination_eliminated=True; all 10 stored memories carry embeddings (`embedding_status=embedded`) and pgvector `<=>` cosine ranking is correct. Benchmark acceptance still `passed=true`.

## Open Risks / Notes

- pgvector semantic retrieval is restored; embeddings are deterministic hashed bag-of-words (not learned), so similarity is a proxy. Swapping in a real embedding model later only touches `similarity.stable_embedding` (keep determinism for benchmarks or gate behind config).
- PG15 data volumes are incompatible with the `pg16` image; switching requires `docker-compose down -v` (destructive). This env uses standalone `docker-compose` (the `docker compose` subcommand is unavailable).
- Cross-workspace leakage prevented by workspace-scoped candidate retrieval (lexical AND vector KNN both filter by workspace_id); gate `workspace_mismatch` is defense-in-depth (unit-tested).
- Lifecycle filtering of superseded/archived memory lives only in the retrieval candidate stage (see PITFALLS); the new vector path reuses the same `list_memories` lifecycle filter, so it stays in sync.
- Generated reports live under ignored `reports/`; regenerate them with the benchmark runner rather than treating them as source artifacts.

## Implemented (全量代码审查 + 安全/一致性修复 — 2026-06-13)

- **审查范围:** 并行逐行审查 runtime / retrieval / memory / observability+storage / SDK+benchmark+api 六大模块，产出带文件:行号、严重度、修复建议的结构化清单。
- **已修复（含测试，未触动确定性 benchmark）:**
  1. `app/memory/secrets.py` 脱敏覆盖面扩展：新增 JWT / PEM 私钥块 / Slack `xox*` / Google `AIza*` / 自然语「password is X」模式。整个抽取分支由 `contains_secret` 把关，漏检即密钥落库。
  2. `app/memory/writer.py` 否定短语去矛盾：`"should not use X"` / `"不想用 X"` 曾同时产出 `project.runtime=X` + `project.runtime.excluded=X`；新增后置过滤，被排除的 runtime 不得作为正向约束。
  3. `app/memory/resolver.py` `_SINGLE_VALUED_KEYS` 扩展到 LLM 受控 key 契约（language/database/test_framework/test_command/formatting/package_manager），使后到冲突值无 `supersede=true` 也能被正确 supersede。
  4. `app/observability/reports.py` `_accepted_memories` 把 `degrade` 错计为 accepted，与 metrics/replay 权威 `{accept,warn}` 冲突、导致 per-access 行与 summary 自相矛盾；已对齐为 `{accept,warn}`。
- **新增测试:** `test_writer.py`（secret 多格式覆盖 + 否定短语不产正向 runtime）、`test_resolver.py`（受控单值 key 冲突 supersede）。
- **未修复但已登记（需更大设计决策/触及并发模型，写入 ROADMAP §1.1 + §13）:** 正向打包路径无脱敏纵深防御 [High]、`variant_1` 过度关闭 hard/risk policy [High]、in-process/HTTP isomorphism（StateTreeError 未映射、replay_access run 检查只在 HTTP）[High]、`next_sequence_no` 并发重复 [High]、检索超时 split-brain [High]、token 估算复用剔停用词分词器 + CJK 无法截断 [Medium]、服务端无鉴权但 SDK 发 Bearer [Medium]、benchmark 公平性恢复仅覆盖 access_count [Medium]、LLM provider 每次新建 AsyncClient [Medium]、ORM/迁移 compaction 索引漂移 [Medium]、gate log 排序非确定性 [Medium]、summarizer LLM provenance 校验可能恒失败 [Medium]、状态机边界（rolled_back/幽灵节点/退化 rollback）[Medium]、负向证据非受保护块 [Medium]，以及若干 Low。
- **ROADMAP 丰富:** 新增 §1.1（审查发现清单，已修复/未修复分区）、§13 安全与一致性加固（13.1 安全闭环 / 13.2 一致性并发 / 13.3 精度健壮性）、§11 新增「本体作为单一真相源」消除三处单值语义漂移、推荐推进顺序新增第 8 步「安全与一致性加固」置于 Provider Registry 之前。

## Latest Verification (2026-06-13 全量审查 + 修复)

- 编译：`uv run --extra dev python -m compileall -q apps/api/app` -> 通过。
- 目标测试：`uv run --extra dev pytest apps/api/tests/memory/test_writer.py apps/api/tests/memory/test_resolver.py apps/api/tests/observability/test_reports.py -q` -> **30 passed**。
- 全量回归：`uv run --extra dev pytest -q` -> **308 passed**（原 305 + 3 新测试）。
- 确定性 benchmark + 可复现：`uv run python -m app.benchmark.runner --output-dir reports && bash scripts/reproduce.sh` -> `acceptance.passed=true (12/12 checks true)`。

## Next Recommended Action

全量审查已完成并修复 4 项安全/一致性缺陷（详见上节）；其余已登记到 ROADMAP §1.1/§13。**推荐下一步：先做 ROADMAP §13.1 安全闭环（正向打包脱敏 + `variant_1` gate 收敛 + 鉴权去装饰化）与 §13.2 两条 High（`next_sequence_no` 原子化、检索超时 split-brain、后端 isomorphism），再进入 §10/§11 Provider Registry / Key Ontology。** 安全相关两条（正向脱敏、variant_1）触及检索热路径但不改 benchmark 语义，应优先。Heavy infra（Redis/Celery）、高级存储（ES/Neo4j）、多租户治理、React dashboard 仍后置。

---

## (历史) 旧 Next Recommended Action

The MVP (P0+P1+P2), Phase 3-A backend observability, showcase/reproducibility baseline, Context Compaction C0-C5, Failure-aware Negative Memory Injection I1-I6, Phase 3.5 SDK/LangGraph adapter/CLI S1-S6, and ROADMAP §7 `docs/design/SIX_STRATEGY_BENCHMARK_PLAN.md` are complete. **Recommended next slice: choose between ROADMAP §10 Provider Registry and §11 Controlled Memory Key Ontology.** Provider Registry would formalize deterministic/default providers plus optional real embedding/LLM-style provider seams; Controlled Key Ontology would stabilize memory key taxonomy before more provider-driven extraction/ranking work. I7 compaction negative retained remains deferred as an independent cross-feature design. Heavy infra (Redis/Celery), advanced storage (ES/Neo4j), multi-tenant governance, and the React dashboard (Phase 3-B) remain deferred until those priorities are stable.
