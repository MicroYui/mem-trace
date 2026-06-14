# Concepts

MemTrace is an agent-memory runtime, not a document-ingestion RAG application. It records execution traces first, derives memory from those traces, and retrieves prompt context through state-aware scoring plus a safety gate.

## Run, step, and event

- A **run** is one agent task or conversation segment. It has a `run_id`, `session_id`, `workspace_id`, and task description.
- A **step** is a unit of agent work inside a run, such as planning, tool use, debugging, or recovery.
- An **event** is an ordered message/tool call/tool result inside a step. Events use run-local `sequence_no` ordering so replay does not depend on wall-clock timestamps.

Raw events are persisted before derived memory extraction. This makes replay, audit, and debugging possible even when later memory extraction behavior changes.

## Execution state tree

The state tree tracks active, completed, failed, rolled-back, and recovery branches. Retrieval uses the active path so memories from a failed or rolled-back branch do not automatically become prompt context just because they are semantically similar.

Recovery steps attach to the failed step's parent, not under the failed node. This keeps the recovered execution path clean while preserving provenance for what went wrong.

## Memory items

A memory item is a derived fact, preference, tool observation, working state, or procedural summary. Memory has both:

- **Branch status:** whether its source state is active/completed/failed/rolled back.
- **Lifecycle status:** whether the memory is active, superseded, archived, quarantined, pinned, conflicted, or deleted.

Both matter. A completed memory can be superseded by a correction; a failed memory can be useful only as negative evidence; a quarantined memory remains inspectable but cannot enter prompt context.

## Retrieval strategies

The deterministic benchmark compares six strategies:

- `baseline_0`: no memory.
- `long_context`: includes all retrievable workspace memory with effectively unbounded budget for token-bloat comparison, while non-bypassable safety floors remain.
- `baseline_1`: lexical/vector memory without state-aware isolation or the full gate, while safety floors remain.
- `variant_1`: state-aware reranking with failed/rolled-back rejection relaxed for ablation, while hard/risk safety policy remains enabled.
- `variant_2`: state-aware retrieval plus the admission gate.
- `variant_3`: `variant_2` plus deterministic reflection-lite retention reranking, a placeholder for a fuller scheduler-backed reflection flow.

## Admission gate

The gate decides whether each candidate memory can be used:

- `accept` / `warn`: positive prompt context can be packed.
- `degrade`: memory is not positive context, but may render as safe warning-only negative evidence.
- `reject`: memory is excluded from prompt context.

The gate protects against stale, superseded, failed-branch, workspace-mismatched, secret, destructive, tool-sensitive, and quarantined memories. Packer-level redaction is still applied as defense in depth.

## Negative evidence

Negative evidence lets an agent learn from safe failures without repeating them. For example, “we tried `npm test` and it failed because this project uses Bun” can appear as an `avoided_attempts` block. It is not treated as a positive instruction to run `npm test`.

Unsafe failures, secrets, destructive commands, or production-environment incidents are rendered with sanitized templates or rejected outright. Observability APIs use the same safe rendering boundary.

## Context compaction

When packed context exceeds the token budget, MemTrace compacts ordinary blocks while protecting critical constraints and notices. It persists `ContextCompactionLog` records so reports and replay can explain what changed.

Compaction can retain metadata about dropped negative evidence without forcing that evidence into prompt context. This preserves auditability and benchmark metrics while keeping prompt semantics safe.

## Provider registry and key ontology

Providers for extraction, embedding, summarization, and judge contracts are registered with non-secret capability metadata. Deterministic providers are the default so tests and benchmarks are reproducible. Real providers are config-gated and must degrade safely.

The controlled memory-key ontology defines canonical keys, aliases, cardinality, default scope/type, and safe free-form rules. This keeps writer, resolver, LLM extraction, and conflict behavior aligned.

## Lifecycle, versions, and conflicts

Lifecycle signals and scheduler outputs track retention and reflection priority separately from memory content. Memory versions record redacted semantic changes and lifecycle transitions. Conflict APIs expose read-only views of conflicting single-valued facts such as project runtime or package manager.

## Governance defaults

Local/dev/benchmark behavior is default-off for auth, quotas, and governance. Hosted or multi-user deployments can enable API keys, workspace authorization, quota checks, and stricter raw-payload controls. Raw payload retention is disabled by default.

## Telemetry export

OpenTelemetry/OpenInference-compatible export is an observability projection, not a second source of truth. It maps persisted runs, steps, events, and retrieval accesses into redacted spans through a pluggable exporter. The stable attribute contract uses `memtrace.*` keys; OpenInference keys are compatibility hints only.

Telemetry is disabled/noop by default. When enabled, runtime hooks export only after authoritative persistence succeeds and fail open if the sink is unavailable; terminal run/step snapshots are emitted once per lifecycle id to avoid duplicate OpenTelemetry span ids. JSONL output is intended for local no-network smoke/debug use, while OTLP export is optional and requires an explicit endpoint plus optional telemetry dependencies. Exporters never send raw event content, raw memory content, raw failed-attempt text, raw payload references, API keys, auth headers, destructive commands, or production-path markers.

The HTTP run export endpoint is read-only and returns only export counts and warnings, not raw span payloads. CLI telemetry export is deferred so the CLI does not duplicate HTTP/export semantics.

## Public integration boundaries

External integrations should use one of the public boundaries:

- Python SDK / CLI / LangGraph adapter
- `/v1` HTTP API
- TypeScript SDK
- MCP server

They should not import storage modules or duplicate retrieval, gate, context-packing, replay, or governance semantics.
