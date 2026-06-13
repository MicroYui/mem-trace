"""Stable retrieval policy snapshots for replay/drift classification."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import Any

from app.retrieval.gate import GateConfig
from app.runtime.models import RetrievalRequest, RetrievalStrategy


POLICY_VERSION = "retrieval-policy-v1"
LIFECYCLE_FILTER_VERSION = "retrievable-statuses-v1"
TOKEN_ESTIMATOR_VERSION = "regex-stopword-cjk-v1"


def build_policy_snapshot(
    request: RetrievalRequest,
    *,
    gate_config: GateConfig,
    effective_token_budget: int,
    vector_enabled: bool,
    vector_weight: float,
    compaction_notice_reserve_tokens: int,
) -> dict[str, Any]:
    """Build a JSON-compatible, non-secret retrieval policy snapshot."""
    vector_active = bool(vector_enabled)
    return {
        "policy_version": POLICY_VERSION,
        "strategy": request.strategy.value,
        "top_k": request.top_k,
        "token_budget": effective_token_budget,
        "gate_config": asdict(gate_config),
        "retrieval": {
            "vector_enabled": vector_active,
            "vector_weight": float(vector_weight) if vector_active else 0.0,
            "include_all": request.strategy == RetrievalStrategy.long_context,
            "lifecycle_filter_version": LIFECYCLE_FILTER_VERSION,
        },
        "packer": {
            "token_estimator_version": TOKEN_ESTIMATOR_VERSION,
            "compaction_notice_reserve_tokens": compaction_notice_reserve_tokens,
            "negative_evidence_max_blocks": 3,
        },
        "providers": {
            "embedding": "deterministic_hash_default",
            "summarizer": "persisted_or_config_gated",
        },
    }


def policy_hash(snapshot: dict[str, Any]) -> str:
    payload = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()
