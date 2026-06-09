"""Repository protocol and an in-memory implementation.

The in-memory repo gives deterministic, DB-free unit tests and powers the demo
without requiring PostgreSQL. The SQL implementation (storage/sql_repository.py)
satisfies the same protocol so the runtime facade is storage-agnostic.

All methods are async to keep a single runtime code path across both backends.
"""
from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable

from app.retrieval.similarity import cosine_similarity, stable_embedding
from app.runtime.models import (
    AgentEvent,
    AgentRun,
    AgentStep,
    EmbeddingStatus,
    MemoryAccessLog,
    BenchmarkCaseRecord,
    BenchmarkResultRecord,
    MemoryGateLog,
    MemoryItem,
    ProfileEvent,
    StateNode,
)

EMBED_DIM = 256


def ensure_embedding(memory: MemoryItem, *, dim: int = EMBED_DIM) -> MemoryItem:
    """Backfill a deterministic embedding so the memory is vector-searchable.

    Applied at the single write chokepoint (``add_memory``) so every stored
    memory carries an embedding regardless of whether it came from the rule
    writer or was seeded directly in tests/benchmarks. The embedding is a
    process-stable hashed bag-of-words vector, so it is reproducible and needs
    no external provider.
    """
    if memory.embedding_vector is None and memory.content:
        memory.embedding_vector = stable_embedding(memory.content, dim)
        memory.embedding_status = EmbeddingStatus.embedded
    return memory


