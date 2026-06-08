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

