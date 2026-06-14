from __future__ import annotations

import pytest

from app.memory import scheduler
from app.runtime.models import (
    AdminActionAuditRecord,
    AgentEvent,
    AgentRun,
    AgentStep,
    BranchStatus,
    EmbeddingStatus,
    EventRole,
    EventType,
    MaintenanceOperation,
    MemoryConflictRecord,
    MemoryItem,
    MemoryScope,
    MemoryStatus,
    MemoryType,
    MaintenanceRunRecord,
    MaintenanceTaskAttemptRecord,
    QuotaLimitRecord,
    RiskFlags,
    RunStatus,
    SchedulerRunStatus,
    SchedulerTaskStatus,
    StepStatus,
    StateNode,
    StateNodeStatus,
    StateNodeType,
)
from app.runtime.repository import InMemoryRepository


def _project_memory(**overrides) -> MemoryItem:
    data = {
        "workspace_id": "ws_1",
        "memory_type": MemoryType.project,
        "key": "project.runtime",
        "value": "bun",
        "scope": MemoryScope.workspace,
        "content": "project.runtime=bun",
        "summary": "project.runtime=bun",
        "status": MemoryStatus.active,
        "branch_status": BranchStatus.completed,
        "trust_score": 0.6,
        "confidence": 0.6,
    }
    data.update(overrides)
    return MemoryItem(**data)


@pytest.mark.asyncio
async def test_maintenance_run_and_attempt_round_trip() -> None:
    repo = InMemoryRepository()
    run = await repo.add_maintenance_run(
        MaintenanceRunRecord(workspace_id="ws_1", operations=[MaintenanceOperation.score_memory])
    )
    attempt = await repo.add_maintenance_task_attempt(
        MaintenanceTaskAttemptRecord(
            scheduler_run_id=run.scheduler_run_id,
            workspace_id="ws_1",
            operation=MaintenanceOperation.score_memory,
            idempotency_key=f"maintenance:{run.scheduler_run_id}:score_memory",
        )
    )
    attempt.status = SchedulerTaskStatus.completed
    attempt.result = {"scored_count": 2}
    await repo.update_maintenance_task_attempt(attempt)
    run.status = SchedulerRunStatus.completed
    await repo.update_maintenance_run(run)

    stored_run = await repo.get_maintenance_run(run.scheduler_run_id)
    assert stored_run is not None
    assert stored_run.status == SchedulerRunStatus.completed
    attempts = await repo.list_maintenance_task_attempts(scheduler_run_id=run.scheduler_run_id)
    assert attempts[0].result == {"scored_count": 2}


@pytest.mark.asyncio
async def test_maintenance_run_rejects_duplicate_operations() -> None:
    repo = InMemoryRepository()

    with pytest.raises(ValueError, match="duplicate maintenance operation"):
        await repo.add_maintenance_run(
            MaintenanceRunRecord(
                workspace_id="ws_1",
                operations=[MaintenanceOperation.score_memory, MaintenanceOperation.score_memory],
            )
        )


@pytest.mark.asyncio
async def test_update_maintenance_run_preserves_immutable_identity_fields() -> None:
    repo = InMemoryRepository()
    run = await repo.add_maintenance_run(
        MaintenanceRunRecord(
            workspace_id="ws_1",
            requested_by="admin:alice",
            reason="safe preview",
            operations=[MaintenanceOperation.score_memory],
            dry_run=True,
        )
    )

    changed = run.model_copy(
        update={
            "workspace_id": "ws_2",
            "requested_by": "admin:bob",
            "reason": "different",
            "operations": [MaintenanceOperation.decay_memory],
            "dry_run": False,
            "status": SchedulerRunStatus.completed,
            "summary": {"completed_count": 1},
        },
        deep=True,
    )
    object.__setattr__(changed, "created_at", run.updated_at)

    stored = await repo.update_maintenance_run(changed)

    assert stored.status == SchedulerRunStatus.completed
    assert stored.summary == {"completed_count": 1}
    assert stored.workspace_id == "ws_1"
    assert stored.requested_by == "admin:alice"
    assert stored.reason == "safe preview"
    assert stored.operations == [MaintenanceOperation.score_memory]
    assert stored.dry_run is True
    assert stored.created_at == run.created_at


