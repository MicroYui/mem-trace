"""Agentic real-trajectory benchmark — REAL SWE-agent traces, A/B contamination (opt-in).

This is the honest home-turf test: instead of synthetic markers, it ingests REAL
[SWE-agent](https://github.com/SWE-agent/SWE-agent) execution trajectories (agents
solving real SWE-bench GitHub issues) — sequences of (assistant action, tool
observation) turns that include genuinely FAILED shell commands (non-zero
``<returncode>``). Each failed command is finished as ``failed`` and its branch
rolled back, exactly as a live agent would; the successful commands stay on the
active path.

Then it runs a controlled **A/B** over the identical ingested memory:

  - **A = plain vector** (``baseline_1``): vector/lexical retrieval, no gate.
  - **B = MemTrace** (``variant_2``): state-aware retrieval + admission gate.

and measures **dead-branch contamination** — how many of the retrieved
positive-context blocks came from a *failed/rolled-back* command (a mistake the
agent already abandoned). A plain vector store re-surfaces those failed commands
because they're semantically similar; MemTrace's gate isolates them. Deterministic
(no LLM, no network beyond fetching the traces): the win is structural, driven by
``branch_status``, so the numbers are reproducible.

    ./scripts/fetch-swe-trajectories.sh                 # -> /tmp/swe_trajs/*.traj.json
    uv run python -m app.benchmark.agentic_trace_bench --dir /tmp/swe_trajs --output-dir reports
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
from pathlib import Path
from typing import Any

from app.runtime.context_actions import positive_blocks
from app.runtime.memory_runtime import MemoryRuntime
from app.runtime.models import (
    EventRole,
    EventType,
    FinishStepRequest,
    RetrievalRequest,
    RetrievalStrategy,
    RollbackRequest,
    StartRunRequest,
    StartStepRequest,
    StepStatus,
    WriteEventRequest,
)
from app.runtime.repository import InMemoryRepository

_RETURNCODE = re.compile(r"<returncode>\s*(-?\d+)\s*</returncode>")
_CONDITIONS = [("plain_vector", RetrievalStrategy.baseline_1), ("memtrace", RetrievalStrategy.variant_2)]


# --------------------------------------------------------------------------- #
# Parse mini-swe-agent trajectories
# --------------------------------------------------------------------------- #
def parse_trajectory(traj: dict[str, Any]) -> list[dict[str, Any]]:
    """Pair each assistant action with the following tool observation. Failed steps
    are those whose observation reports a non-zero ``<returncode>``."""
    messages = traj.get("messages") or []
    steps: list[dict[str, Any]] = []
    pending_action: str | None = None
    for msg in messages:
        role, content = msg.get("role"), (msg.get("content") or "")
        if role == "assistant":
            pending_action = content.strip()
        elif role == "tool" and pending_action is not None:
            m = _RETURNCODE.search(content)
            rc = int(m.group(1)) if m else 0
            failed = rc != 0
            steps.append({
                "action": pending_action[:600],
                "observation": content.strip()[:1200],
                "returncode": rc,
                "failed": failed,
            })
            pending_action = None
    return steps


def load_trajectories(directory: str) -> list[tuple[str, dict[str, Any]]]:
    out: list[tuple[str, dict[str, Any]]] = []
    for p in sorted(Path(directory).glob("*.traj.json")):
        try:
            out.append((p.stem.replace(".traj", ""), json.loads(p.read_text(encoding="utf-8"))))
        except Exception:  # noqa: BLE001 - skip an unparseable file, don't abort
            continue
    return out


# --------------------------------------------------------------------------- #
# Ingest into MemTrace + A/B retrieval
# --------------------------------------------------------------------------- #
async def _ingest(rt: MemoryRuntime, ws: str, instance_id: str, steps: list[dict[str, Any]]):
    """Drive the real runtime: each step is a tool call+result; failed steps are
    finished ``failed`` and rolled back. Returns (run_id, probe_step_id, failed_mem_ids,
    success_mem_ids)."""
    run = await rt.start_run(StartRunRequest(session_id=instance_id, task="resolve the issue", workspace_id=ws))
    failed_mem_ids: set[str] = set()
    success_mem_ids: set[str] = set()
    last_failed: str | None = None
    for i, step in enumerate(steps):
        s = await rt.start_step(StartStepRequest(
            run_id=run.run_id, intent=f"step {i}: {step['action'][:60]}",
            recovery_from_step_id=last_failed))
        await rt.write_event(WriteEventRequest(
            run_id=run.run_id, step_id=s.step_id, role=EventRole.assistant,
            event_type=EventType.tool_call, tool_name="bash", content=step["action"]))
        res = await rt.write_event(WriteEventRequest(
            run_id=run.run_id, step_id=s.step_id, role=EventRole.tool,
            event_type=EventType.tool_result, tool_name="bash", content=step["observation"],
            status="failed" if step["failed"] else "success"))
        mem_ids = list(res.created_memory_ids or [])
        if step["failed"]:
            await rt.finish_step(FinishStepRequest(
                run_id=run.run_id, step_id=s.step_id, status=StepStatus.failed,
                error_message=f"returncode={step['returncode']}"))
            await rt.rollback_branch(RollbackRequest(run_id=run.run_id, step_id=s.step_id, reason="command failed"))
            failed_mem_ids.update(mem_ids)
            last_failed = s.step_id
        else:
            await rt.finish_step(FinishStepRequest(run_id=run.run_id, step_id=s.step_id, status=StepStatus.completed))
            success_mem_ids.update(mem_ids)
    probe = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="review what we tried"))
    return run.run_id, probe.step_id, failed_mem_ids, success_mem_ids


async def run_agentic_trace_bench(directory: str, *, limit: int = 0, top_k: int = 12,
                                  token_budget: int = 1200, output_dir: str | None = "reports") -> dict[str, Any]:
    trajs = load_trajectories(directory)
    if not trajs:
        return {"skipped": True, "reason": f"no *.traj.json under {directory} (run scripts/fetch-swe-trajectories.sh)"}
    if limit > 0:
        trajs = trajs[:limit]

    agg = {c: {"contam_blocks": 0, "total_blocks": 0, "contaminated_probes": 0, "recall_hit": 0,
               "tokens": 0, "probes": 0} for c, _ in _CONDITIONS}
    rows: list[dict[str, Any]] = []
    total_steps = total_failed = 0
    for instance_id, traj in trajs:
        steps = parse_trajectory(traj)
        n_failed = sum(1 for s in steps if s["failed"])
        total_steps += len(steps)
        total_failed += n_failed
        if not steps:
            continue
        repo = InMemoryRepository()
        ws = f"swe_{instance_id}"
        rt = MemoryRuntime(repo, default_workspace_id=ws)
        run_id, step_id, failed_ids, success_ids = await _ingest(rt, ws, instance_id, steps)
        # Probe: recall the commands that were run for this issue (surfaces tool evidence).
        query = "what shell commands were run to investigate and fix this issue and what were the results"
        row: dict[str, Any] = {"instance_id": instance_id, "steps": len(steps), "failed_steps": n_failed,
                               "by_condition": {}}
        for cond, strategy in _CONDITIONS:
            ctx = await rt.retrieve_context(RetrievalRequest(
                run_id=run_id, step_id=step_id, query=query, strategy=strategy,
                token_budget=token_budget, top_k=top_k))
            blocks = positive_blocks(ctx)
            contam = sum(1 for b in blocks if b.memory_id in failed_ids)
            recall = any(b.memory_id in success_ids for b in blocks)
            tokens = sum(b.tokens or 0 for b in ctx.context_blocks)
            a = agg[cond]
            a["contam_blocks"] += contam
            a["total_blocks"] += len(blocks)
            a["contaminated_probes"] += int(contam > 0)
            a["recall_hit"] += int(recall)
            a["tokens"] += tokens
            a["probes"] += 1
            row["by_condition"][cond] = {"blocks": len(blocks), "failed_blocks": contam, "recall_hit": recall}
        rows.append(row)

    payload = _aggregate(agg, rows, len(trajs), total_steps, total_failed, top_k)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        with open(os.path.join(output_dir, "agentic_trace_bench_results.json"), "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
    return payload


def _aggregate(agg, rows, n_traj, total_steps, total_failed, top_k) -> dict[str, Any]:
    def rate(num, den):
        return round(num / den, 4) if den else 0.0

    conds = {}
    for c, _ in _CONDITIONS:
        a = agg[c]
        conds[c] = {
            "contamination_rate": rate(a["contaminated_probes"], a["probes"]),        # any failed cmd leaked
            "failed_block_share": rate(a["contam_blocks"], a["total_blocks"]),         # fraction of context that's a mistake
            "recall_rate": rate(a["recall_hit"], a["probes"]),                          # a successful cmd still surfaced
            "avg_context_tokens": rate(a["tokens"], a["probes"]),
        }
    delta = {
        "contamination_reduction": round(conds["plain_vector"]["contamination_rate"]
                                         - conds["memtrace"]["contamination_rate"], 4),
        "failed_block_share_reduction": round(conds["plain_vector"]["failed_block_share"]
                                              - conds["memtrace"]["failed_block_share"], 4),
        "recall_delta": round(conds["memtrace"]["recall_rate"] - conds["plain_vector"]["recall_rate"], 4),
    }
    return {
        "skipped": False,
        "source": "SWE-agent (mini-swe-agent) real trajectories",
        "trajectories": n_traj,
        "total_steps": total_steps,
        "total_failed_steps": total_failed,
        "top_k": top_k,
        "by_condition": conds,
        "delta": delta,
        "rows": rows,
    }


def main() -> int:
    p = argparse.ArgumentParser(description="Agentic real-trajectory (SWE-agent) A/B contamination benchmark")
    p.add_argument("--dir", default=os.environ.get("MEMTRACE_SWE_DIR", "/tmp/swe_trajs"))
    p.add_argument("--limit", type=int, default=0, help="max trajectories (0 = all)")
    p.add_argument("--top-k", type=int, default=12)
    p.add_argument("--token-budget", type=int, default=1200)
    p.add_argument("--output-dir", default="reports")
    a = p.parse_args()
    payload = asyncio.run(run_agentic_trace_bench(a.dir, limit=a.limit, top_k=a.top_k,
                                                  token_budget=a.token_budget, output_dir=a.output_dir))
    if payload.get("skipped"):
        print(f"agentic_trace_bench skipped: {payload['reason']}")
        return 0
    print(f"source={payload['source']}  trajectories={payload['trajectories']}  "
          f"steps={payload['total_steps']} (failed={payload['total_failed_steps']})")
    for c, _ in _CONDITIONS:
        cc = payload["by_condition"][c]
        print(f"  {c:>12}: contamination={cc['contamination_rate']:.1%}  "
              f"failed_block_share={cc['failed_block_share']:.1%}  recall={cc['recall_rate']:.1%}  "
              f"ctx_tokens={cc['avg_context_tokens']:.0f}")
    d = payload["delta"]
    print(f"  A/B delta: contamination -{d['contamination_reduction']:.1%}  "
          f"failed_share -{d['failed_block_share_reduction']:.1%}  recall {d['recall_delta']:+.1%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
