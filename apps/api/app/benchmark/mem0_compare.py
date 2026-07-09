"""SOTA head-to-head — Mem0 vs plain-vector vs MemTrace on LongMemEval (opt-in).

Answers "compare against a real SOTA memory system, not just plain vector". For a
stratified sample of LongMemEval questions it runs FOUR conditions over the same
questions + the same real LLM answering + the same real LLM judge:

  - no_memory   — control (no context).
  - plain_vector— MemTrace's baseline_1 (vector/lexical retrieval, no gate).
  - mem0        — the Mem0 OSS memory system (LLM fact-extraction + semantic recall).
  - memtrace    — MemTrace variant_2 (state-aware retrieval + admission gate).

Mem0 and MemTrace/plain-vector are fundamentally different (Mem0 *extracts* salient
facts via an LLM; MemTrace retrieves gated raw turns), so this is a genuine
cross-system comparison on a real dataset with one shared judge — not a leaderboard.

    ./scripts/fetch-longmemeval.sh s_cleaned
    MEMTRACE_LLM_API_KEY=local MEMTRACE_LLM_BASE_URL=http://localhost:4141/v1 \
      MEMTRACE_LLM_MODEL=gpt-5.4 MEMTRACE_RETRIEVAL_HYBRID_BACKEND=inmemory \
      uv run --with ijson --with mem0ai --with chromadb \
        python -m app.benchmark.mem0_compare --dataset /tmp/longmemeval_s_cleaned.json --limit 48
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any

import httpx

from app.benchmark.llm_bench import _resolve_endpoints
from app.benchmark.longmemeval_bench import (
    BatchEmbeddingProvider,
    _answer,
    _embed_docs_batch,
    _embedding_config,
    _judge,
    build_memories,
    is_abstention,
    select_sessions,
    stream_stratified,
)
from app.providers.base import ProviderKind
from app.providers.registry import ProviderRegistry
from app.runtime.context_actions import positive_blocks
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

EMBED_DIM = 256
_CONDITIONS = ["no_memory", "plain_vector", "mem0", "memtrace"]
_STRATEGY = {"plain_vector": RetrievalStrategy.baseline_1, "memtrace": RetrievalStrategy.variant_2}


def _question_sessions(question: dict[str, Any], chosen: list[int]) -> list[list[dict[str, str]]]:
    """The chosen sessions as separate message lists for Mem0's add() — added one
    session at a time so each embedding batch stays under the endpoint's token limit."""
    sessions = question.get("haystack_sessions") or []
    out: list[list[dict[str, str]]] = []
    for si in chosen:
        msgs: list[dict[str, str]] = []
        for turn in sessions[si]:
            content = (turn.get("content") or "").strip()
            if content:
                role = turn.get("role", "user")
                msgs.append({"role": role if role in ("user", "assistant") else "user", "content": content})
        if msgs:
            out.append(msgs)
    return out


def _mem0_memory(emb_cfg: dict[str, Any], llm: dict[str, Any], db_path: str):
    from mem0 import Memory
    cfg = {
        "llm": {"provider": "openai", "config": {
            "model": llm["model"], "openai_base_url": llm["base_url"], "api_key": llm["api_key"]}},
        "embedder": {"provider": "openai", "config": {
            "model": emb_cfg["model"], "openai_base_url": emb_cfg["base_url"], "api_key": emb_cfg["api_key"],
            "embedding_dims": 1536}},
        "vector_store": {"provider": "chroma", "config": {"collection_name": "mem0_lme", "path": db_path}},
    }
    return Memory.from_config(cfg)


def _mem0_context(mem, uid: str, question: str, top_k: int) -> tuple[str, int]:
    """Add nothing here (caller already added); search + format Mem0's recalled facts."""
    res = mem.search(question, filters={"user_id": uid}, limit=top_k)
    hits = res.get("results", res) if isinstance(res, dict) else res
    facts = [h.get("memory") for h in hits if isinstance(h, dict) and h.get("memory")]
    return ("\n".join(f"- {f}" for f in facts) or "(no relevant memory found)"), len(facts)