@pytest.mark.asyncio
async def test_task_attempt_is_unique_per_run_operation_but_not_cross_run() -> None:
    repo = InMemoryRepository()
    first_run = await repo.add_maintenance_run(
        MaintenanceRunRecord(workspace_id="ws_1", operations=[MaintenanceOperation.score_memory])
    )
    second_run = await repo.add_maintenance_run(
        MaintenanceRunRecord(workspace_id="ws_1", operations=[MaintenanceOperation.score_memory])
    )
    await repo.add_maintenance_task_attempt(
        MaintenanceTaskAttemptRecord(
            scheduler_run_id=first_run.scheduler_run_id,
            workspace_id="ws_1",
            operation=MaintenanceOperation.score_memory,
        )
    )

    with pytest.raises(ValueError, match="duplicate maintenance task attempt"):
        await repo.add_maintenance_task_attempt(
            MaintenanceTaskAttemptRecord(
                scheduler_run_id=first_run.scheduler_run_id,
                workspace_id="ws_1",
                operation=MaintenanceOperation.score_memory,
            )
        )

    await repo.add_maintenance_task_attempt(
        MaintenanceTaskAttemptRecord(
            scheduler_run_id=second_run.scheduler_run_id,
            workspace_id="ws_1",
            operation=MaintenanceOperation.score_memory,
        )
    )


@pytest.mark.asyncio
async def test_quota_workspace_wide_override_is_unique_when_principal_is_none() -> None:
    repo = InMemoryRepository()
    first = await repo.upsert_quota_limit(
        QuotaLimitRecord(
            workspace_id="ws_1",
            principal_id=None,
            unit="write_event",
            limit=1,
            window_seconds=60,
            created_by="admin",
        )
    )
    second = await repo.upsert_quota_limit(first.model_copy(update={"limit": 2}))

    limits = await repo.list_quota_limits(workspace_id="ws_1", principal_id=None)
    assert len(limits) == 1
    assert limits[0].quota_limit_id == second.quota_limit_id
    assert limits[0].limit == 2


@pytest.mark.asyncio
async def test_quota_upsert_preserves_existing_identifier_for_same_identity() -> None:
    repo = InMemoryRepository()
    first = await repo.upsert_quota_limit(
        QuotaLimitRecord(
            workspace_id="ws_1",
            principal_id="principal_1",
            unit="write_event",
            limit=1,
            window_seconds=60,
            created_by="admin",
        )
    )
    second = await repo.upsert_quota_limit(
        QuotaLimitRecord(
            workspace_id="ws_1",
            principal_id="principal_1",
            unit="write_event",
            limit=5,
            window_seconds=60,
            created_by="admin",
        )
    )

    assert second.quota_limit_id == first.quota_limit_id
    limits = await repo.list_quota_limits(workspace_id="ws_1", principal_id="principal_1")
    assert [limit.quota_limit_id for limit in limits] == [first.quota_limit_id]
    assert limits[0].limit == 5


@pytest.mark.asyncio
async def test_quota_upsert_preserves_immutable_identity_and_creation_audit() -> None:
    repo = InMemoryRepository()
    first = await repo.upsert_quota_limit(
        QuotaLimitRecord(
            workspace_id="ws_1",
            principal_id="principal_1",
            unit="write_event",
            limit=1,
            window_seconds=60,
            created_by="admin_1",
        )
    )

    second = await repo.upsert_quota_limit(
        QuotaLimitRecord(
            workspace_id="ws_1",
            principal_id="principal_1",
            unit="write_event",
            limit=9,
            window_seconds=120,
            created_by="admin_2",
        )
    )

    assert second.quota_limit_id == first.quota_limit_id
    assert second.workspace_id == first.workspace_id
    assert second.principal_id == first.principal_id
    assert second.unit == first.unit
    assert second.created_by == "admin_1"
    assert second.created_at == first.created_at
    assert second.limit == 9
    assert second.window_seconds == 120


