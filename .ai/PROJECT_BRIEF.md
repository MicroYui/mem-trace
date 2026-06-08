# Project Brief

- **Project definition:** MemTrace is a state-aware memory runtime and profiler for long-horizon LLM agents.
- **Target users:** developers building long-running agents; infra/platform engineers inspecting agent memory behavior; project authors demonstrating agent state management and observability.
- **Usage scenarios:** coding/debugging demo agent, multi-step tool workflows, failed-branch recovery, project preference persistence, memory access replay, retrieval/gate profiling.
- **Core value proposition:** upgrade vector-memory retrieval into execution-state-aware context construction, step-aware retrieval, admission-gated memory injection, and phase-aware profiling.
- **Main technical themes:** Agent trace collection, execution state tree, MemoryRuntime facade, rule-based admission gate, structured context packing, PostgreSQL-backed memory model, profiler/evaluation harness.
- **Resume-worthy value:** demonstrates agent infra beyond RAG by making memory a runtime component with traceability, failure isolation, safety policy, and measurable cost/quality effects.

