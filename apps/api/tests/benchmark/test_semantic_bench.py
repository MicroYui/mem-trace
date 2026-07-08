"""Structural tests for the semantic bench (no model download required)."""
from __future__ import annotations

from app.benchmark.semantic_bench import FACTS, QUERIES, _rank_targets, _recall
from app.retrieval.similarity import stable_embedding


def test_every_query_targets_a_known_fact():
    fact_ids = {fid for fid, _ in FACTS}
    assert {qid for qid, _ in QUERIES} <= fact_ids
    assert len(QUERIES) >= 8


def test_recall_metric_math():
    r = _recall([1, 1, 2, 4])  # 2 at rank1, 3 within top3
    assert r["recall@1"] == 0.5
    assert r["recall@3"] == 0.75
    assert r["mean_rank"] == 2.0


def test_hash_ranking_runs_without_a_model():
    # exercised with the deterministic hash embedding (no torch/sentence-transformers)
    ranks = _rank_targets(lambda t: stable_embedding(t, 256), lambda t: stable_embedding(t, 256))
    assert len(ranks) == len(QUERIES)
    assert all(1 <= r <= len(FACTS) for r in ranks)
