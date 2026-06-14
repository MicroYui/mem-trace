"""SQL repository implementing the Repository protocol over PostgreSQL.

Opens one transaction per method via the session factory. Sequence numbers are
made monotonic and concurrency-safe with a per-run transactional advisory lock.
"""
from __future__ import annotations

from typing import Optional
from datetime import datetime

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.runtime.repository import ensure_embedding, _preserved_lifecycle_fields
from app.runtime.models import (
    ApiKeyRecord,
    AgentEvent,
    AgentRun,
    AgentStep,
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
    MemoryVersionRecord,
    MemoryConflictRecord,
    ProfileEvent,
    RetainedNegativeEvidence,
    RiskFlags,
    StateNode,
)
from app.memory.versioning import redacted_memory_snapshot, should_create_memory_version
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
        lifecycle_metadata=m.lifecycle_metadata,
        superseded_by=m.superseded_by,
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
        lifecycle_metadata=getattr(o, "lifecycle_metadata", None) or {},
        superseded_by=o.superseded_by,
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
        token_budget=a.token_budget, top_k=a.top_k, actual_tokens=a.actual_tokens,
        latency_ms=a.latency_ms, policy_version=a.policy_version,
        policy_hash=a.policy_hash, policy_snapshot=a.policy_snapshot,
        created_at=a.created_at,
    )


def _access_from_orm(o: orm.AccessLogORM) -> MemoryAccessLog:
    return MemoryAccessLog(
        access_id=o.access_id, workspace_id=o.workspace_id, run_id=o.run_id,
        step_id=o.step_id, query=o.query, task_intent=o.task_intent,
        retrieval_strategy=o.retrieval_strategy, candidate_count=o.candidate_count,
        accepted_count=o.accepted_count, rejected_count=o.rejected_count,
        token_budget=o.token_budget, top_k=o.top_k, actual_tokens=o.actual_tokens,
        latency_ms=o.latency_ms, policy_version=o.policy_version,
        policy_hash=o.policy_hash, policy_snapshot=o.policy_snapshot or {},
        created_at=o.created_at,
    )


def _lifecycle_audit_to_orm(a: MemoryLifecycleAuditRecord) -> orm.MemoryLifecycleAuditORM:
    return orm.MemoryLifecycleAuditORM(
        audit_id=a.audit_id,
        workspace_id=a.workspace_id,
        memory_id=a.memory_id,
        from_status=a.from_status.value,
        to_status=a.to_status.value,
        reason=a.reason,
        actor=a.actor,
        scheduler_run_id=a.scheduler_run_id,
        audit_metadata=a.metadata,
        created_at=a.created_at,
    )


def _lifecycle_audit_from_orm(o: orm.MemoryLifecycleAuditORM) -> MemoryLifecycleAuditRecord:
    return MemoryLifecycleAuditRecord(
        audit_id=o.audit_id,
        workspace_id=o.workspace_id,
        memory_id=o.memory_id,
        from_status=o.from_status,
        to_status=o.to_status,
        reason=o.reason,
        actor=o.actor,
        scheduler_run_id=o.scheduler_run_id,
        metadata=o.audit_metadata or {},
        created_at=o.created_at,
    )


def _retention_signal_to_orm(signal: MemoryRetentionSignal) -> orm.MemoryRetentionSignalORM:
    return orm.MemoryRetentionSignalORM(
        memory_id=signal.memory_id,
        workspace_id=signal.workspace_id,
        retention_score=signal.retention_score,
        reflection_priority=signal.reflection_priority,
        reason=signal.reason,
        policy_version=signal.policy_version,
        scored_at=signal.scored_at,
        updated_at=signal.updated_at,
    )


def _retention_signal_from_orm(o: orm.MemoryRetentionSignalORM) -> MemoryRetentionSignal:
    return MemoryRetentionSignal(
        memory_id=o.memory_id,
        workspace_id=o.workspace_id,
        retention_score=o.retention_score,
        reflection_priority=o.reflection_priority,
        reason=o.reason or {},
        policy_version=o.policy_version,
        scored_at=o.scored_at,
        updated_at=o.updated_at,
    )


def _memory_version_to_orm(version: MemoryVersionRecord) -> orm.MemoryVersionORM:
    return orm.MemoryVersionORM(
        version_id=version.version_id,
        memory_id=version.memory_id,
        workspace_id=version.workspace_id,
        version_no=version.version_no,
        snapshot=version.snapshot,
        change_reason=version.change_reason,
        created_at=version.created_at,
    )


