"""Smoke test for the perf harness — structure only, never asserts wall-clock."""
from __future__ import annotations

import pytest

from app.benchmark.perf_bench import run_perf_bench


@pytest.mark.asyncio
async def test_perf_bench_returns_well_formed_results():
    payload = await run_perf_bench(sizes=[50, 120], trials=3, write_events=40, output_dir=None)
    rows = payload["retrieve_by_workspace_size"]
    assert [r["workspace_memories"] for r in rows] == [50, 120]
    for r in rows:
        assert r["retrieve_p50_ms"] >= 0.0
        assert r["retrieve_p95_ms"] >= r["retrieve_p50_ms"] - 1e-6 or r["trials"] < 5
    assert payload["write_throughput"]["events"] == 40
    assert payload["write_throughput"]["throughput_events_per_s"] > 0.0
