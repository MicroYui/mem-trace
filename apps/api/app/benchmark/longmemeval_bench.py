"""Real-dataset (LongMemEval) real-embedding + real-LLM benchmark (opt-in).

The large-scale counterpart to the deterministic suites: it runs the real
LongMemEval long-term-memory benchmark through MemTrace with **real
Qwen3-Embedding-0.6B** semantic vectors (in an in-process cosine index) and a
**real LLM** answering + a **real LLM judge** — so the numbers come from a real
dataset, real embeddings, and a real model rather than substring markers over a
hash embedding.

Each LongMemEval question ships its own haystack of chat sessions (a few gold
sessions that contain the answer + dozens of distractor sessions). For each
sampled question we ingest its haystack turns as episodic memories (real Qwen3
vectors) into a per-question workspace, then answer under three conditions over
the identical store:

  - ``no_memory``    (``baseline_0``) — the LLM answers with no context (control).
  - ``plain_vector`` (``baseline_1``) — vector/lexical retrieval, no admission gate.
  - ``memtrace``     (``variant_2``)  — state-aware retrieval + admission gate.

A separate LLM judge grades each answer against the gold answer. Accuracy is
reported overall and per LongMemEval ``question_type`` (single-session-*,
multi-session, temporal-reasoning, knowledge-update), plus an **abstention**
sub-score (questions whose answer is "not enough information") and **context
precision** (injected tokens + distractor rate) for plain-vector vs MemTrace.

HONEST SCOPE: on pure conversational recall MemTrace ties plain vector — its edge
shows on abstention/precision and (with keyed extraction, see
``run_knowledge_update_extraction``) knowledge-update. This harness proves the
pipeline on real data + a real model + real embeddings; it is not a leaderboard
submission.

    ./scripts/fetch-longmemeval.sh s_cleaned          # -> /tmp/longmemeval_s_cleaned.json
    MEMTRACE_LLM_API_KEY=local MEMTRACE_LLM_BASE_URL=http://localhost:4141/v1 \
      MEMTRACE_LLM_MODEL=gpt-5.4 \
      uv run --with ijson python -m app.benchmark.longmemeval_bench \
        --dataset /tmp/longmemeval_s_cleaned.json --limit 300 --output-dir reports

Memory/CPU are kept modest on purpose (real embeddings come from the API, the
dataset is stream-parsed, and each question uses a fresh in-memory store), so it is
slow-but-light rather than a machine hog. ``--with ijson`` enables the streaming
loader (falls back to a full parse if absent)."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

import httpx

from app.benchmark.llm_bench import _resolve_endpoints
from app.benchmark.qa_bench import _chat
from app.providers.base import ProviderCapabilities, ProviderKind
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

# In-memory store with REAL OpenAI-compatible embeddings (text-embedding-3-small,
# 256-dim): this is a retrieval-QUALITY benchmark (accuracy), so it uses an
# in-process cosine index with the same real vectors as pgvector — the
# Postgres/pgvector storage path is covered by the dedicated perf/scale benchmarks
# (perf_bench / perf-scale.sh), and using it here would only add per-INSERT latency
# without changing any retrieval-quality number. Embeddings come from the same
# OpenAI-compatible endpoint as the LLM (batched, so tens of thousands of turns
# embed in seconds — far faster than a local model on laptop MPS).
EMBED_DIM = 256
_EMBED_MODEL_DEFAULT = "text-embedding-3-small"
_WS_PREFIX = "lme_"

_CONDITIONS = [
    ("no_memory", RetrievalStrategy.baseline_0),
    ("plain_vector", RetrievalStrategy.baseline_1),
    ("memtrace", RetrievalStrategy.variant_2),
]

_ANSWER_SYSTEM = (
    "You answer questions about a user's long chat history using ONLY the provided "
    "memory snippets. Be concise. If the snippets do not contain enough information "
    "to answer, reply exactly: No information available."
)
_JUDGE_SYSTEM = (
    "You grade a predicted answer against a gold answer for a long-term-memory QA "
    "task. Reply with exactly one word: CORRECT if the prediction captures the gold "
    "answer's key fact (allowing paraphrase, date/number formatting, or extra words), "
    "else INCORRECT. When the gold answer says the information is not available / not "
    "enough / cannot be determined, an abstention such as 'No information available' "
    "is CORRECT and any confident factual answer is INCORRECT."
)


# --------------------------------------------------------------------------- #
# Dataset shaping
# --------------------------------------------------------------------------- #
def load_dataset(path: str | os.PathLike[str]) -> list[dict[str, Any]]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def stream_stratified(path: str | os.PathLike[str], limit: int) -> list[dict[str, Any]]:
    """Memory-bounded stratified sample. The full ``s_cleaned`` file is 264 MB and a
    plain ``json.load`` peaks at ~1.5 GB; stream it with ijson and keep only a small
    per-type bucket so peak memory stays ~tens of MB. Falls back to a full parse when
    ijson is unavailable (used only by tests on tiny files)."""
    try:
        import ijson  # optional, lightweight streaming parser (uv run --with ijson)
    except ImportError:
        return stratified_sample(load_dataset(path), limit)
    cap = max(4, limit // 4 + 4)  # per-type cap bounds held questions to ~6*cap
    buckets: dict[str, list[dict[str, Any]]] = {}
    with open(path, "rb") as fh:
        for q in ijson.items(fh, "item"):
            b = buckets.setdefault(q.get("question_type", "other"), [])
            if len(b) < cap:
                b.append(q)
    order = sorted(buckets)
    picked: list[dict[str, Any]] = []
    idx = 0
    while len(picked) < limit and any(idx < len(buckets[t]) for t in order):
        for t in order:
            if idx < len(buckets[t]):
                picked.append(buckets[t][idx])
                if len(picked) >= limit:
                    break
        idx += 1
    return picked


def is_abstention(question: dict[str, Any]) -> bool:
    return str(question.get("question_id", "")).endswith("_abs")


def stratified_sample(data: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Deterministic round-robin across question_type so every type is represented."""
    by_type: dict[str, list[dict[str, Any]]] = {}
    for q in data:
        by_type.setdefault(q.get("question_type", "other"), []).append(q)
    order = sorted(by_type)
    picked: list[dict[str, Any]] = []
    idx = 0
    while len(picked) < limit and any(idx < len(by_type[t]) for t in order):
        for t in order:
            if idx < len(by_type[t]):
                picked.append(by_type[t][idx])
                if len(picked) >= limit:
                    break
        idx += 1
    return picked


