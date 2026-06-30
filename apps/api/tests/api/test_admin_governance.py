from __future__ import annotations

from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import app_state, get_quota_service, get_repository, get_runtime
from app.config import Settings, get_settings
from app.governance.auth import authenticate_api_key, create_api_key_record
from app.governance.quota import InMemoryQuotaCounter, QuotaService
from app.main import app
from app.runtime.memory_runtime import MemoryRuntime
from app.runtime.models import (
    MemoryConflictRecord,
    MemoryItem,
    MemoryStatus,
    MemoryType,
    WorkspacePermission,
)
from app.runtime.repository import InMemoryRepository


@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
    app.dependency_overrides.clear()
    app_state.maintenance_enqueue = None


def _override(repo: InMemoryRepository | None = None) -> InMemoryRepository:
    repo = repo or InMemoryRepository()
    app_state.repository = repo
    app.dependency_overrides[get_runtime] = lambda: MemoryRuntime(repo, default_workspace_id="ws_admin")
    app.dependency_overrides[get_repository] = lambda: repo
    return repo


async def _add_owner_key(repo: InMemoryRepository, *, workspace_id: str = "ws_1", raw: str = "mt_owner_ws_1") -> str:
    await repo.add_api_key(
        create_api_key_record(
            raw,
            workspace_id=workspace_id,
            principal_id="owner_1",
            roles=[WorkspacePermission.owner.value],
        )
    )
    return raw


def _admin_env(monkeypatch) -> None:
    monkeypatch.setenv("MEMTRACE_ADMIN_API_ENABLED", "true")
    monkeypatch.setenv("MEMTRACE_AUTH_ENABLED", "true")
    monkeypatch.setenv("MEMTRACE_GOVERNANCE_ENABLED", "true")


# --------------------------------------------------------------------------- #
# Task 6: API key administration
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_api_key_admin_disabled_by_default(monkeypatch):
    monkeypatch.setenv("MEMTRACE_ADMIN_API_ENABLED", "false")
    _override()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/v1/admin/api-keys",
            json={"workspace_id": "ws_1", "principal_id": "u1", "roles": ["reader"]},
        )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_create_api_key_returns_raw_once_and_list_is_redacted(monkeypatch):
    _admin_env(monkeypatch)
    repo = _override()
    raw = await _add_owner_key(repo)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/v1/admin/api-keys",
            json={"workspace_id": "ws_1", "principal_id": "user_2", "roles": ["writer"]},
            headers={"X-API-Key": raw},
        )
        listed = await client.get(
            "/v1/admin/api-keys?workspace_id=ws_1",
            headers={"X-API-Key": raw},
        )

    assert created.status_code == 200
    body = created.json()
    raw_key = body["raw_api_key"]
    assert raw_key.startswith("mtk_")
    # Public DTO must not leak the digest, and raw key only appears in create.
    assert "key_digest" not in body["api_key"]
    assert listed.status_code == 200
    rows = listed.json()
    assert any(r["principal_id"] == "user_2" for r in rows)
    for r in rows:
        assert "key_digest" not in r
        assert raw_key not in str(r)

    # Audit must never store raw key or digest.
    audits = await repo.list_admin_action_audits(workspace_id="ws_1")
    assert any(a.action == "create_api_key" for a in audits)
    for a in audits:
        assert raw_key not in str(a.metadata)


@pytest.mark.asyncio
async def test_created_api_key_authenticates(monkeypatch):
    _admin_env(monkeypatch)
    repo = _override()
    raw = await _add_owner_key(repo)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/v1/admin/api-keys",
            json={"workspace_id": "ws_1", "principal_id": "user_2", "roles": ["writer"]},
            headers={"X-API-Key": raw},
        )
    raw_key = created.json()["raw_api_key"]
    principal = await authenticate_api_key(raw_key, repo, Settings(auth_enabled=True, governance_enabled=True))
    assert principal.principal_id == "user_2"
    assert principal.workspace_ids == ["ws_1"]


@pytest.mark.asyncio
async def test_create_api_key_rejects_empty_roles_and_wildcard(monkeypatch):
    _admin_env(monkeypatch)
    repo = _override()
    raw = await _add_owner_key(repo)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        empty = await client.post(
            "/v1/admin/api-keys",
            json={"workspace_id": "ws_1", "principal_id": "u", "roles": []},
            headers={"X-API-Key": raw},
        )
        # wildcard owner key cannot pass owner gate for "*" so it is 403, not creatable
        wildcard_owner = await _add_owner_key(repo, workspace_id="*", raw="mt_wild_owner")
        wildcard = await client.post(
            "/v1/admin/api-keys",
            json={"workspace_id": "*", "principal_id": "u", "roles": ["reader"]},
            headers={"X-API-Key": wildcard_owner},
        )

    assert empty.status_code == 400
    assert wildcard.status_code == 403


