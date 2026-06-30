"""Stable retrieval policy snapshots for replay/drift classification."""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import asdict
from typing import Any

from app.providers.base import ProviderKind
from app.retrieval.gate import GateConfig
from app.runtime.models import RetrievalRequest, RetrievalStrategy


POLICY_VERSION = "retrieval-policy-v2"
LIFECYCLE_FILTER_VERSION = "retrievable-statuses-v1"
TOKEN_ESTIMATOR_VERSION = "regex-stopword-cjk-v1"
_RETRIEVAL_PROVIDER_KINDS = (ProviderKind.embedding.value, ProviderKind.summarizer.value)


def build_policy_snapshot(
    request: RetrievalRequest,
    *,
    gate_config: GateConfig,
    effective_token_budget: int,
    vector_enabled: bool,
    vector_weight: float,
    compaction_notice_reserve_tokens: int,
    provider_snapshot: dict[str, Any] | None = None,
    reflection_signal_source: str = "fallback_lite",
    retention_policy_version: str | None = None,
    scheduler_signal_memory_ids: list[str] | None = None,
    fallback_lite_memory_ids: list[str] | None = None,
    retention_policy_versions: list[str] | None = None,
    fusion: str = "linear",
    rrf_k: int | None = None,
    query_planner: str = "off",
    query_planner_weight: float | None = None,
    multi_hop_hops: int = 0,
    hybrid_backend: str | None = None,
    hybrid_weight: float | None = None,
) -> dict[str, Any]:
    """Build a JSON-compatible, non-secret retrieval policy snapshot."""
    vector_active = bool(vector_enabled)
    retrieval: dict[str, Any] = {
        "vector_enabled": vector_active,
        "vector_weight": float(vector_weight) if vector_active else 0.0,
        "include_all": request.strategy == RetrievalStrategy.long_context,
        "lifecycle_filter_version": LIFECYCLE_FILTER_VERSION,
        "reflection_signal_source": reflection_signal_source,
        "retention_policy_version": retention_policy_version,
        "scheduler_signal_memory_ids": sorted(scheduler_signal_memory_ids or []),
        "fallback_lite_memory_ids": sorted(fallback_lite_memory_ids or []),
        "retention_policy_versions": sorted(retention_policy_versions or ([] if retention_policy_version is None else [retention_policy_version])),
    }
    # Only emit fusion fields for the non-default mode so existing linear-mode
    # policy hashes and replay snapshots stay byte-stable.
    if fusion and fusion != "linear":
        retrieval["fusion"] = fusion
        retrieval["rrf_k"] = rrf_k
    # Same byte-stability rule for the default-off query planner (ROADMAP §4):
    # omit the field entirely while disabled so existing hashes are unchanged.
    if query_planner and query_planner != "off":
        retrieval["query_planner"] = query_planner
        retrieval["query_planner_weight"] = query_planner_weight
    # Same byte-stability rule for default-off multi-hop iterative retrieval.
    if multi_hop_hops and multi_hop_hops > 0:
        retrieval["multi_hop_hops"] = multi_hop_hops
    # Same byte-stability rule for the default-off hybrid BM25 backend.
    if hybrid_backend and hybrid_backend != "off":
        retrieval["hybrid_backend"] = hybrid_backend
        retrieval["hybrid_weight"] = hybrid_weight
    return {
        "policy_version": POLICY_VERSION,
        "strategy": request.strategy.value,
        "top_k": request.top_k,
        "token_budget": effective_token_budget,
        "gate_config": asdict(gate_config),
        "retrieval": retrieval,
        "packer": {
            "token_estimator_version": TOKEN_ESTIMATOR_VERSION,
            "compaction_notice_reserve_tokens": compaction_notice_reserve_tokens,
            "negative_evidence_max_blocks": 3,
        },
        "providers": _retrieval_provider_snapshot(provider_snapshot),
    }


def _retrieval_provider_snapshot(provider_snapshot: dict[str, Any] | None) -> dict[str, Any]:
    providers = _default_retrieval_provider_snapshot()
    if provider_snapshot is None:
        return providers
    for kind in _RETRIEVAL_PROVIDER_KINDS:
        if kind in provider_snapshot:
            providers[kind] = copy.deepcopy(provider_snapshot[kind])
    return providers


def _default_retrieval_provider_snapshot() -> dict[str, Any]:
    return {
        "embedding": {
            "provider_id": "embedding.deterministic_hash.v1",
            "kind": "embedding",
            "deterministic": True,
            "requires_network": False,
            "endpoint_types": [],
            "model": None,
            "configured": True,
            "fallback_provider_id": None,
            "metadata": {"algorithm": "blake2b_hash_bow", "dim": 256},
        },
        "summarizer": {
            "provider_id": "summarizer.rule.v1",
            "kind": "summarizer",
            "deterministic": True,
            "requires_network": False,
            "endpoint_types": [],
            "model": None,
            "configured": True,
            "fallback_provider_id": None,
            "metadata": {"algorithm": "structured_must_retain_facts"},
        },
    }


def policy_hash(snapshot: dict[str, Any]) -> str:
    payload = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()
