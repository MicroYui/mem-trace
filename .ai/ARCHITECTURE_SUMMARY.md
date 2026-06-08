# Architecture Summary

## High-Level Architecture

```text
Agent / demo loop
  -> Memory Gateway / SDK / MemoryRuntime facade
  -> Runtime Core
     -> Trace Collector
     -> Execution State Tree
     -> Rule-based Write Pipeline
     -> Retrieval Controller
     -> Admission Gate
     -> Profiler
  -> PostgreSQL + pgvector source of truth
  -> CLI/JSON/Markdown report first; dashboard later
```

Longer-term documents also describe Redis/Celery, Elasticsearch, Neo4j, React dashboard, and evaluation harness, but the MVP narrows the first hot path.

## Core Modules and Responsibilities

- **MemoryRuntime facade:** stable external API; hides storage, indexing, policy, profiling, and future async work.
- **Agent Trace Collector:** records raw agent events before extraction; source for state tree, memories, and profiler.
- **Execution State Tree:** organizes runs into active/completed/failed/rolled_back paths; isolates failed branches from prompt context.
- **Write Pipeline:** converts selected events into memory items; P0 uses deterministic rules, P2 may add LLM extraction and buffering.
- **Retrieval Controller:** plans retrieval using query, step intent, active state, workspace scope, and memory metadata.
- **Admission Gate:** policy engine before prompt injection; hard policies precede risk policy and soft ranking.
- **Context Packer:** emits structured blocks: active state, tool evidence, project constraints, profile/procedural/episodic memory, warnings.
- **Profiler:** records phase-level latency, candidate counts, gate counts, token/cost fields when available.
- **Evaluation/Demo:** compares vector-only versus state-aware/gated retrieval on deterministic cases.

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
- **Demo:** user states Bun constraint -> npm failed branch -> rollback -> retrieval rejects failed npm memory -> recommends Bun path.

## Boundaries

- Gateway/facade is the only public runtime boundary.
- PostgreSQL is source of truth; pgvector/ES/Neo4j are retrieval/projection mechanisms, not authoritative memory state.
- Gate is mandatory before prompt injection.
- Profiler failures must not block the hot path.
- P0 write rules must not become a general NLP/extraction system by accident.

## Persistence / Storage Design

- MVP: PostgreSQL + pgvector, tables for workspaces, sessions, runs, steps, events, state nodes, memory items, access logs, gate logs, profile events, benchmark cases/results.
- Later: Elasticsearch for hybrid retrieval, Neo4j for graph/provenance projection, Redis/Celery for buffers and async queues.

## External Integrations

- P0: OpenAI-compatible LLM client only if demo generation needs it; retrieval benchmark can use rule evaluator.
- Later: LangGraph adapter, TypeScript SDK, OpenTelemetry/OpenInference exporter, frontend dashboard.

