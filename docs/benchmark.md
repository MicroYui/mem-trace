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

The benchmark acceptance summary should report `passed=true`. Reproducibility currently checks 16 acceptance criteria.

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

## Real-LLM Q&A bench (opt-in)

The deterministic benchmark above is reproducible and runs without a network. To
validate real-world effectiveness — does MemTrace-managed context produce better
*real LLM answers*? — there is an opt-in question-answering bench. For each
scenario it seeds memory through the real `MemoryRuntime`, retrieves context twice
(no-memory `baseline_0` vs state-aware + gated `variant_2`), and asks a real LLM
the same question with each context, then checks whether the gated-memory answer
is correct and whether it improves on the no-memory answer.

It is env-gated and skips cleanly with no endpoint configured (no default-CI /
benchmark / reproducibility impact). Against a local OpenAI-compatible proxy:

```bash
MEMTRACE_LLM_API_KEY=sk-local \
MEMTRACE_LLM_BASE_URL=http://localhost:4141/v1 \
MEMTRACE_LLM_MODEL=gpt-5-mini \
uv run python -m app.benchmark.qa_bench --output-dir reports
```

Example contrast (project-preference scenario): with the gated context
`"This project uses Bun."` the model answers `bun test`; with no memory it
answers `I do not have that information.` Scenarios cover project preference,
failed-branch avoidance, stale-endpoint exclusion, and multi-fact recall.
`app/benchmark/llm_bench.py` remains the separate opt-in real-LLM *extraction*
bench.

## Dataset-driven recall bench (LoCoMo / MemoryArena-style)

The deterministic benchmark above hard-codes its cases in Python. To evaluate at
scale on real, externally-sourced datasets — and to quantify MemTrace's edge over
plain vector memory — `app/benchmark/dataset_bench.py` ingests a JSONL dataset and
contrasts a plain-vector/lexical baseline (`baseline_1`, no gate) against the
state-aware + gated path (`variant_2`) over identical seeds. Scoring is fully
deterministic (no LLM, no network): for each probe it measures whether the gold
fact reaches **positive** context (recall) and whether a superseded/failed-branch
distractor leaks in.

```bash
# Built-in 3-record sample (no external data needed):
uv run python -m app.benchmark.dataset_bench --output-dir reports

# A larger converted LoCoMo / MemoryArena file:
MEMTRACE_DATASET_PATH=/data/locomo.jsonl uv run python -m app.benchmark.dataset_bench
# or: uv run python -m app.benchmark.dataset_bench --dataset /data/locomo.jsonl
```

On the built-in sample, plain vector leaks a failed-branch `npm test` distractor
(`distractor_leakage=0.5`) while the gated path isolates it (`0.0`) — a
`leakage_reduction=0.5` MemTrace edge — and a superseded endpoint is lifecycle-
filtered for both strategies.

**Record schema** (one JSON object per line):

```json
{
  "id": "temporal_update",
  "facts": [
    {"key": "endpoint.users", "value": "/api/v1/users",
     "content": "The legacy users endpoint was /api/v1/users.",
     "memory_type": "project", "status": "superseded", "branch_status": "completed"},
    {"key": "endpoint.users", "value": "/api/v2/users",
     "content": "The current users endpoint is /api/v2/users.",
     "memory_type": "project", "status": "active", "branch_status": "completed"}
  ],
  "probes": [
    {"question": "What is the current users API endpoint path?",
     "recall_markers": ["/api/v2/users"], "distractor_markers": ["/api/v1/users"]}
  ]
}
```

A fact's `status: "superseded"` models a temporal knowledge update; a
`branch_status: "failed"` (or `"rolled_back"`) models a distractor from a dead
branch. `recall_markers` are substrings that must appear in positive context;
`distractor_markers` must not. Convert a real LoCoMo/MemoryArena split into this
schema (one record per conversation, one probe per QA pair) to evaluate at scale.
This bench is standalone — it does not affect the deterministic benchmark or its
16/16 acceptance.

### Scale run (thousands of records) + charts

`app/benchmark/generate_dataset.py` deterministically synthesizes thousands of
records in this schema, across categories: **dead-branch** distractors (failed /
rolled-back / multi — a wrong value plain vector admits and the gate rejects),
**superseded** distractors (both lifecycle-filter → honesty control), **clean**
recall controls, and **valid_on_failed** (the *correct* fact itself sits on a
failed branch, so MemTrace's gate over-drops it — the mechanism's recall cost).
The record `id` encodes its category so results break down by type. `dataset_bench`
adds `clean_context_rate` (correct fact present **and** no distractor) and accepts
`--strategies all` for the 6-strategy ablation ladder; `app/benchmark/plot_benchmarks.py`
renders committed PNG charts under `docs/assets/` (matplotlib is a chart-only
dependency, run with an ephemeral `uv run --with matplotlib`, not added to the project):

