"""OpenAI-compatible /v1/embeddings server backed by Qwen3-Embedding-0.6B.

Makes the semantic embeddings validated in ``app.benchmark.semantic_bench``
deployable end-to-end: point ``MEMTRACE_EMBEDDING_PROVIDER=openai`` +
``MEMTRACE_EMBEDDING_BASE_URL`` at this server and MemTrace's retrieval uses real
semantic vectors instead of the deterministic hash default.

It honors the OpenAI ``dimensions`` parameter via Matryoshka (MRL) truncation +
L2 renormalize, so its output matches the pgvector ``vector(256)`` column that
``MEMTRACE_EMBEDDING_DIM`` defaults to. The model is loaded once at startup (warm)
so requests never pay a cold-start; loading is FP16 on MPS/CUDA/CPU as available.

Heavy: needs ``sentence-transformers`` + ``torch`` and the model (~1.2GB). Run
with an ephemeral install so nothing is added to the project deps:

    uv run --with fastapi --with "uvicorn[standard]" --with sentence-transformers \
      uvicorn app.embedding_server:app --host 0.0.0.0 --port 8090

Config (env):
  QWEN3_EMBEDDING_MODEL  (default Qwen/Qwen3-Embedding-0.6B)
  QWEN3_EMBEDDING_DIM    (default 256; the MRL output dimension)
  QWEN3_EMBEDDING_WARM   (default "1"; set "0" to defer model load to first request)
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

_MODEL_ID = os.environ.get("QWEN3_EMBEDDING_MODEL", "Qwen/Qwen3-Embedding-0.6B")
_DEFAULT_DIM = int(os.environ.get("QWEN3_EMBEDDING_DIM", "256"))


class _ModelHolder:
    """Lazy singleton so importing this module never loads torch/the model."""

    _model: Any = None
    _device: str = "unknown"

    @classmethod
    def get(cls) -> Any:
        if cls._model is None:
            import torch
            from sentence_transformers import SentenceTransformer

            if torch.backends.mps.is_available():
                cls._device = "mps"
            elif torch.cuda.is_available():
                cls._device = "cuda"
            else:
                cls._device = "cpu"
            cls._model = SentenceTransformer(
                _MODEL_ID, model_kwargs={"torch_dtype": torch.float16}, device=cls._device
            )
        return cls._model


def _embed(texts: list[str], dim: int) -> list[list[float]]:
    import numpy as np

    model = _ModelHolder.get()
    vecs = model.encode(texts, convert_to_numpy=True, normalize_embeddings=False)
    v = np.asarray(vecs, dtype="float32")
    if 0 < dim < v.shape[1]:  # Matryoshka truncation to the requested dimension
        v = v[:, :dim]
    norms = np.linalg.norm(v, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (v / norms).tolist()


class EmbeddingRequest(BaseModel):
    input: str | list[str]
    model: str = "qwen3-embedding-0.6b"
    dimensions: int | None = None
    encoding_format: str | None = None  # accepted for OpenAI-client compatibility; only "float" is produced


def create_app() -> FastAPI:
    @asynccontextmanager
    async def _lifespan(_app: FastAPI):
        if os.environ.get("QWEN3_EMBEDDING_WARM", "1") != "0":
            _ModelHolder.get()  # warm so the first request isn't a cold start
        yield

    app = FastAPI(title="Qwen3 Embedding Server", lifespan=_lifespan)

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "model": _MODEL_ID, "default_dim": _DEFAULT_DIM,
                "loaded": _ModelHolder._model is not None, "device": _ModelHolder._device}

    @app.post("/v1/embeddings")
    def embeddings(req: EmbeddingRequest) -> dict[str, Any]:
        texts = [req.input] if isinstance(req.input, str) else list(req.input)
        if not texts or any(not isinstance(t, str) for t in texts):
            raise HTTPException(status_code=400, detail="input must be a non-empty string or list of strings")
        dim = req.dimensions if (req.dimensions and req.dimensions > 0) else _DEFAULT_DIM
        try:
            vectors = _embed(texts, dim)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"embedding failed: {type(exc).__name__}: {exc}")
        data = [{"object": "embedding", "index": i, "embedding": vec} for i, vec in enumerate(vectors)]
        return {"object": "list", "data": data, "model": req.model,
                "usage": {"prompt_tokens": 0, "total_tokens": 0}}

    return app


app = create_app()
