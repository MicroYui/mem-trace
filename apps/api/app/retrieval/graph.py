"""Optional provenance-graph neighbor expansion (ROADMAP §4, default-off).

A memory's provenance forms a graph: SUPERSEDES edges (``superseded_by`` lineage)
and CONFLICTS_WITH edges (open ``MemoryConflictRecord.memory_ids`` pairs). Two
memories linked through that graph are *related* even when neither matches the
query lexically — surfacing such a neighbor (e.g. the active memory that
conflicts with a hit) is the value of graph expansion.

This module provides a deterministic in-process graph and an optional Neo4j
store behind one protocol:

- ``InMemoryProvenanceGraph`` — deterministic BFS neighbor expansion over the
  edges the caller assembles from the repository. No network, reproducible.
- ``Neo4jProvenanceGraph`` — lazy-imports ``neo4j``, MERGEs the edges and runs a
  variable-length path query. Degrades to ``available = False`` / ``{}`` when the
  dependency or endpoint is absent or any query fails. A driver may be injected
  for tests.

Default-off: ``MEMTRACE_RETRIEVAL_GRAPH_BACKEND=off`` keeps candidate scoring
byte-identical. Graph-surfaced neighbors are still subject to the lifecycle
filter at the call site, so retired (superseded/archived/...) memories never leak.
"""
from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from typing import Iterable, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

SUPERSEDES = "SUPERSEDES"
CONFLICTS_WITH = "CONFLICTS_WITH"


@dataclass(frozen=True, slots=True)
class ProvenanceEdge:
    """An undirected-for-relatedness provenance link between two memories."""

    src: str
    dst: str
    rel_type: str


def provenance_edges(memories, conflicts) -> list[ProvenanceEdge]:
    """Assemble SUPERSEDES + CONFLICTS_WITH edges from repository provenance.

    ``memories`` supplies ``superseded_by`` lineage; ``conflicts`` supplies open
    conflict groups (all pairs in ``memory_ids`` conflict). Deterministic order.
    """
    edges: list[ProvenanceEdge] = []
    for mem in memories:
        target = getattr(mem, "superseded_by", None)
        if target:
            edges.append(ProvenanceEdge(mem.memory_id, target, SUPERSEDES))
    for conflict in conflicts:
        ids = list(getattr(conflict, "memory_ids", []) or [])
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                edges.append(ProvenanceEdge(ids[i], ids[j], CONFLICTS_WITH))
    return edges


def _adjacency(edges: Iterable[ProvenanceEdge]) -> dict[str, set[str]]:
    adj: dict[str, set[str]] = {}
    for edge in edges:
        if not edge.src or not edge.dst or edge.src == edge.dst:
            continue
        adj.setdefault(edge.src, set()).add(edge.dst)
        adj.setdefault(edge.dst, set()).add(edge.src)  # relatedness is symmetric
    return adj


def _bfs_relatedness(
    adj: dict[str, set[str]], seed_ids: Iterable[str], *, max_hops: int
) -> dict[str, float]:
    """Min-distance BFS from the seeds; relatedness = ``1 / distance`` in (0, 1]."""
    seeds = {sid for sid in seed_ids if sid}
    dist: dict[str, int] = {sid: 0 for sid in seeds}
    queue: deque[str] = deque(seeds)
    while queue:
        node = queue.popleft()
        d = dist[node]
        if d >= max_hops:
            continue
        for neigh in sorted(adj.get(node, ())):  # sorted => deterministic
            if neigh not in dist:
                dist[neigh] = d + 1
                queue.append(neigh)
    return {
        node: round(1.0 / d, 6)
        for node, d in dist.items()
        if node not in seeds and d > 0
    }


@runtime_checkable
class GraphBackend(Protocol):
    """Expands a seed set to provenance-related memories with a relatedness score."""

    name: str

    @property
    def available(self) -> bool:
        ...

    async def related(
        self, seed_ids: list[str], edges: list[ProvenanceEdge], *, max_hops: int
    ) -> dict[str, float]:
        ...


