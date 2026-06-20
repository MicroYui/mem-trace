# Architecture Summary

## High-Level Architecture

```text
Agent / demo loop
  -> Memory Gateway / SDK / MemoryRuntime facade
  -> Runtime Core
     -> Trace Collector
     -> Execution State Tree
     -> Rule-based Write Pipeline
     -> Provider Registry + Key Ontology (§10/§11 P10 complete boundary)
     -> Retrieval Controller
     -> Admission Gate
     -> Profiler
     -> Telemetry projection package (core exporter slice complete)
  -> PostgreSQL + pgvector source of truth
  -> CLI/JSON/Markdown reports + built-in static viewer
  -> apps/web React/TypeScript dashboard (Phase 3-B complete)
```

Longer-term documents also describe Redis/Celery, Elasticsearch, Neo4j, React dashboard, and evaluation harness, but the MVP narrows the first hot path.

## Core Modules and Responsibilities

- **MemoryRuntime facade:** stable external API; hides storage, indexing, policy, profiling, and future async work.
- **Agent Trace Collector:** records raw agent events before extraction; source for state tree, memories, and profiler.
- **Execution State Tree:** organizes runs into active/completed/failed/rolled_back paths; isolates failed branches from prompt context.
- **Write Pipeline:** converts selected events into memory items; deterministic rules, config-gated LLM extraction, buffering, resolver, compaction, and provider/key-ontology boundaries are implemented.
- **Provider Registry (§10 complete slice):** unified boundary for extraction, embedding, summarizer, and contract-only judge providers. P1/P2/P9 provider-only infrastructure exists under `app.providers`; P3 factory/DI/runtime registry injection is complete; P4 runtime/retrieval/replay integration is complete with `retrieval-policy-v2`, retrieval-relevant provider snapshots, flat `AccessInspection` policy fields, runtime write-path embedding provider fallback, retrieval query embedding provider fallback, repository-level deterministic backfill preservation, and replay policy drift using public `RetrievalController.provider_snapshot`; P8 forces deterministic benchmark registries and adds provider snapshot conformance. Settings-derived embedding providers are fixed to the 256-dim pgvector contract even if `MEMTRACE_EMBEDDING_DIM` is configured differently.
- **Key Ontology (§11 complete slice):** code-defined source of truth for canonical memory keys, aliases, cardinality, default memory type/scope, LLM prompt rendering, and candidate normalization. P5-P7 completed `app.memory.key_ontology`, writer/resolver/runtime canonical identity migration, and LLM extraction normalization with safe `free_form` handling; final review verifies ontology schema coverage, package-manager correction semantics (`npm -> bun`), summarizer provider wiring, and the whole provider/ontology/runtime/replay/benchmark path.
- **Retrieval Controller:** plans retrieval using query, step intent, active state, workspace scope, and memory metadata.
- **Admission Gate:** policy engine before prompt injection; hard policies precede risk policy and soft ranking.
- **Context Packer:** emits structured blocks: active state, tool evidence, project constraints, profile/procedural/episodic memory, warnings.
- **Profiler:** records phase-level latency, candidate counts, gate counts, token/cost fields when available.
- **Evaluation/Demo:** compares vector-only versus state-aware/gated retrieval on deterministic cases.
- **Telemetry Projection Package:** `docs/design/OTEL_OPENINFERENCE_EXPORTER_PLAN.md` core exporter slice is complete through Segment 4 closeout and final full-plan review hardening. The package provides redacted `memtrace.*` / OpenInference-compatible spans, noop/in-memory/JSONL/optional OTLP sinks, settings-driven factory construction with strict/header/sample-rate controls, a fail-open `TelemetryService`, post-persistence runtime hooks, and a minimal read-only run export endpoint returning counts/generic warnings only. Runtime hooks must not synchronously perform network OTLP export, must remain fail-open on hot paths (including projection reads), and must avoid duplicate run/step lifecycle span ids; CLI export and richer access/backfill surfaces remain deferred.
- **Showcase Dashboard:** `docs/design/PHASE3B_DASHBOARD_PLAN.md` defines `apps/web` as a separate React/TypeScript frontend over `@memtrace/sdk` and existing read-only `/v1` APIs. WEB-A through WEB-J are complete as of 2026-06-20: scaffold/build boundary, SDK/query/normalizer layer, visual system, Overview/run gallery, Run Explorer, Access Replay / Memory Flow, Benchmark Lab, Memory Atlas, read-only Ops, fixture-backed Showcase route, screenshot workflow, docs, and closeout. Live API payloads and showcase fixtures pass through the same normalizers before reaching components. Memory Atlas combines `GET /v1/memories` with dashboard-table versions/conflicts and recursively redacts nested version snapshots before display; Ops uses owner-gated dashboard rows and `CapabilityState` without admin mutation UI. The app must continue not to duplicate runtime semantics, infer unavailable DTO fields, add a workspace listing API for selector polish, expand `/v1/dashboard/ui` into a large frontend, or add mutation/admin behavior without a new selected plan.

