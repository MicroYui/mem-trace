"""Load driver for scripts/perf-scale.sh — drive concurrent POST
/v1/context/retrieve against a running MemTrace server and report throughput.

argv: <base_url> <concurrency> <total_requests>
env:  MEMTRACE_SCALE_RUN_ID, MEMTRACE_SCALE_STEP_ID (an existing run/step in PG)
Prints one line: 'rps=<n> p50=<ms> p95=<ms> errors=<n>'.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time

import httpx

QUERY = "which module holds the escalation value for the message broker"


async def main(base: str, conc: int, total: int) -> int:
    run_id = os.environ["MEMTRACE_SCALE_RUN_ID"]
    step_id = os.environ["MEMTRACE_SCALE_STEP_ID"]
    url = f"{base.rstrip('/')}/v1/context/retrieve"
    body = {"run_id": run_id, "step_id": step_id, "query": QUERY, "strategy": "variant_2"}

    sem = asyncio.Semaphore(conc)
    latencies: list[float] = []
    errors = 0

    async with httpx.AsyncClient(timeout=60, limits=httpx.Limits(max_connections=conc + 4)) as client:
        # warmup (fills pools / JITs the path; not measured)
        for _ in range(min(conc, 12)):
            try:
                await client.post(url, json=body)
            except Exception:  # noqa: BLE001
                pass

        async def one() -> None:
            nonlocal errors
            async with sem:
                t0 = time.perf_counter()
                try:
                    r = await client.post(url, json=body)
                    if r.status_code != 200:
                        errors += 1
                        return
                except Exception:  # noqa: BLE001
                    errors += 1
                    return
                latencies.append((time.perf_counter() - t0) * 1000.0)

        t_start = time.perf_counter()
        await asyncio.gather(*(one() for _ in range(total)))
        wall = time.perf_counter() - t_start

    ok = len(latencies)
    rps = ok / wall if wall > 0 else 0.0
    latencies.sort()
    p50 = latencies[int(0.50 * (ok - 1))] if ok else 0.0
    p95 = latencies[int(0.95 * (ok - 1))] if ok else 0.0
    print(f"rps={rps:.1f} p50={p50:.0f}ms p95={p95:.0f}ms errors={errors}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1], int(sys.argv[2]), int(sys.argv[3]))))
