"""Structural tests for the Qwen3 embedding server (no model download/load)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.embedding_server import EmbeddingRequest, create_app


def test_health_and_empty_input_validation(monkeypatch):
    monkeypatch.setenv("QWEN3_EMBEDDING_WARM", "0")  # do not load torch/the model
    app = create_app()
    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200
        body = health.json()
        assert body["default_dim"] == 256
        assert body["loaded"] is False  # warm disabled -> model not loaded
        # empty input is rejected before any model work
        resp = client.post("/v1/embeddings", json={"input": []})
        assert resp.status_code == 400


def test_request_model_shape():
    req = EmbeddingRequest(input="hello", dimensions=256)
    assert req.dimensions == 256
    assert EmbeddingRequest(input=["a", "b"]).dimensions is None
