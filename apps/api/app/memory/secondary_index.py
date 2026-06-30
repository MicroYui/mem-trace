"""Multi-store eventual-consistency reconciler (ROADMAP §4, default-safe).

The optional Elasticsearch hybrid index and Neo4j provenance graph are secondary
stores: PostgreSQL stays the source of truth, and the secondary stores are
reconciled toward it in the background. This module tracks per-memory sync state
and re-syncs anything pending/failed/stale, with failures left for the next run
to retry.

Sync state lives in the existing JSONB ``lifecycle_metadata`` (``index_status`` /
``graph_status`` / ``last_indexed_at`` / ``last_graph_synced_at``) so no schema
migration is required and the default path (no secondary store configured) leaves
every memory ``not_applicable``. Everything here is deterministic given the
backends; the backends themselves degrade cleanly when their dependency/endpoint
is absent.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.runtime.models import MemoryStatus
from app.runtime.repository import Repository

# Sync-state values stored in lifecycle_metadata.
NOT_APPLICABLE = "not_applicable"
PENDING = "pending"
INDEXED = "indexed"
FAILED = "failed"
STALE = "stale"

_NEEDS_SYNC = {PENDING, FAILED, STALE}
_RETRIEVABLE = {
    MemoryStatus.active,
    MemoryStatus.pinned,
    MemoryStatus.conflicted,
    MemoryStatus.quarantined,
}


def _index_state(metadata: dict[str, Any], key: str) -> str:
    value = metadata.get(key)
    return value if isinstance(value, str) else PENDING


async def reconcile_secondary_indexes(
    repo: Repository,
    *,
    workspace_id: str,
    hybrid_backend: Any | None = None,
    graph_backend: Any | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Reconcile retrievable memories into the configured secondary stores.

    For each retrievable memory whose ``index_status`` / ``graph_status`` is
    pending/failed/stale, push it to the available backend and mark it indexed
    (with ``last_indexed_at`` / ``last_graph_synced_at``); on backend failure mark
    it failed so the next run retries. With no backend configured, the status is
    set to ``not_applicable`` once and skipped thereafter.
    """
    now = now or datetime.now(timezone.utc)
    hybrid_available = hybrid_backend is not None and getattr(hybrid_backend, "available", False)
    graph_available = graph_backend is not None and getattr(graph_backend, "available", False)
    indexed = graph_synced = failed = skipped = 0

    memories = [m for m in await repo.list_memories(workspace_id=workspace_id) if m.status in _RETRIEVABLE]
    for memory in memories:
        metadata = dict(memory.lifecycle_metadata or {})
        changed = False

        # --- hybrid (BM25) index ---
        if hybrid_available:
            if _index_state(metadata, "index_status") in _NEEDS_SYNC:
                try:
                    await hybrid_backend.bm25_scores(
                        query=memory.content, memories=[memory],
                        workspace_id=workspace_id, top_k=1,
                    )
                    metadata["index_status"] = INDEXED
                    metadata["last_indexed_at"] = now.isoformat()
                    indexed += 1
                except Exception:  # noqa: BLE001 - failures retry next run
                    metadata["index_status"] = FAILED
                    failed += 1
                changed = True
        elif metadata.get("index_status") not in (None, NOT_APPLICABLE):
            metadata["index_status"] = NOT_APPLICABLE
            changed = True
        elif "index_status" not in metadata:
            metadata["index_status"] = NOT_APPLICABLE
            changed = True

        # --- graph store ---
        if graph_available:
            if _index_state(metadata, "graph_status") in _NEEDS_SYNC:
                try:
                    edges = []
                    if memory.superseded_by:
                        from app.retrieval.graph import SUPERSEDES, ProvenanceEdge

                        edges.append(ProvenanceEdge(memory.memory_id, memory.superseded_by, SUPERSEDES))
                    await graph_backend.related([memory.memory_id], edges, max_hops=1)
                    metadata["graph_status"] = INDEXED
                    metadata["last_graph_synced_at"] = now.isoformat()
                    graph_synced += 1
                except Exception:  # noqa: BLE001 - failures retry next run
                    metadata["graph_status"] = FAILED
                    failed += 1
                changed = True
        elif metadata.get("graph_status") not in (None, NOT_APPLICABLE):
            metadata["graph_status"] = NOT_APPLICABLE
            changed = True
        elif "graph_status" not in metadata:
            metadata["graph_status"] = NOT_APPLICABLE
            changed = True

        if changed:
            await repo.update_memory(memory.model_copy(update={"lifecycle_metadata": metadata}, deep=True))
        else:
            skipped += 1

    return {
        "workspace_id": workspace_id,
        "indexed_count": indexed,
        "graph_synced_count": graph_synced,
        "failed_count": failed,
        "skipped_count": skipped,
        "hybrid_available": hybrid_available,
        "graph_available": graph_available,
    }


def mark_memory_pending_secondary_index(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Stamp a (new/updated) memory as needing secondary-index sync.

    Called from the write path when a secondary store is configured so the next
    reconcile run picks it up. Returns a new metadata dict.
    """
    out = dict(metadata or {})
    out["index_status"] = PENDING
    out["graph_status"] = PENDING
    return out


__all__ = [
    "NOT_APPLICABLE",
    "PENDING",
    "INDEXED",
    "FAILED",
    "STALE",
    "reconcile_secondary_indexes",
    "mark_memory_pending_secondary_index",
]