@pytest.mark.asyncio
async def test_quota_upsert_rejects_identity_change_for_existing_id() -> None:
    repo = InMemoryRepository()
    first = await repo.upsert_quota_limit(
        QuotaLimitRecord(
            workspace_id="ws_1",
            principal_id="principal_1",
            unit="write_event",
            limit=1,
            window_seconds=60,
            created_by="admin_1",
        )
    )

    with pytest.raises(ValueError, match="quota limit identity cannot change"):
        await repo.upsert_quota_limit(
            first.model_copy(update={"workspace_id": "ws_2", "principal_id": None})
        )


@pytest.mark.asyncio
async def test_update_maintenance_task_attempt_rejects_duplicate_run_operation() -> None:
    repo = InMemoryRepository()
    run = await repo.add_maintenance_run(
        MaintenanceRunRecord(
            workspace_id="ws_1",
            operations=[MaintenanceOperation.score_memory, MaintenanceOperation.decay_memory],
        )
    )
    first = await repo.add_maintenance_task_attempt(
        MaintenanceTaskAttemptRecord(
            scheduler_run_id=run.scheduler_run_id,
            workspace_id="ws_1",
            operation=MaintenanceOperation.score_memory,
        )
    )
    second = await repo.add_maintenance_task_attempt(
        MaintenanceTaskAttemptRecord(
            scheduler_run_id=run.scheduler_run_id,
            workspace_id="ws_1",
            operation=MaintenanceOperation.decay_memory,
        )
    )

    with pytest.raises(ValueError, match="maintenance task attempt identity cannot change"):
        await repo.update_maintenance_task_attempt(
            second.model_copy(update={"operation": first.operation})
        )


@pytest.mark.asyncio
async def test_update_maintenance_task_attempt_rejects_identity_change() -> None:
    repo = InMemoryRepository()
    first_run = await repo.add_maintenance_run(
        MaintenanceRunRecord(workspace_id="ws_1", operations=[MaintenanceOperation.score_memory])
    )
    second_run = await repo.add_maintenance_run(
        MaintenanceRunRecord(workspace_id="ws_2", operations=[MaintenanceOperation.decay_memory])
    )
    attempt = await repo.add_maintenance_task_attempt(
        MaintenanceTaskAttemptRecord(
            scheduler_run_id=first_run.scheduler_run_id,
            workspace_id="ws_1",
            operation=MaintenanceOperation.score_memory,
        )
    )

    with pytest.raises(ValueError, match="maintenance task attempt identity cannot change"):
        await repo.update_maintenance_task_attempt(
            attempt.model_copy(
                update={
                    "scheduler_run_id": second_run.scheduler_run_id,
                    "workspace_id": "ws_2",
                    "operation": MaintenanceOperation.decay_memory,
                }
            )
        )


@pytest.mark.asyncio
async def test_update_maintenance_task_attempt_preserves_created_at() -> None:
    repo = InMemoryRepository()
    run = await repo.add_maintenance_run(
        MaintenanceRunRecord(workspace_id="ws_1", operations=[MaintenanceOperation.score_memory])
    )
    attempt = await repo.add_maintenance_task_attempt(
        MaintenanceTaskAttemptRecord(
            scheduler_run_id=run.scheduler_run_id,
            workspace_id="ws_1",
            operation=MaintenanceOperation.score_memory,
        )
    )
    changed = attempt.model_copy(update={"status": SchedulerTaskStatus.completed})
    object.__setattr__(changed, "created_at", run.created_at)

    stored = await repo.update_maintenance_task_attempt(changed)

    assert stored.status == SchedulerTaskStatus.completed
    assert stored.created_at == attempt.created_at


@pytest.mark.asyncio
async def test_admin_list_methods_reject_unbounded_or_negative_pagination() -> None:
    repo = InMemoryRepository()
    with pytest.raises(ValueError, match="limit must be between 1 and 500"):
        await repo.list_maintenance_runs(limit=0)
    with pytest.raises(ValueError, match="limit must be between 1 and 500"):
        await repo.list_admin_action_audits(limit=501)
    with pytest.raises(ValueError, match="offset must be non-negative"):
        await repo.list_quota_limits(workspace_id="ws_1", offset=-1)