## Key Data Structures

- `AgentRun`: run ID, workspace/session, task, status, timestamps, metadata.
- `AgentStep`: step ID, run/workspace, parent/recovery links, state node ID, intent, status, error, timestamps.
- `AgentEvent`: event ID, run/step/state node, sequence number, role, event type, content digest, redaction, tool metadata, tokens, latency.
- `StateNode`: node ID, parent, step ID, node type, status, goal/summary, path/depth, branch/failure reason.
- `MemoryItem`: memory ID, workspace/session/run, type, key/value/scope, content/summary, source IDs, branch status, scores, risk flags, lifecycle status, sensitivity, embedding state.
- `MemoryAccessLog`, `MemoryGateLog`, `ProfileEvent`: auditability and profiler data.

## Key Workflows

- **Run/trace:** `start_run -> start_step -> write_event* -> finish_step`.
- **Rollback/recovery:** failed step becomes failed/rolled_back; recovery node attaches to failed step's parent, not under the failed node.
- **Write:** raw event persists first; deterministic P0 rules create project/tool/working-state memory.
- **Retrieve:** load active state -> retrieve candidates -> gate -> pack context -> write access/gate/profile logs.
- **Provider/key-ontology plan:** P1/P2/P9, P3 provider factory/DI, P4 runtime/retrieval/replay embedding provider integration, P5-P7 key ontology/write-conflict/LLM-extraction migration, P8 benchmark deterministic registry + provider conformance, and P10 full closeout are complete.
- **Demo:** user states Bun constraint -> npm failed branch -> rollback -> retrieval rejects failed npm memory -> recommends Bun path.

## Boundaries

- Gateway/facade is the only public runtime boundary.
- PostgreSQL is source of truth; pgvector/ES/Neo4j are retrieval/projection mechanisms, not authoritative memory state.
- Gate is mandatory before prompt injection.
- Profiler failures must not block the hot path.
- P0 write rules must not become a general NLP/extraction system by accident.
- Provider capability snapshots and retrieval policy snapshots must stay non-secret.
- Benchmarks must force deterministic providers even when real-provider env vars are set.
- Telemetry export is an external egress surface: it must be disabled/noop by default, recursively redacted/capped, best-effort/fail-open on runtime hot paths, no synchronous network export from hot-path hooks, quota-governed for HTTP export surfaces, and read-only when projecting persisted run data. Access-level export/backfill remains future work.
- Browser dashboard rendering is also an egress surface: consume redacted read-only APIs, preserve authz/quota/workspace isolation, never put API keys in URLs/logs/fixtures, and avoid untrusted HTML rendering.

## Persistence / Storage Design

- MVP: PostgreSQL + pgvector, tables for workspaces, sessions, runs, steps, events, state nodes, memory items, access logs, gate logs, profile events, benchmark cases/results.
- Later: Elasticsearch for hybrid retrieval, Neo4j for graph/provenance projection, Redis/Celery for buffers and async queues.

## External Integrations

- Implemented: Python SDK/CLI/LangGraph adapter, TypeScript SDK, MCP server, and MCP config templates.
- Latest completed feature: Phase 3-B Showcase Dashboard in `apps/web`; WEB-A through WEB-J are complete and fully rechecked. OpenTelemetry/OpenInference exporter remains previously complete through Segment 4 closeout.
- Future: select the next roadmap target deliberately. Dedicated IDE extension remains deferred until MCP adoption feedback shows editor-specific needs; vendor-specific LangSmith/Phoenix/Langfuse bridges remain deferred until explicitly selected as a separate bridge slice.