def select_sessions(question: dict[str, Any], max_sessions: int) -> list[int]:
    """Indices of the haystack sessions to ingest: always the gold (answer) sessions,
    then fill with distractor sessions up to ``max_sessions`` (deterministic)."""
    sessions = question.get("haystack_sessions") or []
    sids = question.get("haystack_session_ids") or []
    answer_ids = set(question.get("answer_session_ids") or [])
    gold = [i for i in range(len(sessions)) if i < len(sids) and sids[i] in answer_ids]
    others = [i for i in range(len(sessions)) if i not in set(gold)]
    chosen = gold + others[: max(0, max_sessions - len(gold))]
    return sorted(set(chosen))


def build_memories(
    question: dict[str, Any], ws: str, chosen: list[int]
) -> tuple[list[MemoryItem], list[str]]:
    """Return (memories, gold_texts) for the chosen sessions. Gold turns are those
    flagged ``has_answer``; their raw text is used to score retrieval precision."""
    sessions = question.get("haystack_sessions") or []
    dates = question.get("haystack_dates") or []
    memories: list[MemoryItem] = []
    gold_texts: list[str] = []
    for si in chosen:
        session = sessions[si]
        date = dates[si] if si < len(dates) else ""
        for ti, turn in enumerate(session):
            content = (turn.get("content") or "").strip()
            if not content:
                continue
            if str(turn.get("has_answer")) == "True":
                gold_texts.append(content)
            memories.append(
                MemoryItem(
                    memory_id=f"{ws}_s{si}_t{ti}",
                    workspace_id=ws,
                    memory_type=MemoryType.episodic,
                    scope=MemoryScope.workspace,
                    content=f"[{date}] {turn.get('role', '?')}: {content}",
                    summary=content[:80],
                )
            )
    return memories, gold_texts