@pytest.mark.asyncio
async def test_revoke_api_key_is_idempotent_and_disables_auth(monkeypatch):
    _admin_env(monkeypatch)
    repo = _override()
    raw = await _add_owner_key(repo)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/v1/admin/api-keys",
            json={"workspace_id": "ws_1", "principal_id": "user_2", "roles": ["writer"]},
            headers={"X-API-Key": raw},
        )
        api_key_id = created.json()["api_key"]["api_key_id"]
        first = await client.post(
            f"/v1/admin/api-keys/{api_key_id}/revoke",
            headers={"X-API-Key": raw},
        )
        second = await client.post(
            f"/v1/admin/api-keys/{api_key_id}/revoke",
            headers={"X-API-Key": raw},
        )

    assert first.status_code == 200
    assert first.json()["revoked_at"] is not None
    assert second.status_code == 200  # idempotent


# --------------------------------------------------------------------------- #
# Task 7: quota override administration
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_quota_override_crud(monkeypatch):
    _admin_env(monkeypatch)
    repo = _override()
    raw = await _add_owner_key(repo)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        put = await client.put(
            "/v1/admin/quota-limits",
            json={"workspace_id": "ws_1", "principal_id": "alice", "unit": "write_event", "limit": 5, "window_seconds": 60},
            headers={"X-API-Key": raw},
        )
        listed = await client.get(
            "/v1/admin/quota-limits?workspace_id=ws_1&principal_id=alice",
            headers={"X-API-Key": raw},
        )
        quota_limit_id = put.json()["quota_limit_id"]
        deleted = await client.delete(
            f"/v1/admin/quota-limits/{quota_limit_id}?workspace_id=ws_1",
            headers={"X-API-Key": raw},
        )

    assert put.status_code == 200
    assert listed.status_code == 200
    assert listed.json()[0]["limit"] == 5
    assert deleted.status_code == 204


@pytest.mark.asyncio
async def test_quota_override_multiple_units_same_principal(monkeypatch):
    _admin_env(monkeypatch)
    repo = _override()
    raw = await _add_owner_key(repo)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.put(
            "/v1/admin/quota-limits",
            json={"workspace_id": "ws_1", "principal_id": "alice", "unit": "write_event", "limit": 5, "window_seconds": 60},
            headers={"X-API-Key": raw},
        )
        # A second unit for the same (workspace, principal) must create a
        # distinct override, not collide with the first unit's identity.
        second = await client.put(
            "/v1/admin/quota-limits",
            json={"workspace_id": "ws_1", "principal_id": "alice", "unit": "retrieve_context", "limit": 9, "window_seconds": 60},
            headers={"X-API-Key": raw},
        )
        # Updating the first unit again must keep its own identity.
        update_first = await client.put(
            "/v1/admin/quota-limits",
            json={"workspace_id": "ws_1", "principal_id": "alice", "unit": "write_event", "limit": 7, "window_seconds": 60},
            headers={"X-API-Key": raw},
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert update_first.status_code == 200
    assert first.json()["unit"] == "write_event"
    assert second.json()["unit"] == "retrieve_context"
    assert first.json()["quota_limit_id"] != second.json()["quota_limit_id"]
    # Re-upserting the first unit preserves its identity and applies the new limit.
    assert update_first.json()["quota_limit_id"] == first.json()["quota_limit_id"]
    assert update_first.json()["limit"] == 7
    rows = await repo.list_quota_limits(workspace_id="ws_1", principal_id="alice")
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_quota_override_validation(monkeypatch):
    _admin_env(monkeypatch)
    repo = _override()
    raw = await _add_owner_key(repo)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        negative_limit = await client.put(
            "/v1/admin/quota-limits",
            json={"workspace_id": "ws_1", "unit": "write_event", "limit": -1, "window_seconds": 60},
            headers={"X-API-Key": raw},
        )
        bad_window = await client.put(
            "/v1/admin/quota-limits",
            json={"workspace_id": "ws_1", "unit": "write_event", "limit": 1, "window_seconds": 0},
            headers={"X-API-Key": raw},
        )

    assert negative_limit.status_code == 400
    assert bad_window.status_code == 400


# --------------------------------------------------------------------------- #
# Task 8: manual lifecycle + conflict resolution administration
# --------------------------------------------------------------------------- #
async def _seed_memory(repo: InMemoryRepository, *, workspace_id="ws_1", value="bun", status=MemoryStatus.active) -> MemoryItem:
    return await repo.add_memory(
        MemoryItem(
            workspace_id=workspace_id,
            memory_type=MemoryType.project,
            key="project.runtime",
            value=value,
            content=value,
            status=status,
        )
    )


@pytest.mark.asyncio
async def test_admin_set_memory_status_pins_and_audits(monkeypatch):
    _admin_env(monkeypatch)
    repo = _override()
    raw = await _add_owner_key(repo)
    memory = await _seed_memory(repo)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            f"/v1/admin/memories/{memory.memory_id}/status",
            json={"to_status": "pinned", "reason": "operator decision"},
            headers={"X-API-Key": raw},
        )

    assert resp.status_code == 200
    assert resp.json()["status"] == "pinned"
    audits = await repo.list_lifecycle_audits(workspace_id="ws_1", memory_id=memory.memory_id)
    assert audits[-1].actor == "admin:owner_1"


