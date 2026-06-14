"""Repository protocol and an in-memory implementation.

The in-memory repo gives deterministic, DB-free unit tests and powers the demo
without requiring PostgreSQL. The SQL implementation (storage/sql_repository.py)
satisfies the same protocol so the runtime facade is storage-agnostic.

All methods are async to keep a single runtime code path across both backends.
"""
from __future__ import annotations

from typing import Optional, Protocol, runtime_checkable
from datetime import datetime

from app.retrieval.similarity import cosine_similarity, stable_embedding
from app.runtime.models import (
    AdminActionAuditRecord,
    ApiKeyRecord,
    AgentEvent,
    AgentRun,
    AgentStep,
    EmbeddingStatus,
    MemoryAccessLog,
    BenchmarkCaseRecord,
    BenchmarkResultRecord,
    ContextCompactionLog,
    EvalCaseRecord,
    EvalResultRecord,
    EvalRunRecord,
    MemoryLifecycleAuditRecord,
    MemoryGateLog,
    MemoryItem,
    MemoryRetentionSignal,
    MemoryStatus,
    MaintenanceRunRecord,
    MaintenanceTaskAttemptRecord,
    MemoryVersionRecord,
    MemoryConflictRecord,
    ProfileEvent,
    QuotaLimitRecord,
    StateNode,
)
from app.memory.versioning import redacted_memory_snapshot, should_create_memory_version

EMBED_DIM = 256
MAX_ADMIN_PAGE_SIZE = 500


def _validate_pagination(*, limit: int, offset: int) -> None:
    if limit < 1 or limit > MAX_ADMIN_PAGE_SIZE:
        raise ValueError("limit must be between 1 and 500")
    if offset < 0:
        raise ValueError("offset must be non-negative")


def _same_quota_limit_identity(left: QuotaLimitRecord, right: QuotaLimitRecord) -> bool:
    return (
        left.workspace_id == right.workspace_id
        and left.principal_id == right.principal_id
        and left.unit == right.unit
    )


def _quota_limit_with_preserved_identity(
    incoming: QuotaLimitRecord,
    existing: QuotaLimitRecord,
) -> QuotaLimitRecord:
    return incoming.model_copy(
        update={
            "quota_limit_id": existing.quota_limit_id,
            "workspace_id": existing.workspace_id,
            "principal_id": existing.principal_id,
            "unit": existing.unit,
            "created_by": existing.created_by,
            "created_at": existing.created_at,
        },
        deep=True,
    )


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


