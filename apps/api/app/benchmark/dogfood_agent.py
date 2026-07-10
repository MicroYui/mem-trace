"""Dogfooding A/B — does MemTrace stop a real coding agent repeating a mistake? (opt-in)

A minimal but REAL coding-agent loop (a real LLM proposes shell commands, a sandboxed
executor runs them, results are recorded to MemTrace) run as a controlled **A/B**:

  - Phase 1 (learn): the agent solves a task in project #1. The obvious first move —
    running ``./check.sh`` — FAILS, because the project must be initialized with
    ``./setup.sh`` first; that prerequisite is stated nowhere in a readable file, only
    in the check's runtime failure output. So the agent learns it by *trying*, and the
    failed command + the working ``setup -> check`` sequence are recorded to MemTrace.
  - Phase 2 (test): a *fresh* agent solves the same-shaped task in a fresh project,
    twice:
      * **A = no memory** — no prior context, so it tends to run the check first and
        stumble on the same trap.
      * **B = MemTrace** — it first retrieves the lesson and sets up before checking.
    We measure, over N trials, how often each **stumbles** (runs a command that fails)
    and how many steps each takes to succeed.

If MemTrace works, B avoids the mistake it made (and recorded) in phase 1 and solves
in fewer steps than A.

Safety: the executor runs in a throwaway temp dir with a timeout and a deny-list for
destructive commands; it is not a general shell. Needs an LLM endpoint (MEMTRACE_LLM_*).

    MEMTRACE_LLM_API_KEY=local MEMTRACE_LLM_BASE_URL=http://localhost:4141/v1 \
      MEMTRACE_LLM_MODEL=gpt-5.4 uv run python -m app.benchmark.dogfood_agent --output-dir reports
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import httpx

from app.benchmark.llm_bench import _resolve_endpoints
from app.benchmark.qa_bench import _chat
from app.runtime.context_actions import positive_blocks
from app.runtime.memory_runtime import MemoryRuntime
from app.runtime.models import (
    EventRole,
    EventType,
    FinishStepRequest,
    RetrievalRequest,
    RetrievalStrategy,
    StartRunRequest,
    StartStepRequest,
    StepStatus,
    WriteEventRequest,
)
from app.runtime.repository import InMemoryRepository

# Deny-list: block obviously destructive / exfiltrating commands. The scenario only
# needs ls/cat/setup.sh/check.sh, so this never rejects a legitimate step.
_DENY = re.compile(
    r"\b(rm\s+-|sudo|mkfs|dd\s+if=|:\s*\(\s*\)|chmod\s+-R|chown\s+-R|curl|wget|nc\s|ncat|"
    r"scp|ssh|>\s*/dev/|/etc/|~/\.ssh|shutdown|reboot|kill\s+-9\s+1)\b",
    re.IGNORECASE,
)


def _make_project(root: str) -> str:
    """A throwaway project whose check.sh only passes AFTER ./setup.sh has been run
    (it creates a ``.ready`` marker). The prerequisite is NOT stated in any readable
    file — check.sh only tests for ``.ready`` — so an agent learns it by *running* the
    check and reading the runtime failure, exactly the kind of lesson MemTrace can
    carry forward. The obvious first move ("run the check") therefore fails once,
    until the agent knows to set up first."""
    d = tempfile.mkdtemp(prefix="dogfood_", dir=root)
    Path(d, "check.sh").write_text(
        '#!/usr/bin/env bash\n'
        'if [ -f .ready ]; then echo "PASS: checks green"; exit 0; fi\n'
        'echo "FAIL: project not initialized. run ./setup.sh first, then re-run this check." >&2\n'
        'exit 1\n',
        encoding="utf-8",
    )
    Path(d, "setup.sh").write_text('#!/usr/bin/env bash\ntouch .ready\necho "setup complete"\n', encoding="utf-8")
    Path(d, "README.md").write_text("Verify this project by running ./check.sh — it should print PASS.\n", encoding="utf-8")
    for f in ("check.sh", "setup.sh"):
        os.chmod(Path(d, f), 0o755)
    return d


def _execute(cmd: str, cwd: str, timeout: int = 10) -> tuple[int, str]:
    """Sandboxed executor: temp cwd, timeout, deny-list. Returns (returncode, output)."""
    if _DENY.search(cmd):
        return 126, "blocked by safety policy (destructive/exfiltrating command refused)"
    try:
        p = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        out = (p.stdout or "") + (p.stderr or "")
        return p.returncode, out.strip()[:800]
    except subprocess.TimeoutExpired:
        return 124, "command timed out"
    except Exception as exc:  # noqa: BLE001
        return 1, f"execution error: {type(exc).__name__}: {exc}"


_AGENT_SYSTEM = (
    "You are an autonomous coding agent working in a shell. Each turn, output EXACTLY ONE "
    "shell command (no prose, no backticks) to make progress on the task. You see prior "
    "commands and their output. If a MEMORY section is provided, it records what worked or "
    "failed in past sessions — use it and DO NOT repeat approaches it shows as failed. When "
    "the task is already accomplished, output exactly: DONE"
)


async def _propose(client, endpoint, task: str, history: list[str], memory: str) -> str:
    mem_block = f"\nMEMORY (past sessions):\n{memory}\n" if memory else ""
    hist = "\n".join(history[-8:]) or "(no commands yet)"
    prompt = f"Task: {task}\n{mem_block}\nSession so far:\n{hist}\n\nNext single shell command:"
    # Retry transient errors / empty responses (some models, e.g. gemini, occasionally
    # return a 5xx or an empty completion) so a flaky call doesn't drop a whole trial.
    raw = ""
    last_exc: Exception | None = None
    for attempt in range(4):
        try:
            raw = (await _chat(client, endpoint, _AGENT_SYSTEM, prompt)).strip()
            if raw:
                break
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
        await asyncio.sleep(1.0 * (attempt + 1))
    if not raw:
        if last_exc is not None:
            raise last_exc
        return "DONE"
    if raw.startswith("```"):  # strip a markdown code fence + any language tag line
        raw = "\n".join(ln for ln in raw.splitlines() if not ln.strip().startswith("```")).strip()
    for line in raw.splitlines():
        line = line.strip().lstrip("$ ").strip()
        if line:
            return line
    return "DONE"


async def _run_agent(client, endpoint, rt: MemoryRuntime, ws: str, task: str, project: str,
                     *, use_memory: bool, max_steps: int = 6) -> dict[str, Any]:
    """One agent episode. Records each command+result to MemTrace. Returns metrics.

    ``stumbled`` = the agent ran a command that failed (i.e. it hit the uninitialized-
    project trap instead of setting up first). With the phase-1 lesson in memory, B
    should go straight to the working sequence and not stumble."""
    run = await rt.start_run(StartRunRequest(session_id=f"dog-{ws}", task=task, workspace_id=ws))
    history: list[str] = []
    failed_cmds = 0
    succeeded = False
    steps = 0
    for _ in range(max_steps):
        step = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="propose next command"))
        memory = ""
        if use_memory:
            ctx = await rt.retrieve_context(RetrievalRequest(
                run_id=run.run_id, step_id=step.step_id,
                query="how to run this project's checks; what setup is required and what command failed or worked",
                strategy=RetrievalStrategy.variant_2, token_budget=900, top_k=10))
            pos = positive_blocks(ctx)
            # MemTrace's failure-aware negative evidence: the commands that FAILED before
            # (avoided-attempts channel). Surfacing it is the whole point — it tells the
            # agent what NOT to do, not just what worked.
            neg = [b for b in ctx.context_blocks
                   if b.type == "avoided_attempts" or b.source == "negative_evidence"]
            parts: list[str] = []
            if pos:
                parts.append("What worked in past sessions:\n" + "\n".join(f"- {b.content}" for b in pos))
            if neg:
                parts.append("AVOID — these FAILED in past sessions (do not repeat):\n"
                             + "\n".join(f"- {b.content}" for b in neg))
            memory = "\n\n".join(parts)
        cmd = await _propose(client, endpoint, task, history, memory)
        if cmd.upper().startswith("DONE"):
            break
        steps += 1
        rc, out = await asyncio.to_thread(_execute, cmd, project)  # thread so concurrent trials don't block
        failed = rc != 0
        if failed:
            failed_cmds += 1
        history.append(f"$ {cmd}\n(exit {rc}) {out[:200]}")
        # record command + result to MemTrace (failed steps get rolled back)
        await rt.write_event(WriteEventRequest(
            run_id=run.run_id, step_id=step.step_id, role=EventRole.assistant,
            event_type=EventType.tool_call, tool_name="bash", content=cmd))
        await rt.write_event(WriteEventRequest(
            run_id=run.run_id, step_id=step.step_id, role=EventRole.tool,
            event_type=EventType.tool_result, tool_name="bash",
            content=f"$ {cmd}\n(exit {rc}) {out[:300]}", status="failed" if failed else "success"))
        await rt.finish_step(FinishStepRequest(
            run_id=run.run_id, step_id=step.step_id,
            status=StepStatus.failed if failed else StepStatus.completed,
            error_message=f"exit {rc}" if failed else None))
        if not failed and "PASS" in out:
            succeeded = True
            break
    return {"steps": steps, "failed_commands": failed_cmds, "stumbled": failed_cmds > 0, "succeeded": succeeded}


async def _one_trial(t: int, client, endpoint, task: str, root: str) -> dict[str, Any]:
    """One independent A/B trial (own repo/runtime/projects)."""
    repo = InMemoryRepository()
    ws = f"dogfood_{t}"
    rt = MemoryRuntime(repo, default_workspace_id=ws)
    # Three SEPARATE fresh projects: phase-1 learn, and one each for A and B, so A's
    # setup can't initialize B's project (that would rig the comparison).
    proj1, proj_a, proj_b = _make_project(root), _make_project(root), _make_project(root)
    try:
        learn = await _run_agent(client, endpoint, rt, ws, task, proj1, use_memory=False)
        a = await _run_agent(client, endpoint, rt, f"{ws}_A", task, proj_a, use_memory=False)
        b = await _run_agent(client, endpoint, rt, ws, task, proj_b, use_memory=True)
    finally:
        for p in (proj1, proj_a, proj_b):
            shutil.rmtree(p, ignore_errors=True)
    return {"trial": t, "learn": learn, "A": a, "B": b}


def _agg(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate a list of trial rows into the A/B stats."""
    n = len(rows)

    def _sum(side: str, key: str) -> int:
        return sum(r[side][key] for r in rows)

    a_stumble = sum(1 for r in rows if r["A"]["stumbled"])
    b_stumble = sum(1 for r in rows if r["B"]["stumbled"])
    return {
        "trials": n,
        "A_no_memory": {"total_steps": _sum("A", "steps"), "total_failed_commands": _sum("A", "failed_commands"),
                        "trials_stumbled": a_stumble, "success_rate": round(_sum("A", "succeeded") / max(1, n), 3)},
        "B_memtrace": {"total_steps": _sum("B", "steps"), "total_failed_commands": _sum("B", "failed_commands"),
                       "trials_stumbled": b_stumble, "success_rate": round(_sum("B", "succeeded") / max(1, n), 3)},
        "delta": {"steps_saved": _sum("A", "steps") - _sum("B", "steps"),
                  "failed_commands_saved": _sum("A", "failed_commands") - _sum("B", "failed_commands"),
                  "stumbles_avoided": a_stumble - b_stumble},
    }