# --------------------------------------------------------------------------- #
# Real embeddings (OpenAI-compatible, batch)
# --------------------------------------------------------------------------- #
def _embedding_config(llm_endpoint: dict[str, Any]) -> dict[str, Any]:
    """Embedding endpoint: dedicated MEMTRACE_EMBEDDING_* if set, else reuse the LLM
    endpoint's base_url/key (the proxy serves both chat and /embeddings)."""
    return {
        "base_url": os.environ.get("MEMTRACE_EMBEDDING_BASE_URL", llm_endpoint["base_url"]).rstrip("/"),
        "api_key": os.environ.get("MEMTRACE_EMBEDDING_API_KEY", llm_endpoint["api_key"]),
        "model": os.environ.get("MEMTRACE_EMBEDDING_MODEL", _EMBED_MODEL_DEFAULT),
    }


async def _embed_docs_batch(client, cfg: dict[str, Any], texts: list[str], batch_size: int = 128) -> list[list[float]]:
    """Embed documents through the OpenAI-compatible /embeddings endpoint in batches."""
    out: list[list[float]] = []
    headers = {"Authorization": f"Bearer {cfg['api_key']}", "Content-Type": "application/json"}
    url = f"{cfg['base_url']}/embeddings"
    for i in range(0, len(texts), batch_size):
        chunk = texts[i:i + batch_size]
        resp = await client.post(url, headers=headers,
                                 json={"model": cfg["model"], "input": chunk, "dimensions": EMBED_DIM})
        resp.raise_for_status()
        data = sorted(resp.json()["data"], key=lambda d: d["index"])
        out.extend([[float(x) for x in d["embedding"]] for d in data])
    return out


class BatchEmbeddingProvider:
    """Query-side EmbeddingProvider for the runtime. Sends ``input`` as a list (the
    endpoint requires it) via the same batch helper, so query + doc vectors share one
    model/dimension/normalization space."""

    def __init__(self, client, cfg: dict[str, Any]) -> None:
        self._client = client
        self._cfg = cfg
        self.capabilities = ProviderCapabilities(
            provider_id="embedding.openai_compatible.v1", kind=ProviderKind.embedding,
            deterministic=False, requires_network=True, model=cfg["model"],
            metadata={"dim": EMBED_DIM})

    async def embed_text(self, text: str | None) -> list[float]:
        return (await _embed_docs_batch(self._client, self._cfg, [text or ""]))[0]


# --------------------------------------------------------------------------- #
# Answer + judge (reuses qa_bench._chat)
# --------------------------------------------------------------------------- #
async def _chat_retry(client, endpoint, system: str, user: str, *, tries: int = 4) -> str:
    """_chat with retry/backoff: transient proxy timeouts must not kill a whole run."""
    last: Exception | None = None
    for i in range(tries):
        try:
            return await _chat(client, endpoint, system, user)
        except Exception as exc:  # noqa: BLE001 - retry any transient network/proxy error
            last = exc
            await asyncio.sleep(1.5 * (i + 1))
    raise last if last else RuntimeError("chat failed")


async def _answer(context: str, question: str, client, endpoint) -> str:
    prompt = f"Memory snippets:\n{context}\n\nQuestion: {question}\nAnswer concisely:"
    return await _chat_retry(client, endpoint, _ANSWER_SYSTEM, prompt)


async def _judge(question: str, gold: str, prediction: str, client, endpoint) -> bool:
    prompt = (
        f"Question: {question}\nGold answer: {gold}\nPredicted answer: {prediction}\n\n"
        "Is the prediction CORRECT or INCORRECT?"
    )
    verdict = (await _chat_retry(client, endpoint, _JUDGE_SYSTEM, prompt)).strip().upper()
    return verdict.startswith("CORRECT")


