# Agent Instructions

This is an implementation-stage project driven by top-level design documents and `.ai/` project memory. Production code exists under `apps/api/` and `packages/python-sdk/`; do not invent unsupported requirements beyond the current plans.

Before non-trivial work, read:

- `.ai/PROJECT_BRIEF.md`
- `.ai/MVP_SCOPE.md`
- `.ai/ARCHITECTURE_SUMMARY.md`
- `.ai/PROJECT_STATE.md`

The MVP (P0+P1+P2) is complete. For what remains to be done (future work, deferred features, tech debt, open decisions), read `docs/design/ROADMAP.md` — it is the authoritative backlog and maps every item back to `docs/design/architecture.md` / `docs/design/draft.md` / `.ai/` sources.

Context Compaction (ROADMAP §9) is complete through C5 per `docs/design/CONTEXT_COMPACTION_PLAN.md`: `PackResult`, budget-aware `compacted_constraints` + `compaction_notice`, durable `ContextCompactionLog` with observability/replay wiring, rule/LLM `SummarizerProvider`, config-gated rolling history summary, and retention-quality benchmark/report/replay sync.
Failure-aware Negative Memory Injection is complete through I6 per `docs/design/FAILURE_AWARE_NEGATIVE_MEMORY_PLAN.md`: the gate supports three-way `accept / degrade / reject`; `NegativeEvidence` DTO + shared `retrieval/negative_evidence.py` builder + packer `avoided_attempts` are wired through controller/inspect/replay; observability exposes explicit negative-evidence metrics; benchmark includes `case_10` safe failure learning + `case_11` sanitized destructive failure with evaluator positive/negative block split, historically expanding to 44 benchmark result rows, and acceptance `variant_2_learns_from_failure_without_repeating` + `variant_2_sanitizes_destructive_failure_without_leakage`; I6 finalized ROADMAP / CONTEXT_COMPACTION_PLAN / project-memory sync. I7 (compaction negative retained) is deferred. Phase 3.5 SDK/LangGraph adapter/CLI is complete through S6 per `docs/design/SDK_ADAPTER_PLAN.md`: S1 `event_source` passthrough, S0 packaging/workspace skeleton, S2a in-process SDK backend, S2b HTTP backend + route/isomorphism, S3 LangGraph adapter, S4 examples, S5 CLI, and S6 README/project-memory finalization are done. ROADMAP §7 "完整 6 策略对比 + benchmark 落库" is complete through Task 11 per `docs/design/SIX_STRATEGY_BENCHMARK_PLAN.md`: six strategies, `case_12_reflection_retention`, 12×6=72 benchmark rows, reflection/token-bloat acceptance (12/12 checks), eval-table persistence, persisted-run workspace isolation, dashboard summary surfacing, docs sync, and full reproducibility closeout. A full six-module code review (2026-06-13) fixed four security/consistency defects; ROADMAP §13 Security & Consistency Hardening is complete through H18, including H15 migration policy, H16 redacted trace bundle export/validation, H17 deterministic dogfood harnesses, and H18 docs/project-memory closeout. **Current priority / selected plan:** proceed to §10/§11 Provider Registry / Controlled Memory Key Ontology unless explicitly selecting deferred I7 compaction-negative retention or another roadmap item.

Before coding, also read `.ai/REQUIREMENTS.md` and confirm the current task is concrete enough to implement.

After meaningful work, update `.ai/PROJECT_STATE.md` with current state, changed files, and next recommended action. When you complete a `docs/design/ROADMAP.md` item or discover new future work, update `docs/design/ROADMAP.md` too.

Keep AGENTS.md concise and stable. Do not put transient task state, task checklists, or session notes here; use `.ai/PROJECT_STATE.md`, `.ai/OPEN_QUESTIONS.md`, or task-specific notes instead.