@pytest.mark.asyncio
async def test_admin_set_memory_status_rejects_invalid_transition(monkeypatch):
    _admin_env(monkeypatch)
    repo = _override()
    raw = await _add_owner_key(repo)
    memory = await _seed_memory(repo)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            f"/v1/admin/memories/{memory.memory_id}/status",
            json={"to_status": "archived", "reason": "skip dormant"},
            headers={"X-API-Key": raw},
        )

    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_admin_set_memory_status_missing_returns_404(monkeypatch):
    _admin_env(monkeypatch)
    repo = _override()
    raw = await _add_owner_key(repo)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/v1/admin/memories/mem_missing/status",
            json={"to_status": "pinned", "reason": "x"},
            headers={"X-API-Key": raw},
        )

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_resolve_conflict_choose_winner_supersedes_losers(monkeypatch):
    _admin_env(monkeypatch)
    repo = _override()
    raw = await _add_owner_key(repo)
    winner = await _seed_memory(repo, value="bun")
    loser = await _seed_memory(repo, value="node")
    conflict = await repo.upsert_memory_conflict(
        MemoryConflictRecord(
            workspace_id="ws_1",
            subject_key="project.runtime",
            memory_ids=sorted([winner.memory_id, loser.memory_id]),
            status="open",
        )
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            f"/v1/admin/memory-conflicts/{conflict.conflict_id}/resolve",
            json={"action": "choose_winner", "winner_memory_id": winner.memory_id, "reason": "owner picks bun"},
            headers={"X-API-Key": raw},
        )

    assert resp.status_code == 200
    assert resp.json()["status"] == "resolved_choose_winner"
    loser_after = await repo.get_memory(loser.memory_id)
    assert loser_after.status == MemoryStatus.superseded
    assert loser_after.superseded_by == winner.memory_id
    winner_after = await repo.get_memory(winner.memory_id)
    assert winner_after.status == MemoryStatus.active


@pytest.mark.asyncio
async def test_resolve_conflict_apply_suggested_uses_7rule_policy(monkeypatch):
    _admin_env(monkeypatch)
    repo = _override()
    raw = await _add_owner_key(repo)
    winner = await repo.add_memory(
        MemoryItem(workspace_id="ws_1", memory_type=MemoryType.project,
                   key="project.runtime", value="bun", content="bun", trust_score=0.9)
    )
    loser = await repo.add_memory(
        MemoryItem(workspace_id="ws_1", memory_type=MemoryType.project,
                   key="project.runtime", value="node", content="node", trust_score=0.4)
    )
    conflict = await repo.upsert_memory_conflict(
        MemoryConflictRecord(
            workspace_id="ws_1",
            subject_key="project.runtime",
            memory_ids=sorted([winner.memory_id, loser.memory_id]),
            status="open",
        )
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            f"/v1/admin/memory-conflicts/{conflict.conflict_id}/resolve",
            json={"action": "apply_suggested", "reason": "accept 7-rule suggestion"},
            headers={"X-API-Key": raw},
        )

    assert resp.status_code == 200
    assert resp.json()["status"] == "resolved_choose_winner"
    # the 7-rule policy supersedes the lower-trust value, keeps the winner active
    loser_after = await repo.get_memory(loser.memory_id)
    assert loser_after.status == MemoryStatus.superseded
    assert loser_after.superseded_by == winner.memory_id
    assert (await repo.get_memory(winner.memory_id)).status == MemoryStatus.active
    # audit records which rule was applied and the suggested winner
    audits = await repo.list_admin_action_audits(workspace_id="ws_1")
    applied = [a for a in audits if a.action == "resolve_conflict_apply_suggested"]
    assert applied and applied[0].metadata.get("applied_rule") == "legacy_trust_recency"
    assert applied[0].metadata.get("winner_memory_id") == winner.memory_id


