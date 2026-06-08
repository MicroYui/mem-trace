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