async def run_mem0_compare(dataset: str, *, limit: int, max_sessions: int, top_k: int,
                           concurrency: int, output_dir: str | None) -> dict[str, Any]:
    endpoints = _resolve_endpoints()
    if not endpoints or not Path(dataset).exists():
        return {"skipped": True, "reason": "needs MEMTRACE_LLM_* env and a LongMemEval dataset"}
    llm = endpoints[0]
    emb_cfg = _embedding_config(llm)
    db_path = os.path.join(os.environ.get("MEMTRACE_LME_DIR", "/tmp"), "mem0_lme_db")
    shutil.rmtree(db_path, ignore_errors=True)

    try:
        mem = _mem0_memory(emb_cfg, llm, db_path)
    except Exception as exc:  # noqa: BLE001
        return {"skipped": True, "reason": f"Mem0 unavailable ({type(exc).__name__}: {exc})"}

    embed_client = httpx.AsyncClient(timeout=60)
    query_provider = BatchEmbeddingProvider(embed_client, emb_cfg)
    registry = ProviderRegistry()
    registry.register(ProviderKind.embedding, query_provider, query_provider.capabilities)
    questions = stream_stratified(dataset, limit)

    prepared: list[dict[str, Any]] = []
    t0 = time.perf_counter()
    mem0_fact_total = 0
    try:
        for qi, q in enumerate(questions):
            chosen = select_sessions(q, max_sessions)
            mems, gold_texts = build_memories(q, f"lme_{qi}", chosen)
            if not mems:
                continue
            # plain_vector / memtrace context via MemTrace retrieval over real vectors
            vectors = await _embed_docs_batch(embed_client, emb_cfg, [m.content or "" for m in mems])
            repo = InMemoryRepository()
            for m, v in zip(mems, vectors):
                m.embedding_vector = v
                await repo.add_memory(m)
            rt = MemoryRuntime(repo, default_workspace_id=f"lme_{qi}", provider_registry=registry)
            run = await rt.start_run(StartRunRequest(session_id=f"m0-{qi}", task="recall", workspace_id=f"lme_{qi}"))
            step = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="answer"))
            contexts = {"no_memory": "(no memory provided)"}
            for cond, strat in _STRATEGY.items():
                ctx = await rt.retrieve_context(RetrievalRequest(
                    run_id=run.run_id, step_id=step.step_id, query=q["question"], strategy=strat,
                    token_budget=1600, top_k=top_k))
                contexts[cond] = "\n".join(f"- {b.content}" for b in positive_blocks(ctx)) or "(no relevant memory found)"
            # mem0: extract facts from the haystack (add one session at a time so each
            # embedding batch stays under the endpoint token limit), then recall.
            uid = f"q{qi}"
            for sess_msgs in _question_sessions(q, chosen):
                try:
                    await asyncio.to_thread(mem.add, messages=sess_msgs, user_id=uid)
                except Exception:  # noqa: BLE001 - a bad session add must not abort the run
                    pass
            m0_ctx, n_facts = await asyncio.to_thread(_mem0_context, mem, uid, q["question"], top_k)
            contexts["mem0"] = m0_ctx
            mem0_fact_total += n_facts
            prepared.append({"qi": qi, "question": q["question"], "gold": str(q.get("answer")),
                             "type": q.get("question_type", "other"), "abstention": is_abstention(q),
                             "contexts": contexts})
            q.clear()
            if (qi + 1) % 10 == 0:
                print(f"  built {qi + 1}/{len(questions)} questions (mem0 facts so far: {mem0_fact_total}) …", flush=True)
        build_s = time.perf_counter() - t0
        print(f"  build done: {len(prepared)} questions, {mem0_fact_total} mem0 facts in {build_s:.0f}s", flush=True)

        sem = asyncio.Semaphore(concurrency)
        async with httpx.AsyncClient() as client:
            async def _one(item):
                by = {}
                for cond in _CONDITIONS:
                    try:
                        async with sem:
                            pred = await _answer(item["contexts"][cond], item["question"], client, llm)
                            correct = await _judge(item["question"], item["gold"], pred, client, llm)
                        by[cond] = {"answer": pred, "correct": correct}
                    except Exception as exc:  # noqa: BLE001
                        by[cond] = {"answer": f"<error: {type(exc).__name__}>", "correct": False}
                return {**{k: item[k] for k in ("qi", "question", "gold", "type", "abstention")}, "by_condition": by}
            rows = await asyncio.gather(*(_one(it) for it in prepared))

        payload = _aggregate(rows, dataset, llm, emb_cfg, mem0_fact_total, limit)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
            with open(os.path.join(output_dir, "mem0_compare_results.json"), "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2, ensure_ascii=False)
        return payload
    finally:
        await embed_client.aclose()
        shutil.rmtree(db_path, ignore_errors=True)


def _aggregate(rows, dataset, llm, emb_cfg, mem0_facts, limit) -> dict[str, Any]:
    agg = {c: {"correct": 0, "total": 0} for c in _CONDITIONS}
    by_type: dict[str, dict[str, dict[str, int]]] = {}
    for r in rows:
        for c in _CONDITIONS:
            ok = int(r["by_condition"][c]["correct"])
            agg[c]["total"] += 1
            agg[c]["correct"] += ok
            tt = by_type.setdefault(r["type"], {x: {"correct": 0, "total": 0} for x in _CONDITIONS})
            tt[c]["total"] += 1
            tt[c]["correct"] += ok

    def acc(d):
        return round(d["correct"] / d["total"], 4) if d["total"] else 0.0

    return {
        "skipped": False, "dataset": str(dataset), "sample_size": len(rows),
        "embedding": emb_cfg["model"], "endpoint": {"base_url": llm["base_url"], "model": llm["model"]},
        "mem0_facts_extracted": mem0_facts, "config": {"limit": limit},
        "accuracy": {c: acc(agg[c]) for c in _CONDITIONS},
        "accuracy_by_type": {t: {c: acc(tt[c]) for c in _CONDITIONS} for t, tt in sorted(by_type.items())},
        "rows": rows,
    }


def main() -> int:
    p = argparse.ArgumentParser(description="Mem0 vs plain-vector vs MemTrace on LongMemEval")
    p.add_argument("--dataset", help="Path to longmemeval_*.json (or set MEMTRACE_LONGMEMEVAL_PATH)")
    p.add_argument("--limit", type=int, default=48)
    p.add_argument("--max-sessions", type=int, default=8)
    p.add_argument("--top-k", type=int, default=20)
    p.add_argument("--concurrency", type=int, default=6)
    p.add_argument("--output-dir", default="reports")
    a = p.parse_args()
    dataset = a.dataset or os.environ.get("MEMTRACE_LONGMEMEVAL_PATH") or ""
    payload = asyncio.run(run_mem0_compare(dataset, limit=a.limit, max_sessions=a.max_sessions,
                                           top_k=a.top_k, concurrency=a.concurrency, output_dir=a.output_dir))
    if payload.get("skipped"):
        print(f"mem0_compare skipped: {payload['reason']}")
        return 0
    print(f"dataset={payload['dataset']}  n={payload['sample_size']}  mem0_facts={payload['mem0_facts_extracted']}")
    for c in _CONDITIONS:
        print(f"  {c:>12}: accuracy={payload['accuracy'][c]:.1%}")
    print(f"  by type: {json.dumps(payload['accuracy_by_type'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
