#!/usr/bin/env bash
# Opt-in end-to-end smoke for the Qwen3 OpenAI-compatible embedding server
# (app/embedding_server.py). Start the server first, e.g.:
#   uv run --with fastapi --with "uvicorn[standard]" --with sentence-transformers \
#     uvicorn app.embedding_server:app --app-dir apps/api --port 8090
# then:
#   MEMTRACE_EMBEDDING_BASE_URL=http://localhost:8090/v1 ./scripts/smoke-embedding-server.sh
# It verifies, through MemTrace's real OpenAIEmbeddingProvider, that (1) the server
# returns 256-dim vectors and (2) a full retrieve_context wired to this provider
# recalls the semantically-matched memory for a paraphrased query. Skips cleanly
# when the server is unreachable. NOT part of default CI.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR/apps/api"

echo "==> Qwen3 embedding-server smoke (${MEMTRACE_EMBEDDING_BASE_URL:-http://localhost:8090/v1})"

uv run python - <<'PY'
import asyncio
import os
import sys

import httpx

from app.providers.base import ProviderCapabilities, ProviderKind
from app.providers.embedding import OpenAIEmbeddingProvider
from app.providers.registry import ProviderRegistry
from app.runtime.memory_runtime import MemoryRuntime
from app.runtime.models import (
    MemoryItem, MemoryScope, MemoryType, RetrievalRequest, RetrievalStrategy,
    StartRunRequest, StartStepRequest,
)
from app.runtime.repository import InMemoryRepository

BASE = os.environ.get("MEMTRACE_EMBEDDING_BASE_URL", "http://localhost:8090/v1").rstrip("/")
ROOT = BASE[:-3] if BASE.endswith("/v1") else BASE  # derive the server root for /health

FACTS = {
    "runtime": "The project uses Bun as its JavaScript runtime.",
    "db": "PostgreSQL is the primary relational database.",
    "deploy": "We ship the service to a Kubernetes cluster.",
    "cache": "Redis provides the in-memory caching layer.",
    "auth": "Users authenticate with JSON Web Tokens.",
}
PARAPHRASE = "What executes the client-side script code in this repo?"  # -> runtime (Bun)


async def main() -> int:
    try:
        httpx.get(f"{ROOT}/health", timeout=5).raise_for_status()
    except Exception as exc:  # noqa: BLE001
        print(f"  ⏭️  skip: embedding server not reachable at {ROOT}/health ({type(exc).__name__})")
        print("advanced-embedding smoke skipped")
        return 0

    provider = OpenAIEmbeddingProvider(api_key="local", base_url=BASE,
                                       model="qwen3-embedding-0.6b", dimensions=256, timeout_s=60)
    try:
        # 1) the server returns a finite 256-dim vector through MemTrace's provider
        vec = await provider.embed_text(PARAPHRASE)
        assert len(vec) == 256, f"expected 256 dims, got {len(vec)}"
        print(f"  ✅ provider: server returned a {len(vec)}-dim vector via MemTrace's OpenAIEmbeddingProvider")

        # 2) full retrieval wired to this provider recalls the paraphrase's semantic target
        registry = ProviderRegistry()
        registry.register(ProviderKind.embedding, provider, ProviderCapabilities(
            provider_id="embedding.qwen3_server.v1", kind=ProviderKind.embedding,
            deterministic=False, requires_network=True, model="qwen3-embedding-0.6b",
            metadata={"dim": 256}))
        repo = InMemoryRepository()
        ws = "emb_smoke_ws"
        for fid, text in FACTS.items():
            fv = await provider.embed_text(text)  # store the real semantic vector
            await repo.add_memory(MemoryItem(memory_id=f"m_{fid}", workspace_id=ws,
                                             memory_type=MemoryType.project, scope=MemoryScope.workspace,
                                             content=text, summary=text[:60], embedding_vector=fv))
        rt = MemoryRuntime(repo, default_workspace_id=ws, provider_registry=registry)
        run = await rt.start_run(StartRunRequest(session_id="emb", task="emb", workspace_id=ws))
        step = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="answer"))
        ctx = await rt.retrieve_context(RetrievalRequest(
            run_id=run.run_id, step_id=step.step_id, query=PARAPHRASE, strategy=RetrievalStrategy.variant_2))
        text = " ".join((b.content or "") for b in ctx.context_blocks)
        assert "Bun" in text, f"paraphrase did not recall the runtime fact; context={text[:200]!r}"
        print("  ✅ retrieval: full retrieve_context via the real provider recalled the Bun fact for a paraphrase")
    finally:
        await provider.aclose()
    print("advanced-embedding smoke passed")
    return 0


sys.exit(asyncio.run(main()))
PY