@pytest.mark.asyncio
async def test_admin_action_audits_are_workspace_scoped_and_paginated() -> None:
    repo = InMemoryRepository()
    await repo.add_admin_action_audit(
        AdminActionAuditRecord(
            workspace_id="ws_1",
            principal_id="admin_1",
            action="maintenance.start",
            target_type="maintenance_run",
            target_id="msrun_1",
        )
    )
    await repo.add_admin_action_audit(
        AdminActionAuditRecord(
            workspace_id="ws_2",
            principal_id="admin_2",
            action="quota.upsert",
            target_type="quota_limit",
            target_id="qlim_1",
        )
    )

    audits = await repo.list_admin_action_audits(workspace_id="ws_1", limit=1, offset=0)
    assert len(audits) == 1
    assert audits[0].workspace_id == "ws_1"


@pytest.mark.asyncio
async def test_conflict_scan_persists_and_resolves_stale_conflicts() -> None:
    repo = InMemoryRepository()
    first = await repo.add_memory(_project_memory(memory_id="mem_conflict_bun", value="bun"))
    second = await repo.add_memory(
        _project_memory(memory_id="mem_conflict_node", value="node", content="project.runtime=node")
    )

    result = await scheduler.conflict_scan(repo, workspace_id="ws_1", scheduler_run_id="sched_conflict")

    assert result["open_conflict_count"] == 1
    assert result["created_or_updated_count"] == 1
    conflicts = await repo.list_memory_conflicts(workspace_id="ws_1")
    assert len(conflicts) == 1
    assert conflicts[0].status == "open"
    assert conflicts[0].memory_ids == sorted([first.memory_id, second.memory_id])

    second.status = MemoryStatus.superseded
    second.superseded_by = first.memory_id
    await repo.update_memory(second)
    rerun = await scheduler.conflict_scan(repo, workspace_id="ws_1", scheduler_run_id="sched_conflict_2")

    assert rerun["open_conflict_count"] == 0
    assert rerun["stale_resolved_count"] == 1
    resolved = await repo.list_memory_conflicts(workspace_id="ws_1", status="resolved")
    assert len(resolved) == 1
    assert resolved[0].resolved_at is not None


@pytest.mark.asyncio
async def test_conflict_scan_resolves_stale_conflicts_beyond_default_page() -> None:
    repo = InMemoryRepository()
    for idx in range(105):
        await repo.upsert_memory_conflict(
            MemoryConflictRecord(
                conflict_id=f"mconf_stale_{idx:03d}",
                workspace_id="ws_1",
                subject_key="project.runtime",
                memory_ids=[f"mem_a_{idx}", f"mem_b_{idx}"],
                status="open",
                detected_by="maintenance_conflict_scan_v1",
            )
        )

    result = await scheduler.conflict_scan(repo, workspace_id="ws_1", scheduler_run_id="sched_conflict")

    assert result["stale_resolved_count"] == 105
    assert await repo.list_memory_conflicts(workspace_id="ws_1", status="open") == []
    resolved = await repo.list_memory_conflicts(workspace_id="ws_1", status="resolved", limit=500)
    assert len(resolved) == 105


@pytest.mark.asyncio
async def test_dedup_memory_dry_run_reports_pairs_without_mutation() -> None:
    repo = InMemoryRepository()
    await repo.add_memory(_project_memory(memory_id="mem_survivor", trust_score=0.9, access_count=2))
    await repo.add_memory(_project_memory(memory_id="mem_duplicate", trust_score=0.5, access_count=1))

    result = await scheduler.dedup_memory(repo, workspace_id="ws_1", scheduler_run_id="sched_dry", dry_run=True)

    assert result["deduped_count"] == 0
    assert result["candidate_pair_count"] == 1
    assert result["candidate_pairs"] == [
        {
            "survivor_memory_id": "mem_survivor",
            "duplicate_memory_id": "mem_duplicate",
            "canonical_key": "project.runtime",
            "scope": "workspace",
            "value_digest": result["candidate_pairs"][0]["value_digest"],
            "reason": "exact_same_canonical_key_scope_value",
        }
    ]
    assert result["candidate_pairs"][0]["value_digest"]
    assert "value" not in result["candidate_pairs"][0]
    memories = await repo.list_memories(workspace_id="ws_1")
    assert {memory.status for memory in memories} == {MemoryStatus.active}
    assert await repo.list_lifecycle_audits(workspace_id="ws_1") == []