@pytest.mark.asyncio
async def test_resolve_conflict_apply_suggested_rejects_uncertain_tie(monkeypatch):
    _admin_env(monkeypatch)
    repo = _override()
    raw = await _add_owner_key(repo)
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    a = MemoryItem(workspace_id="ws_1", memory_type=MemoryType.project,
                   key="project.runtime", value="bun", content="bun", trust_score=0.8)
    a.updated_at = ts
    b = MemoryItem(workspace_id="ws_1", memory_type=MemoryType.project,
                   key="project.runtime", value="node", content="node", trust_score=0.8)
    b.updated_at = ts
    a = await repo.add_memory(a)
    b = await repo.add_memory(b)
    conflict = await repo.upsert_memory_conflict(
        MemoryConflictRecord(
            workspace_id="ws_1",
            subject_key="project.runtime",
            memory_ids=sorted([a.memory_id, b.memory_id]),
            status="open",
        )
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            f"/v1/admin/memory-conflicts/{conflict.conflict_id}/resolve",
            json={"action": "apply_suggested", "reason": "try auto"},
            headers={"X-API-Key": raw},
        )

    # genuine tie -> uncertain -> no auto-winner; owner must choose_winner manually
    assert resp.status_code == 409
    assert (await repo.get_memory(a.memory_id)).status == MemoryStatus.active
    assert (await repo.get_memory(b.memory_id)).status == MemoryStatus.active
    assert (await repo.get_memory_conflict(conflict.conflict_id)).status == "open"


@pytest.mark.asyncio
async def test_resolve_conflict_mark_false_positive(monkeypatch):
    _admin_env(monkeypatch)
    repo = _override()
    raw = await _add_owner_key(repo)
    a = await _seed_memory(repo, value="bun")
    b = await _seed_memory(repo, value="node")
    conflict = await repo.upsert_memory_conflict(
        MemoryConflictRecord(
            workspace_id="ws_1",
            subject_key="project.runtime",
            memory_ids=sorted([a.memory_id, b.memory_id]),
            status="open",
        )
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            f"/v1/admin/memory-conflicts/{conflict.conflict_id}/resolve",
            json={"action": "mark_false_positive", "reason": "not really conflicting"},
            headers={"X-API-Key": raw},
        )
        open_list = await client.get(
            "/v1/admin/maintenance/runs?workspace_id=ws_1",
            headers={"X-API-Key": raw},
        )

    assert resp.status_code == 200
    assert resp.json()["status"] == "resolved_false_positive"
    # Both memories remain active (no supersede on false positive).
    assert (await repo.get_memory(a.memory_id)).status == MemoryStatus.active
    assert (await repo.get_memory(b.memory_id)).status == MemoryStatus.active
    # Resolved conflict no longer appears in the open list.
    open_conflicts = await repo.list_memory_conflicts(workspace_id="ws_1", status="open")
    assert open_conflicts == []
    assert open_list.status_code == 200


