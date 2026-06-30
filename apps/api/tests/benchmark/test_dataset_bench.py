"""Dataset-driven retrieval bench tests (ROADMAP §7).

Validates the LoCoMo/MemoryArena-style JSONL ingestion + the deterministic
MemTrace-vs-plain-vector recall / distractor-leakage scoring over the committed
sample, plus loader edge cases. Fully deterministic; no LLM, no network.
"""
from __future__ import annotations

import json

import pytest

from app.benchmark.dataset_bench import (
    MEMTRACE,
    PLAIN_VECTOR,
    DatasetRecord,
    load_dataset,
    run_dataset_bench,
)


def test_load_sample_dataset_parses_three_records():
    records = load_dataset()  # built-in sample
    assert [r.id for r in records] == ["temporal_update", "failed_branch_distractor", "multi_hop_stack"]
    assert all(isinstance(r, DatasetRecord) for r in records)
    assert records[0].facts[0].status.value == "superseded"


@pytest.mark.asyncio
async def test_dataset_bench_sample_quantifies_memtrace_edge():
    payload = await run_dataset_bench(output_dir=None)

    assert payload["dataset"] == "builtin_sample"
    assert payload["record_count"] == 3
    assert payload["probe_count"] == 3

    plain = payload["by_strategy"][PLAIN_VECTOR.value]
    memtrace = payload["by_strategy"][MEMTRACE.value]

    # Both recall the gold fact on this sample...
    assert plain["recall_rate"] == 1.0
    assert memtrace["recall_rate"] == 1.0
    # ...but plain vector leaks a failed-branch distractor that MemTrace gates.
    assert plain["distractor_leakage_rate"] == 0.5
    assert memtrace["distractor_leakage_rate"] == 0.0
    assert payload["delta"]["distractor_leakage_reduction"] == 0.5
    assert payload["delta"]["recall_rate_gain"] == 0.0

    # General invariants (robust if the sample grows): MemTrace never recalls
    # less and never leaks more than plain vector.
    assert memtrace["recall_rate"] >= plain["recall_rate"]
    assert memtrace["distractor_leakage_rate"] <= plain["distractor_leakage_rate"]


@pytest.mark.asyncio
async def test_failed_branch_probe_isolated_only_by_memtrace():
    payload = await run_dataset_bench(output_dir=None)
    failed = next(p for p in payload["probes"] if p["record_id"] == "failed_branch_distractor")
    # plain vector admits the failed "npm test" memory into positive context;
    # the gated path isolates it.
    assert failed["by_strategy"][PLAIN_VECTOR.value]["distractor_leak"] is True
    assert failed["by_strategy"][MEMTRACE.value]["distractor_leak"] is False
    # Both still recall the Bun fact.
    assert failed["by_strategy"][PLAIN_VECTOR.value]["recall_hit"] is True
    assert failed["by_strategy"][MEMTRACE.value]["recall_hit"] is True


@pytest.mark.asyncio
async def test_superseded_temporal_distractor_excluded_for_both(tmp_path):
    payload = await run_dataset_bench(output_dir=None)
    temporal = next(p for p in payload["probes"] if p["record_id"] == "temporal_update")
    # A superseded fact is lifecycle-filtered for every strategy, so neither leaks
    # the old endpoint, and both recall the current one.
    for strategy in (PLAIN_VECTOR.value, MEMTRACE.value):
        assert temporal["by_strategy"][strategy]["distractor_leak"] is False
        assert temporal["by_strategy"][strategy]["recall_hit"] is True


def test_load_dataset_from_custom_path(tmp_path):
    record = {
        "id": "custom",
        "facts": [{"content": "The CI runner is GitHub Actions.", "key": "ci.runner", "value": "github-actions"}],
        "probes": [{"question": "What CI runner?", "recall_markers": ["github-actions"]}],
    }
    path = tmp_path / "custom.jsonl"
    path.write_text(json.dumps(record) + "\n\n", encoding="utf-8")  # trailing blank line ignored

    records = load_dataset(path)
    assert len(records) == 1
    assert records[0].id == "custom"


def test_load_dataset_rejects_malformed_record(tmp_path):
    path = tmp_path / "bad.jsonl"
    path.write_text('{"id": "x", "facts": []}\n', encoding="utf-8")  # missing required "probes"

    with pytest.raises(ValueError, match=r"invalid dataset record at .*:1"):
        load_dataset(path)


@pytest.mark.asyncio
async def test_dataset_bench_writes_report(tmp_path):
    payload = await run_dataset_bench(output_dir=str(tmp_path))
    written = tmp_path / "dataset_bench_results.json"
    assert written.exists()
    assert json.loads(written.read_text(encoding="utf-8"))["probe_count"] == payload["probe_count"]