@pytest.mark.asyncio
async def test_dedup_memory_skips_secret_like_memory_keys_without_leaking_key() -> None:
    repo = InMemoryRepository()
    await repo.add_memory(
        _project_memory(memory_id="mem_secret_a", key="project.api_token", value="same", content="project.api_token=same")
    )
    await repo.add_memory(
        _project_memory(memory_id="mem_secret_b", key="project.api_token", value="same", content="project.api_token=same")
    )

    result = await scheduler.dedup_memory(repo, workspace_id="ws_1", scheduler_run_id="sched_dedup", dry_run=True)

    assert result["candidate_pair_count"] == 0
    assert result["skipped_sensitive_count"] == 2
    assert "project.api_token" not in str(result)
    memories = await repo.list_memories(workspace_id="ws_1")
    assert {memory.status for memory in memories} == {MemoryStatus.active}


@pytest.mark.asyncio
async def test_dedup_memory_supersedes_safe_same_value_duplicates() -> None:
    repo = InMemoryRepository()
    survivor = await repo.add_memory(_project_memory(memory_id="mem_survivor", trust_score=0.9))
    duplicate = await repo.add_memory(_project_memory(memory_id="mem_duplicate", trust_score=0.4))
    await repo.add_memory(
        _project_memory(
            memory_id="mem_secret_duplicate",
            trust_score=0.1,
            sensitivity="secret",
            risk_flags=RiskFlags(contains_secret=True),
        )
    )

    result = await scheduler.dedup_memory(repo, workspace_id="ws_1", scheduler_run_id="sched_dedup")

    assert result["deduped_count"] == 1
    assert result["skipped_sensitive_count"] == 1
    stored_duplicate = await repo.get_memory(duplicate.memory_id)
    assert stored_duplicate is not None
    assert stored_duplicate.status == MemoryStatus.superseded
    assert stored_duplicate.superseded_by == survivor.memory_id
    audits = await repo.list_lifecycle_audits(workspace_id="ws_1", memory_id=duplicate.memory_id)
    assert len(audits) == 1
    assert audits[0].reason == "maintenance_dedup"
    assert audits[0].scheduler_run_id == "sched_dedup"


@pytest.mark.asyncio
async def test_reindex_memory_uses_deterministic_local_embedding_only() -> None:
    repo = InMemoryRepository()
    stale = await repo.add_memory(
        _project_memory(
            memory_id="mem_stale_embedding",
            embedding_vector=[0.2] * 256,
            embedding_status=EmbeddingStatus.stale,
        )
    )
    fresh = await repo.add_memory(
        _project_memory(
            memory_id="mem_fresh_embedding",
            embedding_vector=[0.1] * 256,
            embedding_status=EmbeddingStatus.embedded,
        )
    )

    result = await scheduler.reindex_memory(repo, workspace_id="ws_1", scheduler_run_id="sched_reindex")

    assert result["reindexed_count"] == 1
    assert result["skipped_count"] == 1
    assert result["provider"] == "deterministic_stable_embedding"
    assert result["provider_backed"] is False
    stored_stale = await repo.get_memory(stale.memory_id)
    stored_fresh = await repo.get_memory(fresh.memory_id)
    assert stored_stale is not None and stored_stale.embedding_status == EmbeddingStatus.embedded
    assert stored_stale.embedding_vector is not None and len(stored_stale.embedding_vector) == 256
    assert stored_fresh is not None and stored_fresh.embedding_vector == [0.1] * 256