@pytest.mark.asyncio
async def test_resolve_conflict_choose_winner_requires_member_winner(monkeypatch):
    _admin_env(monkeypatch)
    repo = _override()
    raw = await _add_owner_key(repo)
    a = await _seed_memory(repo, value="bun")
    b = await _seed_memory(repo, value="node")
    conflict = await repo.upsert_memory_conflict(
        MemoryConflictRecord(
            workspace_id="ws_1",
            subject_key="project.runtime",
            memory_ids=sorted([a.memory_id, b.memory_id]),
            status="open",
        )
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        no_winner = await client.post(
            f"/v1/admin/memory-conflicts/{conflict.conflict_id}/resolve",
            json={"action": "choose_winner", "reason": "missing winner"},
            headers={"X-API-Key": raw},
        )
        non_member = await client.post(
            f"/v1/admin/memory-conflicts/{conflict.conflict_id}/resolve",
            json={"action": "choose_winner", "winner_memory_id": "mem_other", "reason": "bad winner"},
            headers={"X-API-Key": raw},
        )

    assert no_winner.status_code == 400
    assert non_member.status_code == 400


@pytest.mark.asyncio
async def test_resolve_conflict_choose_winner_supersedes_conflicted_loser(monkeypatch):
    _admin_env(monkeypatch)
    repo = _override()
    raw = await _add_owner_key(repo)
    winner = await _seed_memory(repo, value="bun")
    # A real conflict_scan conflict commonly contains conflicted-status members
    # (resolver tie). conflicted -> superseded must be a legal adjudication exit.
    loser = await _seed_memory(repo, value="node", status=MemoryStatus.conflicted)
    conflict = await repo.upsert_memory_conflict(
        MemoryConflictRecord(
            workspace_id="ws_1",
            subject_key="project.runtime",
            memory_ids=sorted([winner.memory_id, loser.memory_id]),
            status="open",
        )
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            f"/v1/admin/memory-conflicts/{conflict.conflict_id}/resolve",
            json={"action": "choose_winner", "winner_memory_id": winner.memory_id, "reason": "pick bun"},
            headers={"X-API-Key": raw},
        )

    assert resp.status_code == 200
    loser_after = await repo.get_memory(loser.memory_id)
    assert loser_after.status == MemoryStatus.superseded
    assert loser_after.superseded_by == winner.memory_id


@pytest.mark.asyncio
async def test_resolve_conflict_choose_winner_invalid_loser_makes_no_partial_change(monkeypatch):
    _admin_env(monkeypatch)
    repo = _override()
    raw = await _add_owner_key(repo)
    winner = await _seed_memory(repo, value="bun")
    active_loser = await _seed_memory(repo, value="node")
    # archived cannot transition to superseded; this must abort BEFORE the
    # active loser is persisted as superseded (no partial state change).
    archived_loser = await _seed_memory(repo, value="deno", status=MemoryStatus.archived)
    conflict = await repo.upsert_memory_conflict(
        MemoryConflictRecord(
            workspace_id="ws_1",
            subject_key="project.runtime",
            memory_ids=sorted([winner.memory_id, active_loser.memory_id, archived_loser.memory_id]),
            status="open",
        )
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            f"/v1/admin/memory-conflicts/{conflict.conflict_id}/resolve",
            json={"action": "choose_winner", "winner_memory_id": winner.memory_id, "reason": "pick bun"},
            headers={"X-API-Key": raw},
        )

    assert resp.status_code == 400
    # No loser should have been superseded; conflict stays open.
    assert (await repo.get_memory(active_loser.memory_id)).status == MemoryStatus.active
    assert (await repo.get_memory(archived_loser.memory_id)).status == MemoryStatus.archived
    assert (await repo.get_memory_conflict(conflict.conflict_id)).status == "open"


@pytest.mark.asyncio
async def test_resolve_already_resolved_conflict_returns_409(monkeypatch):
    _admin_env(monkeypatch)
    repo = _override()
    raw = await _add_owner_key(repo)
    a = await _seed_memory(repo, value="bun")
    b = await _seed_memory(repo, value="node")
    conflict = await repo.upsert_memory_conflict(
        MemoryConflictRecord(
            workspace_id="ws_1",
            subject_key="project.runtime",
            memory_ids=sorted([a.memory_id, b.memory_id]),
            status="open",
        )
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post(
            f"/v1/admin/memory-conflicts/{conflict.conflict_id}/resolve",
            json={"action": "mark_false_positive", "reason": "first"},
            headers={"X-API-Key": raw},
        )
        # Re-resolving (even with a different action) must be rejected so it
        # cannot supersede memories the false-positive decision kept.
        second = await client.post(
            f"/v1/admin/memory-conflicts/{conflict.conflict_id}/resolve",
            json={"action": "choose_winner", "winner_memory_id": a.memory_id, "reason": "flip"},
            headers={"X-API-Key": raw},
        )

    assert first.status_code == 200
    assert second.status_code == 409
    # The kept memories remain active; the flip was blocked.
    assert (await repo.get_memory(a.memory_id)).status == MemoryStatus.active
    assert (await repo.get_memory(b.memory_id)).status == MemoryStatus.active


@pytest.mark.asyncio
async def test_conflict_resolution_workspace_isolation(monkeypatch):
    _admin_env(monkeypatch)
    repo = _override()
    await _add_owner_key(repo, workspace_id="ws_1", raw="mt_ws1_owner_key")
    owner_ws2 = await _add_owner_key(repo, workspace_id="ws_2", raw="mt_ws2_owner_key")
    a = await _seed_memory(repo, value="bun")
    b = await _seed_memory(repo, value="node")
    conflict = await repo.upsert_memory_conflict(
        MemoryConflictRecord(
            workspace_id="ws_1",
            subject_key="project.runtime",
            memory_ids=sorted([a.memory_id, b.memory_id]),
            status="open",
        )
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        cross = await client.post(
            f"/v1/admin/memory-conflicts/{conflict.conflict_id}/resolve",
            json={"action": "mark_false_positive", "reason": "cross"},
            headers={"X-API-Key": owner_ws2},
        )

    assert cross.status_code == 403