async def run_dogfood_ab(*, root: str, models: list[str] | None = None, trials: int = 100,
                         concurrency: int = 8, output_dir: str | None = "reports") -> dict[str, Any]:
    endpoints = _resolve_endpoints()
    if not endpoints:
        return {"skipped": True, "reason": "needs MEMTRACE_LLM_API_KEY (+ BASE_URL/MODEL)"}
    base = endpoints[0]
    model_list = models or [base["model"]]
    task = ("Verify this project by running ./check.sh — it should print PASS. If it does not, "
            "get it to PASS.")
    sem = asyncio.Semaphore(max(1, concurrency))

    async def _run_for(endpoint: dict[str, Any], client) -> list[dict[str, Any]]:
        done = 0
        lock = asyncio.Lock()

        async def _bounded(t: int) -> dict[str, Any] | None:
            nonlocal done
            async with sem:
                try:
                    row = await _one_trial(t, client, endpoint, task, root)
                except Exception as exc:  # noqa: BLE001 - one flaky trial must not kill the batch
                    row = None
                    if done < 2:
                        print(f"  [{endpoint['model']}] trial {t} errored ({type(exc).__name__})", flush=True)
            async with lock:
                done += 1
                if done % 25 == 0:
                    print(f"  [{endpoint['model']}] {done}/{trials} trials …", flush=True)
            return row

        results = await asyncio.gather(*(_bounded(t) for t in range(trials)))
        return [r for r in results if r is not None]

    by_model: dict[str, Any] = {}
    all_rows: list[dict[str, Any]] = []
    async with httpx.AsyncClient() as client:
        for model in model_list:
            rows = await _run_for({**base, "model": model}, client)
            if rows:
                by_model[model] = _agg(rows)
                all_rows.extend(rows)
            else:
                print(f"  model {model}: all trials errored (not accessible?) — excluded", flush=True)
    if not all_rows:
        return {"skipped": True, "reason": "all trials errored across all models (endpoint unreachable?)"}

    payload = {
        "skipped": False,
        "endpoint": {"base_url": base["base_url"], "model": " · ".join(by_model.keys())},
        "task": task,
        "models": list(by_model.keys()),
        "trials_per_model": trials,
        **_agg(all_rows),  # overall: trials, A_no_memory, B_memtrace, delta
        "by_model": by_model,
    }
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        with open(os.path.join(output_dir, "dogfood_agent_results.json"), "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
    return payload


def main() -> int:
    p = argparse.ArgumentParser(description="Dogfooding A/B: does MemTrace stop an agent repeating a mistake?")
    p.add_argument("--root", default=tempfile.gettempdir(), help="parent dir for throwaway projects")
    p.add_argument("--trials", type=int, default=100, help="trials PER model")
    p.add_argument("--models", default="", help="comma-separated model ids (default: MEMTRACE_LLM_MODEL)")
    p.add_argument("--concurrency", type=int, default=8, help="trials to run in parallel")
    p.add_argument("--output-dir", default="reports")
    a = p.parse_args()
    models = [m.strip() for m in a.models.split(",") if m.strip()] or None
    payload = asyncio.run(run_dogfood_ab(root=a.root, models=models, trials=a.trials,
                                         concurrency=a.concurrency, output_dir=a.output_dir))
    if payload.get("skipped"):
        print(f"dogfood_agent skipped: {payload['reason']}")
        return 0
    print(f"models={payload['endpoint']['model']}  trials/model={payload['trials_per_model']}  "
          f"total_trials={payload['trials']}")
    print(f"  OVERALL  A (no memory): {payload['A_no_memory']}")
    print(f"  OVERALL  B (MemTrace):  {payload['B_memtrace']}")
    for model, agg in payload.get("by_model", {}).items():
        print(f"  [{model}]  A stumbled {agg['A_no_memory']['trials_stumbled']}/{agg['trials']}  "
              f"B stumbled {agg['B_memtrace']['trials_stumbled']}/{agg['trials']}  "
              f"steps {agg['A_no_memory']['total_steps']}->{agg['B_memtrace']['total_steps']}")
    d = payload["delta"]
    print(f"  A/B delta: steps_saved={d['steps_saved']}  failed_commands_saved={d['failed_commands_saved']}  "
          f"stumbles_avoided={d['stumbles_avoided']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
