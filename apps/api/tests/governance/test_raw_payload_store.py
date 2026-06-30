"""Encrypted raw-payload store tests (ROADMAP §3.4 / ADR-017, default-off)."""
from __future__ import annotations

import importlib.util

import pytest

from app.config import Settings
from app.governance.raw_payload_store import (
    FernetRawPayloadStore,
    build_raw_payload_store,
)

_HAS_CRYPTO = importlib.util.find_spec("cryptography") is not None


def test_build_returns_none_when_retention_disabled():
    assert build_raw_payload_store(Settings()) is None


def test_build_returns_none_without_encrypted_scheme():
    settings = Settings(
        raw_payload_retention_enabled=True,
        governance_enabled=True,
        raw_payload_store_url="s3://bucket",
    )
    assert build_raw_payload_store(settings) is None


def test_store_unavailable_without_key():
    store = FernetRawPayloadStore(key="")
    assert store.available is False
    assert store.get("ref") is None


@pytest.mark.skipif(not _HAS_CRYPTO, reason="cryptography not installed")
def test_encrypted_round_trip_when_crypto_available():
    from cryptography.fernet import Fernet

    store = FernetRawPayloadStore(key=Fernet.generate_key().decode())
    assert store.available is True
    store.put("ref-1", "super secret payload")
    assert store.get("ref-1") == "super secret payload"
    assert store.get("missing") is None


@pytest.mark.skipif(_HAS_CRYPTO, reason="exercises the no-dependency degrade path")
def test_store_degrades_without_cryptography_dependency():
    store = FernetRawPayloadStore(key="anything")
    assert store.available is False
