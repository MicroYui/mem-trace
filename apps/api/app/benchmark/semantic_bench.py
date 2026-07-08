"""Real semantic embedding validation: Qwen3-Embedding-0.6B vs the hash default.

The default `EMBEDDING_PROVIDER=deterministic` is a blake2b bag-of-words hash — it
is effectively lexical, so a paraphrased query that shares no words with the
relevant memory gets no vector signal. This quantifies what a REAL semantic
embedding buys: it seeds facts and asks paraphrased questions (deliberately low
lexical overlap with the target fact) and measures recall@1 / recall@3 under
MemTrace's own `cosine_similarity`, for the hash embedding vs Qwen3-Embedding-0.6B
(FP16, MRL-truncated to the pgvector 256-dim contract). It also drives one case
through the real `MemoryRuntime.retrieve_context` with an injected Qwen3
`EmbeddingProvider` to prove the provider plumbing works end-to-end.

Opt-in / heavy: needs `sentence-transformers` + `torch` and downloads the model
(~1.2GB). Run with an ephemeral install so nothing is added to the project:

    uv run --with sentence-transformers python -m app.benchmark.semantic_bench
"""
from __future__ import annotations

import argparse
import asyncio
from typing import Any, Callable

from app.providers.base import ProviderCapabilities, ProviderKind
from app.providers.registry import ProviderRegistry
from app.retrieval.similarity import cosine_similarity, stable_embedding
from app.runtime.memory_runtime import MemoryRuntime
from app.runtime.models import (
    MemoryItem,
    MemoryScope,
    MemoryType,
    RetrievalRequest,
    RetrievalStrategy,
    StartRunRequest,
    StartStepRequest,
)
from app.runtime.repository import InMemoryRepository

# (id, fact) and paraphrased queries whose wording deliberately shares little/no
# vocabulary with the target fact — lexical/hash retrieval should struggle, a real
# semantic model should not.
FACTS: list[tuple[str, str]] = [
    ("runtime", "The project uses Bun as its JavaScript runtime."),
    ("db", "PostgreSQL is the primary relational database."),
    ("deploy", "We ship the service to a Kubernetes cluster."),
    ("cache", "Redis provides the in-memory caching layer."),
    ("queue", "Background jobs run through a Celery task queue."),
    ("auth", "Users authenticate with JSON Web Tokens."),
    ("lang", "The backend is written in Python."),
    ("ci", "Continuous integration runs on GitHub Actions."),
    ("search", "Full-text search is powered by Elasticsearch."),
    ("graph", "Relationships are stored in a Neo4j graph."),
    ("payments", "Stripe handles the subscription billing."),
    ("frontend", "The UI is built with React and TypeScript."),
]

QUERIES: list[tuple[str, str]] = [
    ("runtime", "What executes the client-side script code in this repo?"),
    ("db", "Which SQL engine persists the application records?"),
    ("deploy", "Where do the containers get orchestrated when we release?"),
    ("cache", "What gives us fast ephemeral key lookups without disk?"),
    ("queue", "How are asynchronous long-running chores dispatched off the hot path?"),
    ("auth", "How is a caller's identity verified on each request?"),
    ("lang", "What language is the server logic implemented in?"),
    ("ci", "Where do automated checks execute after a push?"),
    ("search", "How do users find documents by keyword across the corpus?"),
    ("graph", "What backs the connected-entity relationship traversals?"),
    ("payments", "Which vendor charges customers for their recurring plans?"),
    ("frontend", "What renders the interactive browser interface?"),
]


