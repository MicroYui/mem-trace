"""Structural tests for longmemeval_bench (no network, no model, no DB).

These lock the pure dataset-shaping + metric helpers and the clean-skip contract so
the opt-in real benchmark never breaks the default no-network suite.
"""
from __future__ import annotations

import asyncio
from collections import Counter
from types import SimpleNamespace

from app.benchmark import longmemeval_bench as lme


def _question(qid: str, qtype: str, sessions, session_ids, answer_ids, answer="a") -> dict:
    return {
        "question_id": qid,
        "question_type": qtype,
        "question": f"q for {qid}",
        "answer": answer,
        "haystack_sessions": sessions,
        "haystack_session_ids": session_ids,
        "haystack_dates": [f"d{i}" for i in range(len(sessions))],
        "answer_session_ids": answer_ids,
    }


def test_is_abstention():
    assert lme.is_abstention({"question_id": "x_abs"}) is True
    assert lme.is_abstention({"question_id": "x"}) is False


def test_stratified_sample_is_even_and_deterministic():
    data = [_question(f"k{i}", "knowledge-update", [], [], []) for i in range(5)]
    data += [_question(f"t{i}", "temporal-reasoning", [], [], []) for i in range(5)]
    picked = lme.stratified_sample(data, 6)
    counts = Counter(q["question_type"] for q in picked)
    assert counts["knowledge-update"] == 3 and counts["temporal-reasoning"] == 3
    assert lme.stratified_sample(data, 6) == picked  # deterministic


def test_select_sessions_always_keeps_gold_then_fills_distractors():
    sessions = [[{"role": "user", "content": f"s{i}"}] for i in range(6)]
    sids = [f"sid_{i}" for i in range(6)]
    q = _question("q1", "multi-session", sessions, sids, answer_ids={"sid_4"})
    chosen = lme.select_sessions(q, max_sessions=3)
    assert 4 in chosen  # the gold session is always included
    assert len(chosen) == 3


def test_build_memories_maps_turns_and_flags_gold():
    sessions = [[
        {"role": "user", "content": "hello there", "has_answer": "False"},
        {"role": "assistant", "content": "the answer is 42", "has_answer": "True"},
    ]]
    q = _question("q1", "single-session-user", sessions, ["sid_0"], answer_ids={"sid_0"})
    mems, gold = lme.build_memories(q, "lme_0", chosen=[0])
    assert len(mems) == 2
    assert all(m.workspace_id == "lme_0" for m in mems)
    assert gold == ["the answer is 42"]  # only the has_answer turn is gold
    assert "the answer is 42" in mems[1].content


def test_precision_counts_distractors_and_gold_recall():
    blocks = [
        SimpleNamespace(content="[d0] assistant: the answer is 42"),  # gold
        SimpleNamespace(content="[d1] user: unrelated chatter"),       # distractor
        SimpleNamespace(content="[d2] user: more noise"),              # distractor
    ]
    p = lme._precision(blocks, gold_texts=["the answer is 42"])
    assert p["blocks"] == 3
    assert p["gold_recall"] == 1.0
    assert round(p["distractor_rate"], 2) == round(2 / 3, 2)
    assert p["injected_tokens"] > 0


def test_precision_no_gold_returns_none_recall():
    p = lme._precision([SimpleNamespace(content="noise")], gold_texts=[])
    assert p["gold_recall"] is None


def test_run_skips_cleanly_without_llm_env_or_dataset(monkeypatch):
    # No MEMTRACE_LLM_* env -> no endpoints -> skip before any DB/model/network use.
    for var in ("MEMTRACE_LLM_API_KEY", "MEMTRACE_LLM_BASE_URL", "MEMTRACE_LLM_MODEL"):
        monkeypatch.delenv(var, raising=False)
    out = asyncio.run(lme.run_longmemeval_bench("/nonexistent/longmemeval.json", limit=1))
    assert out["skipped"] is True
    assert "LongMemEval" in out["reason"] or "MEMTRACE_LLM" in out["reason"]
