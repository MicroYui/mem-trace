"""Performance / scaling harness for the retrieval hot path (production-readiness).

Measures what the deterministic correctness benchmark does NOT: wall-clock cost.
Reports ``retrieve_context`` p50/p95 latency across growing workspace sizes and
``write_event`` throughput, over the default config (state-aware + gate, vector
on). It runs over the in-memory repository so it isolates the *algorithmic* cost
(no DB I/O) — which is exactly where the O(N) "load all workspace memories then
score in Python" growth shows up. A SQL backend adds I/O but the pgvector KNN is
indexed; the lexical/gate/pack path still scans the loaded candidate set.

Deterministic, no network, no LLM. This is a measurement tool, not a CI gate.

    uv run python -m app.benchmark.perf_bench --sizes 200,1000,5000,20000 --trials 30
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from statistics import median
from typing import Any

from app.providers.factory import deterministic_provider_registry
from app.runtime.memory_runtime import MemoryRuntime
from app.runtime.models import (
    EventRole,
    EventType,
    FinishStepRequest,
    MemoryItem,
    MemoryScope,
    MemoryType,
    RetrievalRequest,
    RetrievalStrategy,
    StartRunRequest,
    StartStepRequest,
    StepStatus,
    WriteEventRequest,
)
from app.runtime.repository import InMemoryRepository

_TOPICS = [
    "test runner", "database", "cache layer", "message broker", "cloud provider",
    "container runtime", "frontend framework", "css approach", "config format",
    "auth method", "linter", "type checker", "build tool", "http client", "orm",
    "template engine", "task queue", "api style", "logging library", "vector store",
]


def _mem(ws: str, i: int) -> MemoryItem:
    topic = _TOPICS[i % len(_TOPICS)]
    content = f"fact {i}: the {topic} for module {i} is value_{i} in the {topic} subsystem"
    return MemoryItem(
        memory_id=f"m_{i}",
        workspace_id=ws,
        memory_type=MemoryType.episodic,
        scope=MemoryScope.workspace,
        content=content,
        summary=content[:80],
    )


def _pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = min(len(s) - 1, int(q * len(s)))
    return round(s[idx], 3)


async def _seed(repo: InMemoryRepository, ws: str, n: int) -> None:
    for i in range(n):
        await repo.add_memory(_mem(ws, i))


async def measure_retrieve(sizes: list[int], trials: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for n in sizes:
        repo = InMemoryRepository()
        ws = "perf_ws"
        rt = MemoryRuntime(repo, default_workspace_id=ws, provider_registry=deterministic_provider_registry())
        run = await rt.start_run(StartRunRequest(session_id="perf", task="perf", workspace_id=ws))
        step = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="answer"))
        await _seed(repo, ws, n)
        # warmup
        for _ in range(3):
            await rt.retrieve_context(RetrievalRequest(
                run_id=run.run_id, step_id=step.step_id, query="what is the value for module 1",
                strategy=RetrievalStrategy.variant_2))
        latencies: list[float] = []
        for t in range(trials):
            q = f"what is the {_TOPICS[t % len(_TOPICS)]} value for module {(t * 7) % n}"
            t0 = time.perf_counter()
            await rt.retrieve_context(RetrievalRequest(
                run_id=run.run_id, step_id=step.step_id, query=q, strategy=RetrievalStrategy.variant_2))
            latencies.append((time.perf_counter() - t0) * 1000.0)
        rows.append({
            "workspace_memories": n,
            "trials": trials,
            "retrieve_p50_ms": round(median(latencies), 3),
            "retrieve_p95_ms": _pct(latencies, 0.95),
            "retrieve_max_ms": round(max(latencies), 3),
        })
    return rows


async def measure_write(n_events: int) -> dict[str, Any]:
    repo = InMemoryRepository()
    ws = "perf_ws"
    rt = MemoryRuntime(repo, default_workspace_id=ws, provider_registry=deterministic_provider_registry())
    run = await rt.start_run(StartRunRequest(session_id="perf", task="perf", workspace_id=ws))
    step = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="work"))
    t0 = time.perf_counter()
    for i in range(n_events):
        await rt.write_event(WriteEventRequest(
            run_id=run.run_id, step_id=step.step_id, role=EventRole.tool,
            event_type=EventType.tool_result, tool_name="bash", status="success",
            content=f"Confirmed the {_TOPICS[i % len(_TOPICS)]} is value_{i}."))
    elapsed = time.perf_counter() - t0
    await rt.finish_step(FinishStepRequest(run_id=run.run_id, step_id=step.step_id, status=StepStatus.completed))
    return {
        "events": n_events,
        "elapsed_s": round(elapsed, 3),
        "throughput_events_per_s": round(n_events / elapsed, 1) if elapsed else 0.0,
        "avg_ms_per_event": round(elapsed / n_events * 1000.0, 3) if n_events else 0.0,
    }


async def run_perf_bench(sizes: list[int], trials: int, write_events: int, output_dir: str | None) -> dict[str, Any]:
    retrieve = await measure_retrieve(sizes, trials)
    write = await measure_write(write_events)
    # scaling factor: how much p50 grows from smallest to largest workspace
    scaling = None
    if len(retrieve) >= 2 and retrieve[0]["retrieve_p50_ms"] > 0:
        scaling = round(retrieve[-1]["retrieve_p50_ms"] / retrieve[0]["retrieve_p50_ms"], 2)
    payload = {
        "config": "default (variant_2, vector on, in-memory repo)",
        "retrieve_by_workspace_size": retrieve,
        "retrieve_p50_scaling_factor_min_to_max": scaling,
        "write_throughput": write,
    }
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        with open(os.path.join(output_dir, "perf_bench_results.json"), "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Retrieval hot-path performance / scaling harness")
    parser.add_argument("--sizes", default="200,1000,5000,20000", help="comma-separated workspace sizes")
    parser.add_argument("--trials", type=int, default=30)
    parser.add_argument("--write-events", type=int, default=2000)
    parser.add_argument("--output-dir", default="reports")
    args = parser.parse_args()
    sizes = [int(s) for s in args.sizes.split(",") if s.strip()]
    payload = asyncio.run(run_perf_bench(sizes, args.trials, args.write_events, args.output_dir))
    print(f"config: {payload['config']}")
    print(f"{'workspace_memories':>18} | {'p50 ms':>8} | {'p95 ms':>8} | {'max ms':>8}")
    for r in payload["retrieve_by_workspace_size"]:
        print(f"{r['workspace_memories']:>18} | {r['retrieve_p50_ms']:>8} | {r['retrieve_p95_ms']:>8} | {r['retrieve_max_ms']:>8}")
    print(f"retrieve p50 scaling (min->max workspace): {payload['retrieve_p50_scaling_factor_min_to_max']}x")
    w = payload["write_throughput"]
    print(f"write_event: {w['throughput_events_per_s']} events/s ({w['avg_ms_per_event']} ms/event over {w['events']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