def _precision(blocks: list[Any], gold_texts: list[str]) -> dict[str, Any]:
    """Retrieval precision for one (question, condition): injected tokens, how many
    blocks are distractors (not a gold turn), and gold-turn recall."""
    n = len(blocks)
    tokens = sum(max(1, len(b.content or "") // 4) for b in blocks)
    gold_hit_blocks = sum(1 for b in blocks if any(g in (b.content or "") for g in gold_texts))
    golds_found = sum(1 for g in gold_texts if any(g in (b.content or "") for b in blocks))
    return {
        "blocks": n,
        "injected_tokens": tokens,
        "distractor_rate": round((n - gold_hit_blocks) / n, 4) if n else 0.0,
        "gold_recall": round(golds_found / len(gold_texts), 4) if gold_texts else None,
    }


# --------------------------------------------------------------------------- #
# Embedded-record cache (embedding is the slow part; cache it so a Phase-B hiccup
# or a floor-tuning re-run never forces a full re-embed)
# --------------------------------------------------------------------------- #
def _cache_path(dataset: str, limit: int, max_sessions: int) -> str:
    stem = Path(dataset).stem
    return os.path.join(os.environ.get("MEMTRACE_LME_DIR", "/tmp"),
                        f"lme_embcache_{stem}_l{limit}_s{max_sessions}.jsonl")


async def _embedded_records(dataset: str, limit: int, max_sessions: int, emb_cfg, client, cache: str | None):
    """Yield-list of per-question embedded records: {question, gold, type, abstention,
    contents, vectors, gold_texts}. Loads from cache if present, else embeds + writes it."""
    if cache and Path(cache).exists():
        recs = [json.loads(line) for line in Path(cache).read_text(encoding="utf-8").splitlines() if line.strip()]
        print(f"  loaded {len(recs)} embedded questions from cache {cache}", flush=True)
        return recs
    questions = stream_stratified(dataset, limit)
    recs: list[dict[str, Any]] = []
    total_mem = 0
    for qi, q in enumerate(questions):
        chosen = select_sessions(q, max_sessions)
        mems, gold_texts = build_memories(q, f"{_WS_PREFIX}{qi}", chosen)
        if not mems:
            continue
        vectors = await _embed_docs_batch(client, emb_cfg, [m.content or "" for m in mems])
        recs.append({
            "qi": qi, "question": q["question"], "gold": str(q.get("answer")),
            "type": q.get("question_type", "other"), "abstention": is_abstention(q),
            "contents": [m.content for m in mems], "vectors": vectors, "gold_texts": gold_texts,
        })
        total_mem += len(mems)
        q.clear()
        if (qi + 1) % 25 == 0:
            print(f"  embedded {qi + 1}/{len(questions)} questions, {total_mem} memories …", flush=True)
    if cache:
        with open(cache, "w", encoding="utf-8") as fh:
            for r in recs:
                fh.write(json.dumps(r) + "\n")
        print(f"  wrote embedding cache -> {cache}", flush=True)
    return recs


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #
async def run_longmemeval_bench(
    dataset_path: str | os.PathLike[str] | None = None,
    *,
    limit: int = 300,
    max_sessions: int = 8,
    top_k: int = 20,
    token_budget: int = 1600,
    concurrency: int = 6,
    output_dir: str | None = "reports",
    use_cache: bool = True,
) -> dict[str, Any]:
    endpoints = _resolve_endpoints()
    resolved = dataset_path or os.environ.get("MEMTRACE_LONGMEMEVAL_PATH")
    if not endpoints or not resolved or not Path(resolved).exists():
        return {"skipped": True, "reason": (
            "Needs MEMTRACE_LLM_API_KEY (+ BASE_URL/MODEL) and a LongMemEval JSON at "
            "--dataset / MEMTRACE_LONGMEMEVAL_PATH (run scripts/fetch-longmemeval.sh)."
        )}
    endpoint = endpoints[0]
    emb_cfg = _embedding_config(endpoint)

    # One shared client for both query-side (runtime provider) and doc-side (batch)
    # embeddings; both hit the same OpenAI-compatible /embeddings endpoint.
    embed_client = httpx.AsyncClient(timeout=60)
    query_provider = BatchEmbeddingProvider(embed_client, emb_cfg)
    try:
        probe = await query_provider.embed_text("healthcheck")
    except Exception as exc:  # noqa: BLE001
        await embed_client.aclose()
        return {"skipped": True, "reason": f"embedding endpoint unavailable ({type(exc).__name__}: {exc})"}
    if len(probe) != EMBED_DIM:
        await embed_client.aclose()
        return {"skipped": True, "reason": f"embedding endpoint returned {len(probe)} dims, expected {EMBED_DIM}"}
    registry = ProviderRegistry()
    registry.register(ProviderKind.embedding, query_provider, query_provider.capabilities)

    cache = _cache_path(str(resolved), limit, max_sessions) if use_cache else None

    # ---- Phase A: embed (cached) then retrieve per condition (current floor) ---- #
    t_ingest = time.perf_counter()
    total_memories = 0
    prepared: list[dict[str, Any]] = []
    try:
        records = await _embedded_records(str(resolved), limit, max_sessions, emb_cfg, embed_client, cache)
        total_questions = len(records)
        for qi, rec in enumerate(records):
            contents, vectors, gold_texts = rec["contents"], rec["vectors"], rec["gold_texts"]
            if not contents:
                continue
            ws = f"{_WS_PREFIX}{qi}"
            repo = InMemoryRepository()  # fresh per question -> live memory stays ~one haystack, not all
            for ci, (content, vec) in enumerate(zip(contents, vectors)):
                await repo.add_memory(MemoryItem(
                    memory_id=f"{ws}_m{ci}", workspace_id=ws, memory_type=MemoryType.episodic,
                    scope=MemoryScope.workspace, content=content, summary=(content or "")[:80],
                    embedding_vector=vec))
            total_memories += len(contents)
            rt = MemoryRuntime(repo, default_workspace_id=ws, provider_registry=registry)
            run = await rt.start_run(StartRunRequest(session_id=f"lme-{qi}", task="recall", workspace_id=ws))
            step = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="answer"))
            contexts: dict[str, str] = {}
            precision: dict[str, Any] = {}
            for cond, strategy in _CONDITIONS:
                if strategy == RetrievalStrategy.baseline_0:
                    contexts[cond] = "(no memory provided)"
                    continue
                ctx = await rt.retrieve_context(RetrievalRequest(
                    run_id=run.run_id, step_id=step.step_id, query=rec["question"],
                    strategy=strategy, token_budget=token_budget, top_k=top_k))
                blocks = positive_blocks(ctx)
                contexts[cond] = "\n".join(f"- {b.content}" for b in blocks) or "(no relevant memory found)"
                precision[cond] = _precision(blocks, gold_texts)
            prepared.append({
                "qi": qi, "question": rec["question"], "gold": rec["gold"],
                "type": rec["type"], "abstention": rec["abstention"],
                "contexts": contexts, "precision": precision,
            })
        ingest_s = time.perf_counter() - t_ingest
        print(f"  Phase A done: {len(prepared)} questions, {total_memories} memories in {ingest_s:.0f}s", flush=True)

        # ---- Phase B: answer + judge (concurrent, LLM-bound, per-question resilient) ---- #
        sem = asyncio.Semaphore(concurrency)
        async with httpx.AsyncClient() as client:
            async def _one(item: dict[str, Any]) -> dict[str, Any]:
                by_condition: dict[str, Any] = {}
                for cond, _strategy in _CONDITIONS:
                    try:
                        async with sem:
                            pred = await _answer(item["contexts"][cond], item["question"], client, endpoint)
                            correct = await _judge(item["question"], item["gold"], pred, client, endpoint)
                        by_condition[cond] = {"answer": pred, "correct": correct}
                    except Exception as exc:  # noqa: BLE001 - a persistent failure counts as wrong, never crashes the run
                        by_condition[cond] = {"answer": f"<error: {type(exc).__name__}>", "correct": False, "error": True}
                return {**{k: item[k] for k in ("qi", "question", "gold", "type", "abstention", "precision")},
                        "by_condition": by_condition}
            rows = await asyncio.gather(*(_one(it) for it in prepared))

        payload = _aggregate(rows, resolved, endpoint, emb_cfg, total_memories, ingest_s, limit, max_sessions)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
            with open(os.path.join(output_dir, "longmemeval_bench_results.json"), "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2, ensure_ascii=False)
        return payload
    finally:
        await embed_client.aclose()


def _aggregate(rows, dataset, endpoint, emb_cfg, total_memories, ingest_s, limit, max_sessions) -> dict[str, Any]:
    conds = [c for c, _ in _CONDITIONS]
    agg = {c: {"correct": 0, "total": 0} for c in conds}
    by_type: dict[str, dict[str, dict[str, int]]] = {}
    abst = {c: {"correct": 0, "total": 0} for c in conds}
    prec = {c: {"tokens": 0, "distractor": 0.0, "gold_recall": 0.0, "n": 0} for c in ("plain_vector", "memtrace")}
    for r in rows:
        for c in conds:
            ok = int(r["by_condition"][c]["correct"])
            agg[c]["total"] += 1
            agg[c]["correct"] += ok
            tt = by_type.setdefault(r["type"], {x: {"correct": 0, "total": 0} for x in conds})
            tt[c]["total"] += 1
            tt[c]["correct"] += ok
            if r["abstention"]:
                abst[c]["total"] += 1
                abst[c]["correct"] += ok
        for c in ("plain_vector", "memtrace"):
            p = r["precision"].get(c)
            if p:
                prec[c]["tokens"] += p["injected_tokens"]
                prec[c]["distractor"] += p["distractor_rate"]
                if p["gold_recall"] is not None:
                    prec[c]["gold_recall"] += p["gold_recall"]
                    prec[c]["n"] += 1

    def acc(d):
        return round(d["correct"] / d["total"], 4) if d["total"] else 0.0

    n = len(rows) or 1
    return {
        "skipped": False,
        "dataset": str(dataset),
        "embedding": f"{emb_cfg['model']} ({EMBED_DIM}d, in-memory cosine index)",
        "endpoint": {"base_url": endpoint["base_url"], "model": endpoint["model"]},
        "sample_size": len(rows),
        "total_memories": total_memories,
        "ingest_seconds": round(ingest_s, 1),
        "config": {"limit": limit, "max_sessions": max_sessions},
        "accuracy": {c: acc(agg[c]) for c in conds},
        "accuracy_by_type": {t: {c: acc(tt[c]) for c in conds} for t, tt in sorted(by_type.items())},
        "abstention_accuracy": {c: acc(abst[c]) for c in conds},
        "abstention_n": abst["memtrace"]["total"],
        "context_precision": {
            c: {
                "avg_injected_tokens": round(prec[c]["tokens"] / n, 1),
                "avg_distractor_rate": round(prec[c]["distractor"] / n, 4),
                "avg_gold_recall": round(prec[c]["gold_recall"] / prec[c]["n"], 4) if prec[c]["n"] else None,
            } for c in ("plain_vector", "memtrace")
        },
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Real-dataset (LongMemEval) real-embedding + real-LLM benchmark")
    parser.add_argument("--dataset", help="Path to a longmemeval_*.json (or set MEMTRACE_LONGMEMEVAL_PATH)")
    parser.add_argument("--limit", type=int, default=300, help="questions to sample (stratified by type)")
    parser.add_argument("--max-sessions", type=int, default=8, help="haystack sessions ingested per question (gold always kept)")
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--token-budget", type=int, default=1600)
    parser.add_argument("--concurrency", type=int, default=6)
    parser.add_argument("--no-cache", action="store_true", help="do not reuse/write the embedding cache")
    parser.add_argument("--output-dir", default="reports")
    args = parser.parse_args()
    payload = asyncio.run(run_longmemeval_bench(
        args.dataset, limit=args.limit, max_sessions=args.max_sessions, top_k=args.top_k,
        token_budget=args.token_budget, concurrency=args.concurrency, output_dir=args.output_dir,
        use_cache=not args.no_cache))
    if payload.get("skipped"):
        print(f"longmemeval_bench skipped: {payload['reason']}")
        return 0
    print(f"dataset={payload['dataset']}  model={payload['endpoint']['model']}  "
          f"n={payload['sample_size']}  memories={payload['total_memories']}")
    for cond, a in payload["accuracy"].items():
        print(f"  {cond:>12}: accuracy={a:.1%}")
    print(f"  abstention (n={payload['abstention_n']}): "
          + "  ".join(f"{c}={payload['abstention_accuracy'][c]:.1%}" for c in payload["abstention_accuracy"]))
    print(f"  context precision: {json.dumps(payload['context_precision'])}")
    print(f"  by type: {json.dumps(payload['accuracy_by_type'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
