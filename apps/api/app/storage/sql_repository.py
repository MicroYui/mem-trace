"""SQL repository implementing the Repository protocol over PostgreSQL.

Opens one transaction per method via the session factory. Sequence numbers are
made monotonic and concurrency-safe with a per-run transactional advisory lock.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.runtime.models import (
    AgentEvent,
    AgentRun,
    AgentStep,
    MemoryAccessLog,
    BenchmarkCaseRecord,
    BenchmarkResultRecord,
    MemoryGateLog,
    MemoryItem,
    ProfileEvent,
    RiskFlags,
    StateNode,
)
from app.storage import orm


# --------------------------------------------------------------------------- #
# ORM <-> domain conversion
# --------------------------------------------------------------------------- #
def _run_to_orm(r: AgentRun) -> orm.RunORM:
    return orm.RunORM(
        run_id=r.run_id, workspace_id=r.workspace_id, session_id=r.session_id,
        task=r.task, status=r.status.value, started_at=r.started_at,
        finished_at=r.finished_at, run_metadata=r.metadata,
        created_at=r.created_at, updated_at=r.updated_at,
    )


def _run_from_orm(o: orm.RunORM) -> AgentRun:
    return AgentRun(
        run_id=o.run_id, workspace_id=o.workspace_id, session_id=o.session_id,
        task=o.task, status=o.status, started_at=o.started_at,
        finished_at=o.finished_at, metadata=o.run_metadata or {},
        created_at=o.created_at, updated_at=o.updated_at,
    )


def _step_to_orm(s: AgentStep) -> orm.StepORM:
    return orm.StepORM(
        step_id=s.step_id, workspace_id=s.workspace_id, run_id=s.run_id,
        parent_step_id=s.parent_step_id, recovery_from_step_id=s.recovery_from_step_id,
        state_node_id=s.state_node_id, intent=s.intent, status=s.status.value,
        started_at=s.started_at, finished_at=s.finished_at, error_message=s.error_message,
        step_metadata=s.metadata, created_at=s.created_at, updated_at=s.updated_at,
    )


def _step_from_orm(o: orm.StepORM) -> AgentStep:
    return AgentStep(
        step_id=o.step_id, workspace_id=o.workspace_id, run_id=o.run_id,
        parent_step_id=o.parent_step_id, recovery_from_step_id=o.recovery_from_step_id,
        state_node_id=o.state_node_id, intent=o.intent, status=o.status,
        started_at=o.started_at, finished_at=o.finished_at, error_message=o.error_message,
        metadata=o.step_metadata or {}, created_at=o.created_at, updated_at=o.updated_at,
    )


def _event_to_orm(e: AgentEvent) -> orm.EventORM:
    return orm.EventORM(
        event_id=e.event_id, workspace_id=e.workspace_id, session_id=e.session_id,
        run_id=e.run_id, step_id=e.step_id, state_node_id=e.state_node_id,
        sequence_no=e.sequence_no, event_source=e.event_source, visibility=e.visibility,
        role=e.role.value, event_type=e.event_type.value, content=e.content,
        content_digest=e.content_digest, raw_payload_ref=e.raw_payload_ref,
        redaction_status=e.redaction_status, causality_id=e.causality_id,
        tool_name=e.tool_name, tool_args_digest=e.tool_args_digest, status=e.status,
        token_input=e.token_input, token_output=e.token_output, latency_ms=e.latency_ms,
        event_metadata=e.metadata, created_at=e.created_at,
    )


def _event_from_orm(o: orm.EventORM) -> AgentEvent:
    return AgentEvent(
        event_id=o.event_id, workspace_id=o.workspace_id, session_id=o.session_id,
        run_id=o.run_id, step_id=o.step_id, state_node_id=o.state_node_id,
        sequence_no=o.sequence_no, event_source=o.event_source, visibility=o.visibility,
        role=o.role, event_type=o.event_type, content=o.content,
        content_digest=o.content_digest, raw_payload_ref=o.raw_payload_ref,
        redaction_status=o.redaction_status, causality_id=o.causality_id,
        tool_name=o.tool_name, tool_args_digest=o.tool_args_digest, status=o.status,
        token_input=o.token_input, token_output=o.token_output, latency_ms=o.latency_ms,
        metadata=o.event_metadata or {}, created_at=o.created_at,
    )


def _node_to_orm(n: StateNode) -> orm.StateNodeORM:
    return orm.StateNodeORM(
        node_id=n.node_id, workspace_id=n.workspace_id, run_id=n.run_id,
        parent_id=n.parent_id, step_id=n.step_id, node_type=n.node_type.value,
        status=n.status.value, goal=n.goal, summary=n.summary,
        raw_event_ids=list(n.raw_event_ids), memory_refs=list(n.memory_refs),
        branch_reason=n.branch_reason, failure_reason=n.failure_reason,
        depth=n.depth, path=n.path, created_at=n.created_at, updated_at=n.updated_at,
    )


def _node_from_orm(o: orm.StateNodeORM) -> StateNode:
    return StateNode(
        node_id=o.node_id, workspace_id=o.workspace_id, run_id=o.run_id,
        parent_id=o.parent_id, step_id=o.step_id, node_type=o.node_type,
        status=o.status, goal=o.goal, summary=o.summary,
        raw_event_ids=o.raw_event_ids or [], memory_refs=o.memory_refs or [],
        branch_reason=o.branch_reason or {}, failure_reason=o.failure_reason,
        depth=o.depth, path=o.path, created_at=o.created_at, updated_at=o.updated_at,
    )


def _mem_to_orm(m: MemoryItem) -> orm.MemoryORM:
    return orm.MemoryORM(
        memory_id=m.memory_id, workspace_id=m.workspace_id, session_id=m.session_id,
        run_id=m.run_id, memory_type=m.memory_type.value, key=m.key, value=m.value,
        scope=m.scope.value, content=m.content, summary=m.summary,
        source_event_id=m.source_event_id, source_event_ids=m.source_event_ids,
        source_run_id=m.source_run_id, source_state_node_id=m.source_state_node_id,
        branch_status=m.branch_status.value, confidence=m.confidence,
        importance=m.importance, value_score=m.value_score,
        freshness_score=m.freshness_score, trust_score=m.trust_score,
        risk_score=m.risk_score, embedding_vector=m.embedding_vector,
        risk_flags=m.risk_flags.model_dump(), status=m.status.value,
        sensitivity=m.sensitivity.value, embedding_status=m.embedding_status.value,
        expires_at=m.expires_at, last_accessed_at=m.last_accessed_at,
        access_count=m.access_count, created_at=m.created_at, updated_at=m.updated_at,
    )


def _mem_from_orm(o: orm.MemoryORM) -> MemoryItem:
    vec = list(o.embedding_vector) if o.embedding_vector is not None else None
    return MemoryItem(
        memory_id=o.memory_id, workspace_id=o.workspace_id, session_id=o.session_id,
        run_id=o.run_id, memory_type=o.memory_type, key=o.key, value=o.value,
        scope=o.scope, content=o.content, summary=o.summary,
        source_event_id=o.source_event_id, source_event_ids=o.source_event_ids,
        source_run_id=o.source_run_id, source_state_node_id=o.source_state_node_id,
        branch_status=o.branch_status, confidence=o.confidence, importance=o.importance,
        value_score=o.value_score, freshness_score=o.freshness_score,
        trust_score=o.trust_score, risk_score=o.risk_score, embedding_vector=vec,
        risk_flags=RiskFlags(**(o.risk_flags or {})), status=o.status,
        sensitivity=o.sensitivity, embedding_status=o.embedding_status,
        expires_at=o.expires_at, last_accessed_at=o.last_accessed_at,
        access_count=o.access_count, created_at=o.created_at, updated_at=o.updated_at,
    )


def _access_to_orm(a: MemoryAccessLog) -> orm.AccessLogORM:
    return orm.AccessLogORM(
        access_id=a.access_id, workspace_id=a.workspace_id, run_id=a.run_id,
        step_id=a.step_id, query=a.query, task_intent=a.task_intent,
        retrieval_strategy=a.retrieval_strategy.value, candidate_count=a.candidate_count,
        accepted_count=a.accepted_count, rejected_count=a.rejected_count,
        token_budget=a.token_budget, actual_tokens=a.actual_tokens,
        latency_ms=a.latency_ms, created_at=a.created_at,
    )


def _access_from_orm(o: orm.AccessLogORM) -> MemoryAccessLog:
    return MemoryAccessLog(
        access_id=o.access_id, workspace_id=o.workspace_id, run_id=o.run_id,
        step_id=o.step_id, query=o.query, task_intent=o.task_intent,
        retrieval_strategy=o.retrieval_strategy, candidate_count=o.candidate_count,
        accepted_count=o.accepted_count, rejected_count=o.rejected_count,
        token_budget=o.token_budget, actual_tokens=o.actual_tokens,
        latency_ms=o.latency_ms, created_at=o.created_at,
    )


def _gate_to_orm(g: MemoryGateLog) -> orm.GateLogORM:
    return orm.GateLogORM(
        gate_id=g.gate_id, access_id=g.access_id, memory_id=g.memory_id,
        layer=g.layer.value, decision=g.decision.value, reject_reason=g.reject_reason,
        relevance_score=g.relevance_score, state_match_score=g.state_match_score,
        freshness_score=g.freshness_score, trust_score=g.trust_score,
        risk_score=g.risk_score, final_score=g.final_score, created_at=g.created_at,
    )


def _gate_from_orm(o: orm.GateLogORM) -> MemoryGateLog:
    return MemoryGateLog(
        gate_id=o.gate_id, access_id=o.access_id, memory_id=o.memory_id,
        layer=o.layer, decision=o.decision, reject_reason=o.reject_reason,
        relevance_score=o.relevance_score, state_match_score=o.state_match_score,
        freshness_score=o.freshness_score, trust_score=o.trust_score,
        risk_score=o.risk_score, final_score=o.final_score, created_at=o.created_at,
    )


def _profile_to_orm(p: ProfileEvent) -> orm.ProfileEventORM:
    return orm.ProfileEventORM(
        profile_id=p.profile_id, run_id=p.run_id, step_id=p.step_id,
        access_id=p.access_id, phase=p.phase.value, operation=p.operation,
        latency_ms=p.latency_ms, input_tokens=p.input_tokens,
        output_tokens=p.output_tokens, llm_calls=p.llm_calls, db_calls=p.db_calls,
        candidate_count=p.candidate_count, accepted_count=p.accepted_count,
        rejected_count=p.rejected_count, error_code=p.error_code,
        profile_metadata=p.metadata, created_at=p.created_at,
    )


def _profile_from_orm(o: orm.ProfileEventORM) -> ProfileEvent:
    return ProfileEvent(
        profile_id=o.profile_id, run_id=o.run_id, step_id=o.step_id,
        access_id=o.access_id, phase=o.phase, operation=o.operation,
        latency_ms=o.latency_ms, input_tokens=o.input_tokens,
        output_tokens=o.output_tokens, llm_calls=o.llm_calls, db_calls=o.db_calls,
        candidate_count=o.candidate_count, accepted_count=o.accepted_count,
        rejected_count=o.rejected_count, error_code=o.error_code,
        metadata=o.profile_metadata or {}, created_at=o.created_at,
    )


def _benchmark_case_to_orm(c: BenchmarkCaseRecord) -> orm.BenchmarkCaseORM:
    return orm.BenchmarkCaseORM(
        case_id=c.case_id,
        name=c.name,
        description=c.description,
        config=c.config,
        created_at=c.created_at,
    )


def _benchmark_case_from_orm(o: orm.BenchmarkCaseORM) -> BenchmarkCaseRecord:
    return BenchmarkCaseRecord(
        case_id=o.case_id,
        name=o.name,
        description=o.description,
        config=o.config or {},
        created_at=o.created_at,
    )


def _benchmark_result_to_orm(r: BenchmarkResultRecord) -> orm.BenchmarkResultORM:
    return orm.BenchmarkResultORM(
        result_id=r.result_id,
        case_id=r.case_id,
        strategy=r.strategy,
        metrics=r.metrics,
        created_at=r.created_at,
    )


def _benchmark_result_from_orm(o: orm.BenchmarkResultORM) -> BenchmarkResultRecord:
    return BenchmarkResultRecord(
        result_id=o.result_id,
        case_id=o.case_id,
        strategy=o.strategy,
        metrics=o.metrics or {},
        created_at=o.created_at,
    )


# --------------------------------------------------------------------------- #
# Repository
# --------------------------------------------------------------------------- #
class SqlRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._sf = session_factory

    async def _merge(self, session: AsyncSession, obj) -> None:
        await session.merge(obj)

    # runs
    async def add_run(self, run: AgentRun) -> AgentRun:
        async with self._sf() as s:
            await s.merge(_run_to_orm(run))
            await s.commit()
        return run

    async def get_run(self, run_id: str) -> Optional[AgentRun]:
        async with self._sf() as s:
            o = await s.get(orm.RunORM, run_id)
            return _run_from_orm(o) if o else None

    async def update_run(self, run: AgentRun) -> AgentRun:
        return await self.add_run(run)

    async def list_runs(self, *, workspace_id: Optional[str] = None) -> list[AgentRun]:
        async with self._sf() as s:
            stmt = select(orm.RunORM)
            if workspace_id is not None:
                stmt = stmt.where(orm.RunORM.workspace_id == workspace_id)
            stmt = stmt.order_by(orm.RunORM.created_at)
            rows = (await s.execute(stmt)).scalars().all()
            return [_run_from_orm(o) for o in rows]

    # steps
    async def add_step(self, step: AgentStep) -> AgentStep:
        async with self._sf() as s:
            await s.merge(_step_to_orm(step))
            await s.commit()
        return step

    async def get_step(self, step_id: str) -> Optional[AgentStep]:
        async with self._sf() as s:
            o = await s.get(orm.StepORM, step_id)
            return _step_from_orm(o) if o else None

    async def update_step(self, step: AgentStep) -> AgentStep:
        return await self.add_step(step)

    async def list_steps(self, run_id: str) -> list[AgentStep]:
        async with self._sf() as s:
            rows = (await s.execute(
                select(orm.StepORM).where(orm.StepORM.run_id == run_id).order_by(orm.StepORM.created_at)
            )).scalars().all()
            return [_step_from_orm(o) for o in rows]

    # events
    async def next_sequence_no(self, run_id: str) -> int:
        async with self._sf() as s:
            # transactional advisory lock keyed by run_id keeps seq monotonic
            await s.execute(text("SELECT pg_advisory_xact_lock(hashtext(:r))"), {"r": run_id})
            cur = (await s.execute(
                select(func.coalesce(func.max(orm.EventORM.sequence_no), 0)).where(orm.EventORM.run_id == run_id)
            )).scalar_one()
            nxt = int(cur) + 1
            await s.commit()
            return nxt

    async def add_event(self, event: AgentEvent) -> AgentEvent:
        async with self._sf() as s:
            await s.merge(_event_to_orm(event))
            await s.commit()
        return event

    async def list_events(self, run_id: str) -> list[AgentEvent]:
        async with self._sf() as s:
            rows = (await s.execute(
                select(orm.EventORM).where(orm.EventORM.run_id == run_id).order_by(orm.EventORM.sequence_no)
            )).scalars().all()
            return [_event_from_orm(o) for o in rows]

    async def get_event(self, event_id: str) -> Optional[AgentEvent]:
        async with self._sf() as s:
            o = await s.get(orm.EventORM, event_id)
            return _event_from_orm(o) if o else None

    # state nodes
    async def add_state_node(self, node: StateNode) -> StateNode:
        async with self._sf() as s:
            await s.merge(_node_to_orm(node))
            await s.commit()
        return node

    async def get_state_node(self, node_id: str) -> Optional[StateNode]:
        async with self._sf() as s:
            o = await s.get(orm.StateNodeORM, node_id)
            return _node_from_orm(o) if o else None

    async def update_state_node(self, node: StateNode) -> StateNode:
        return await self.add_state_node(node)

    async def list_state_nodes(self, run_id: str) -> list[StateNode]:
        async with self._sf() as s:
            rows = (await s.execute(
                select(orm.StateNodeORM).where(orm.StateNodeORM.run_id == run_id)
                .order_by(orm.StateNodeORM.depth, orm.StateNodeORM.created_at)
            )).scalars().all()
            return [_node_from_orm(o) for o in rows]

    # memories
    async def add_memory(self, memory: MemoryItem) -> MemoryItem:
        async with self._sf() as s:
            await s.merge(_mem_to_orm(memory))
            await s.commit()
        return memory

    async def get_memory(self, memory_id: str) -> Optional[MemoryItem]:
        async with self._sf() as s:
            o = await s.get(orm.MemoryORM, memory_id)
            return _mem_from_orm(o) if o else None

    async def update_memory(self, memory: MemoryItem) -> MemoryItem:
        return await self.add_memory(memory)

    async def list_memories(
        self, *, workspace_id: Optional[str] = None, run_id: Optional[str] = None
    ) -> list[MemoryItem]:
        async with self._sf() as s:
            stmt = select(orm.MemoryORM)
            if workspace_id is not None:
                stmt = stmt.where(orm.MemoryORM.workspace_id == workspace_id)
            if run_id is not None:
                stmt = stmt.where(orm.MemoryORM.run_id == run_id)
            stmt = stmt.order_by(orm.MemoryORM.created_at)
            rows = (await s.execute(stmt)).scalars().all()
            return [_mem_from_orm(o) for o in rows]

    # logs / profile
    async def add_access_log(self, log: MemoryAccessLog) -> MemoryAccessLog:
        async with self._sf() as s:
            await s.merge(_access_to_orm(log))
            await s.commit()
        return log

    async def get_access_log(self, access_id: str) -> Optional[MemoryAccessLog]:
        async with self._sf() as s:
            o = await s.get(orm.AccessLogORM, access_id)
            return _access_from_orm(o) if o else None

    async def list_access_logs(self, *, workspace_id: Optional[str] = None) -> list[MemoryAccessLog]:
        async with self._sf() as s:
            stmt = select(orm.AccessLogORM)
            if workspace_id is not None:
                stmt = stmt.where(orm.AccessLogORM.workspace_id == workspace_id)
            stmt = stmt.order_by(orm.AccessLogORM.created_at)
            rows = (await s.execute(stmt)).scalars().all()
            return [_access_from_orm(o) for o in rows]

    async def add_gate_log(self, log: MemoryGateLog) -> MemoryGateLog:
        async with self._sf() as s:
            s.add(_gate_to_orm(log))
            await s.commit()
        return log

    async def list_gate_logs(self, access_id: str) -> list[MemoryGateLog]:
        async with self._sf() as s:
            rows = (await s.execute(
                select(orm.GateLogORM).where(orm.GateLogORM.access_id == access_id)
                .order_by(orm.GateLogORM.created_at)
            )).scalars().all()
            return [_gate_from_orm(o) for o in rows]

    async def add_profile_event(self, event: ProfileEvent) -> ProfileEvent:
        async with self._sf() as s:
            s.add(_profile_to_orm(event))
            await s.commit()
        return event

    async def list_profile_events(
        self, *, run_id: Optional[str] = None, access_id: Optional[str] = None
    ) -> list[ProfileEvent]:
        async with self._sf() as s:
            stmt = select(orm.ProfileEventORM)
            if run_id is not None:
                stmt = stmt.where(orm.ProfileEventORM.run_id == run_id)
            if access_id is not None:
                stmt = stmt.where(orm.ProfileEventORM.access_id == access_id)
            stmt = stmt.order_by(orm.ProfileEventORM.created_at)
            rows = (await s.execute(stmt)).scalars().all()
            return [_profile_from_orm(o) for o in rows]

    # benchmark / dashboard tables
    async def add_benchmark_case(self, case: BenchmarkCaseRecord) -> BenchmarkCaseRecord:
        async with self._sf() as s:
            await s.merge(_benchmark_case_to_orm(case))
            await s.commit()
        return case

    async def add_benchmark_result(self, result: BenchmarkResultRecord) -> BenchmarkResultRecord:
        async with self._sf() as s:
            await s.merge(_benchmark_result_to_orm(result))
            await s.commit()
        return result

    async def list_benchmark_cases(self) -> list[BenchmarkCaseRecord]:
        async with self._sf() as s:
            rows = (await s.execute(
                select(orm.BenchmarkCaseORM).order_by(orm.BenchmarkCaseORM.case_id)
            )).scalars().all()
            return [_benchmark_case_from_orm(o) for o in rows]

    async def list_benchmark_results(self) -> list[BenchmarkResultRecord]:
        async with self._sf() as s:
            rows = (await s.execute(
                select(orm.BenchmarkResultORM).order_by(
                    orm.BenchmarkResultORM.case_id,
                    orm.BenchmarkResultORM.strategy,
                    orm.BenchmarkResultORM.created_at,
                )
            )).scalars().all()
            return [_benchmark_result_from_orm(o) for o in rows]


__all__ = ["SqlRepository"]
