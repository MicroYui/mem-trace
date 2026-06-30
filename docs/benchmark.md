# Benchmark Guide

MemTrace includes a deterministic benchmark that compares memory strategies across agent-memory failure modes. It is designed to prove that state-aware retrieval, admission gating, negative evidence, and compaction improve prompt context without relying on live LLM calls.

## Run the benchmark

```bash
uv run python -m app.benchmark.runner --output-dir reports
```

Run the full reproducibility bundle:

```bash
./scripts/reproduce.sh
```

Outputs are generated under `reports/` and ignored by git:

- `reports/benchmark_report.md`
- `reports/benchmark_results.json`
- `reports/observability_report.json`
- `reports/observability_report.md`
- `reports/observability_report.html`

The benchmark acceptance summary should report `passed=true`. Reproducibility currently checks 13 acceptance criteria.

## Strategies

- `baseline_0`: no memory.
- `long_context`: all retrievable workspace memory, effectively unbounded budget, policies disabled for bloat/contamination comparison except non-bypassable safety floors.
- `baseline_1`: lexical/vector memory without state-aware isolation or the full admission gate, while safety floors remain.
- `variant_1`: state-aware rerank; failed/rolled-back branch rejection is relaxed for ablation while hard/risk safety policy remains enabled.
- `variant_2`: state-aware retrieval plus admission gate.
- `variant_3`: `variant_2` plus deterministic reflection-lite retention reranking, a placeholder for fuller scheduler-backed reflection.

## Cases

The current suite has 16 cases:

1. Project preference retention.
2. Failed-branch isolation.
3. Workspace isolation.
4. Tool-call safety.
5. Explicit correction and superseding stale facts.
6. Completed-run reuse.
7. Stale rejection.
8. No-memory failure recovery.
9. Over-budget context compaction and constraint retention.
10. Safe failure learning through negative evidence.
11. Sanitized destructive-failure handling.
12. Reflection-retention under tight budget.
13. Retained negative lessons through compaction metadata.
14. Long-horizon single-hop recall (LoCoMo-style): a fact recorded early is recalled after intervening steps and amid distractor memories, where a no-memory baseline cannot.
15. Temporal knowledge update (LoCoMo-style): only the current value of an updated fact is recalled, never the superseded history.
16. Multi-hop recall (LoCoMo-style): two complementary facts are both retrieved into context.

## How to interpret key metrics

- **Acceptance `passed`:** overall benchmark criteria passed. This is the headline reproducibility check.
- **Failed-branch contamination:** a positive context block repeats failed branch evidence. Lower is better; `variant_2` should avoid contamination in the core Bun-vs-Node scenario.
- **Cross-workspace leakage:** memory from another workspace entered context. This should stay zero.
- **Tool-sensitive blocked rate:** risky tool evidence was blocked by the gate.
- **Negative lesson retained:** safe failed attempts were available as warning-only negative evidence, not positive prompt instructions.
- **Unsafe negative leakage:** destructive or secret failed content leaked. This should stay zero.
- **Compaction trigger / retained constraints:** over-budget retrieval compacted ordinary context while retaining protected facts and notices.
- **Retained negative evidence count:** metadata about dropped negative evidence was preserved in compaction logs. This does not mean the evidence entered the prompt.
- **Reflection retention hit rate:** `variant_3` retained a high-value memory under budget pressure. Current reflection-lite behavior is deterministic and intentionally simpler than a future scheduler-backed implementation.
- **Target recall hit rate:** the LoCoMo/MemoryArena-style cases (14–16) recalled the expected fact(s) into positive context; the no-memory baseline cannot, and historical/superseded values must not leak.
- **Token overhead:** `long_context` should show why unbounded recall is expensive and risky.

## Persisted rows and dashboard parity

When a repository is provided, the benchmark can persist eval runs, cases, and results. Dashboard summaries mirror benchmark metrics so report and API views stay consistent.

Generated reports are not source of truth. If results look stale, rerun the benchmark and inspect `reports/benchmark_results.json`.

## Reproducibility rules

- Benchmarks force deterministic providers even if real provider environment variables are set.
- Redis/Celery, live PostgreSQL integration tests, and real LLM providers are not required.
- Strategy comparisons use isolated seeded workspaces so one strategy's side effects do not pollute another.
- Wall-clock latency values are observational; acceptance checks focus on semantic metrics.
