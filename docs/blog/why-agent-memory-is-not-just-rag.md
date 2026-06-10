# Why Agent Memory Is Not Just RAG

Long-horizon agents do not just need a bigger vector store. They need memory that understands execution state: which branch succeeded, which branch failed, which workspace a fact belongs to, whether a fact is stale, and whether recalling a tool command would be unsafe.

MemTrace is built around that premise. It treats memory as runtime infrastructure for agents instead of a generic retrieval-augmented generation layer.

## The failure mode: vector memory recalls the wrong past

A vector store can retrieve semantically similar text, but similarity is not the same as usefulness. In agent workflows, a highly similar memory can be dangerous:

- A failed debugging branch said `npm test`, but the project actually uses Bun.
- Another workspace prefers Deno, but the current workspace uses Bun.
- An endpoint recommendation is expired.
- A destructive tool command like `git push --force` is present in prior trace evidence.

The common thread is that these are not pure semantic-ranking problems. They are runtime-state and policy problems.

## Trace first, extract later

MemTrace persists raw agent traces before derived memories:

```text
run -> step -> event -> memory item -> retrieval access -> gate log -> profile event
```

That ordering matters. If a memory decision looks wrong later, the system can inspect the original event, replay the retrieval, and compare gate decisions. This is why MemTrace exposes access inspection and retrieval replay rather than only returning packed prompt text.

## State-aware retrieval

Each run has an execution state tree. Completed active-path steps can support future context, while failed and rolled-back branches remain auditable but should not enter the prompt by default.

In the canonical Bun-vs-Node demo:

1. The user states that the project uses Bun.
2. A failed branch tries `npm test`.
3. The branch is rolled back.
4. A recovery step asks how to run tests.

Vector-only memory can recall `npm test` because it is semantically similar to the query. State-aware retrieval plus the admission gate rejects the rolled-back branch and keeps the Bun constraint.

## Admission gates are not optional

MemTrace applies a gate before context packing. The gate rejects or degrades memories based on runtime and safety metadata:

- cross-workspace mismatch
- deleted, archived, quarantined, or superseded lifecycle state
- secret sensitivity
- failed or rolled-back branch status
- stale expiration
- tool-sensitive, destructive, or production-risk flags

This makes the prompt context a policy-checked artifact, not just the top-k output of a retriever.

## Observability turns memory into debuggable infrastructure

Agent memory is hard to trust if you cannot explain why something was recalled. MemTrace records:

- candidates selected by retrieval
- gate decisions and rejection reasons
- packed context blocks
- retrieval/gate/context-packing latency
- quality and safety counters
- deterministic replay diffs

The static observability report and replay APIs make memory behavior inspectable without a full frontend dashboard.

## Benchmarking the mechanism

The deterministic benchmark compares four strategies:

- `baseline_0`: no memory
- `baseline_1`: vector/lexical memory without state isolation or gate
- `variant_1`: state-aware retrieval
- `variant_2`: state-aware retrieval plus admission gate

The benchmark cases cover failed-branch isolation, workspace isolation, tool safety, stale rejection, explicit correction, completed-run reuse, and no-memory failure recovery. The goal is not to chase a generic long-memory leaderboard; it is to show which runtime mechanism prevents which class of agent-memory failure.

## The takeaway

For long-horizon agents, memory quality depends on more than semantic similarity. A useful memory runtime needs traceability, execution state, lifecycle metadata, policy gates, replay, and profiler evidence.

That is the distinction MemTrace is designed to demonstrate: agent memory is not just RAG; it is stateful runtime infrastructure.
