"""ROADMAP §7: end-to-end safety-axis regression through the MemoryRuntime facade.

The gate unit tests cover policy in isolation and the benchmark covers the axes
through its own seeding harness. This module is a third, facade-level guard: it
drives the *public* ``MemoryRuntime.retrieve_context`` path and asserts what
actually reaches the packed prompt for the four safety axes — failed-branch
isolation, workspace isolation, stale exclusion, and tool-sensitive blocking —
plus a positive control so the assertions cannot pass by retrieving nothing.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.runtime.memory_runtime import MemoryRuntime
from app.runtime.models import (
    BranchStatus,
    MemoryItem,
    MemoryScope,
    MemoryType,
    RetrievalRequest,
    RetrievalStrategy,
    RiskFlags,
    StartRunRequest,
    StartStepRequest,
)
from app.runtime.repository import InMemoryRepository

_WS = "ws_axes"
_QUERY = "how should I deploy the service"


def _mem(repo_value: str, *, content: str, workspace_id=_WS, branch=BranchStatus.active,
         expires_at=None, risk_flags=None, mid=None) -> MemoryItem:
    kwargs = dict(
        workspace_id=workspace_id,
        memory_type=MemoryType.project,
        key="project.deploy_note",
        value=repo_value,
        content=content,
        scope=MemoryScope.workspace,
        branch_status=branch,
        expires_at=expires_at,
        risk_flags=risk_flags or RiskFlags(),
    )
    if mid is not None:
        kwargs["memory_id"] = mid
    return MemoryItem(**kwargs)


async def _retrieve(repo: InMemoryRepository, *seeds: MemoryItem):
    runtime = MemoryRuntime(repo, default_workspace_id=_WS)
    run = await runtime.start_run(StartRunRequest(session_id="s", task="deploy", workspace_id=_WS))
    await runtime.start_step(StartStepRequest(run_id=run.run_id, intent="planning", goal="deploy the service"))
    step = await runtime.start_step(StartStepRequest(run_id=run.run_id, intent="deploying", goal="deploy now"))
    for m in seeds:
        await repo.add_memory(m)
    ctx = await runtime.retrieve_context(
        RetrievalRequest(run_id=run.run_id, step_id=step.step_id, query=_QUERY,
                         strategy=RetrievalStrategy.variant_2)
    )
    positive = "\n".join(b.content for b in ctx.context_blocks if b.type != "avoided_attempts")
    return ctx, positive


@pytest.mark.asyncio
async def test_positive_control_safe_memory_reaches_prompt():
    repo = InMemoryRepository()
    _ctx, positive = await _retrieve(
        repo, _mem("kubernetes", content="deploy the service on kubernetes", mid="m_good"),
    )
    assert "kubernetes" in positive


@pytest.mark.asyncio
async def test_failed_branch_memory_excluded_from_positive_context():
    repo = InMemoryRepository()
    _ctx, positive = await _retrieve(
        repo,
        _mem("kubernetes", content="deploy the service on kubernetes", mid="m_good"),
        _mem("badheroku", content="deploy the service on badheroku", branch=BranchStatus.failed, mid="m_failed"),
    )
    assert "kubernetes" in positive
    assert "badheroku" not in positive


@pytest.mark.asyncio
async def test_cross_workspace_memory_excluded_from_positive_context():
    repo = InMemoryRepository()
    _ctx, positive = await _retrieve(
        repo,
        _mem("kubernetes", content="deploy the service on kubernetes", mid="m_good"),
        _mem("otherwsdeploy", content="deploy the service on otherwsdeploy",
             workspace_id="ws_other", mid="m_other"),
    )
    assert "kubernetes" in positive
    assert "otherwsdeploy" not in positive


@pytest.mark.asyncio
async def test_stale_memory_excluded_from_positive_context():
    repo = InMemoryRepository()
    past = datetime.now(timezone.utc) - timedelta(days=1)
    _ctx, positive = await _retrieve(
        repo,
        _mem("kubernetes", content="deploy the service on kubernetes", mid="m_good"),
        _mem("stalefly", content="deploy the service on stalefly", expires_at=past, mid="m_stale"),
    )
    assert "kubernetes" in positive
    assert "stalefly" not in positive


@pytest.mark.asyncio
async def test_tool_sensitive_memory_excluded_from_positive_context():
    repo = InMemoryRepository()
    _ctx, positive = await _retrieve(
        repo,
        _mem("kubernetes", content="deploy the service on kubernetes", mid="m_good"),
        _mem("toolsecret", content="deploy the service with toolsecret credentials",
             risk_flags=RiskFlags(tool_sensitive=True), mid="m_tool"),
    )
    assert "kubernetes" in positive
    assert "toolsecret" not in positive
