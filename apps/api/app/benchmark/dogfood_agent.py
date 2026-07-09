"""Dogfooding A/B — does MemTrace stop a real coding agent repeating a mistake? (opt-in)

A minimal but REAL coding-agent loop (a real LLM proposes shell commands, a sandboxed
executor runs them, results are recorded to MemTrace) run as a controlled **A/B**:

  - Phase 1 (learn): the agent solves a task in project #1. It discovers by trial that
    the check only passes with a specific incantation (``APP_ENV=test bash check.sh``);
    the naive command fails. Both the failed and the successful commands are recorded
    to MemTrace via the real runtime.
  - Phase 2 (test): a *fresh* agent solves the same-shaped task in project #2, twice:
      * **A = no memory** — no prior context.
      * **B = MemTrace** — it first retrieves the lesson from MemTrace.
    We measure whether the agent **repeats the known-bad command** and how many steps
    it takes to succeed.

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
# needs ls/cat/bash check.sh, so this never rejects a legitimate step.
_DENY = re.compile(
    r"\b(rm\s+-|sudo|mkfs|dd\s+if=|:\s*\(\s*\)|chmod\s+-R|chown\s+-R|curl|wget|nc\s|ncat|"
    r"scp|ssh|>\s*/dev/|/etc/|~/\.ssh|shutdown|reboot|kill\s+-9\s+1)\b",
    re.IGNORECASE,
)
# The mistake the agent should learn to avoid: running the check WITHOUT APP_ENV=test.
_BAD_MARKER = "bash check.sh"  # a plain invocation (no APP_ENV) -> fails
_GOOD_MARKER = "app_env=test"  # the incantation that works


def _make_project(root: str) -> str:
    """A throwaway project whose check.sh passes only with APP_ENV=test."""
    d = tempfile.mkdtemp(prefix="dogfood_", dir=root)
    Path(d, "check.sh").write_text(
        '#!/usr/bin/env bash\n'
        'if [ "$APP_ENV" = "test" ]; then echo "PASS: checks green"; exit 0; fi\n'
        'echo "FAIL: this project\'s checks require APP_ENV=test in the environment" >&2\n'
        'exit 1\n',
        encoding="utf-8",
    )
    Path(d, "README.md").write_text("Run the project's checks (see check.sh) and make them pass.\n", encoding="utf-8")
    os.chmod(Path(d, "check.sh"), 0o755)
    return d


def _execute(cmd: str, cwd: str, timeout: int = 10) -> tuple[int, str]:
    """Sandboxed executor: temp cwd, timeout, deny-list. Returns (returncode, output)."""
    if _DENY.search(cmd):
        return 126, "blocked by safety policy (destructive/exfiltrating command refused)"
    try:
        # Clear APP_ENV in the base env so a plain `bash check.sh` fails; the agent must
        # supply `APP_ENV=test` inline (a shell var-assignment prefix) for it to pass.
        env = {**os.environ, "APP_ENV": ""}
        p = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)
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
    raw = (await _chat(client, endpoint, _AGENT_SYSTEM, prompt)).strip()
    if raw.startswith("```"):  # strip a markdown code fence + any language tag line
        raw = "\n".join(ln for ln in raw.splitlines() if not ln.strip().startswith("```")).strip()
    for line in raw.splitlines():
        line = line.strip().lstrip("$ ").strip()
        if line:
            return line
    return "DONE"


async def _run_agent(client, endpoint, rt: MemoryRuntime, ws: str, task: str, project: str,
                     *, use_memory: bool, max_steps: int = 6) -> dict[str, Any]:
    """One agent episode. Records each command+result to MemTrace. Returns metrics."""
    run = await rt.start_run(StartRunRequest(session_id=f"dog-{ws}", task=task, workspace_id=ws))
    history: list[str] = []
    failed_cmds = 0
    repeated_bad = False
    succeeded = False
    steps = 0
    for _ in range(max_steps):
        step = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="propose next command"))
        memory = ""
        if use_memory:
            ctx = await rt.retrieve_context(RetrievalRequest(
                run_id=run.run_id, step_id=step.step_id,
                query="how to run this project's checks; what command failed and what worked",
                strategy=RetrievalStrategy.variant_2, token_budget=800, top_k=10))
            memory = "\n".join(f"- {b.content}" for b in positive_blocks(ctx))
        cmd = await _propose(client, endpoint, task, history, memory)
        if cmd.upper().startswith("DONE"):
            break
        steps += 1
        rc, out = _execute(cmd, project)
        failed = rc != 0
        if failed:
            failed_cmds += 1
            # "repeated the known-bad approach": ran the plain check (no APP_ENV) and failed
            if _BAD_MARKER in cmd.lower() and _GOOD_MARKER not in cmd.lower():
                repeated_bad = True
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
    return {"steps": steps, "failed_commands": failed_cmds, "repeated_bad": repeated_bad, "succeeded": succeeded}


async def run_dogfood_ab(*, root: str, trials: int = 3, output_dir: str | None = "reports") -> dict[str, Any]:
    endpoints = _resolve_endpoints()
    if not endpoints:
        return {"skipped": True, "reason": "needs MEMTRACE_LLM_API_KEY (+ BASE_URL/MODEL)"}
    endpoint = endpoints[0]
    task = ("Make this project's checks pass. Inspect the files, run the check script, and if it "
            "fails, work out the required setup and run it correctly.")
    trial_rows: list[dict[str, Any]] = []
    async with httpx.AsyncClient() as client:
        for t in range(trials):
            repo = InMemoryRepository()
            ws = f"dogfood_{t}"
            rt = MemoryRuntime(repo, default_workspace_id=ws)
            proj1, proj2 = _make_project(root), _make_project(root)
            try:
                # Phase 1 — learn on project #1 (records failed + working commands to MemTrace).
                learn = await _run_agent(client, endpoint, rt, ws, task, proj1, use_memory=False)
                # Phase 2 — A (no memory) vs B (MemTrace) on project #2. A uses a separate
                # workspace (no memory); B retrieves phase-1's lesson from `ws`.
                a = await _run_agent(client, endpoint, rt, f"{ws}_A", task, proj2, use_memory=False)
                b = await _run_agent(client, endpoint, rt, ws, task, proj2, use_memory=True)
            finally:
                shutil.rmtree(proj1, ignore_errors=True)
                shutil.rmtree(proj2, ignore_errors=True)
            trial_rows.append({"trial": t, "learn": learn, "A": a, "B": b})

    def _sum(side: str, key: str) -> int:
        return sum(r[side][key] for r in trial_rows)

    a_steps, b_steps = _sum("A", "steps"), _sum("B", "steps")
    a_fail, b_fail = _sum("A", "failed_commands"), _sum("B", "failed_commands")
    a_mistake = sum(1 for r in trial_rows if r["A"]["repeated_bad"])
    b_mistake = sum(1 for r in trial_rows if r["B"]["repeated_bad"])
    payload = {
        "skipped": False,
        "endpoint": {"base_url": endpoint["base_url"], "model": endpoint["model"]},
        "task": task,
        "trials": trials,
        "A_no_memory": {"total_steps": a_steps, "total_failed_commands": a_fail,
                        "trials_with_repeated_mistake": a_mistake,
                        "success_rate": round(_sum("A", "succeeded") / trials, 3)},
        "B_memtrace": {"total_steps": b_steps, "total_failed_commands": b_fail,
                       "trials_with_repeated_mistake": b_mistake,
                       "success_rate": round(_sum("B", "succeeded") / trials, 3)},
        "delta": {
            "steps_saved": a_steps - b_steps,
            "failed_commands_saved": a_fail - b_fail,
            "mistakes_avoided": a_mistake - b_mistake,
        },
        "trial_rows": trial_rows,
    }
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        with open(os.path.join(output_dir, "dogfood_agent_results.json"), "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
    return payload


def main() -> int:
    p = argparse.ArgumentParser(description="Dogfooding A/B: does MemTrace stop an agent repeating a mistake?")
    p.add_argument("--root", default=tempfile.gettempdir(), help="parent dir for throwaway projects")
    p.add_argument("--trials", type=int, default=3)
    p.add_argument("--output-dir", default="reports")
    a = p.parse_args()
    payload = asyncio.run(run_dogfood_ab(root=a.root, trials=a.trials, output_dir=a.output_dir))
    if payload.get("skipped"):
        print(f"dogfood_agent skipped: {payload['reason']}")
        return 0
    print(f"model={payload['endpoint']['model']}  trials={payload['trials']}")
    print(f"  A (no memory):  {payload['A_no_memory']}")
    print(f"  B (MemTrace):   {payload['B_memtrace']}")
    d = payload["delta"]
    print(f"  A/B delta: steps_saved={d['steps_saved']}  failed_commands_saved={d['failed_commands_saved']}  "
          f"mistakes_avoided={d['mistakes_avoided']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
