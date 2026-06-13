"""Pure-function tests for the dedup/merge + conflict resolver (mvp.md §2.3).

The resolver reconciles an incoming memory against same-identity active
memories: dedup/merge for equal values, trust/recency conflict resolution for a
single-valued key, and a conflicted-tie fallback. It is storage-agnostic and
deterministic, so these tests call it directly with plain MemoryItem objects.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.memory import resolver
from app.runtime.models import MemoryItem, MemoryScope, MemoryStatus, MemoryType


def _mem(value, *, key="project.runtime", trust=0.8, updated=None, source_event_id=None, mid=None):
    kwargs = dict(
        workspace_id="ws",
        memory_type=MemoryType.project,
        key=key,
        value=value,
        scope=MemoryScope.workspace,
        content=f"{key}={value}",
        trust_score=trust,
        source_event_id=source_event_id,
    )
    if mid is not None:
        kwargs["memory_id"] = mid
    m = MemoryItem(**kwargs)
    if updated is not None:
        m.updated_at = updated
    return m


def test_no_existing_actives_adds_incoming():
    incoming = _mem("bun")
    result = resolver.resolve(incoming, [])
    assert result.add is incoming
    assert result.updates == []


def test_same_value_dedup_merges_into_existing():
    existing = _mem("bun", trust=0.8, source_event_id="e1", mid="mem_old")
    incoming = _mem("bun", trust=0.9, source_event_id="e2", mid="mem_new")
    result = resolver.resolve(incoming, [existing])

    # incoming is folded into the existing representative -> no new row added
    assert result.add is None
    primary = next(u for u in result.updates if u.memory_id == "mem_old")
    assert primary.status == MemoryStatus.active
    # scores raised to the max and provenance unioned
    assert primary.trust_score == 0.9
    assert set(primary.source_event_ids or []) == {"e1", "e2"}


def test_same_value_extra_duplicates_are_superseded():
    older = _mem("bun", trust=0.7, source_event_id="e1", mid="mem_a")
    newer = _mem("bun", trust=0.9, source_event_id="e2", mid="mem_b")
    incoming = _mem("bun", trust=0.6, source_event_id="e3", mid="mem_c")
    result = resolver.resolve(incoming, [older, newer])

    assert result.add is None
    by_id = {u.memory_id: u for u in result.updates}
    # strongest (mem_b) survives; the other duplicate is superseded -> winner
    assert by_id["mem_b"].status == MemoryStatus.active
    assert by_id["mem_a"].status == MemoryStatus.superseded
    assert by_id["mem_a"].superseded_by == "mem_b"


def test_conflict_higher_trust_wins():
    existing = _mem("nodejs", trust=0.6, mid="mem_node")
    incoming = _mem("bun", trust=0.9, mid="mem_bun")
    result = resolver.resolve(incoming, [existing])

    # incoming is a new value -> it is added as a new row
    assert result.add is incoming
    node = next(u for u in result.updates if u.memory_id == "mem_node")
    assert node.status == MemoryStatus.superseded
    assert node.superseded_by == "mem_bun"


def test_conflict_recency_breaks_equal_trust():
    old_ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    new_ts = old_ts + timedelta(days=1)
    existing = _mem("nodejs", trust=0.8, updated=old_ts, mid="mem_node")
    incoming = _mem("bun", trust=0.8, updated=new_ts, mid="mem_bun")
    result = resolver.resolve(incoming, [existing])

    assert result.add is incoming
    node = next(u for u in result.updates if u.memory_id == "mem_node")
    assert node.status == MemoryStatus.superseded
    assert node.superseded_by == "mem_bun"


def test_conflict_true_tie_marks_both_conflicted():
    ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
    existing = _mem("nodejs", trust=0.8, updated=ts, mid="mem_node")
    incoming = _mem("bun", trust=0.8, updated=ts, mid="mem_bun")
    result = resolver.resolve(incoming, [existing])

    # genuine tie: incoming still added, but both flagged conflicted for the gate
    assert result.add is incoming
    assert incoming.status == MemoryStatus.conflicted
    node = next(u for u in result.updates if u.memory_id == "mem_node")
    assert node.status == MemoryStatus.conflicted


def test_different_value_multi_valued_key_coexists():
    # project.runtime.excluded is a set: distinct excluded values are not a conflict
    existing = _mem("nodejs", key="project.runtime.excluded", mid="mem_x")
    incoming = _mem("deno", key="project.runtime.excluded", mid="mem_y")
    result = resolver.resolve(incoming, [existing])

    assert result.add is incoming
    # the existing excluded value is left untouched (no supersede)
    assert all(u.memory_id != "mem_x" for u in result.updates)


def test_controlled_single_valued_key_conflict_supersedes_old_value():
    """A later value for a controlled single-valued key (e.g. project.language)
    must supersede the old one even without an explicit supersede flag."""
    existing = _mem("python", key="project.language", trust=0.6, mid="mem_py")
    incoming = _mem("go", key="project.language", trust=0.9, mid="mem_go")
    result = resolver.resolve(incoming, [existing])

    assert result.add is incoming
    old = next(u for u in result.updates if u.memory_id == "mem_py")
    assert old.status == MemoryStatus.superseded
    assert old.superseded_by == "mem_go"


def test_alias_key_conflict_uses_ontology_single_valued_semantics():
    existing = _mem("npm", key="project.pkg_manager", trust=0.6, mid="mem_npm")
    incoming = _mem("pnpm", key="project.package_manager", trust=0.9, mid="mem_pnpm")

    result = resolver.resolve(incoming, [existing])

    assert result.add is incoming
    old = next(u for u in result.updates if u.memory_id == "mem_npm")
    assert old.status == MemoryStatus.superseded
    assert old.superseded_by == "mem_pnpm"


def test_same_value_alias_dedup_promotes_survivor_to_canonical_key():
    existing = _mem("pnpm", key="project.pkg_manager", trust=0.6, mid="mem_alias")
    incoming = _mem("pnpm", key="project.package_manager", trust=0.9, mid="mem_canonical")

    result = resolver.resolve(incoming, [existing])

    assert result.add is None
    survivor = next(u for u in result.updates if u.memory_id == "mem_alias")
    assert survivor.status == MemoryStatus.active
    assert survivor.key == "project.package_manager"
    assert survivor.summary == "project.package_manager=pnpm"


def test_alias_conflict_existing_winner_is_promoted_to_canonical_key():
    existing = _mem("npm", key="project.pkg_manager", trust=0.9, mid="mem_alias")
    incoming = _mem("pnpm", key="project.package_manager", trust=0.6, mid="mem_canonical")

    result = resolver.resolve(incoming, [existing])

    assert result.add is incoming
    survivor = next(u for u in result.updates if u.memory_id == "mem_alias")
    assert survivor.status == MemoryStatus.active
    assert survivor.key == "project.package_manager"
    assert survivor.summary == "project.package_manager=npm"
    assert incoming.status == MemoryStatus.superseded
    assert incoming.superseded_by == "mem_alias"


def test_endpoint_current_is_single_valued_but_deprecated_is_multi_valued():
    existing = _mem("/v1/old", key="endpoint.current", trust=0.6, mid="mem_old")
    incoming = _mem("/v1/new", key="endpoint.current", trust=0.9, mid="mem_new")
    result = resolver.resolve(incoming, [existing])
    assert next(u for u in result.updates if u.memory_id == "mem_old").status == MemoryStatus.superseded

    deprecated = _mem("/v1/old", key="endpoint.deprecated", mid="mem_deprecated")
    incoming_deprecated = _mem("/v0/older", key="endpoint.deprecated", mid="mem_deprecated_2")
    result = resolver.resolve(incoming_deprecated, [deprecated])
    assert result.add is incoming_deprecated
    assert result.updates == []
