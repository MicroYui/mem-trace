# P4-B Lifecycle and Reflection Scheduler Design

## Goal

Implement Phase 4 P4-B1 through P4-B4: lifecycle transition policy and audit, durable retention/reflection signals, deterministic scheduler functions, `variant_3` scheduler-backed reflection ranking, and benchmark/replay closeout while preserving deterministic default benchmark and reproduce behavior.

## Architecture

Use a minimal, separate signal layer. `MemoryItem` remains the source for base memory content, lifecycle status, access counters, and built-in scores. Scheduler-derived outputs live in `memory_retention_signals`; lifecycle changes are recorded in `memory_lifecycle_audits`. Retrieval remains behind `MemoryRuntime`/`RetrievalController`, and scheduler/Celery wrappers call runtime/repository boundaries rather than writer/resolver internals.

## Components

- `app.memory.lifecycle`: validates lifecycle transitions and produces audit records. Mainline transitions are `active -> dormant -> archived -> deleted`; side transitions include `active -> pinned`, `pinned -> previous_status`, `active -> conflicted`, `active -> quarantined`, and `active -> superseded`.
- `app.memory.retention`: computes deterministic `retention_score` and `reflection_priority` from existing memory score fields, access counts, timestamps, and expiration.
- `app.memory.scheduler`: exposes pure async functions for scoring, decay, archive, quarantine, and profile refresh. These functions do not require Celery and are directly testable.
- `app.async_tasks.tasks`: adds maintenance task wrappers that deserialize `TaskEnvelope`, use idempotency, call scheduler functions, and return `TaskResult`.
- Repository and SQL storage: add lifecycle audit and retention signal records with in-memory and SQL implementations.
- Retrieval policy: `variant_3` uses persisted `MemoryRetentionSignal.reflection_priority` when available; otherwise it falls back to the existing deterministic lite score. Policy snapshots include `reflection_signal_source` and `retention_policy_version` so replay detects ranking-semantic drift.

## Data Flow

1. Retrieval accepts memory candidates using the existing lifecycle filter: active, pinned, conflicted, and quarantined are candidates; dormant, archived, deleted, and superseded are not.
2. Accepted memories update `access_count` and `last_accessed_at` together.
3. Scheduler scoring reads memories for a workspace, computes deterministic signals, and upserts one signal per memory.
4. `variant_3` bulk-loads signals for accepted candidate memory ids. If any signal is present, scheduler signals are used for those memories and fallback lite scores are used only for missing rows.
5. Lifecycle scheduler transitions call the lifecycle policy helper, persist the changed memory, and write `MemoryLifecycleAuditRecord`.

## Error Handling and Safety

- Invalid lifecycle transitions raise `ValueError` before mutation.
- Scheduler archive/decay must not archive pinned memory.
- Expired or high-risk memories receive low retention scores but scoring never makes a non-retrievable memory retrievable.
- Quarantined memory may remain observable as a candidate but gate safety floors continue to reject it from accepted memories and prompt blocks.
- Redis/Celery remain optional; scheduler functions work without Celery.

## Testing

- Unit tests cover lifecycle transition legality, pin/unpin metadata, audit persistence, retention scoring determinism, signal persistence, and scheduler functions.
- Retrieval tests cover `last_accessed_at` updates and scheduler-backed `variant_3` ranking.
- Conformance tests cover lifecycle retrieval invariants.
- Benchmark/replay tests cover case 12 with scheduler signal present and default fallback behavior unchanged.