```bash
uv run python -m app.benchmark.generate_dataset --count 3000 --out /tmp/scale.jsonl
uv run python -m app.benchmark.dataset_bench --dataset /tmp/scale.jsonl --strategies all --output-dir reports
uv run --with matplotlib python -m app.benchmark.plot_benchmarks   # writes docs/assets/*.png + benchmark_summary.json
```

On the committed 3,000-record run this is a **tradeoff**, not a one-sided win:
plain vector has recall **100%** but contamination **78.6%** (clean context 45%);
MemTrace gives up **15%** recall (over-gating valid facts on failed branches) to
drop contamination to **0%**, nearly doubling clean usable context to **85%**.
Only `variant_2`/`variant_3` (the state-aware gate) remove contamination; the
recall cost is isolated entirely to the `valid_on_failed` category. The run is
deterministic synthetic data — it stresses the isolation *mechanism* and its cost
at scale.

### Real execution-tree benchmark (deterministic)

`app/benchmark/trace_bench.py` goes a step further than the flat scale run: it
drives the **real `MemoryRuntime`** to build a long-horizon *execution tree* per
scenario — a run of many subgoals where each subgoal may make attempts that
**fail and get rolled back** (dead branches) before a **recovery** attempt
succeeds. Memories are created by the real write path (free-form `tool_result`
content), so they carry genuine `branch_status` / state-node provenance, and
retrieval runs the full pipeline (state tree → active-path filtering → gate →
compaction) — the structure a plain vector store cannot represent.

```bash
uv run python -m app.benchmark.trace_bench --scenarios 120 --subgoals 10 --output-dir reports
```

On the 120 runs × 10 subgoals (1,200 probes) run: MemTrace keeps recall at
**100%**, removes **100%** of dead-branch contamination (plain vector leaks it
all → clean context **33% → 100%**), and uses **~58%** of the `long_context`
dump-all token count. Here there is **no** recall cost, because correct facts are
always established on the recovered/active path (the `valid_on_failed` cost case
only appears in the flat scale run above). This exercises MemTrace's agentic edge
end-to-end, deterministically.

### Real dataset (LoCoMo) + real-LLM judge (opt-in)

`app/benchmark/locomo_bench.py` runs the real LoCoMo long-conversation QA dataset
with a real LLM answering + a real LLM judge, under three conditions (no-memory /
plain-vector / MemTrace). It is env-gated (needs `MEMTRACE_LLM_*` and a downloaded
`locomo10.json` at `MEMTRACE_LOCOMO_PATH`) and skips cleanly otherwise.

```bash
# download locomo10.json from the snap-research/locomo repo first, then:
MEMTRACE_LLM_API_KEY=... MEMTRACE_LLM_MODEL=gpt-5.4 MEMTRACE_LOCOMO_PATH=locomo10.json \
  uv run python -m app.benchmark.locomo_bench --limit 30 --output-dir reports
```

On a 30-question sample (`gpt-5.4`): no-memory **0%**, plain vector **30%**,
MemTrace **30%**. Honest read: memory clearly helps, and MemTrace *ties* plain
vector because LoCoMo is **conversational** — it has no failed execution branches
for the gate to isolate (MemTrace's edge is agentic, shown in the synthetic scale
run). Retrieval also uses lexical/deterministic vectors here (no real embedding
endpoint), so absolute accuracy is modest. This proves the pipeline on real data
+ a real model; it is not a leaderboard submission.

## Performance / load testing (resource-capped)

`app/benchmark/perf_bench.py` measures wall-clock cost (the correctness benchmark
does not). It has two modes, both in-memory (no Postgres/ES, negligible disk):

- **Scaling** (default): `retrieve_context` p50/p95 vs workspace size + `write_event`
  throughput. `uv run python -m app.benchmark.perf_bench --sizes 200,1000,5000,20000`.
- **Load**: sustained concurrent retrieval for a fixed duration, reporting
  throughput (RPS) + p50/p95/p99 latency.
  `uv run python -m app.benchmark.perf_bench --load --concurrency 16 --duration 15`.

To measure the throughput ceiling under a **fixed CPU/memory quota** without
hogging the host, run the load mode inside a capped container via
`scripts/perf-load.sh` — it wraps `docker run --cpus/--memory`, so the
single-process asyncio load saturates exactly the allotted budget:

```bash
PERF_CPUS=1 PERF_MEM=1g PERF_CONCURRENCY=16 PERF_DURATION=15 ./scripts/perf-load.sh
```

Both modes are measurement tools, not CI gates.
