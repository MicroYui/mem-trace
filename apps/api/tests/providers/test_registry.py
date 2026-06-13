from __future__ import annotations

import pytest

from app.providers.base import ProviderCapabilities, ProviderKind
from app.providers.registry import ProviderRegistry


class _Provider:
    pass


def test_capability_snapshot_is_stable_and_non_secret():
    metadata = {
        "dim": 256,
        "nested": {"dim": 256},
        "api_key": "must-not-render",
        "x_api_key_header": "must-not-render",
        "note": "sk-must-not-render",
        "description": "password=must-not-render",
        "diagnostic": "ghp_secretTOKEN123",
        "safe_note": "deterministic hash embedding",
        "safe_nested": {"label": "token=must-not-render", "dim": 256},
    }
    caps = ProviderCapabilities(
        provider_id="embedding.deterministic_hash.v1",
        kind=ProviderKind.embedding,
        deterministic=True,
        requires_network=False,
        endpoint_types=(),
        model=None,
        configured=True,
        fallback_provider_id=None,
        metadata=metadata,
    )
    metadata["dim"] = 999
    metadata["nested"]["dim"] = 999

    snap = caps.snapshot()

    assert snap == {
        "provider_id": "embedding.deterministic_hash.v1",
        "kind": "embedding",
        "deterministic": True,
        "requires_network": False,
        "endpoint_types": [],
        "model": None,
        "configured": True,
        "fallback_provider_id": None,
        "metadata": {
            "dim": 256,
            "nested": {"dim": 256},
            "safe_nested": {"dim": 256},
            "safe_note": "deterministic hash embedding",
        },
    }


def test_registry_registers_and_snapshots_by_provider_kind():
    registry = ProviderRegistry()
    provider = _Provider()
    caps = ProviderCapabilities(
        provider_id="extraction.fake_writer.v1",
        kind=ProviderKind.extraction,
        deterministic=True,
        requires_network=False,
    )

    registry.register(ProviderKind.extraction, provider, caps)

    assert registry.get(ProviderKind.extraction) is provider
    assert registry.capabilities(ProviderKind.extraction) is caps
    assert registry.snapshot() == {"extraction": caps.snapshot()}


def test_registry_rejects_kind_mismatch():
    registry = ProviderRegistry()
    caps = ProviderCapabilities(
        provider_id="summary.rule.v1",
        kind=ProviderKind.summarizer,
        deterministic=True,
        requires_network=False,
    )

    with pytest.raises(ValueError, match="provider capability kind mismatch"):
        registry.register(ProviderKind.embedding, _Provider(), caps)


def test_capability_snapshot_redacts_secret_like_top_level_strings():
    caps = ProviderCapabilities(
        provider_id="embedding.openai_compatible.v1",
        kind=ProviderKind.embedding,
        deterministic=False,
        requires_network=True,
        endpoint_types=("openai_embeddings", "bearer secret endpoint"),
        model="sk-model-secret",
        fallback_provider_id="fallback-secret-token",
        metadata={"dim": 256},
    )

    snap = caps.snapshot()

    assert snap["model"] is None
    assert snap["fallback_provider_id"] is None
    assert snap["endpoint_types"] == ["openai_embeddings"]
    assert "sk-model-secret" not in str(snap)
    assert "fallback-secret-token" not in str(snap)
