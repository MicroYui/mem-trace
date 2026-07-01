"""Deterministic synthetic dataset generator for the scale benchmark (ROADMAP §7).

Produces thousands of LoCoMo / MemoryArena-style records (schema in
``docs/benchmark.md``, consumed by ``app.benchmark.dataset_bench``) that stress
the *real* difference between plain-vector retrieval and MemTrace's state-aware +
gated path: **dead-branch contamination**. Each record seeds a correct fact plus,
depending on category, a distractor the plain-vector baseline cannot tell apart:

  - ``failed`` / ``rolled_back`` branch distractors — a plausible wrong answer
    left behind by a dead execution branch. ``baseline_1`` (no state isolation)
    admits it; ``variant_2`` gates it. This is the differentiator.
  - ``superseded`` distractors — an outdated value. Both strategies drop it via
    the universal lifecycle filter, so it is an honesty control (neither leaks).
  - ``clean`` records — a correct fact with no distractor (recall-only control),
    so aggregate leakage is a real fraction, not a rigged 100%.

Fully deterministic: no randomness, no network, no LLM. The record ``id`` encodes
its category (``failed_00012``) so downstream reporting can break leakage down by
distractor type. Markers are substring-safe (dataset_bench scores by substring),
including across topics used as noise.

    uv run python -m app.benchmark.generate_dataset --count 3000 --out /tmp/scale.jsonl
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

# (subject phrase, correct value, wrong value). Values are chosen so that within
# a record neither marker is a substring of the other, and no wrong-value marker
# is a substring of any correct value (correct values are what noise facts carry,
# so a collision there would be a false-positive leak). Audited for containment.
TOPICS: list[tuple[str, str, str]] = [
    ("test runner", "bun", "npm"),
    ("dependency manager", "poetry", "pipenv"),
    ("primary database", "postgres", "mysql"),
    ("cache layer", "redis", "memcached"),
    ("message broker", "rabbitmq", "kafka"),
    ("cloud provider", "gcp", "azure"),
    ("container runtime", "podman", "dockerd"),
    ("frontend framework", "svelte", "ember"),
    ("css approach", "tailwind", "bootstrap"),
    ("config format", "toml", "yaml"),
    ("auth method", "oauth", "ldap"),
    ("python linter", "ruff", "pylint"),
    ("type checker", "mypy", "pyright"),
    ("build tool", "vite", "webpack"),
    ("http client", "httpx", "urllib"),
    ("orm layer", "sqlalchemy", "peewee"),
    ("template engine", "jinja", "mako"),
    ("task queue", "celery", "dramatiq"),
    ("api style", "graphql", "soap"),
    ("logging library", "structlog", "loguru"),
    ("date library", "pendulum", "delorean"),
    ("wire format", "msgpack", "protobuf"),
    ("vector store", "pgvector", "faiss"),
    ("deploy region", "us-west", "eu-central"),
]

_QUESTION_TEMPLATES = [
    "What is the {subject} for this project?",
    "Which {subject} should I use here?",
    "Remind me: what {subject} does this project use?",
    "I forget — what's the {subject} configured for this repo?",
]
_CORRECT_TEMPLATES = [
    "The {subject} for this project is {value}.",
    "This project's {subject} is {value}; use it everywhere.",
    "We standardized the {subject} on {value}.",
    "Decision: the {subject} is {value}.",
]
_FAILED_TEMPLATES = [
    "An earlier attempt set the {subject} to {value}, but that branch failed and was abandoned.",
    "Tried using {value} as the {subject}; it broke the build and the branch was rolled back.",
    "A dead branch had configured the {subject} as {value} before it was discarded.",
]
_SUPERSEDED_TEMPLATES = [
    "The {subject} used to be {value}, but that value is now outdated.",
    "Legacy note: the old {subject} was {value} (since replaced).",
]

# 20-slot category cycle => fixed proportions independent of --count.
# dead-branch distractors (the differentiator): failed 6 + rolled_back 3 + multi 2
# = 11 (55%). superseded 3 (15%, both lifecycle-filter). clean 3 (15%, no distractor).
# valid_on_failed 3 (15%): the CORRECT fact itself sits on a failed branch, so
# MemTrace's gate over-rejects it (its recall/precision COST) while plain vector
# recalls it — this is what makes the comparison a real tradeoff, not 0-vs-82.
_CATEGORY_CYCLE = (
    ["failed"] * 6 + ["rolled_back"] * 3 + ["multi"] * 2
    + ["superseded"] * 3 + ["clean"] * 3 + ["valid_on_failed"] * 3
)


def _noise_facts(index: int, subject: str) -> list[dict[str, Any]]:
    """1-2 irrelevant correct facts from other topics (share no subject terms)."""
    facts = []
    for offset in (5, 11):
        subj_n, correct_n, _ = TOPICS[(index + offset) % len(TOPICS)]
        if subj_n == subject:
            continue
        facts.append(
            {
                "content": f"Unrelated: the {subj_n} for this project is {correct_n}.",
                "memory_type": "project",
                "status": "active",
                "branch_status": "completed",
            }
        )
    return facts


def _record(index: int) -> dict[str, Any]:
    subject, correct, wrong = TOPICS[index % len(TOPICS)]
    category = _CATEGORY_CYCLE[index % len(_CATEGORY_CYCLE)]
    q = _QUESTION_TEMPLATES[index % len(_QUESTION_TEMPLATES)]
    correct_tpl = _CORRECT_TEMPLATES[index % len(_CORRECT_TEMPLATES)]

    correct_fact = {
        "key": f"topic.{subject.replace(' ', '_')}",
        "value": correct,
        "content": correct_tpl.format(subject=subject, value=correct),
        "memory_type": "project",
        "status": "active",
        "branch_status": "completed",
    }
    # valid_on_failed: the correct fact is only recorded on a branch that later
    # failed. Plain vector still recalls it; MemTrace's blanket failed-branch
    # isolation drops it too — a genuine recall cost of the safety mechanism.
    if category == "valid_on_failed":
        correct_fact["branch_status"] = "failed"
        correct_fact["memory_type"] = "tool_evidence"
    facts: list[dict[str, Any]] = [correct_fact]
    distractor_markers: list[str] = []

    if category in ("failed", "rolled_back", "multi"):
        branch = "rolled_back" if category == "rolled_back" else "failed"
        failed_tpl = _FAILED_TEMPLATES[index % len(_FAILED_TEMPLATES)]
        facts.append(
            {
                "content": failed_tpl.format(subject=subject, value=wrong),
                "memory_type": "tool_evidence",
                "status": "active",
                "branch_status": branch,
            }
        )
        distractor_markers.append(wrong)
        if category == "multi":
            # A second dead-branch distractor with a different wrong value.
            _, _, wrong2 = TOPICS[(index + 7) % len(TOPICS)]
            if wrong2 != wrong and wrong2 != correct:
                facts.append(
                    {
                        "content": f"A separate failed branch tried {wrong2} for the {subject}.",
                        "memory_type": "tool_evidence",
                        "status": "active",
                        "branch_status": "rolled_back",
                    }
                )
                distractor_markers.append(wrong2)
    elif category == "superseded":
        sup_tpl = _SUPERSEDED_TEMPLATES[index % len(_SUPERSEDED_TEMPLATES)]
        facts.append(
            {
                "key": f"topic.{subject.replace(' ', '_')}",
                "value": wrong,
                "content": sup_tpl.format(subject=subject, value=wrong),
                "memory_type": "project",
                "status": "superseded",
                "branch_status": "completed",
            }
        )
        distractor_markers.append(wrong)
    # clean: no distractor

    facts.extend(_noise_facts(index, subject))

    return {
        "id": f"{category}_{index:05d}",
        "facts": facts,
        "probes": [
            {
                "question": q.format(subject=subject),
                "recall_markers": [correct],
                "distractor_markers": distractor_markers,
            }
        ],
    }


def generate(count: int) -> list[dict[str, Any]]:
    """Deterministically generate ``count`` records (index-driven, no RNG)."""
    return [_record(i) for i in range(count)]


def write_jsonl(records: list[dict[str, Any]], path: str | Path) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a deterministic synthetic scale-benchmark dataset")
    parser.add_argument("--count", type=int, default=3000, help="number of records")
    parser.add_argument("--out", default="reports/scale_dataset.jsonl", help="output JSONL path")
    args = parser.parse_args()
    records = generate(args.count)
    write_jsonl(records, args.out)
    categories: dict[str, int] = {}
    for record in records:
        categories[record["id"].rsplit("_", 1)[0]] = categories.get(record["id"].rsplit("_", 1)[0], 0) + 1
    print(f"wrote {len(records)} records to {args.out}")
    print(f"category mix: {categories}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
