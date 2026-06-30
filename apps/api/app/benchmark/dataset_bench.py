"""Dataset-driven retrieval evaluation: MemTrace vs plain-vector (ROADMAP §7).

Ingests LoCoMo / MemoryArena-style records — a set of facts (some superseded or
on a failed branch, to model temporal updates and distractors) plus QA probes
with gold *recall markers* — and measures, per strategy, how often the gold fact
reaches POSITIVE context (recall) and how often a superseded/failed distractor
leaks in. It contrasts a plain-vector/lexical baseline (``baseline_1``, no gate)
against the state-aware + gated path (``variant_2``) to quantify MemTrace's
recall/safety edge on the same seeded memory.

Fully deterministic: no LLM, no network. Scoring is marker presence in positive
context, consistent with the deterministic benchmark evaluator's recall metrics.
The committed sample ``data/sample_dataset.jsonl`` keeps the harness runnable and
testable with no external data; point ``--dataset`` / ``MEMTRACE_DATASET_PATH``
at a larger converted LoCoMo / MemoryArena JSONL file to evaluate at scale. The
record schema is documented in ``docs/benchmark.md``.

    uv run python -m app.benchmark.dataset_bench --output-dir reports
    MEMTRACE_DATASET_PATH=/data/locomo.jsonl uv run python -m app.benchmark.dataset_bench
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.providers.factory import deterministic_provider_registry
from app.runtime.context_actions import positive_blocks
from app.runtime.memory_runtime import MemoryRuntime
from app.runtime.models import (
    BranchStatus,
    MemoryItem,
    MemoryScope,
    MemoryStatus,
    MemoryType,
    RetrievalRequest,
    RetrievalStrategy,
    StartRunRequest,
    StartStepRequest,
)
from app.runtime.repository import InMemoryRepository

# The strategies we contrast: plain vector/lexical memory (no gate, no state
# awareness) vs the state-aware + gated MemTrace path, over identical seeds.
PLAIN_VECTOR = RetrievalStrategy.baseline_1
MEMTRACE = RetrievalStrategy.variant_2

_SAMPLE_PATH = Path(__file__).parent / "data" / "sample_dataset.jsonl"


class DatasetFact(BaseModel):
    """One seeded memory. `status="superseded"` models a temporal update; a
    `failed`/`rolled_back` branch_status models a distractor from a dead branch."""

    content: str
    key: str | None = None
    value: str | None = None
    memory_type: MemoryType = MemoryType.project
    status: MemoryStatus = MemoryStatus.active
    branch_status: BranchStatus = BranchStatus.completed


class DatasetProbe(BaseModel):
    question: str
    recall_markers: list[str] = Field(default_factory=list)
    distractor_markers: list[str] = Field(default_factory=list)


class DatasetRecord(BaseModel):
    id: str
    facts: list[DatasetFact]
    probes: list[DatasetProbe]


def load_dataset(path: str | os.PathLike[str] | None = None) -> list[DatasetRecord]:
    """Load and validate a JSONL dataset (one JSON record per line).

    Falls back to the committed sample when no path is given. Blank lines are
    ignored; a malformed line raises ``ValueError`` with its line number.
    """
    source = Path(path) if path is not None else _SAMPLE_PATH
    records: list[DatasetRecord] = []
    for lineno, line in enumerate(source.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            records.append(DatasetRecord.model_validate_json(stripped))
        except ValidationError as exc:  # pragma: no cover - exercised via test
            raise ValueError(f"invalid dataset record at {source}:{lineno}: {exc}") from exc
    return records


async def _seed_record(rt: MemoryRuntime, ws: str, record: DatasetRecord) -> tuple[str, str]:
    run = await rt.start_run(StartRunRequest(session_id=f"ds-{record.id}", task="recall probe", workspace_id=ws))
    for idx, fact in enumerate(record.facts):
        await rt._repo.add_memory(  # noqa: SLF001 - deterministic seeding, mirrors qa_bench
            MemoryItem(
                memory_id=f"mem_{record.id}_{idx}",
                workspace_id=ws,
                run_id=run.run_id,
                memory_type=fact.memory_type,
                scope=MemoryScope.workspace,
                key=fact.key,
                value=fact.value,
                content=fact.content,
                summary=fact.content[:80],
                status=fact.status,
                branch_status=fact.branch_status,
            )
        )
    step = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="recall", goal="answer the probe"))
    return run.run_id, step.step_id


def _recall_hit(text: str, markers: list[str]) -> bool:
    return bool(markers) and all(m.lower() in text for m in markers)


def _distractor_leak(text: str, markers: list[str]) -> bool:
    return any(m.lower() in text for m in markers)


async def _probe_strategy(rt: MemoryRuntime, run_id: str, step_id: str, probe: DatasetProbe, strategy: RetrievalStrategy) -> dict[str, Any]:
    ctx = await rt.retrieve_context(
        RetrievalRequest(run_id=run_id, step_id=step_id, query=probe.question, strategy=strategy)
    )
    text = " ".join(b.content.lower() for b in positive_blocks(ctx))
    has_recall_markers = bool(probe.recall_markers)
    has_distractors = bool(probe.distractor_markers)
    return {
        "recall_scored": has_recall_markers,
        "recall_hit": _recall_hit(text, probe.recall_markers),
        "distractor_scored": has_distractors,
        "distractor_leak": _distractor_leak(text, probe.distractor_markers),
    }


def _rate(hits: int, total: int) -> float:
    return round(hits / total, 6) if total else 0.0


async def run_dataset_bench(
    dataset_path: str | os.PathLike[str] | None = None,
    *,
    output_dir: str | None = "reports",
) -> dict[str, Any]:
    """Run every probe under both strategies and aggregate recall / leakage."""
    resolved = dataset_path or os.environ.get("MEMTRACE_DATASET_PATH") or None
    records = load_dataset(resolved)

    strategies = [PLAIN_VECTOR, MEMTRACE]
    agg: dict[str, dict[str, int]] = {
        s.value: {"recall_total": 0, "recall_hits": 0, "distractor_total": 0, "distractor_leaks": 0}
        for s in strategies
    }
    probe_results: list[dict[str, Any]] = []

    for record in records:
        for probe_idx, probe in enumerate(record.probes):
            row: dict[str, Any] = {"record_id": record.id, "probe_index": probe_idx, "question": probe.question, "by_strategy": {}}
            for strategy in strategies:
                # Fresh runtime per (record, strategy) so seeds are identical and
                # access bumps from one strategy never bleed into the next.
                repo = InMemoryRepository()
                rt = MemoryRuntime(repo, default_workspace_id="ds_ws", provider_registry=deterministic_provider_registry())
                run_id, step_id = await _seed_record(rt, "ds_ws", record)
                scored = await _probe_strategy(rt, run_id, step_id, probe, strategy)
                row["by_strategy"][strategy.value] = scored
                bucket = agg[strategy.value]
                if scored["recall_scored"]:
                    bucket["recall_total"] += 1
                    bucket["recall_hits"] += int(scored["recall_hit"])
                if scored["distractor_scored"]:
                    bucket["distractor_total"] += 1
                    bucket["distractor_leaks"] += int(scored["distractor_leak"])
            probe_results.append(row)

    by_strategy = {
        name: {
            "recall_rate": _rate(b["recall_hits"], b["recall_total"]),
            "recall_hits": b["recall_hits"],
            "recall_total": b["recall_total"],
            "distractor_leakage_rate": _rate(b["distractor_leaks"], b["distractor_total"]),
            "distractor_leaks": b["distractor_leaks"],
            "distractor_total": b["distractor_total"],
        }
        for name, b in agg.items()
    }
    plain = by_strategy[PLAIN_VECTOR.value]
    memtrace = by_strategy[MEMTRACE.value]
    payload: dict[str, Any] = {
        "dataset": str(resolved) if resolved else "builtin_sample",
        "record_count": len(records),
        "probe_count": len(probe_results),
        "by_strategy": by_strategy,
        "delta": {
            # Positive recall_rate_gain / leakage_reduction => MemTrace beats plain vector.
            "recall_rate_gain": round(memtrace["recall_rate"] - plain["recall_rate"], 6),
            "distractor_leakage_reduction": round(plain["distractor_leakage_rate"] - memtrace["distractor_leakage_rate"], 6),
        },
        "probes": probe_results,
    }
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        with open(os.path.join(output_dir, "dataset_bench_results.json"), "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Dataset-driven MemTrace vs plain-vector recall bench")
    parser.add_argument("--dataset", help="Path to a LoCoMo/MemoryArena-style JSONL file (default: built-in sample)")
    parser.add_argument("--output-dir", default="reports")
    args = parser.parse_args()
    payload = asyncio.run(run_dataset_bench(args.dataset, output_dir=args.output_dir))
    plain = payload["by_strategy"][PLAIN_VECTOR.value]
    memtrace = payload["by_strategy"][MEMTRACE.value]
    print(f"dataset: {payload['dataset']}  records={payload['record_count']}  probes={payload['probe_count']}")
    print(f"  plain-vector (baseline_1): recall={plain['recall_rate']}  distractor_leakage={plain['distractor_leakage_rate']}")
    print(f"  MemTrace     (variant_2) : recall={memtrace['recall_rate']}  distractor_leakage={memtrace['distractor_leakage_rate']}")
    print(f"  delta: recall_gain={payload['delta']['recall_rate_gain']}  leakage_reduction={payload['delta']['distractor_leakage_reduction']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