def _load_qwen3(dim: int) -> Callable[[list[str], bool], list[list[float]]]:
    import numpy as np
    import torch
    from sentence_transformers import SentenceTransformer

    device = "mps" if torch.backends.mps.is_available() else "cpu"
    print(f"loading Qwen/Qwen3-Embedding-0.6B (fp16) on {device} ...")
    model = SentenceTransformer(
        "Qwen/Qwen3-Embedding-0.6B",
        model_kwargs={"torch_dtype": torch.float16},
        device=device,
    )
    query_prompt = "Instruct: Given a question, retrieve the fact that answers it\nQuery: "

    def embed(texts: list[str], is_query: bool) -> list[list[float]]:
        prompt = query_prompt if is_query else None
        vecs = model.encode(texts, prompt=prompt, convert_to_numpy=True, normalize_embeddings=False)
        v = np.asarray(vecs, dtype="float32")[:, :dim]  # MRL truncation to the 256-dim contract
        norms = np.linalg.norm(v, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return (v / norms).tolist()

    return embed


def _recall(rank_of_target: list[int]) -> dict[str, float]:
    n = len(rank_of_target)
    return {
        "recall@1": round(sum(1 for r in rank_of_target if r == 1) / n, 3),
        "recall@3": round(sum(1 for r in rank_of_target if r <= 3) / n, 3),
        "mean_rank": round(sum(rank_of_target) / n, 2),
    }


def _rank_targets(embed_fact, embed_query) -> list[int]:
    fact_vecs = {fid: embed_fact(text) for fid, text in FACTS}
    ranks: list[int] = []
    for target_id, query in QUERIES:
        qv = embed_query(query)
        scored = sorted(
            ((fid, cosine_similarity(qv, fv)) for fid, fv in fact_vecs.items()),
            key=lambda kv: (-kv[1], kv[0]),
        )
        ranks.append(1 + [fid for fid, _ in scored].index(target_id))
    return ranks


async def _runtime_end_to_end(embed) -> dict[str, Any]:
    """Prove the full pipeline works with an injected real EmbeddingProvider."""
    dim = 256

    class _Qwen3Provider:
        def __init__(self) -> None:
            self.dim = dim
            self.capabilities = ProviderCapabilities(
                provider_id="embedding.qwen3_0_6b.v1", kind=ProviderKind.embedding,
                deterministic=False, requires_network=False, model="Qwen3-Embedding-0.6B",
                metadata={"dim": dim, "precision": "fp16"})

        async def embed_text(self, text: str | None) -> list[float]:
            return embed([text or ""], True)[0]

    registry = ProviderRegistry()
    provider = _Qwen3Provider()
    registry.register(ProviderKind.embedding, provider, provider.capabilities)

    repo = InMemoryRepository()
    ws = "sem_ws"
    for fid, text in FACTS:
        vec = embed([text], False)[0]  # store the real semantic vector directly
        await repo.add_memory(MemoryItem(memory_id=f"m_{fid}", workspace_id=ws,
                                         memory_type=MemoryType.project, scope=MemoryScope.workspace,
                                         content=text, summary=text[:60], embedding_vector=vec))
    rt = MemoryRuntime(repo, default_workspace_id=ws, provider_registry=registry)
    run = await rt.start_run(StartRunRequest(session_id="sem", task="semantic", workspace_id=ws))
    step = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="answer"))
    # a paraphrased query with no lexical overlap with "Bun ... JavaScript runtime"
    ctx = await rt.retrieve_context(RetrievalRequest(
        run_id=run.run_id, step_id=step.step_id,
        query="What executes the client-side script code in this repo?",
        strategy=RetrievalStrategy.variant_2))
    text = " ".join((b.content or "") for b in ctx.context_blocks)
    return {"paraphrase_query": "What executes the client-side script code in this repo?",
            "recalled_bun_fact": "Bun" in text}


async def run_semantic_bench(dim: int, *, with_runtime: bool = True) -> dict[str, Any]:
    embed = _load_qwen3(dim)
    hash_ranks = _rank_targets(lambda t: stable_embedding(t, dim), lambda t: stable_embedding(t, dim))
    qwen_ranks = _rank_targets(lambda t: embed([t], False)[0], lambda t: embed([t], True)[0])
    result: dict[str, Any] = {
        "queries": len(QUERIES),
        "embedding_dim": dim,
        "hash_default": _recall(hash_ranks),
        "qwen3_0_6b_fp16": _recall(qwen_ranks),
    }
    if with_runtime:
        result["runtime_end_to_end"] = await _runtime_end_to_end(embed)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Semantic embedding validation (Qwen3 vs hash)")
    parser.add_argument("--dim", type=int, default=256)
    parser.add_argument("--no-runtime", action="store_true")
    args = parser.parse_args()
    payload = asyncio.run(run_semantic_bench(args.dim, with_runtime=not args.no_runtime))
    h, q = payload["hash_default"], payload["qwen3_0_6b_fp16"]
    print(f"\nparaphrased-query recall over {payload['queries']} queries (dim={payload['embedding_dim']}):")
    print(f"  hash default : recall@1={h['recall@1']}  recall@3={h['recall@3']}  mean_rank={h['mean_rank']}")
    print(f"  Qwen3-0.6B   : recall@1={q['recall@1']}  recall@3={q['recall@3']}  mean_rank={q['mean_rank']}")
    if "runtime_end_to_end" in payload:
        e = payload["runtime_end_to_end"]
        print(f"  runtime end-to-end (injected Qwen3 provider): recalled Bun fact for a paraphrase = {e['recalled_bun_fact']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