def _memory_version_from_orm(o: orm.MemoryVersionORM) -> MemoryVersionRecord:
    return MemoryVersionRecord(
        version_id=o.version_id,
        memory_id=o.memory_id,
        workspace_id=o.workspace_id,
        version_no=o.version_no,
        snapshot=o.snapshot or {},
        change_reason=o.change_reason,
        created_at=o.created_at,
    )


def _memory_conflict_to_orm(conflict: MemoryConflictRecord) -> orm.MemoryConflictORM:
    return orm.MemoryConflictORM(
        conflict_id=conflict.conflict_id,
        workspace_id=conflict.workspace_id,
        subject_key=conflict.subject_key,
        memory_ids=list(conflict.memory_ids),
        status=conflict.status,
        detected_by=conflict.detected_by,
        explanation=conflict.explanation,
        created_at=conflict.created_at,
        resolved_at=conflict.resolved_at,
    )


def _memory_conflict_from_orm(o: orm.MemoryConflictORM) -> MemoryConflictRecord:
    return MemoryConflictRecord(
        conflict_id=o.conflict_id,
        workspace_id=o.workspace_id,
        subject_key=o.subject_key,
        memory_ids=list(o.memory_ids or []),
        status=o.status,
        detected_by=o.detected_by,
        explanation=o.explanation or "",
        created_at=o.created_at,
        resolved_at=o.resolved_at,
    )


def _api_key_to_orm(key: ApiKeyRecord) -> orm.ApiKeyORM:
    return orm.ApiKeyORM(
        api_key_id=key.api_key_id,
        workspace_id=key.workspace_id,
        principal_id=key.principal_id,
        key_prefix=key.key_prefix,
        key_digest=key.key_digest,
        roles=list(key.roles),
        created_at=key.created_at,
        last_used_at=key.last_used_at,
        revoked_at=key.revoked_at,
    )


