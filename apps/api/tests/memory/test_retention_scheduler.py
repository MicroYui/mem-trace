from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math

import pytest

from app.memory.retention import RETENTION_POLICY_VERSION, RetentionPolicy, compute_retention_signals
from app.memory.scheduler import archive_memory, profile_refresh, quarantine_memory, score_memory
from app.retrieval.controller import retention_score
from app.runtime.models import MemoryItem, MemoryStatus, MemoryType, RiskFlags
from app.runtime.repository import InMemoryRepository


NOW = datetime(2026, 6, 14, 12, 0, tzinfo=timezone.utc)


def _memory(**kwargs) -> MemoryItem:
    fields = {
        "memory_id": "mem_retention",
        "workspace_id": "ws_retention",
        "memory_type": MemoryType.episodic,
        "content": "retain critical fact",
        "value_score": 0.8,
        "freshness_score": 0.7,
        "trust_score": 0.9,
        "risk_score": 0.1,
        "access_count": 5,
        "last_accessed_at": NOW - timedelta(days=2),
    }
    fields.update(kwargs)
    return MemoryItem(**fields)


def test_compute_retention_signals_uses_scores_access_and_timestamps_deterministically():
    signal = compute_retention_signals(_memory(), now=NOW, policy=RetentionPolicy())

    assert signal.memory_id == "mem_retention"
    assert signal.workspace_id == "ws_retention"
    assert signal.policy_version == RETENTION_POLICY_VERSION
    assert signal.reason["components"]["value"] == 0.8
    assert signal.reason["components"]["trust"] == 0.9
    assert signal.reason["components"]["usage"] == 0.5
    assert signal.reason["components"]["recency"] > 0.9
    assert 0.0 <= signal.retention_score <= 1.0
    assert 0.0 <= signal.reflection_priority <= 1.0


def test_expired_or_high_risk_memory_gets_low_retention():
    expired = compute_retention_signals(_memory(expires_at=NOW - timedelta(seconds=1)), now=NOW)
    risky = compute_retention_signals(_memory(risk_score=1.0, risk_flags=RiskFlags(destructive_command=True)), now=NOW)

    assert expired.retention_score < 0.2
    assert expired.reason["expired"] is True
    assert risky.retention_score < 0.3
    assert risky.reason["high_risk"] is True


def test_non_finite_scores_do_not_inflate_retention_or_reflection_priority():
    signal = compute_retention_signals(
        _memory(value_score=math.nan, freshness_score=math.inf, trust_score=-math.inf, risk_score=math.nan),
        now=NOW,
    )

    assert signal.reason["components"]["value"] == 0.0
    assert signal.reason["components"]["freshness"] == 0.0
    assert signal.reason["components"]["trust"] == 0.0
    assert signal.reason["components"]["risk"] == 0.0
    assert signal.retention_score < 0.3
    assert signal.reflection_priority < 0.3
    assert retention_score(_memory(trust_score=math.nan, freshness_score=math.inf, access_count=10)) == 0.3


@pytest.mark.asyncio
async def test_retention_signal_repository_round_trip_and_filtering():
    repo = InMemoryRepository()
    mem1 = await repo.add_memory(_memory(memory_id="mem_1"))
    mem2 = await repo.add_memory(_memory(memory_id="mem_2"))
    sig1 = compute_retention_signals(mem1, now=NOW)
    sig2 = compute_retention_signals(mem2, now=NOW)

    await repo.upsert_retention_signal(sig1)
    await repo.upsert_retention_signal(sig2)

    assert (await repo.get_retention_signal("mem_1")).memory_id == "mem_1"
    filtered = await repo.list_retention_signals("ws_retention", memory_ids=["mem_2"])
    assert [s.memory_id for s in filtered] == ["mem_2"]


@pytest.mark.asyncio
async def test_scheduler_score_memory_persists_signals_without_celery():
    repo = InMemoryRepository()
    await repo.add_memory(_memory(memory_id="mem_score"))

    result = await score_memory(repo, workspace_id="ws_retention", now=NOW, scheduler_run_id="sched_score")

    assert result["scored_count"] == 1
    signal = await repo.get_retention_signal("mem_score")
    assert signal is not None
    assert signal.reason["scheduler_run_id"] == "sched_score"


@pytest.mark.asyncio
async def test_scheduler_archive_skips_pinned_and_audits_archived_memory():
    repo = InMemoryRepository()
    low_retention = {
        "access_count": 0,
        "last_accessed_at": NOW - timedelta(days=90),
        "value_score": 0.1,
        "freshness_score": 0.1,
        "trust_score": 0.1,
    }
    await repo.add_memory(_memory(memory_id="mem_archive", **low_retention))
    await repo.add_memory(_memory(memory_id="mem_pinned", status=MemoryStatus.pinned, **low_retention))

    result = await archive_memory(repo, workspace_id="ws_retention", now=NOW, scheduler_run_id="sched_archive")

    assert result["archived_count"] == 1
    assert (await repo.get_memory("mem_archive")).status == MemoryStatus.archived
    assert (await repo.get_memory("mem_pinned")).status == MemoryStatus.pinned
    audits = await repo.list_lifecycle_audits(workspace_id="ws_retention", memory_id="mem_archive")
    assert audits[-1].reason == "retention_archive"


@pytest.mark.asyncio
async def test_scheduler_quarantine_flags_high_risk_memory_and_profile_refresh_is_read_only():
    repo = InMemoryRepository()
    await repo.add_memory(_memory(memory_id="mem_risky", risk_score=1.0, risk_flags=RiskFlags(contains_secret=True)))

    quarantine = await quarantine_memory(repo, workspace_id="ws_retention", now=NOW, scheduler_run_id="sched_quarantine")
    profile = await profile_refresh(repo, workspace_id="ws_retention", now=NOW, scheduler_run_id="sched_profile")

    assert quarantine["quarantined_count"] == 1
    assert (await repo.get_memory("mem_risky")).status == MemoryStatus.quarantined
    assert profile["memory_count"] == 1
    assert profile["status_counts"]["quarantined"] == 1