class InMemoryProvenanceGraph:
    """Deterministic in-process BFS neighbor expansion. No network."""

    name = "inmemory_graph"

    @property
    def available(self) -> bool:
        return True

    async def related(
        self, seed_ids: list[str], edges: list[ProvenanceEdge], *, max_hops: int
    ) -> dict[str, float]:
        if not seed_ids or not edges or max_hops < 1:
            return {}
        return _bfs_relatedness(_adjacency(edges), seed_ids, max_hops=max_hops)


class Neo4jProvenanceGraph:
    """Optional Neo4j provenance store (lazy import, degrade-safe).

    MERGEs the supplied edges then runs a variable-length shortest-path query.
    Any missing dependency / endpoint / query error degrades to ``{}``. A driver
    may be injected for tests.
    """

    name = "neo4j_graph"

    def __init__(
        self,
        *,
        url: str,
        user: str = "neo4j",
        password: str = "",
        database: str = "neo4j",
        driver: object | None = None,
    ) -> None:
        self._database = database
        self._driver = driver
        self._available = driver is not None
        if driver is None and url:
            try:  # lazy: the dependency is an optional extra
                from neo4j import GraphDatabase  # type: ignore
            except ModuleNotFoundError:
                logger.warning(
                    "MEMTRACE_RETRIEVAL_GRAPH_BACKEND=neo4j requires the 'graph' extra "
                    "(pip install '.[graph]'); graph expansion disabled."
                )
                self._available = False
            else:
                try:
                    self._driver = GraphDatabase.driver(url, auth=(user, password))
                    self._available = True
                except Exception:  # noqa: BLE001 - construction must never break startup
                    logger.warning("Failed to construct Neo4j driver; graph expansion disabled.")
                    self._available = False

    @property
    def available(self) -> bool:
        return self._available

    async def related(
        self, seed_ids: list[str], edges: list[ProvenanceEdge], *, max_hops: int
    ) -> dict[str, float]:
        if not self._available or self._driver is None or not seed_ids or max_hops < 1:
            return {}
        try:
            with self._driver.session(database=self._database) as session:  # type: ignore[attr-defined]
                for edge in edges:
                    session.run(
                        "MERGE (a:Memory {id:$src}) MERGE (b:Memory {id:$dst}) "
                        "MERGE (a)-[r:%s]-(b)" % ("REL",),
                        src=edge.src,
                        dst=edge.dst,
                    )
                result = session.run(
                    "MATCH (s:Memory) WHERE s.id IN $seeds "
                    "MATCH p=(s)-[*1..%d]-(n:Memory) WHERE NOT n.id IN $seeds "
                    "RETURN n.id AS id, min(length(p)) AS dist" % int(max_hops),
                    seeds=list(seed_ids),
                )
                out: dict[str, float] = {}
                for record in result:
                    node_id = record["id"]
                    dist = record["dist"]
                    if node_id and dist:
                        out[node_id] = round(1.0 / float(dist), 6)
                return out
        except Exception:  # noqa: BLE001 - retrieval must degrade, never raise
            logger.warning("Neo4j graph expansion failed; degrading to no expansion.")
            return {}


def build_graph_backend(settings) -> GraphBackend | None:
    """Construct the configured graph backend, or ``None`` when default-off."""
    mode = (getattr(settings, "retrieval_graph_backend", "off") or "off").lower()
    if mode == "off":
        return None
    if mode == "inmemory":
        return InMemoryProvenanceGraph()
    if mode == "neo4j":
        return Neo4jProvenanceGraph(
            url=getattr(settings, "neo4j_url", "") or "",
            user=getattr(settings, "neo4j_user", "neo4j") or "neo4j",
            password=getattr(settings, "neo4j_password", "") or "",
            database=getattr(settings, "neo4j_database", "neo4j") or "neo4j",
        )
    return None


__all__ = [
    "SUPERSEDES",
    "CONFLICTS_WITH",
    "ProvenanceEdge",
    "provenance_edges",
    "GraphBackend",
    "InMemoryProvenanceGraph",
    "Neo4jProvenanceGraph",
    "build_graph_backend",
]