@pytest.mark.asyncio
async def test_summary_and_procedural_refresh_create_missing_completed_run_memories() -> None:
    repo = InMemoryRepository()
    run = await repo.add_run(
        AgentRun(
            run_id="run_refresh",
            workspace_id="ws_1",
            session_id="sess_refresh",
            task="ship feature",
            status=RunStatus.completed,
        )
    )
    step = await repo.add_step(
        AgentStep(
            step_id="step_refresh",
            workspace_id="ws_1",
            run_id=run.run_id,
            status=StepStatus.completed,
        )
    )
    node = await repo.add_state_node(
        StateNode(
            node_id="node_refresh",
            workspace_id="ws_1",
            run_id=run.run_id,
            step_id=step.step_id,
            node_type=StateNodeType.step,
            status=StateNodeStatus.completed,
            goal="implemented feature",
            path="/node_refresh",
        )
    )
    await repo.add_event(
        AgentEvent(
            event_id="evt_refresh",
            workspace_id="ws_1",
            run_id=run.run_id,
            step_id=step.step_id,
            state_node_id=node.node_id,
            role=EventRole.tool,
            event_type=EventType.tool_result,
            content="bun test passed",
            sequence_no=1,
        )
    )
    await repo.add_memory(
        MemoryItem(
            workspace_id="ws_1",
            run_id=run.run_id,
            source_run_id=run.run_id,
            source_state_node_id=node.node_id,
            memory_type=MemoryType.tool_evidence,
            key="tool.test.success",
            value="bun test passed",
            content="bun test passed",
            summary="bun test passed",
            branch_status=BranchStatus.completed,
        )
    )

    summary_result = await scheduler.summary_refresh(repo, workspace_id="ws_1", scheduler_run_id="sched_summary")
    procedural_result = await scheduler.procedural_refresh(repo, workspace_id="ws_1", scheduler_run_id="sched_proc")

    assert summary_result["created_summary_count"] == 1
    assert procedural_result["created_procedural_count"] == 1
    memories = await repo.list_memories(workspace_id="ws_1")
    assert any(m.memory_type == MemoryType.episodic and m.source_run_id == run.run_id for m in memories)
    assert any(m.memory_type == MemoryType.procedural and m.source_run_id == run.run_id for m in memories)

    rerun_summary = await scheduler.summary_refresh(repo, workspace_id="ws_1", scheduler_run_id="sched_summary_2")
    rerun_procedural = await scheduler.procedural_refresh(repo, workspace_id="ws_1", scheduler_run_id="sched_proc_2")
    assert rerun_summary["created_summary_count"] == 0
    assert rerun_procedural["created_procedural_count"] == 0


@pytest.mark.asyncio
async def test_conflict_scan_does_not_resolve_other_detector_conflicts() -> None:
    repo = InMemoryRepository()
    await repo.upsert_memory_conflict(
        MemoryConflictRecord(
            conflict_id="mconf_runtime_only",
            workspace_id="ws_1",
            subject_key="project.runtime",
            memory_ids=["mem_a", "mem_b"],
            status="open",
            detected_by="runtime_write_path",
        )
    )

    result = await scheduler.conflict_scan(repo, workspace_id="ws_1", scheduler_run_id="sched_conflict")

    assert result["open_conflict_count"] == 0
    assert result["stale_resolved_count"] == 0
    conflicts = await repo.list_memory_conflicts(workspace_id="ws_1")
    assert conflicts[0].status == "open"
    assert conflicts[0].detected_by == "runtime_write_path"


@pytest.mark.asyncio
async def test_summary_refresh_ignores_superseded_existing_run_summary() -> None:
    repo = InMemoryRepository()
    run = await repo.add_run(
        AgentRun(
            run_id="run_superseded_summary",
            workspace_id="ws_1",
            session_id="sess_summary",
            task="refresh summary",
            status=RunStatus.completed,
        )
    )
    await repo.add_step(
        AgentStep(step_id="step_summary", workspace_id="ws_1", run_id=run.run_id, status=StepStatus.completed)
    )
    await repo.add_event(
        AgentEvent(
            event_id="evt_summary",
            workspace_id="ws_1",
            run_id=run.run_id,
            step_id="step_summary",
            role=EventRole.user,
            event_type=EventType.message,
            content="done",
            sequence_no=1,
        )
    )
    await repo.add_memory(
        MemoryItem(
            workspace_id="ws_1",
            run_id=run.run_id,
            source_run_id=run.run_id,
            memory_type=MemoryType.episodic,
            key=f"run.summary.{run.run_id}",
            content="old summary",
            status=MemoryStatus.superseded,
        )
    )

    result = await scheduler.summary_refresh(repo, workspace_id="ws_1", scheduler_run_id="sched_summary")

    assert result["created_summary_count"] == 1
    summaries = [
        memory
        for memory in await repo.list_memories(workspace_id="ws_1")
        if memory.memory_type == MemoryType.episodic and memory.source_run_id == run.run_id
    ]
    assert sum(1 for memory in summaries if memory.status == MemoryStatus.active) == 1


