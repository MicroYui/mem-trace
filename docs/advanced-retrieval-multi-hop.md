# Multi-hop iterative retrieval

*ROADMAP §4 · default-off · deterministic · no external service*

## The problem

One-shot retrieval only surfaces memories that match what the query **literally
says**. But the fact you actually need is often linked to the query only through
a shared entity the query never names — a service name, a config key, a file
path. Plain vector RAG cannot follow that link: if the load-bearing memory has no
lexical/semantic overlap with the question, it is never retrieved.

MemTrace's multi-hop mode reconstructs those linked facts by *iterative
retrieval*: after the first pass it follows entity cues found in the current
candidates to pull in complementary memories, tagging each with its hop distance.

## How it works

1. Run the normal first pass over the query.
2. `derive_hop_cues(...)` extracts entity-like cues (dotted keys such as
   `service.gateway`, paths such as `src/app.py`, separator/digit identifiers)
   from the current candidates' content — skipping any entity the query already
   targets.
3. Re-query on those cues, append only **new** candidates that still fit the
   request token budget, and tag each with `hop = 1, 2, …`.
4. Repeat up to `MEMTRACE_RETRIEVAL_MULTI_HOP_HOPS` times.

It is fully deterministic — no model, no network. Expansion is bounded by
`MEMTRACE_RETRIEVAL_MULTI_HOP_MAX_CUES` (per-hop cue cap) and the request token
budget, and is skipped entirely under the `long_context` dump-everything
baseline. Graph-surfaced and hop-surfaced candidates stay subject to the
lifecycle filter, so retired memories never leak.

## Enable it

```bash
export MEMTRACE_RETRIEVAL_MULTI_HOP_HOPS=1   # range 0..4; 0 (default) == single pass
```

At `0` the candidate scoring is **byte-identical** to the default path — the
deterministic benchmark stays 16/16 and replay snapshots are unchanged. The
`multi_hop_hops` field appears in the retrieval policy snapshot only when the
feature is on.

## Run the demo

```bash
cd apps/api
uv run python -m app.demo.run_multi_hop_demo --out reports
```

The demo seeds three episodic memories in one workspace and retrieves the same
query twice:

| memory | content | role |
| --- | --- | --- |
| `m_gateway` | *"Request routing is handled by the service.gateway component."* | matches the query; carries the `service.gateway` cue |
| `m_tenant` | *"service.gateway must attach the x-tenant header before forwarding upstream."* | shares **no** query token except via `service.gateway`; carries the load-bearing `x-tenant` fact |
| `m_theme` | *"The dashboard sidebar renders a dark color theme."* | distractor — no shared token, no shared entity |

Query: **`Where is request routing configured?`** (names routing, *not* the
gateway/tenant entities).

```text
single_pass_action = route without x-tenant header
multi_hop_action   = route with x-tenant header
linked_fact_recovered = True
distractor_leaked = False  budget_bounded = True
```

It writes `reports/multi_hop_demo_report.{md,json}`.

## What to look for

- **Hop provenance** — `m_gateway` is `hop 0` (direct); `m_tenant` is `hop 1`
  (recovered by following the `service.gateway` cue).
- **Recovered fact** — the `x-tenant` requirement reaches the packed context only
  under one hop, flipping the deterministic downstream action.
- **Targeted, not indiscriminate** — the `m_theme` distractor shares no cue and
  never surfaces.
- **Budget-bounded** — re-run under a 1-token budget and no hop runs at all.
- **Byte-stability** — `policy_snapshot.retrieval.multi_hop_hops` is absent when
  off and `1` when on; `profile.retrieval.metadata.multi_hop_candidate_count`
  counts the hop-surfaced candidates.

## Guarantees & related knobs

- Default-off and degrade-safe: benchmark/reproduce stay 16/16; replay snapshots
  are unchanged when off. Cross-reference benchmark `case_16_multi_hop_recall`.
- Composes with the other default-off retrieval knobs: the [query
  planner](../README.md#-optional-advanced-retrieval-default-off) `full` mode
  (query rewrite complements cue derivation), multi-path RRF fusion, and
  provenance-graph neighbor expansion.