def _api_key_from_orm(o: orm.ApiKeyORM) -> ApiKeyRecord:
    return ApiKeyRecord(
        api_key_id=o.api_key_id,
        workspace_id=o.workspace_id,
        principal_id=o.principal_id,
        key_prefix=o.key_prefix,
        key_digest=o.key_digest,
        roles=list(o.roles or []),
        created_at=o.created_at,
        last_used_at=o.last_used_at,
        revoked_at=o.revoked_at,
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


def _compaction_to_orm(c: ContextCompactionLog) -> orm.ContextCompactionORM:
    return orm.ContextCompactionORM(
        compaction_id=c.compaction_id,
        access_id=c.access_id,
        run_id=c.run_id,
        step_id=c.step_id,
        workspace_id=c.workspace_id,
        kind=c.kind.value,
        provider=c.provider.value,
        pre_tokens=c.pre_tokens,
        post_tokens=c.post_tokens,
        dropped_block_count=c.dropped_block_count,
        compression_ratio=c.compression_ratio,
        summary_text=c.summary_text,
        retained_facts=[fact.model_dump(mode="json") for fact in c.retained_facts],
        retained_negative_evidence=[item.model_dump(mode="json") for item in c.retained_negative_evidence],
        source_memory_ids=list(c.source_memory_ids),
        source_event_ids=list(c.source_event_ids),
        source_state_node_ids=list(c.source_state_node_ids),
        warnings=list(c.warnings),
        created_at=c.created_at,
    )


def _compaction_from_orm(o: orm.ContextCompactionORM) -> ContextCompactionLog:
    return ContextCompactionLog(
        compaction_id=o.compaction_id,
        access_id=o.access_id,
        run_id=o.run_id,
        step_id=o.step_id,
        workspace_id=o.workspace_id,
        kind=o.kind,
        provider=o.provider,
        pre_tokens=o.pre_tokens,
        post_tokens=o.post_tokens,
        dropped_block_count=o.dropped_block_count,
        compression_ratio=o.compression_ratio,
        summary_text=o.summary_text,
        retained_facts=o.retained_facts or [],
        retained_negative_evidence=[
            RetainedNegativeEvidence.model_validate(item)
            for item in (getattr(o, "retained_negative_evidence", None) or [])
        ],
        source_memory_ids=o.source_memory_ids or [],
        source_event_ids=o.source_event_ids or [],
        source_state_node_ids=o.source_state_node_ids or [],
        warnings=o.warnings or [],
        created_at=o.created_at,
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


def _eval_case_to_orm(c: EvalCaseRecord) -> orm.EvalCaseORM:
    return orm.EvalCaseORM(
        eval_case_id=c.eval_case_id,
        name=c.name,
        description=c.description,
        tags=list(c.tags),
        config=c.config,
        created_at=c.created_at,
    )


def _eval_case_from_orm(o: orm.EvalCaseORM) -> EvalCaseRecord:
    return EvalCaseRecord(
        eval_case_id=o.eval_case_id,
        name=o.name,
        description=o.description,
        tags=o.tags or [],
        config=o.config or {},
        created_at=o.created_at,
    )


def _eval_run_to_orm(r: EvalRunRecord) -> orm.EvalRunORM:
    return orm.EvalRunORM(
        eval_run_id=r.eval_run_id,
        name=r.name,
        workspace_id=r.workspace_id,
        status=r.status,
        config=r.config,
        started_at=r.started_at,
        finished_at=r.finished_at,
        created_at=r.created_at,
    )


def _eval_run_from_orm(o: orm.EvalRunORM) -> EvalRunRecord:
    return EvalRunRecord(
        eval_run_id=o.eval_run_id,
        name=o.name,
        workspace_id=o.workspace_id,
        status=o.status,
        config=o.config or {},
        started_at=o.started_at,
        finished_at=o.finished_at,
        created_at=o.created_at,
    )


def _eval_result_to_orm(r: EvalResultRecord) -> orm.EvalResultORM:
    strategy = r.strategy.value if hasattr(r.strategy, "value") else r.strategy
    return orm.EvalResultORM(
        eval_result_id=r.eval_result_id,
        eval_run_id=r.eval_run_id,
        eval_case_id=r.eval_case_id,
        run_id=r.run_id,
        access_id=r.access_id,
        strategy=strategy,
        metrics=r.metrics,
        passed=r.passed,
        created_at=r.created_at,
    )


def _eval_result_from_orm(o: orm.EvalResultORM) -> EvalResultRecord:
    return EvalResultRecord(
        eval_result_id=o.eval_result_id,
        eval_run_id=o.eval_run_id,
        eval_case_id=o.eval_case_id,
        run_id=o.run_id,
        access_id=o.access_id,
        strategy=o.strategy,
        metrics=o.metrics or {},
        passed=o.passed,
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

    async def append_event(self, event: AgentEvent) -> AgentEvent:
        last_error: IntegrityError | None = None
        for _attempt in range(3):
            try:
                async with self._sf() as s:
                    async with s.begin():
                        await s.execute(
                            text("SELECT pg_advisory_xact_lock(hashtext('memtrace_event_seq'), hashtext(:run_id))"),
                            {"run_id": event.run_id},
                        )
                        cur = (
                            await s.execute(
                                select(func.coalesce(func.max(orm.EventORM.sequence_no), 0)).where(
                                    orm.EventORM.run_id == event.run_id
                                )
                            )
                        ).scalar_one()
                        stored = event.model_copy(update={"sequence_no": int(cur) + 1})
                        s.add(_event_to_orm(stored))
                    return stored
            except IntegrityError as exc:
                last_error = exc
        assert last_error is not None
        raise last_error

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
        ensure_embedding(memory)
        async with self._sf() as s:
            await s.merge(_mem_to_orm(memory))
            await s.commit()
        return memory

    async def get_memory(self, memory_id: str) -> Optional[MemoryItem]:
        async with self._sf() as s:
            o = await s.get(orm.MemoryORM, memory_id)
            return _mem_from_orm(o) if o else None

    async def update_memory(self, memory: MemoryItem) -> MemoryItem:
        ensure_embedding(memory)
        after = memory
        async with self._sf() as s:
            async with s.begin():
                current = await s.get(orm.MemoryORM, memory.memory_id, with_for_update=True)
                if current is not None:
                    before = _mem_from_orm(current)
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
                    if should_create_memory_version(before, after):
                        max_version = await s.scalar(
                            select(func.max(orm.MemoryVersionORM.version_no)).where(
                                orm.MemoryVersionORM.memory_id == memory.memory_id
                            )
                        )
                        version = MemoryVersionRecord(
                            memory_id=after.memory_id,
                            workspace_id=after.workspace_id,
                            version_no=int(max_version or 0) + 1,
                            snapshot=redacted_memory_snapshot(after),
                            change_reason="update_memory",
                        )
                        await s.merge(_memory_version_to_orm(version))
                await s.merge(_mem_to_orm(after))
        return after

    async def bump_memory_access(self, memory_id: str, *, accessed_at: datetime) -> None:
        async with self._sf() as s:
            await s.execute(
                orm.MemoryORM.__table__.update()
                .where(orm.MemoryORM.memory_id == memory_id)
                .values(
                    access_count=orm.MemoryORM.access_count + 1,
                    last_accessed_at=accessed_at,
                    updated_at=accessed_at,
                )
            )
            await s.commit()

    async def transition_memory_with_audit(
        self,
        memory: MemoryItem,
        audit: MemoryLifecycleAuditRecord,
    ) -> tuple[MemoryItem, MemoryLifecycleAuditRecord]:
        async with self._sf() as s:
            async with s.begin():
                current = await s.get(orm.MemoryORM, memory.memory_id, with_for_update=True)
                if current is None:
                    raise ValueError(f"memory not found for lifecycle transition: {memory.memory_id}")
                if current.status != audit.from_status.value:
                    raise ValueError(
                        f"stale lifecycle transition for {memory.memory_id}: "
                        f"expected {audit.from_status.value}, found {current.status}"
                    )
                before = _mem_from_orm(current)
                after = before.model_copy(
                    update={
                        "status": memory.status,
                        "lifecycle_metadata": dict(memory.lifecycle_metadata or {}),
                        "updated_at": memory.updated_at,
                    },
                    deep=True,
                )
                if should_create_memory_version(before, after):
                    max_version = await s.scalar(
                        select(func.max(orm.MemoryVersionORM.version_no)).where(
                            orm.MemoryVersionORM.memory_id == memory.memory_id
                        )
                    )
                    version = MemoryVersionRecord(
                        memory_id=memory.memory_id,
                        workspace_id=memory.workspace_id,
                        version_no=int(max_version or 0) + 1,
                        snapshot=redacted_memory_snapshot(after),
                        change_reason=f"lifecycle:{audit.reason}",
                    )
                    await s.merge(_memory_version_to_orm(version))
                current.status = memory.status.value
                current.lifecycle_metadata = dict(memory.lifecycle_metadata or {})
                current.updated_at = memory.updated_at
                await s.merge(_lifecycle_audit_to_orm(audit))
        return memory, audit

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

    async def search_memories_by_vector(
        self,
        *,
        embedding: list[float],
        workspace_id: Optional[str] = None,
        top_k: int = 10,
    ) -> list[tuple[MemoryItem, float]]:
        # pgvector cosine distance (<=>) is in [0, 2]; convert to a [0, 1]
        # similarity (1 - distance, clamped) so it matches the in-memory path.
        distance = orm.MemoryORM.embedding_vector.cosine_distance(embedding)
        async with self._sf() as s:
            stmt = select(orm.MemoryORM, distance.label("distance")).where(
                orm.MemoryORM.embedding_vector.isnot(None)
            )
            if workspace_id is not None:
                stmt = stmt.where(orm.MemoryORM.workspace_id == workspace_id)
            stmt = stmt.order_by(distance).limit(top_k)
            rows = (await s.execute(stmt)).all()
            out: list[tuple[MemoryItem, float]] = []
            for o, dist in rows:
                sim = round(max(0.0, 1.0 - float(dist)), 6)
                out.append((_mem_from_orm(o), sim))
            return out

    async def add_lifecycle_audit(self, audit: MemoryLifecycleAuditRecord) -> MemoryLifecycleAuditRecord:
        async with self._sf() as s:
            await s.merge(_lifecycle_audit_to_orm(audit))
            await s.commit()
        return audit

    async def list_lifecycle_audits(
        self,
        *,
        workspace_id: Optional[str] = None,
        memory_id: Optional[str] = None,
    ) -> list[MemoryLifecycleAuditRecord]:
        async with self._sf() as s:
            stmt = select(orm.MemoryLifecycleAuditORM)
            if workspace_id is not None:
                stmt = stmt.where(orm.MemoryLifecycleAuditORM.workspace_id == workspace_id)
            if memory_id is not None:
                stmt = stmt.where(orm.MemoryLifecycleAuditORM.memory_id == memory_id)
            stmt = stmt.order_by(orm.MemoryLifecycleAuditORM.created_at, orm.MemoryLifecycleAuditORM.audit_id)
            rows = (await s.execute(stmt)).scalars().all()
            return [_lifecycle_audit_from_orm(o) for o in rows]

    async def upsert_retention_signal(self, signal: MemoryRetentionSignal) -> MemoryRetentionSignal:
        async with self._sf() as s:
            await s.merge(_retention_signal_to_orm(signal))
            await s.commit()
        return signal

    async def get_retention_signal(self, memory_id: str) -> Optional[MemoryRetentionSignal]:
        async with self._sf() as s:
            o = await s.get(orm.MemoryRetentionSignalORM, memory_id)
            return _retention_signal_from_orm(o) if o else None

    async def list_retention_signals(
        self,
        workspace_id: str,
        memory_ids: Optional[list[str]] = None,
    ) -> list[MemoryRetentionSignal]:
        async with self._sf() as s:
            stmt = select(orm.MemoryRetentionSignalORM).where(orm.MemoryRetentionSignalORM.workspace_id == workspace_id)
            if memory_ids is not None:
                if not memory_ids:
                    return []
                stmt = stmt.where(orm.MemoryRetentionSignalORM.memory_id.in_(memory_ids))
            stmt = stmt.order_by(orm.MemoryRetentionSignalORM.memory_id)
            rows = (await s.execute(stmt)).scalars().all()
            return [_retention_signal_from_orm(o) for o in rows]

    async def add_memory_version(self, version: MemoryVersionRecord) -> MemoryVersionRecord:
        async with self._sf() as s:
            await s.merge(_memory_version_to_orm(version))
            await s.commit()
        return version

    async def list_memory_versions(self, memory_id: str) -> list[MemoryVersionRecord]:
        async with self._sf() as s:
            rows = (
                await s.execute(
                    select(orm.MemoryVersionORM)
                    .where(orm.MemoryVersionORM.memory_id == memory_id)
                    .order_by(
                        orm.MemoryVersionORM.version_no,
                        orm.MemoryVersionORM.created_at,
                        orm.MemoryVersionORM.version_id,
                    )
                )
            ).scalars().all()
            return [_memory_version_from_orm(o) for o in rows]

    async def upsert_memory_conflict(self, conflict: MemoryConflictRecord) -> MemoryConflictRecord:
        async with self._sf() as s:
            await s.merge(_memory_conflict_to_orm(conflict))
            await s.commit()
        return conflict

    async def list_memory_conflicts(
        self,
        *,
        workspace_id: Optional[str] = None,
        memory_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> list[MemoryConflictRecord]:
        async with self._sf() as s:
            stmt = select(orm.MemoryConflictORM)
            if workspace_id is not None:
                stmt = stmt.where(orm.MemoryConflictORM.workspace_id == workspace_id)
            if status is not None:
                stmt = stmt.where(orm.MemoryConflictORM.status == status)
            if memory_id is not None:
                stmt = stmt.where(orm.MemoryConflictORM.memory_ids.contains([memory_id]))
            stmt = stmt.order_by(orm.MemoryConflictORM.created_at, orm.MemoryConflictORM.conflict_id)
            rows = (await s.execute(stmt)).scalars().all()
            return [_memory_conflict_from_orm(o) for o in rows]

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
                .order_by(orm.GateLogORM.created_at, orm.GateLogORM.gate_id)
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

    async def add_compaction_log(self, log: ContextCompactionLog) -> ContextCompactionLog:
        async with self._sf() as s:
            await s.merge(_compaction_to_orm(log))
            await s.commit()
        return log

    async def list_compaction_logs(
        self,
        *,
        access_id: Optional[str] = None,
        run_id: Optional[str] = None,
        workspace_id: Optional[str] = None,
    ) -> list[ContextCompactionLog]:
        async with self._sf() as s:
            stmt = select(orm.ContextCompactionORM)
            if access_id is not None:
                stmt = stmt.where(orm.ContextCompactionORM.access_id == access_id)
            if run_id is not None:
                stmt = stmt.where(orm.ContextCompactionORM.run_id == run_id)
            if workspace_id is not None:
                stmt = stmt.where(orm.ContextCompactionORM.workspace_id == workspace_id)
            stmt = stmt.order_by(orm.ContextCompactionORM.created_at, orm.ContextCompactionORM.compaction_id)
            rows = (await s.execute(stmt)).scalars().all()
            return [_compaction_from_orm(o) for o in rows]

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

    # eval / dashboard tables
    async def add_eval_case(self, case: EvalCaseRecord) -> EvalCaseRecord:
        async with self._sf() as s:
            await s.merge(_eval_case_to_orm(case))
            await s.commit()
        return case

    async def list_eval_cases(self) -> list[EvalCaseRecord]:
        async with self._sf() as s:
            rows = (await s.execute(
                select(orm.EvalCaseORM).order_by(orm.EvalCaseORM.eval_case_id)
            )).scalars().all()
            return [_eval_case_from_orm(o) for o in rows]

    async def add_eval_run(self, run: EvalRunRecord) -> EvalRunRecord:
        async with self._sf() as s:
            await s.merge(_eval_run_to_orm(run))
            await s.commit()
        return run

    async def update_eval_run(self, run: EvalRunRecord) -> EvalRunRecord:
        return await self.add_eval_run(run)

    async def list_eval_runs(self, *, workspace_id: Optional[str] = None) -> list[EvalRunRecord]:
        async with self._sf() as s:
            stmt = select(orm.EvalRunORM)
            if workspace_id is not None:
                stmt = stmt.where(orm.EvalRunORM.workspace_id == workspace_id)
            stmt = stmt.order_by(orm.EvalRunORM.created_at)
            rows = (await s.execute(stmt)).scalars().all()
            return [_eval_run_from_orm(o) for o in rows]

    async def add_eval_result(self, result: EvalResultRecord) -> EvalResultRecord:
        async with self._sf() as s:
            await s.merge(_eval_result_to_orm(result))
            await s.commit()
        return result

    async def update_eval_result(self, result: EvalResultRecord) -> EvalResultRecord:
        return await self.add_eval_result(result)

    async def list_eval_results(self, *, eval_run_id: Optional[str] = None) -> list[EvalResultRecord]:
        async with self._sf() as s:
            stmt = select(orm.EvalResultORM)
            if eval_run_id is not None:
                stmt = stmt.where(orm.EvalResultORM.eval_run_id == eval_run_id)
            stmt = stmt.order_by(
                orm.EvalResultORM.eval_run_id,
                orm.EvalResultORM.eval_case_id,
                orm.EvalResultORM.created_at,
            )
            rows = (await s.execute(stmt)).scalars().all()
            return [_eval_result_from_orm(o) for o in rows]

    # governance
    async def add_api_key(self, key: ApiKeyRecord) -> ApiKeyRecord:
        async with self._sf() as s:
            await s.merge(_api_key_to_orm(key))
            await s.commit()
        return key

    async def list_api_keys(self) -> list[ApiKeyRecord]:
        async with self._sf() as s:
            rows = (await s.execute(select(orm.ApiKeyORM).order_by(orm.ApiKeyORM.created_at))).scalars().all()
            return [_api_key_from_orm(row) for row in rows]

    async def get_api_key_by_prefix(self, key_prefix: str) -> Optional[ApiKeyRecord]:
        async with self._sf() as s:
            row = (
                await s.execute(select(orm.ApiKeyORM).where(orm.ApiKeyORM.key_prefix == key_prefix).limit(1))
            ).scalar_one_or_none()
            return _api_key_from_orm(row) if row else None

    async def mark_api_key_used(self, api_key_id: str, *, used_at: datetime) -> None:
        async with self._sf() as s:
            await s.execute(
                orm.ApiKeyORM.__table__.update()
                .where(orm.ApiKeyORM.api_key_id == api_key_id)
                .values(last_used_at=used_at)
            )
            await s.commit()

    async def workspace_for_run(self, run_id: str) -> Optional[str]:
        async with self._sf() as s:
            return await s.scalar(select(orm.RunORM.workspace_id).where(orm.RunORM.run_id == run_id))

    async def workspace_for_step(self, step_id: str) -> Optional[str]:
        async with self._sf() as s:
            return await s.scalar(select(orm.StepORM.workspace_id).where(orm.StepORM.step_id == step_id))

    async def workspace_for_access(self, access_id: str) -> Optional[str]:
        async with self._sf() as s:
            return await s.scalar(select(orm.AccessLogORM.workspace_id).where(orm.AccessLogORM.access_id == access_id))

    async def workspace_for_memory(self, memory_id: str) -> Optional[str]:
        async with self._sf() as s:
            return await s.scalar(select(orm.MemoryORM.workspace_id).where(orm.MemoryORM.memory_id == memory_id))

    async def workspace_for_eval_run(self, eval_run_id: str) -> Optional[str]:
        async with self._sf() as s:
            return await s.scalar(select(orm.EvalRunORM.workspace_id).where(orm.EvalRunORM.eval_run_id == eval_run_id))


__all__ = ["SqlRepository"]