@pytest.mark.asyncio
async def test_summary_and_procedural_refresh_supersede_legacy_same_key_active_memories() -> None:
    repo = InMemoryRepository()
    run = await repo.add_run(
        AgentRun(
            run_id="run_legacy_refresh",
            workspace_id="ws_1",
            session_id="sess_legacy",
            task="refresh legacy memories",
            status=RunStatus.completed,
        )
    )
    step = await repo.add_step(
        AgentStep(step_id="step_legacy", workspace_id="ws_1", run_id=run.run_id, status=StepStatus.completed)
    )
    await repo.add_state_node(
        StateNode(
            node_id="node_legacy",
            workspace_id="ws_1",
            run_id=run.run_id,
            step_id=step.step_id,
            node_type=StateNodeType.step,
            status=StateNodeStatus.completed,
            goal="legacy done",
            path="/node_legacy",
        )
    )
    await repo.add_event(
        AgentEvent(
            event_id="evt_legacy",
            workspace_id="ws_1",
            run_id=run.run_id,
            step_id=step.step_id,
            role=EventRole.tool,
            event_type=EventType.tool_result,
            content="bun test passed",
            sequence_no=1,
        )
    )
    legacy_summary = await repo.add_memory(
        MemoryItem(
            workspace_id="ws_1",
            memory_type=MemoryType.episodic,
            key=f"run.summary.{run.run_id}",
            content="legacy summary",
            status=MemoryStatus.active,
        )
    )
    legacy_procedure = await repo.add_memory(
        MemoryItem(
            workspace_id="ws_1",
            memory_type=MemoryType.procedural,
            key=f"procedure.{run.run_id}",
            content="legacy procedure",
            status=MemoryStatus.active,
        )
    )

    summary_result = await scheduler.summary_refresh(repo, workspace_id="ws_1", scheduler_run_id="sched_summary")
    procedural_result = await scheduler.procedural_refresh(repo, workspace_id="ws_1", scheduler_run_id="sched_proc")

    assert summary_result["created_summary_count"] == 1
    assert procedural_result["created_procedural_count"] == 1
    memories = await repo.list_memories(workspace_id="ws_1")
    summary_rows = [memory for memory in memories if memory.key == f"run.summary.{run.run_id}"]
    procedure_rows = [memory for memory in memories if memory.key == f"procedure.{run.run_id}"]
    assert sum(1 for memory in summary_rows if memory.status == MemoryStatus.active) == 1
    assert sum(1 for memory in procedure_rows if memory.status == MemoryStatus.active) == 1
    stored_legacy_summary = await repo.get_memory(legacy_summary.memory_id)
    stored_legacy_procedure = await repo.get_memory(legacy_procedure.memory_id)
    assert stored_legacy_summary is not None and stored_legacy_summary.status == MemoryStatus.superseded
    assert stored_legacy_procedure is not None and stored_legacy_procedure.status == MemoryStatus.superseded
    assert stored_legacy_summary.superseded_by is not None
    assert stored_legacy_procedure.superseded_by is not None


@pytest.mark.asyncio
async def test_run_workspace_maintenance_records_attempts_and_summary() -> None:
    from app.memory.maintenance import run_workspace_maintenance

    repo = InMemoryRepository()
    await repo.add_memory(_project_memory(memory_id="mem_orchestrator"))

    run = await run_workspace_maintenance(
        repo,
        workspace_id="ws_1",
        operations=[MaintenanceOperation.score_memory, MaintenanceOperation.conflict_scan],
        requested_by="admin:alice",
        dry_run=False,
    )

    assert run.status == SchedulerRunStatus.completed
    assert run.summary["completed_count"] == 2
    assert run.summary["failed_count"] == 0
    attempts = await repo.list_maintenance_task_attempts(scheduler_run_id=run.scheduler_run_id)
    assert [attempt.operation for attempt in attempts] == [
        MaintenanceOperation.score_memory,
        MaintenanceOperation.conflict_scan,
    ]
    assert {attempt.status for attempt in attempts} == {SchedulerTaskStatus.completed}
    assert attempts[0].idempotency_key == f"maintenance:{run.scheduler_run_id}:score_memory"


