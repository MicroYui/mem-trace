"""Real-dataset (LoCoMo) real-LLM benchmark (opt-in, network + LLM required).

This is the "real benchmark" counterpart to the deterministic synthetic suites:
it runs the actual LoCoMo long-conversation QA dataset through MemTrace with a
real LLM answering and a real LLM judge, so the numbers come from real data and a
real model rather than substring markers.

For each sampled question it seeds the conversation's turns as episodic memories,
then answers under three conditions over identical seeds:

  - ``no_memory``   (``baseline_0``) — the LLM answers with no context (control).
  - ``plain_vector``(``baseline_1``) — lexical/vector retrieval, no admission gate.
  - ``memtrace``    (``variant_2``)  — state-aware retrieval + admission gate.

A separate LLM judge grades each answer against the gold answer. Accuracy is
reported overall and per LoCoMo category.

HONEST SCOPE: LoCoMo is *conversational* memory (long-horizon recall, temporal
reasoning), so it does not exercise MemTrace's distinctive **agentic** edge
(failed-branch / dead-branch isolation) — that is what the synthetic suite
isolates. Retrieval here also uses the deterministic/lexical vector (this
environment has no real embedding endpoint). So expect: memory >> no-memory, and
MemTrace competitive with plain vector on this data. This harness proves the
pipeline on real data + a real model; it is not a leaderboard submission.

    # get the dataset (≈? MB):
    #   curl -L https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json -o locomo10.json
    MEMTRACE_LLM_API_KEY=... MEMTRACE_LLM_BASE_URL=http://localhost:4141/v1 \
      MEMTRACE_LLM_MODEL=gpt-5.4 MEMTRACE_LOCOMO_PATH=locomo10.json \
      uv run python -m app.benchmark.locomo_bench --limit 30 --output-dir reports
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Any

import httpx

from app.benchmark.llm_bench import _resolve_endpoints
from app.benchmark.qa_bench import _chat
from app.providers.factory import deterministic_provider_registry
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

_CONDITIONS = [
    ("no_memory", RetrievalStrategy.baseline_0),
    ("plain_vector", RetrievalStrategy.baseline_1),
    ("memtrace", RetrievalStrategy.variant_2),
]
# LoCoMo answer categories (per the dataset paper).
_CATEGORY_NAME = {1: "multi_hop", 2: "temporal", 3: "open_domain", 4: "single_hop", 5: "adversarial"}

_ANSWER_SYSTEM = (
    "You answer questions about a long conversation using ONLY the provided memory "
    "snippets. Be concise (a few words). If the memory does not contain the answer, "
    "reply exactly: No information available."
)
_JUDGE_SYSTEM = (
    "You grade a predicted answer against a gold answer for a conversation-QA task. "
    "Reply with exactly one word: CORRECT if the prediction captures the gold "
    "answer's key fact (allowing paraphrase, date formatting, or extra words), else "
    "INCORRECT. For gold answers indicating the info is not available/unanswerable, "
    "an abstention like 'No information available' is CORRECT."
)


def load_locomo(path: str | os.PathLike[str]) -> list[dict[str, Any]]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _conversation_memories(sample: dict[str, Any]) -> list[MemoryItem]:
    """Seed each dialog turn as one episodic memory, tagged with its date."""
    conv = sample["conversation"]
    ws = f"locomo_{sample.get('sample_id', 's')}"
    memories: list[MemoryItem] = []
    for key in sorted(k for k in conv if k.startswith("session_") and not k.endswith("date_time")):
        turns = conv[key]
        if not isinstance(turns, list):
            continue
        date = conv.get(f"{key}_date_time", "")
        for turn in turns:
            text = (turn.get("text") or "").strip()
            if not text:
                continue
            dia = turn.get("dia_id", f"{key}_{len(memories)}")
            memories.append(
                MemoryItem(
                    memory_id=f"mem_{ws}_{dia}",
                    workspace_id=ws,
                    memory_type=MemoryType.episodic,
                    scope=MemoryScope.workspace,
                    content=f"[{date}] {turn.get('speaker', '?')}: {text}",
                    summary=text[:80],
                )
            )
    return memories


def _sample_questions(sample: dict[str, Any], per_category: int) -> list[dict[str, Any]]:
    """Deterministic stratified sample: first ``per_category`` QA of each category."""
    seen: dict[int, int] = {}
    picked: list[dict[str, Any]] = []
    for qa in sample.get("qa", []):
        if "answer" not in qa or not qa.get("question"):
            continue
        cat = qa.get("category", 0)
        if seen.get(cat, 0) >= per_category:
            continue
        seen[cat] = seen.get(cat, 0) + 1
        picked.append(qa)
    return picked


async def _answer(rt, run_id, step_id, question: str, strategy: RetrievalStrategy, client, endpoint) -> str:
    if strategy == RetrievalStrategy.baseline_0:
        context = "(no memory provided)"
    else:
        ctx = await rt.retrieve_context(
            RetrievalRequest(run_id=run_id, step_id=step_id, query=question, strategy=strategy, token_budget=1200, top_k=14)
        )
        blocks = positive_blocks(ctx)
        context = "\n".join(f"- {b.content}" for b in blocks) or "(no relevant memory found)"
    prompt = f"Memory snippets:\n{context}\n\nQuestion: {question}\nAnswer concisely:"
    return await _chat(client, endpoint, _ANSWER_SYSTEM, prompt)


async def _judge(client, endpoint, question: str, gold: str, prediction: str) -> bool:
    prompt = (
        f"Question: {question}\nGold answer: {gold}\nPredicted answer: {prediction}\n\n"
        "Is the prediction CORRECT or INCORRECT?"
    )
    verdict = (await _chat(client, endpoint, _JUDGE_SYSTEM, prompt)).strip().upper()
    return verdict.startswith("CORRECT")


async def run_locomo_bench(
    dataset_path: str | os.PathLike[str] | None = None,
    *,
    limit: int = 30,
    per_category: int = 3,
    output_dir: str | None = "reports",
) -> dict[str, Any]:
    endpoints = _resolve_endpoints()
    resolved = dataset_path or os.environ.get("MEMTRACE_LOCOMO_PATH")
    if not endpoints or not resolved or not Path(resolved).exists():
        return {"skipped": True, "reason": (
            "Needs MEMTRACE_LLM_API_KEY (+ MEMTRACE_LLM_BASE_URL/MODEL) and a LoCoMo "
            "JSON at MEMTRACE_LOCOMO_PATH / --dataset (download locomo10.json first)."
        )}
    endpoint = endpoints[0]
    samples = load_locomo(resolved)

    # Build a flat, deterministic (conversation, qa) worklist up to `limit`.
    worklist: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for sample in samples:
        for qa in _sample_questions(sample, per_category):
            worklist.append((sample, qa))
            if len(worklist) >= limit:
                break
        if len(worklist) >= limit:
            break

    # Pre-seed each needed conversation once per condition (fresh repo per condition).
    conv_ids = {s.get("sample_id", id(s)) for s, _ in worklist}
    runtimes: dict[tuple[Any, str], tuple[Any, str, str]] = {}
    for sample in samples:
        sid = sample.get("sample_id", id(sample))
        if sid not in conv_ids:
            continue
        mems = _conversation_memories(sample)
        for cond, _strategy in _CONDITIONS:
            repo = InMemoryRepository()
            rt = MemoryRuntime(repo, default_workspace_id=f"locomo_{sid}", provider_registry=deterministic_provider_registry())
            for m in mems:
                await repo.add_memory(m)
            run = await rt.start_run(StartRunRequest(session_id=f"loco-{sid}-{cond}", task="conversation QA", workspace_id=f"locomo_{sid}"))
            step = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="answer"))
            runtimes[(sid, cond)] = (rt, run.run_id, step.step_id)

    agg = {cond: {"correct": 0, "total": 0} for cond, _ in _CONDITIONS}
    by_cat: dict[str, dict[str, dict[str, int]]] = {}
    rows: list[dict[str, Any]] = []
    async with httpx.AsyncClient() as client:
        for sample, qa in worklist:
            sid = sample.get("sample_id", id(sample))
            gold, question = str(qa.get("answer")), qa["question"]
            cat = _CATEGORY_NAME.get(qa.get("category"), "other")
            row: dict[str, Any] = {"sample_id": sid, "category": cat, "question": question, "gold": gold, "by_condition": {}}
            for cond, strategy in _CONDITIONS:
                rt, run_id, step_id = runtimes[(sid, cond)]
                pred = await _answer(rt, run_id, step_id, question, strategy, client, endpoint)
                correct = await _judge(client, endpoint, question, gold, pred)
                row["by_condition"][cond] = {"answer": pred, "correct": correct}
                agg[cond]["total"] += 1
                agg[cond]["correct"] += int(correct)
                cc = by_cat.setdefault(cat, {c: {"correct": 0, "total": 0} for c, _ in _CONDITIONS})
                cc[cond]["total"] += 1
                cc[cond]["correct"] += int(correct)
            rows.append(row)

    def _acc(d: dict[str, int]) -> float:
        return round(d["correct"] / d["total"], 4) if d["total"] else 0.0

    payload = {
        "skipped": False,
        "dataset": str(resolved),
        "endpoint": {"base_url": endpoint["base_url"], "model": endpoint["model"]},
        "sample_size": len(rows),
        "accuracy": {cond: _acc(agg[cond]) for cond, _ in _CONDITIONS},
        "accuracy_by_category": {
            cat: {cond: _acc(cc[cond]) for cond, _ in _CONDITIONS} for cat, cc in sorted(by_cat.items())
        },
        "rows": rows,
    }
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        with open(os.path.join(output_dir, "locomo_bench_results.json"), "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Real-dataset (LoCoMo) real-LLM benchmark")
    parser.add_argument("--dataset", help="Path to locomo10.json (or set MEMTRACE_LOCOMO_PATH)")
    parser.add_argument("--limit", type=int, default=30, help="max questions across conversations")
    parser.add_argument("--per-category", type=int, default=3, help="questions per category per conversation")
    parser.add_argument("--output-dir", default="reports")
    args = parser.parse_args()
    payload = asyncio.run(run_locomo_bench(args.dataset, limit=args.limit, per_category=args.per_category, output_dir=args.output_dir))
    if payload.get("skipped"):
        print(f"locomo_bench skipped: {payload['reason']}")
        return 0
    print(f"dataset: {payload['dataset']}  model={payload['endpoint']['model']}  n={payload['sample_size']}")
    for cond, acc in payload["accuracy"].items():
        print(f"  {cond:>12}: accuracy={acc:.1%}")
    print(f"  by category: {json.dumps(payload['accuracy_by_category'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
