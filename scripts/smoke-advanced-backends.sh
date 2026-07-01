#!/usr/bin/env bash
# Opt-in end-to-end smoke for the ROADMAP §4 external advanced-retrieval backends
# (Elasticsearch BM25 + Neo4j provenance graph). Requires the full compose tier
# up (docker-compose.full.yml) and the extras installed (uv sync --extra search
# --extra graph). Skips cleanly per backend when the package is missing or the
# endpoint is unreachable, so it is safe to run anywhere. Fails only on a real
# functional defect. NOT part of default CI / benchmark / reproduce.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "==> Advanced-backend smoke (Elasticsearch BM25 + Neo4j graph)"
echo "    ES_URL=${MEMTRACE_ES_URL:-http://localhost:9200}  NEO4J_URL=${MEMTRACE_NEO4J_URL:-bolt://localhost:7687}"

uv run python - <<'PY'
import asyncio
import os
import sys

from app.retrieval.graph import Neo4jProvenanceGraph, ProvenanceEdge, SUPERSEDES
from app.retrieval.hybrid import ElasticsearchBM25Backend
from app.runtime.models import MemoryItem, MemoryType

ES_URL = os.environ.get("MEMTRACE_ES_URL", "http://localhost:9200")
NEO4J_URL = os.environ.get("MEMTRACE_NEO4J_URL", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("MEMTRACE_NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("MEMTRACE_NEO4J_PASSWORD", "memtrace-neo4j")


def _mem(mid: str, content: str) -> MemoryItem:
    return MemoryItem(memory_id=mid, workspace_id="smoke_ws", memory_type=MemoryType.episodic,
                      content=content, summary=content[:60])


async def check_elasticsearch():
    try:
        from elasticsearch import Elasticsearch  # type: ignore
    except ModuleNotFoundError:
        return "skip", "elasticsearch package not installed (uv sync --extra search)"
    try:
        client = Elasticsearch(ES_URL, request_timeout=5)
        if not client.ping():
            return "skip", f"Elasticsearch not reachable at {ES_URL}"
    except Exception as exc:  # noqa: BLE001
        return "skip", f"Elasticsearch not reachable at {ES_URL} ({type(exc).__name__})"
    backend = ElasticsearchBM25Backend(url=ES_URL, index_prefix="memtrace_smoke", client=client)
    if not backend.available:
        return "fail", "backend reports available=False despite a live client"
    memories = [
        _mem("m_region", "the deploy region is us-west"),
        _mem("m_cache", "the cache layer is redis"),
        _mem("m_db", "the primary database is postgres"),
    ]
    scores = await backend.bm25_scores(query="which cache layer do we use",
                                       memories=memories, workspace_id="smoke_ws", top_k=5)
    if not scores:
        return "fail", "ES returned no BM25 scores for a matching query"
    top = max(scores, key=scores.get)
    if top != "m_cache":
        return "warn", f"ES BM25 ranked {top} first (expected m_cache); scores={scores}"
    return "pass", f"ES BM25 ranked the cache memory first (scores={scores})"


async def check_neo4j():
    try:
        from neo4j import GraphDatabase  # type: ignore
    except ModuleNotFoundError:
        return "skip", "neo4j package not installed (uv sync --extra graph)"
    try:
        driver = GraphDatabase.driver(NEO4J_URL, auth=(NEO4J_USER, NEO4J_PASSWORD))
        driver.verify_connectivity()
    except Exception as exc:  # noqa: BLE001
        return "skip", f"Neo4j not reachable at {NEO4J_URL} ({type(exc).__name__})"
    backend = Neo4jProvenanceGraph(url=NEO4J_URL, user=NEO4J_USER, password=NEO4J_PASSWORD, driver=driver)
    if not backend.available:
        return "fail", "backend reports available=False despite a live driver"
    # a -> b -> c chain; from seed 'a', both b (1 hop) and c (2 hops) are neighbors
    edges = [ProvenanceEdge("smoke_a", "smoke_b", SUPERSEDES),
             ProvenanceEdge("smoke_b", "smoke_c", SUPERSEDES)]
    related = await backend.related(["smoke_a"], edges, max_hops=2)
    if "smoke_b" not in related or "smoke_c" not in related:
        return "fail", f"Neo4j graph expansion missing expected neighbors: {related}"
    if not (related["smoke_b"] > related["smoke_c"]):
        return "warn", f"Neo4j relatedness not distance-weighted as expected: {related}"
    return "pass", f"Neo4j returned distance-weighted neighbors ({related})"


async def check_pipeline_through_controller():
    """Prove the FULL retrieval pipeline routes through Elasticsearch when the flag
    is set — not just the isolated backend class. Seeds memories in-process, builds
    the real RetrievalController with the backend enabled, and confirms a BM25 score
    reaches the candidates."""
    try:
        from elasticsearch import Elasticsearch  # type: ignore
    except ModuleNotFoundError:
        return "skip", "elasticsearch package not installed"
    try:
        if not Elasticsearch(ES_URL, request_timeout=5).ping():
            return "skip", f"Elasticsearch not reachable at {ES_URL}"
    except Exception as exc:  # noqa: BLE001
        return "skip", f"Elasticsearch not reachable ({type(exc).__name__})"
    os.environ["MEMTRACE_RETRIEVAL_HYBRID_BACKEND"] = "elasticsearch"
    os.environ["MEMTRACE_ES_URL"] = ES_URL
    os.environ["MEMTRACE_RETRIEVAL_USE_VECTOR"] = "false"
    from app.config import get_settings
    get_settings.cache_clear()
    from app.retrieval.controller import RetrievalController
    from app.runtime.repository import InMemoryRepository
    repo = InMemoryRepository()
    for mem in (_mem("m_region", "the deploy region is us-west"),
                _mem("m_cache", "the cache layer is redis"),
                _mem("m_db", "the primary database is postgres")):
        await repo.add_memory(mem)
    controller = RetrievalController(repo)
    backend = getattr(controller, "_hybrid_backend", None)
    if backend is None or not backend.available:
        return "fail", "controller did not construct an available ES hybrid backend from the flag"
    cands = await controller._select_candidates(  # noqa: SLF001
        workspace_id="smoke_ws", run_id="r", query="which cache layer do we use", top_k=5)
    max_bm25 = max((c.bm25_score for c in cands), default=0.0)
    name = getattr(controller, "_hybrid_backend_name", None)
    if max_bm25 <= 0.0:
        return "fail", f"controller retrieval produced no BM25 score (backend={name})"
    return "pass", f"controller routed retrieval through ES (backend={name}, max bm25={max_bm25:.4f})"


async def main() -> int:
    results = {
        "elasticsearch": await check_elasticsearch(),
        "neo4j": await check_neo4j(),
        "pipeline(controller->ES)": await check_pipeline_through_controller(),
    }
    icon = {"pass": "✅", "skip": "⏭️ ", "warn": "⚠️ ", "fail": "❌"}
    for name, (status, detail) in results.items():
        print(f"  {icon[status]} {name}: {detail}")
    if any(s == "fail" for s, _ in results.values()):
        print("advanced-backend smoke FAILED")
        return 1
    if all(s == "skip" for s, _ in results.values()):
        print("advanced-backend smoke skipped (no backend reachable / extras not installed)")
        return 0
    print("advanced-backend smoke passed")
    return 0


sys.exit(asyncio.run(main()))
PY