@runtime_checkable
class Repository(Protocol):
    """Persistence boundary for the runtime. Implementations must be additive
    (upsert by id) and return stored copies."""

    # runs
    async def add_run(self, run: AgentRun) -> AgentRun: ...
    async def get_run(self, run_id: str) -> Optional[AgentRun]: ...
    async def update_run(self, run: AgentRun) -> AgentRun: ...
    async def list_runs(self, *, workspace_id: Optional[str] = None) -> list[AgentRun]: ...

    # steps
    async def add_step(self, step: AgentStep) -> AgentStep: ...
    async def get_step(self, step_id: str) -> Optional[AgentStep]: ...
    async def update_step(self, step: AgentStep) -> AgentStep: ...
    async def list_steps(self, run_id: str) -> list[AgentStep]: ...

    # events
    async def next_sequence_no(self, run_id: str) -> int: ...
    async def add_event(self, event: AgentEvent) -> AgentEvent: ...
    async def list_events(self, run_id: str) -> list[AgentEvent]: ...
    async def get_event(self, event_id: str) -> Optional[AgentEvent]: ...

    # state nodes
    async def add_state_node(self, node: StateNode) -> StateNode: ...
    async def get_state_node(self, node_id: str) -> Optional[StateNode]: ...
    async def update_state_node(self, node: StateNode) -> StateNode: ...
    async def list_state_nodes(self, run_id: str) -> list[StateNode]: ...

    # memories
    async def add_memory(self, memory: MemoryItem) -> MemoryItem: ...
    async def get_memory(self, memory_id: str) -> Optional[MemoryItem]: ...
    async def update_memory(self, memory: MemoryItem) -> MemoryItem: ...
    async def list_memories(
        self,
        *,
        workspace_id: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> list[MemoryItem]: ...
    async def search_memories_by_vector(
        self,
        *,
        embedding: list[float],
        workspace_id: Optional[str] = None,
        top_k: int = 10,
    ) -> list[tuple[MemoryItem, float]]: ...

    # logs / profile
    async def add_access_log(self, log: MemoryAccessLog) -> MemoryAccessLog: ...
    async def get_access_log(self, access_id: str) -> Optional[MemoryAccessLog]: ...
    async def list_access_logs(self, *, workspace_id: Optional[str] = None) -> list[MemoryAccessLog]: ...
    async def add_gate_log(self, log: MemoryGateLog) -> MemoryGateLog: ...
    async def list_gate_logs(self, access_id: str) -> list[MemoryGateLog]: ...
    async def add_profile_event(self, event: ProfileEvent) -> ProfileEvent: ...
    async def list_profile_events(
        self, *, run_id: Optional[str] = None, access_id: Optional[str] = None
    ) -> list[ProfileEvent]: ...

    # benchmark / dashboard tables
    async def add_benchmark_case(self, case: BenchmarkCaseRecord) -> BenchmarkCaseRecord: ...
    async def add_benchmark_result(self, result: BenchmarkResultRecord) -> BenchmarkResultRecord: ...
    async def list_benchmark_cases(self) -> list[BenchmarkCaseRecord]: ...
    async def list_benchmark_results(self) -> list[BenchmarkResultRecord]: ...


class InMemoryRepository:
    """Deterministic in-process repository. Stores deep copies to avoid
    accidental aliasing between caller and store."""

    def __init__(self) -> None:
        self._runs: dict[str, AgentRun] = {}
        self._steps: dict[str, AgentStep] = {}
        self._events: dict[str, AgentEvent] = {}
        self._nodes: dict[str, StateNode] = {}
        self._memories: dict[str, MemoryItem] = {}
        self._access_logs: dict[str, MemoryAccessLog] = {}
        self._gate_logs: list[MemoryGateLog] = []
        self._profile_events: list[ProfileEvent] = []
        self._benchmark_cases: dict[str, BenchmarkCaseRecord] = {}
        self._benchmark_results: dict[str, BenchmarkResultRecord] = {}
        self._seq_counters: dict[str, int] = {}

    # runs
    async def add_run(self, run: AgentRun) -> AgentRun:
        self._runs[run.run_id] = run.model_copy(deep=True)
        return run

    async def get_run(self, run_id: str) -> Optional[AgentRun]:
        r = self._runs.get(run_id)
        return r.model_copy(deep=True) if r else None

    async def update_run(self, run: AgentRun) -> AgentRun:
        self._runs[run.run_id] = run.model_copy(deep=True)
        return run

    async def list_runs(self, *, workspace_id: Optional[str] = None) -> list[AgentRun]:
        runs = []
        for r in self._runs.values():
            if workspace_id is not None and r.workspace_id != workspace_id:
                continue
            runs.append(r.model_copy(deep=True))
        runs.sort(key=lambda r: r.created_at)
        return runs

    # steps
    async def add_step(self, step: AgentStep) -> AgentStep:
        self._steps[step.step_id] = step.model_copy(deep=True)
        return step

    async def get_step(self, step_id: str) -> Optional[AgentStep]:
        s = self._steps.get(step_id)
        return s.model_copy(deep=True) if s else None

    async def update_step(self, step: AgentStep) -> AgentStep:
        self._steps[step.step_id] = step.model_copy(deep=True)
        return step

    async def list_steps(self, run_id: str) -> list[AgentStep]:
        steps = [s for s in self._steps.values() if s.run_id == run_id]
        steps.sort(key=lambda s: s.created_at)
        return [s.model_copy(deep=True) for s in steps]

    # events
    async def next_sequence_no(self, run_id: str) -> int:
        self._seq_counters[run_id] = self._seq_counters.get(run_id, 0) + 1
        return self._seq_counters[run_id]

    async def add_event(self, event: AgentEvent) -> AgentEvent:
        self._events[event.event_id] = event.model_copy(deep=True)
        return event

    async def list_events(self, run_id: str) -> list[AgentEvent]:
        events = [e for e in self._events.values() if e.run_id == run_id]
        events.sort(key=lambda e: e.sequence_no)
        return [e.model_copy(deep=True) for e in events]

    async def get_event(self, event_id: str) -> Optional[AgentEvent]:
        e = self._events.get(event_id)
        return e.model_copy(deep=True) if e else None

    # state nodes
    async def add_state_node(self, node: StateNode) -> StateNode:
        self._nodes[node.node_id] = node.model_copy(deep=True)
        return node

    async def get_state_node(self, node_id: str) -> Optional[StateNode]:
        n = self._nodes.get(node_id)
        return n.model_copy(deep=True) if n else None

    async def update_state_node(self, node: StateNode) -> StateNode:
        self._nodes[node.node_id] = node.model_copy(deep=True)
        return node

    async def list_state_nodes(self, run_id: str) -> list[StateNode]:
        nodes = [n for n in self._nodes.values() if n.run_id == run_id]
        nodes.sort(key=lambda n: (n.depth, n.created_at))
        return [n.model_copy(deep=True) for n in nodes]

    # memories
    async def add_memory(self, memory: MemoryItem) -> MemoryItem:
        ensure_embedding(memory)
        self._memories[memory.memory_id] = memory.model_copy(deep=True)
        return memory

    async def get_memory(self, memory_id: str) -> Optional[MemoryItem]:
        m = self._memories.get(memory_id)
        return m.model_copy(deep=True) if m else None

    async def update_memory(self, memory: MemoryItem) -> MemoryItem:
        self._memories[memory.memory_id] = memory.model_copy(deep=True)
        return memory

    async def list_memories(
        self,
        *,
        workspace_id: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> list[MemoryItem]:
        out = []
        for m in self._memories.values():
            if workspace_id is not None and m.workspace_id != workspace_id:
                continue
            if run_id is not None and m.run_id != run_id:
                continue
            out.append(m.model_copy(deep=True))
        out.sort(key=lambda m: m.created_at)
        return out

    async def search_memories_by_vector(
        self,
        *,
        embedding: list[float],
        workspace_id: Optional[str] = None,
        top_k: int = 10,
    ) -> list[tuple[MemoryItem, float]]:
        scored: list[tuple[MemoryItem, float]] = []
        for m in self._memories.values():
            if workspace_id is not None and m.workspace_id != workspace_id:
                continue
            if not m.embedding_vector:
                continue
            sim = cosine_similarity(embedding, m.embedding_vector)
            if sim > 0.0:
                scored.append((m.model_copy(deep=True), sim))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    # logs / profile
    async def add_access_log(self, log: MemoryAccessLog) -> MemoryAccessLog:
        self._access_logs[log.access_id] = log.model_copy(deep=True)
        return log

    async def get_access_log(self, access_id: str) -> Optional[MemoryAccessLog]:
        a = self._access_logs.get(access_id)
        return a.model_copy(deep=True) if a else None

    async def list_access_logs(self, *, workspace_id: Optional[str] = None) -> list[MemoryAccessLog]:
        logs = []
        for a in self._access_logs.values():
            if workspace_id is not None and a.workspace_id != workspace_id:
                continue
            logs.append(a.model_copy(deep=True))
        logs.sort(key=lambda a: a.created_at)
        return logs

    async def add_gate_log(self, log: MemoryGateLog) -> MemoryGateLog:
        self._gate_logs.append(log.model_copy(deep=True))
        return log

    async def list_gate_logs(self, access_id: str) -> list[MemoryGateLog]:
        return [g.model_copy(deep=True) for g in self._gate_logs if g.access_id == access_id]

    async def add_profile_event(self, event: ProfileEvent) -> ProfileEvent:
        self._profile_events.append(event.model_copy(deep=True))
        return event

    async def list_profile_events(
        self, *, run_id: Optional[str] = None, access_id: Optional[str] = None
    ) -> list[ProfileEvent]:
        out = []
        for p in self._profile_events:
            if run_id is not None and p.run_id != run_id:
                continue
            if access_id is not None and p.access_id != access_id:
                continue
            out.append(p.model_copy(deep=True))
        return out

    # benchmark / dashboard tables
    async def add_benchmark_case(self, case: BenchmarkCaseRecord) -> BenchmarkCaseRecord:
        self._benchmark_cases[case.case_id] = case.model_copy(deep=True)
        return case

    async def add_benchmark_result(self, result: BenchmarkResultRecord) -> BenchmarkResultRecord:
        self._benchmark_results[result.result_id] = result.model_copy(deep=True)
        return result

    async def list_benchmark_cases(self) -> list[BenchmarkCaseRecord]:
        rows = sorted(self._benchmark_cases.values(), key=lambda c: c.case_id)
        return [r.model_copy(deep=True) for r in rows]

    async def list_benchmark_results(self) -> list[BenchmarkResultRecord]:
        rows = sorted(self._benchmark_results.values(), key=lambda r: (r.case_id, r.strategy, r.created_at))
        return [r.model_copy(deep=True) for r in rows]


__all__ = ["Repository", "InMemoryRepository"]