@pytest.mark.asyncio
async def test_run_workspace_maintenance_dry_run_records_skipped_attempts_without_handlers() -> None:
    from app.memory.maintenance import run_workspace_maintenance

    repo = InMemoryRepository()
    await repo.add_memory(_project_memory(memory_id="mem_dry_orchestrator"))

    run = await run_workspace_maintenance(
        repo,
        workspace_id="ws_1",
        operations=[MaintenanceOperation.dedup_memory, MaintenanceOperation.reindex_memory],
        requested_by="admin:alice",
        dry_run=True,
        reason="preview only",
    )

    assert run.status == SchedulerRunStatus.completed
    assert run.dry_run is True
    assert run.summary["skipped_count"] == 2
    attempts = await repo.list_maintenance_task_attempts(scheduler_run_id=run.scheduler_run_id)
    assert [attempt.status for attempt in attempts] == [SchedulerTaskStatus.skipped, SchedulerTaskStatus.skipped]
    assert attempts[0].result["reason"] == "dry_run"
    memories = await repo.list_memories(workspace_id="ws_1")
    assert memories[0].status == MemoryStatus.active


@pytest.mark.asyncio
async def test_run_workspace_maintenance_rejects_duplicate_operations_before_run_creation() -> None:
    from app.memory.maintenance import run_workspace_maintenance

    repo = InMemoryRepository()

    with pytest.raises(ValueError, match="duplicate maintenance operation"):
        await run_workspace_maintenance(
            repo,
            workspace_id="ws_1",
            operations=[MaintenanceOperation.score_memory, MaintenanceOperation.score_memory],
            requested_by="admin:alice",
        )

    assert await repo.list_maintenance_runs(workspace_id="ws_1") == []


@pytest.mark.asyncio
async def test_run_workspace_maintenance_isolates_operation_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.memory import maintenance

    async def boom(*args, **kwargs):  # noqa: ANN002, ANN003
        raise RuntimeError("Authorization: Bearer secret-token raw_payload_ref=abc rm -rf /prod")

    repo = InMemoryRepository()
    monkeypatch.setitem(maintenance.OPERATION_HANDLERS, MaintenanceOperation.score_memory, boom)

    run = await maintenance.run_workspace_maintenance(
        repo,
        workspace_id="ws_1",
        operations=[MaintenanceOperation.score_memory, MaintenanceOperation.profile_refresh],
        requested_by="admin:alice",
    )

    assert run.status == SchedulerRunStatus.failed
    assert run.summary["failed_count"] == 1
    assert run.summary["completed_count"] == 1
    attempts = await repo.list_maintenance_task_attempts(scheduler_run_id=run.scheduler_run_id)
    assert [attempt.status for attempt in attempts] == [SchedulerTaskStatus.failed, SchedulerTaskStatus.completed]
    assert attempts[0].error_summary is not None
    assert "secret-token" not in attempts[0].error_summary
    assert "raw_payload_ref" not in attempts[0].error_summary
    assert "rm -rf" not in attempts[0].error_summary


@pytest.mark.asyncio
async def test_run_workspace_maintenance_redacts_run_level_requested_by_and_reason() -> None:
    from app.memory.maintenance import run_workspace_maintenance

    repo = InMemoryRepository()

    run = await run_workspace_maintenance(
        repo,
        workspace_id="ws_1",
        operations=[MaintenanceOperation.profile_refresh],
        requested_by="Authorization: Bearer secret-token",
        reason="raw_payload_ref=abc rm -rf /prod",
    )

    assert run.status == SchedulerRunStatus.completed
    assert "secret-token" not in run.requested_by
    assert "raw_payload_ref" not in (run.reason or "")
    assert "rm -rf" not in (run.reason or "")
    stored = await repo.get_maintenance_run(run.scheduler_run_id)
    assert stored is not None
    assert stored.requested_by == run.requested_by
    assert stored.reason == run.reason