def _preserved_lifecycle_fields(before: MemoryItem, incoming: MemoryItem) -> dict[str, object]:
    """Prevent stale ordinary updates from re-activating lifecycle-managed rows."""

    if before.status != MemoryStatus.active and incoming.status == MemoryStatus.active:
        return {
            "status": before.status,
            "lifecycle_metadata": dict(before.lifecycle_metadata or {}),
            "superseded_by": before.superseded_by,
        }
    return {}


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
    async def append_event(self, event: AgentEvent) -> AgentEvent: ...
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
    async def bump_memory_access(self, memory_id: str, *, accessed_at: datetime) -> None: ...
    async def transition_memory_with_audit(
        self,
        memory: MemoryItem,
        audit: MemoryLifecycleAuditRecord,
    ) -> tuple[MemoryItem, MemoryLifecycleAuditRecord]: ...
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
    async def add_lifecycle_audit(self, audit: MemoryLifecycleAuditRecord) -> MemoryLifecycleAuditRecord: ...
    async def list_lifecycle_audits(
        self,
        *,
        workspace_id: Optional[str] = None,
        memory_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[MemoryLifecycleAuditRecord]: ...
    async def upsert_retention_signal(self, signal: MemoryRetentionSignal) -> MemoryRetentionSignal: ...
    async def get_retention_signal(self, memory_id: str) -> Optional[MemoryRetentionSignal]: ...
    async def list_retention_signals(
        self,
        workspace_id: str,
        memory_ids: Optional[list[str]] = None,
    ) -> list[MemoryRetentionSignal]: ...
    async def add_memory_version(self, version: MemoryVersionRecord) -> MemoryVersionRecord: ...
    async def list_memory_versions(self, memory_id: str) -> list[MemoryVersionRecord]: ...
    async def upsert_memory_conflict(self, conflict: MemoryConflictRecord) -> MemoryConflictRecord: ...
    async def get_memory_conflict(self, conflict_id: str) -> Optional[MemoryConflictRecord]: ...
    async def update_memory_conflict(self, conflict: MemoryConflictRecord) -> MemoryConflictRecord: ...
    async def list_memory_conflicts(
        self,
        *,
        workspace_id: Optional[str] = None,
        memory_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[MemoryConflictRecord]: ...

    # maintenance/admin records
    async def add_maintenance_run(self, run: MaintenanceRunRecord) -> MaintenanceRunRecord: ...
    async def get_maintenance_run(self, scheduler_run_id: str) -> Optional[MaintenanceRunRecord]: ...
    async def update_maintenance_run(self, run: MaintenanceRunRecord) -> MaintenanceRunRecord: ...
    async def list_maintenance_runs(
        self,
        *,
        workspace_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[MaintenanceRunRecord]: ...
    async def add_maintenance_task_attempt(
        self, attempt: MaintenanceTaskAttemptRecord
    ) -> MaintenanceTaskAttemptRecord: ...
    async def update_maintenance_task_attempt(
        self, attempt: MaintenanceTaskAttemptRecord
    ) -> MaintenanceTaskAttemptRecord: ...
    async def list_maintenance_task_attempts(
        self,
        *,
        scheduler_run_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list[MaintenanceTaskAttemptRecord]: ...
    async def add_admin_action_audit(self, audit: AdminActionAuditRecord) -> AdminActionAuditRecord: ...
    async def list_admin_action_audits(
        self,
        *,
        workspace_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AdminActionAuditRecord]: ...
    async def upsert_quota_limit(self, limit: QuotaLimitRecord) -> QuotaLimitRecord: ...
    async def get_quota_limit(self, quota_limit_id: str) -> Optional[QuotaLimitRecord]: ...
    async def list_quota_limits(
        self,
        *,
        workspace_id: str,
        principal_id: Optional[str] = None,
        all_principals: bool = False,
        unit: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[QuotaLimitRecord]: ...
    async def delete_quota_limit(self, quota_limit_id: str) -> None: ...

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
    async def add_compaction_log(self, log: ContextCompactionLog) -> ContextCompactionLog: ...
    async def list_compaction_logs(
        self,
        *,
        access_id: Optional[str] = None,
        run_id: Optional[str] = None,
        workspace_id: Optional[str] = None,
    ) -> list[ContextCompactionLog]: ...

    # benchmark / dashboard tables
    async def add_benchmark_case(self, case: BenchmarkCaseRecord) -> BenchmarkCaseRecord: ...
    async def add_benchmark_result(self, result: BenchmarkResultRecord) -> BenchmarkResultRecord: ...
    async def list_benchmark_cases(self) -> list[BenchmarkCaseRecord]: ...
    async def list_benchmark_results(self) -> list[BenchmarkResultRecord]: ...

    # eval / dashboard tables
    async def add_eval_case(self, case: EvalCaseRecord) -> EvalCaseRecord: ...
    async def list_eval_cases(self) -> list[EvalCaseRecord]: ...
    async def add_eval_run(self, run: EvalRunRecord) -> EvalRunRecord: ...
    async def update_eval_run(self, run: EvalRunRecord) -> EvalRunRecord: ...
    async def list_eval_runs(self, *, workspace_id: Optional[str] = None) -> list[EvalRunRecord]: ...
    async def add_eval_result(self, result: EvalResultRecord) -> EvalResultRecord: ...
    async def update_eval_result(self, result: EvalResultRecord) -> EvalResultRecord: ...
    async def list_eval_results(self, *, eval_run_id: Optional[str] = None) -> list[EvalResultRecord]: ...

    # governance
    async def add_api_key(self, key: ApiKeyRecord) -> ApiKeyRecord: ...
    async def list_api_keys(
        self,
        *,
        workspace_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ApiKeyRecord]: ...
    async def get_api_key_by_prefix(self, key_prefix: str) -> Optional[ApiKeyRecord]: ...
    async def get_api_key(self, api_key_id: str) -> Optional[ApiKeyRecord]: ...
    async def revoke_api_key(self, api_key_id: str, *, revoked_at: datetime) -> Optional[ApiKeyRecord]: ...
    async def mark_api_key_used(self, api_key_id: str, *, used_at: datetime) -> None: ...
    async def workspace_for_run(self, run_id: str) -> Optional[str]: ...
    async def workspace_for_step(self, step_id: str) -> Optional[str]: ...
    async def workspace_for_access(self, access_id: str) -> Optional[str]: ...
    async def workspace_for_memory(self, memory_id: str) -> Optional[str]: ...
    async def workspace_for_eval_run(self, eval_run_id: str) -> Optional[str]: ...


class InMemoryRepository:
    """Deterministic in-process repository. Stores deep copies to avoid
    accidental aliasing between caller and store."""

    def __init__(self) -> None:
        self._runs: dict[str, AgentRun] = {}
        self._steps: dict[str, AgentStep] = {}
        self._events: dict[str, AgentEvent] = {}
        self._nodes: dict[str, StateNode] = {}
        self._memories: dict[str, MemoryItem] = {}
        self._lifecycle_audits: dict[str, MemoryLifecycleAuditRecord] = {}
        self._retention_signals: dict[str, MemoryRetentionSignal] = {}
        self._memory_versions: dict[str, MemoryVersionRecord] = {}
        self._memory_conflicts: dict[str, MemoryConflictRecord] = {}
        self._maintenance_runs: dict[str, MaintenanceRunRecord] = {}
        self._maintenance_task_attempts: dict[str, MaintenanceTaskAttemptRecord] = {}
        self._admin_action_audits: dict[str, AdminActionAuditRecord] = {}
        self._quota_limits: dict[str, QuotaLimitRecord] = {}
        self._access_logs: dict[str, MemoryAccessLog] = {}
        self._gate_logs: list[MemoryGateLog] = []
        self._profile_events: list[ProfileEvent] = []
        self._compaction_logs: dict[str, ContextCompactionLog] = {}
        self._benchmark_cases: dict[str, BenchmarkCaseRecord] = {}
        self._benchmark_results: dict[str, BenchmarkResultRecord] = {}
        self._eval_cases: dict[str, EvalCaseRecord] = {}
        self._eval_runs: dict[str, EvalRunRecord] = {}
        self._eval_results: dict[str, EvalResultRecord] = {}
        self._api_keys: dict[str, ApiKeyRecord] = {}
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

    async def append_event(self, event: AgentEvent) -> AgentEvent:
        self._seq_counters[event.run_id] = self._seq_counters.get(event.run_id, 0) + 1
        stored = event.model_copy(update={"sequence_no": self._seq_counters[event.run_id]})
        self._events[stored.event_id] = stored.model_copy(deep=True)
        return stored.model_copy(deep=True)

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
        before = self._memories.get(memory.memory_id)
        after = memory
        if before is not None:
            semantic_change = should_create_memory_version(before, memory)
            if semantic_change:
                after = memory.model_copy(
                    update={
                        "access_count": before.access_count,
                        "last_accessed_at": before.last_accessed_at,
                        **_preserved_lifecycle_fields(before, memory),
                    },
                    deep=True,
                )
            else:
                after = memory
        if before is not None and should_create_memory_version(before, after):
            await self.add_memory_version(
                MemoryVersionRecord(
                    memory_id=after.memory_id,
                    workspace_id=after.workspace_id,
                    version_no=self._next_memory_version_no(memory.memory_id),
                    snapshot=redacted_memory_snapshot(after),
                    change_reason="update_memory",
                )
            )
        self._memories[after.memory_id] = after.model_copy(deep=True)
        return after

    def _next_memory_version_no(self, memory_id: str) -> int:
        return 1 + sum(1 for version in self._memory_versions.values() if version.memory_id == memory_id)

    async def bump_memory_access(self, memory_id: str, *, accessed_at: datetime) -> None:
        current = self._memories.get(memory_id)
        if current is None:
            return
        self._memories[memory_id] = current.model_copy(
            update={
                "access_count": current.access_count + 1,
                "last_accessed_at": accessed_at,
                "updated_at": accessed_at,
            },
            deep=True,
        )

    async def transition_memory_with_audit(
        self,
        memory: MemoryItem,
        audit: MemoryLifecycleAuditRecord,
    ) -> tuple[MemoryItem, MemoryLifecycleAuditRecord]:
        current = self._memories.get(memory.memory_id)
        if current is None:
            raise ValueError(f"memory not found for lifecycle transition: {memory.memory_id}")
        if current.status != audit.from_status:
            raise ValueError(
                f"stale lifecycle transition for {memory.memory_id}: "
                f"expected {audit.from_status.value}, found {current.status.value}"
            )
        after = current.model_copy(
            update={
                "status": memory.status,
                "lifecycle_metadata": dict(memory.lifecycle_metadata or {}),
                "superseded_by": memory.superseded_by,
                "updated_at": memory.updated_at,
            },
            deep=True,
        )
        if should_create_memory_version(current, after):
            await self.add_memory_version(
                MemoryVersionRecord(
                    memory_id=memory.memory_id,
                    workspace_id=memory.workspace_id,
                    version_no=self._next_memory_version_no(memory.memory_id),
                    snapshot=redacted_memory_snapshot(after),
                    change_reason=f"lifecycle:{audit.reason}",
                )
            )
        self._memories[memory.memory_id] = current.model_copy(
            update={
                "status": memory.status,
                "lifecycle_metadata": dict(memory.lifecycle_metadata or {}),
                "superseded_by": memory.superseded_by,
                "updated_at": memory.updated_at,
            },
            deep=True,
        )
        self._lifecycle_audits[audit.audit_id] = audit.model_copy(deep=True)
        return memory, audit

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

    async def add_lifecycle_audit(self, audit: MemoryLifecycleAuditRecord) -> MemoryLifecycleAuditRecord:
        self._lifecycle_audits[audit.audit_id] = audit.model_copy(deep=True)
        return audit

    async def list_lifecycle_audits(
        self,
        *,
        workspace_id: Optional[str] = None,
        memory_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[MemoryLifecycleAuditRecord]:
        _validate_pagination(limit=limit, offset=offset)
        rows = []
        for audit in self._lifecycle_audits.values():
            if workspace_id is not None and audit.workspace_id != workspace_id:
                continue
            if memory_id is not None and audit.memory_id != memory_id:
                continue
            rows.append(audit)
        rows.sort(key=lambda a: (a.created_at, a.audit_id))
        return [row.model_copy(deep=True) for row in rows[offset : offset + limit]]

    async def upsert_retention_signal(self, signal: MemoryRetentionSignal) -> MemoryRetentionSignal:
        self._retention_signals[signal.memory_id] = signal.model_copy(deep=True)
        return signal

    async def get_retention_signal(self, memory_id: str) -> Optional[MemoryRetentionSignal]:
        signal = self._retention_signals.get(memory_id)
        return signal.model_copy(deep=True) if signal else None

    async def list_retention_signals(
        self,
        workspace_id: str,
        memory_ids: Optional[list[str]] = None,
    ) -> list[MemoryRetentionSignal]:
        wanted = set(memory_ids) if memory_ids is not None else None
        rows = []
        for signal in self._retention_signals.values():
            if signal.workspace_id != workspace_id:
                continue
            if wanted is not None and signal.memory_id not in wanted:
                continue
            rows.append(signal)
        rows.sort(key=lambda s: (s.workspace_id, s.memory_id))
        return [row.model_copy(deep=True) for row in rows]

    async def add_memory_version(self, version: MemoryVersionRecord) -> MemoryVersionRecord:
        for existing in self._memory_versions.values():
            if (
                existing.memory_id == version.memory_id
                and existing.version_no == version.version_no
                and existing.version_id != version.version_id
            ):
                raise ValueError(
                    f"duplicate memory version for {version.memory_id}#{version.version_no}"
                )
        self._memory_versions[version.version_id] = version.model_copy(deep=True)
        return version

    async def list_memory_versions(self, memory_id: str) -> list[MemoryVersionRecord]:
        rows = [version for version in self._memory_versions.values() if version.memory_id == memory_id]
        rows.sort(key=lambda v: (v.version_no, v.created_at, v.version_id))
        return [row.model_copy(deep=True) for row in rows]

    async def upsert_memory_conflict(self, conflict: MemoryConflictRecord) -> MemoryConflictRecord:
        self._memory_conflicts[conflict.conflict_id] = conflict.model_copy(deep=True)
        return conflict

    async def get_memory_conflict(self, conflict_id: str) -> Optional[MemoryConflictRecord]:
        conflict = self._memory_conflicts.get(conflict_id)
        return conflict.model_copy(deep=True) if conflict else None

    async def update_memory_conflict(self, conflict: MemoryConflictRecord) -> MemoryConflictRecord:
        current = self._memory_conflicts.get(conflict.conflict_id)
        if current is None:
            raise ValueError("memory conflict not found")
        stored = conflict.model_copy(
            update={
                "workspace_id": current.workspace_id,
                "subject_key": current.subject_key,
                "memory_ids": list(current.memory_ids),
                "detected_by": current.detected_by,
                "created_at": current.created_at,
            },
            deep=True,
        )
        self._memory_conflicts[stored.conflict_id] = stored.model_copy(deep=True)
        return stored

    async def list_memory_conflicts(
        self,
        *,
        workspace_id: Optional[str] = None,
        memory_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[MemoryConflictRecord]:
        _validate_pagination(limit=limit, offset=offset)
        rows = []
        for conflict in self._memory_conflicts.values():
            if workspace_id is not None and conflict.workspace_id != workspace_id:
                continue
            if memory_id is not None and memory_id not in conflict.memory_ids:
                continue
            if status is not None and conflict.status != status:
                continue
            rows.append(conflict)
        rows.sort(key=lambda c: (c.created_at, c.conflict_id))
        return [row.model_copy(deep=True) for row in rows[offset : offset + limit]]

    # maintenance/admin records
    async def add_maintenance_run(self, run: MaintenanceRunRecord) -> MaintenanceRunRecord:
        operation_values = [operation.value for operation in run.operations]
        if len(operation_values) != len(set(operation_values)):
            raise ValueError("duplicate maintenance operation in run")
        self._maintenance_runs[run.scheduler_run_id] = run.model_copy(deep=True)
        return run

    async def get_maintenance_run(self, scheduler_run_id: str) -> Optional[MaintenanceRunRecord]:
        run = self._maintenance_runs.get(scheduler_run_id)
        return run.model_copy(deep=True) if run else None

    async def update_maintenance_run(self, run: MaintenanceRunRecord) -> MaintenanceRunRecord:
        current = self._maintenance_runs.get(run.scheduler_run_id)
        if current is None:
            raise ValueError("maintenance run not found")
        stored = run.model_copy(
            update={
                "workspace_id": current.workspace_id,
                "requested_by": current.requested_by,
                "reason": current.reason,
                "operations": list(current.operations),
                "dry_run": current.dry_run,
                "created_at": current.created_at,
            },
            deep=True,
        )
        self._maintenance_runs[stored.scheduler_run_id] = stored.model_copy(deep=True)
        return stored

    async def list_maintenance_runs(
        self,
        *,
        workspace_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[MaintenanceRunRecord]:
        _validate_pagination(limit=limit, offset=offset)
        rows = []
        for run in self._maintenance_runs.values():
            if workspace_id is not None and run.workspace_id != workspace_id:
                continue
            rows.append(run)
        rows.sort(key=lambda run: (run.created_at, run.scheduler_run_id))
        return [row.model_copy(deep=True) for row in rows[offset : offset + limit]]

    async def add_maintenance_task_attempt(
        self, attempt: MaintenanceTaskAttemptRecord
    ) -> MaintenanceTaskAttemptRecord:
        for existing in self._maintenance_task_attempts.values():
            if (
                existing.scheduler_run_id == attempt.scheduler_run_id
                and existing.operation == attempt.operation
                and existing.attempt_id != attempt.attempt_id
            ):
                raise ValueError("duplicate maintenance task attempt for run operation")
        self._maintenance_task_attempts[attempt.attempt_id] = attempt.model_copy(deep=True)
        return attempt

    async def update_maintenance_task_attempt(
        self, attempt: MaintenanceTaskAttemptRecord
    ) -> MaintenanceTaskAttemptRecord:
        current = self._maintenance_task_attempts.get(attempt.attempt_id)
        if current is None:
            raise ValueError("maintenance task attempt not found")
        if (
            current.scheduler_run_id != attempt.scheduler_run_id
            or current.workspace_id != attempt.workspace_id
            or current.operation != attempt.operation
        ):
            raise ValueError("maintenance task attempt identity cannot change")
        for existing in self._maintenance_task_attempts.values():
            if (
                existing.scheduler_run_id == attempt.scheduler_run_id
                and existing.operation == attempt.operation
                and existing.attempt_id != attempt.attempt_id
            ):
                raise ValueError("duplicate maintenance task attempt for run operation")
        attempt = attempt.model_copy(update={"created_at": current.created_at}, deep=True)
        self._maintenance_task_attempts[attempt.attempt_id] = attempt.model_copy(deep=True)
        return attempt

    async def list_maintenance_task_attempts(
        self,
        *,
        scheduler_run_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list[MaintenanceTaskAttemptRecord]:
        _validate_pagination(limit=limit, offset=offset)
        rows = [
            attempt
            for attempt in self._maintenance_task_attempts.values()
            if attempt.scheduler_run_id == scheduler_run_id
        ]
        rows.sort(key=lambda attempt: (attempt.created_at, attempt.attempt_id))
        return [row.model_copy(deep=True) for row in rows[offset : offset + limit]]

    async def add_admin_action_audit(self, audit: AdminActionAuditRecord) -> AdminActionAuditRecord:
        self._admin_action_audits[audit.admin_action_id] = audit.model_copy(deep=True)
        return audit

    async def list_admin_action_audits(
        self,
        *,
        workspace_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AdminActionAuditRecord]:
        _validate_pagination(limit=limit, offset=offset)
        rows = []
        for audit in self._admin_action_audits.values():
            if workspace_id is not None and audit.workspace_id != workspace_id:
                continue
            rows.append(audit)
        rows.sort(key=lambda audit: (audit.created_at, audit.admin_action_id))
        return [row.model_copy(deep=True) for row in rows[offset : offset + limit]]

    async def upsert_quota_limit(self, limit: QuotaLimitRecord) -> QuotaLimitRecord:
        current = self._quota_limits.get(limit.quota_limit_id)
        if current is not None and not _same_quota_limit_identity(current, limit):
            raise ValueError("quota limit identity cannot change")
        for quota_limit_id, existing in list(self._quota_limits.items()):
            if (
                existing.workspace_id == limit.workspace_id
                and existing.principal_id == limit.principal_id
                and existing.unit == limit.unit
                and existing.quota_limit_id != limit.quota_limit_id
            ):
                limit = _quota_limit_with_preserved_identity(limit, existing)
                del self._quota_limits[quota_limit_id]
        if current is not None:
            limit = _quota_limit_with_preserved_identity(limit, current)
        self._quota_limits[limit.quota_limit_id] = limit.model_copy(deep=True)
        return limit

    async def list_quota_limits(
        self,
        *,
        workspace_id: str,
        principal_id: Optional[str] = None,
        all_principals: bool = False,
        unit: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[QuotaLimitRecord]:
        _validate_pagination(limit=limit, offset=offset)
        rows = []
        for quota_limit in self._quota_limits.values():
            if quota_limit.workspace_id != workspace_id:
                continue
            if not all_principals and quota_limit.principal_id != principal_id:
                continue
            if unit is not None and quota_limit.unit != unit:
                continue
            rows.append(quota_limit)
        rows.sort(key=lambda quota_limit: (quota_limit.created_at, quota_limit.quota_limit_id))
        return [row.model_copy(deep=True) for row in rows[offset : offset + limit]]

    async def get_quota_limit(self, quota_limit_id: str) -> Optional[QuotaLimitRecord]:
        limit = self._quota_limits.get(quota_limit_id)
        return limit.model_copy(deep=True) if limit else None

    async def delete_quota_limit(self, quota_limit_id: str) -> None:
        self._quota_limits.pop(quota_limit_id, None)

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
        rows = [g for g in self._gate_logs if g.access_id == access_id]
        rows.sort(key=lambda g: (g.created_at, g.gate_id))
        return [g.model_copy(deep=True) for g in rows]

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

    async def add_compaction_log(self, log: ContextCompactionLog) -> ContextCompactionLog:
        self._compaction_logs[log.compaction_id] = log.model_copy(deep=True)
        return log

    async def list_compaction_logs(
        self,
        *,
        access_id: Optional[str] = None,
        run_id: Optional[str] = None,
        workspace_id: Optional[str] = None,
    ) -> list[ContextCompactionLog]:
        rows = []
        for log in self._compaction_logs.values():
            if access_id is not None and log.access_id != access_id:
                continue
            if run_id is not None and log.run_id != run_id:
                continue
            if workspace_id is not None and log.workspace_id != workspace_id:
                continue
            rows.append(log)
        rows.sort(key=lambda log: (log.created_at, log.compaction_id))
        return [row.model_copy(deep=True) for row in rows]

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

    # eval / dashboard tables
    async def add_eval_case(self, case: EvalCaseRecord) -> EvalCaseRecord:
        self._eval_cases[case.eval_case_id] = case.model_copy(deep=True)
        return case

    async def list_eval_cases(self) -> list[EvalCaseRecord]:
        rows = sorted(self._eval_cases.values(), key=lambda c: c.eval_case_id)
        return [r.model_copy(deep=True) for r in rows]

    async def add_eval_run(self, run: EvalRunRecord) -> EvalRunRecord:
        self._eval_runs[run.eval_run_id] = run.model_copy(deep=True)
        return run

    async def update_eval_run(self, run: EvalRunRecord) -> EvalRunRecord:
        return await self.add_eval_run(run)

    async def list_eval_runs(self, *, workspace_id: Optional[str] = None) -> list[EvalRunRecord]:
        rows = []
        for r in self._eval_runs.values():
            if workspace_id is not None and r.workspace_id != workspace_id:
                continue
            rows.append(r)
        rows.sort(key=lambda r: r.created_at)
        return [r.model_copy(deep=True) for r in rows]

    async def add_eval_result(self, result: EvalResultRecord) -> EvalResultRecord:
        self._eval_results[result.eval_result_id] = result.model_copy(deep=True)
        return result

    async def update_eval_result(self, result: EvalResultRecord) -> EvalResultRecord:
        return await self.add_eval_result(result)

    async def list_eval_results(self, *, eval_run_id: Optional[str] = None) -> list[EvalResultRecord]:
        rows = []
        for r in self._eval_results.values():
            if eval_run_id is not None and r.eval_run_id != eval_run_id:
                continue
            rows.append(r)
        rows.sort(key=lambda r: (r.eval_run_id, r.eval_case_id, r.created_at))
        return [r.model_copy(deep=True) for r in rows]

    # governance
    async def add_api_key(self, key: ApiKeyRecord) -> ApiKeyRecord:
        for existing in self._api_keys.values():
            if existing.key_prefix == key.key_prefix and existing.api_key_id != key.api_key_id:
                raise ValueError("api key key_prefix already exists")
        self._api_keys[key.api_key_id] = key.model_copy(deep=True)
        return key

    async def list_api_keys(
        self,
        *,
        workspace_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ApiKeyRecord]:
        _validate_pagination(limit=limit, offset=offset)
        rows = []
        for key in self._api_keys.values():
            if workspace_id is not None and key.workspace_id != workspace_id:
                continue
            rows.append(key)
        rows.sort(key=lambda key: (key.created_at, key.api_key_id))
        return [row.model_copy(deep=True) for row in rows[offset : offset + limit]]

    async def get_api_key_by_prefix(self, key_prefix: str) -> Optional[ApiKeyRecord]:
        for key in self._api_keys.values():
            if key.key_prefix == key_prefix:
                return key.model_copy(deep=True)
        return None

    async def get_api_key(self, api_key_id: str) -> Optional[ApiKeyRecord]:
        key = self._api_keys.get(api_key_id)
        return key.model_copy(deep=True) if key else None

    async def revoke_api_key(self, api_key_id: str, *, revoked_at: datetime) -> Optional[ApiKeyRecord]:
        current = self._api_keys.get(api_key_id)
        if current is None:
            return None
        if current.revoked_at is not None:
            return current.model_copy(deep=True)
        updated = current.model_copy(update={"revoked_at": revoked_at}, deep=True)
        self._api_keys[api_key_id] = updated
        return updated.model_copy(deep=True)

    async def mark_api_key_used(self, api_key_id: str, *, used_at: datetime) -> None:
        current = self._api_keys.get(api_key_id)
        if current is None:
            return
        self._api_keys[api_key_id] = current.model_copy(update={"last_used_at": used_at}, deep=True)

    async def workspace_for_run(self, run_id: str) -> Optional[str]:
        run = self._runs.get(run_id)
        return run.workspace_id if run else None

    async def workspace_for_step(self, step_id: str) -> Optional[str]:
        step = self._steps.get(step_id)
        return step.workspace_id if step else None

    async def workspace_for_access(self, access_id: str) -> Optional[str]:
        access = self._access_logs.get(access_id)
        return access.workspace_id if access else None

    async def workspace_for_memory(self, memory_id: str) -> Optional[str]:
        memory = self._memories.get(memory_id)
        return memory.workspace_id if memory else None

    async def workspace_for_eval_run(self, eval_run_id: str) -> Optional[str]:
        eval_run = self._eval_runs.get(eval_run_id)
        return eval_run.workspace_id if eval_run else None


__all__ = ["Repository", "InMemoryRepository"]
