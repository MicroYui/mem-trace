"""P4-C memory conflict tests."""
from __future__ import annotations

import pytest

from app.memory.conflicts import detect_memory_conflicts
from app.runtime.memory_runtime import MemoryRuntime
from app.runtime.models import MemoryItem, MemoryScope, MemoryStatus, MemoryType, RiskFlags, Sensitivity
from app.runtime.repository import InMemoryRepository


def _memory(memory_id: str, *, key: str, value: str, trust_score: float = 0.6, memory_type: MemoryType = MemoryType.project) -> MemoryItem:
    return MemoryItem(
        memory_id=memory_id,
        workspace_id="ws_conflicts",
        memory_type=memory_type,
        key=key,
        value=value,
        scope=MemoryScope.workspace,
        content=f"{key}={value}",
        trust_score=trust_score,
        status=MemoryStatus.active,
    )


def test_detect_memory_conflicts_uses_ontology_identity_and_aliases() -> None:
    memories = [
        _memory("mem_pkg_old", key="project.pkg_manager", value="npm"),
        _memory("mem_pkg_new", key="project.package_manager", value="bun"),
        _memory("mem_multi_1", key="project.runtime.excluded", value="node"),
        _memory("mem_multi_2", key="project.runtime.excluded", value="deno"),
    ]

    conflicts = detect_memory_conflicts("ws_conflicts", memories, detected_by="test")

    assert len(conflicts) == 1
    conflict = conflicts[0]
    assert conflict.subject_key == "project.package_manager"
    assert conflict.memory_ids == ["mem_pkg_new", "mem_pkg_old"]
    assert conflict.status == "open"
    assert conflict.detected_by == "test"
    assert "npm" in conflict.explanation
    assert "bun" in conflict.explanation


def test_tool_result_evidence_explains_conflict_without_auto_overwriting_higher_trust_project_constraint() -> None:
    project_constraint = _memory("mem_project", key="project.runtime", value="bun", trust_score=0.9)
    tool_evidence = _memory(
        "mem_tool",
        key="project.runtime",
        value="node",
        trust_score=0.4,
        memory_type=MemoryType.tool_evidence,
    )

    conflicts = detect_memory_conflicts("ws_conflicts", [project_constraint, tool_evidence], detected_by="scan")

    assert len(conflicts) == 1
    assert project_constraint.status == MemoryStatus.active
    assert tool_evidence.status == MemoryStatus.active
    assert "tool evidence" in conflicts[0].explanation.lower()
    assert "manual review" in conflicts[0].explanation.lower()


def test_conflict_explanation_redacts_secret_like_values() -> None:
    safe = _memory("mem_safe", key="project.runtime", value="bun")
    unsafe = _memory("mem_secret", key="project.runtime", value="token=sk-1234567890abcdef1234")
    unsafe.risk_flags = RiskFlags(contains_secret=True)
    unsafe.sensitivity = Sensitivity.secret

    conflict = detect_memory_conflicts("ws_conflicts", [safe, unsafe], detected_by="scan")[0]

    assert "sk-1234567890abcdef1234" not in conflict.explanation
    assert "token=" not in conflict.explanation
    assert "[REDACTED]" in conflict.explanation


@pytest.mark.asyncio
async def test_repository_upserts_conflict_records_deterministically() -> None:
    repo = InMemoryRepository()
    memories = [
        await repo.add_memory(_memory("mem_a", key="project.runtime", value="bun")),
        await repo.add_memory(_memory("mem_b", key="project.runtime", value="node")),
    ]
    conflict = detect_memory_conflicts("ws_conflicts", memories, detected_by="scan")[0]

    await repo.upsert_memory_conflict(conflict)
    await repo.upsert_memory_conflict(conflict)
    listed = await repo.list_memory_conflicts(workspace_id="ws_conflicts")

    assert [row.conflict_id for row in listed] == [conflict.conflict_id]
    assert listed[0].memory_ids == ["mem_a", "mem_b"]


@pytest.mark.asyncio
async def test_runtime_scan_resolves_stale_conflicts_when_active_conflict_disappears() -> None:
    repo = InMemoryRepository()
    runtime = MemoryRuntime(repo)
    mem_a = await repo.add_memory(_memory("mem_a", key="project.runtime", value="bun"))
    mem_b = await repo.add_memory(_memory("mem_b", key="project.runtime", value="node"))
    await runtime._scan_and_persist_conflicts("ws_conflicts")
    assert len(await repo.list_memory_conflicts(workspace_id="ws_conflicts", status="open")) == 1

    mem_b.status = MemoryStatus.superseded
    await repo.update_memory(mem_b)
    await runtime._scan_and_persist_conflicts("ws_conflicts")

    assert await repo.list_memory_conflicts(workspace_id="ws_conflicts", status="open") == []
    resolved = await repo.list_memory_conflicts(workspace_id="ws_conflicts", status="resolved")
    assert len(resolved) == 1
    assert resolved[0].resolved_at is not None
    assert set(resolved[0].memory_ids) == {mem_a.memory_id, mem_b.memory_id}
