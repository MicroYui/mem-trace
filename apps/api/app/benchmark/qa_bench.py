"""Real-LLM Q&A bench: does MemTrace-managed context produce better real answers?

This is the question-answering counterpart to ``llm_bench`` (which validates LLM
*extraction*). For each scenario it seeds memory through the real ``MemoryRuntime``
hot path, retrieves context twice — a no-memory baseline (``baseline_0``) and the
state-aware + gated path (``variant_2``) — and asks a real LLM the same question
with each context. Scoring checks that the gated-memory answer is correct (and,
for contrast, whether it improves on the no-memory answer).

Opt-in / env-gated like ``llm_bench``: with no endpoint configured it skips
cleanly (no default-CI / benchmark / reproducibility impact). Configure via the
standard ``MEMTRACE_LLM_API_KEY`` / ``MEMTRACE_LLM_BASE_URL`` / ``MEMTRACE_LLM_MODEL``
settings, e.g. against a local OpenAI-compatible proxy:

    MEMTRACE_LLM_API_KEY=sk-local \
    MEMTRACE_LLM_BASE_URL=http://localhost:4141/v1 \
    MEMTRACE_LLM_MODEL=gpt-5-mini \
    uv run python -m app.benchmark.qa_bench --output-dir reports
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import httpx

from app.benchmark.llm_bench import _resolve_endpoints
from app.runtime.memory_runtime import MemoryRuntime
from app.runtime.models import (
    BranchStatus,
    MemoryItem,
    MemoryStatus,
    MemoryType,
    RetrievalRequest,
    RetrievalStrategy,
    RiskFlags,
    StartRunRequest,
    StartStepRequest,
)
from app.runtime.repository import InMemoryRepository

_SYSTEM = (
    "You are a coding assistant. Answer using ONLY the provided project memory "
    "context. Be concise. If the context does not contain the answer, say you do "
    "not have that information."
)


@dataclass
class QAScenario:
    name: str
    seed: Callable[[MemoryRuntime, str], Awaitable[tuple[str, str]]]  # -> (run_id, step_id)
    question: str
    expected_markers: list[str]
    forbidden_markers: list[str]


async def _seed_project_preference(rt: MemoryRuntime, ws: str) -> tuple[str, str]:
    run = await rt.start_run(StartRunRequest(session_id="qa", task="run tests", workspace_id=ws))
    await rt._repo.add_memory(  # noqa: SLF001 - deterministic seeding
        MemoryItem(workspace_id=ws, run_id=run.run_id, memory_type=MemoryType.project,
                   key="project.runtime", value="bun",
                   content="This project uses Bun, not Node.js.", branch_status=BranchStatus.completed)
    )
    step = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="testing", goal="run the test suite"))
    return run.run_id, step.step_id


async def _seed_failed_branch(rt: MemoryRuntime, ws: str) -> tuple[str, str]:
    run = await rt.start_run(StartRunRequest(session_id="qa", task="run tests", workspace_id=ws))
    await rt._repo.add_memory(  # noqa: SLF001
        MemoryItem(workspace_id=ws, run_id=run.run_id, memory_type=MemoryType.project,
                   key="project.runtime", value="bun",
                   content="This project uses Bun.", branch_status=BranchStatus.completed)
    )
    await rt._repo.add_memory(  # noqa: SLF001
        MemoryItem(workspace_id=ws, run_id=run.run_id, memory_type=MemoryType.tool_evidence,
                   content="Tried running the tests with `npm test`; it failed because npm is unavailable.",
                   branch_status=BranchStatus.failed)
    )
    step = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="testing", goal="choose a test command"))
    return run.run_id, step.step_id


async def _seed_stale_exclusion(rt: MemoryRuntime, ws: str) -> tuple[str, str]:
    run = await rt.start_run(StartRunRequest(session_id="qa", task="call api", workspace_id=ws))
    await rt._repo.add_memory(  # noqa: SLF001
        MemoryItem(workspace_id=ws, run_id=run.run_id, memory_type=MemoryType.project,
                   key="endpoint.deprecated", value="/api/v1/users",
                   content="The legacy users endpoint was /api/v1/users.",
                   branch_status=BranchStatus.completed, status=MemoryStatus.superseded)
    )
    await rt._repo.add_memory(  # noqa: SLF001
        MemoryItem(workspace_id=ws, run_id=run.run_id, memory_type=MemoryType.project,
                   key="endpoint.current", value="/api/v2/users",
                   content="The current users endpoint is /api/v2/users.", branch_status=BranchStatus.completed)
    )
    step = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="coding", goal="call the users endpoint"))
    return run.run_id, step.step_id


async def _seed_multi_fact(rt: MemoryRuntime, ws: str) -> tuple[str, str]:
    run = await rt.start_run(StartRunRequest(session_id="qa", task="set up project", workspace_id=ws))
    facts = [
        ("project.runtime", "bun", "The runtime is Bun."),
        ("project.package_manager", "pnpm", "The package manager is pnpm."),
        ("project.database", "postgres", "The database is Postgres."),
    ]
    for key, value, content in facts:
        await rt._repo.add_memory(  # noqa: SLF001
            MemoryItem(workspace_id=ws, run_id=run.run_id, memory_type=MemoryType.project,
                       key=key, value=value, content=content, branch_status=BranchStatus.completed)
        )
    step = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="planning", goal="summarize the stack"))
    return run.run_id, step.step_id


SCENARIOS: list[QAScenario] = [
    QAScenario("project_preference", _seed_project_preference,
               "What single command runs the test suite? Answer with just the command.",
               expected_markers=["bun"], forbidden_markers=["npm"]),
    QAScenario("failed_branch_avoidance", _seed_failed_branch,
               "How should I run the tests? Name the command to use.",
               expected_markers=["bun"], forbidden_markers=[]),
    QAScenario("stale_exclusion", _seed_stale_exclusion,
               "What is the current users API endpoint path?",
               expected_markers=["v2"], forbidden_markers=["v1"]),
    QAScenario("multi_fact_recall", _seed_multi_fact,
               "List the runtime, package manager, and database used by this project.",
               expected_markers=["bun", "pnpm", "postgres"], forbidden_markers=[]),
]


def _context_text(blocks) -> str:
    if not blocks:
        return "(no project memory available)"
    return "\n".join(f"- {b.content}" for b in blocks)


async def _chat(client: httpx.AsyncClient, endpoint: dict, system: str, user: str) -> str:
    base = endpoint["base_url"].rstrip("/")
    resp = await client.post(
        f"{base}/chat/completions",
        headers={"Authorization": f"Bearer {endpoint['api_key']}", "Content-Type": "application/json"},
        json={
            "model": endpoint["model"],
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "max_tokens": endpoint.get("max_tokens", 256),
        },
        timeout=endpoint.get("timeout_ms", 60000) / 1000.0,
    )
    resp.raise_for_status()
    data = resp.json()
    return (data["choices"][0]["message"]["content"] or "").strip()


def _scored(answer: str, expected: list[str], forbidden: list[str]) -> bool:
    low = answer.lower()

    def present(marker: str) -> bool:
        # Word-boundary match so e.g. forbidden "npm" does not match "pnpm".
        return re.search(rf"\b{re.escape(marker.lower())}\b", low) is not None

    return all(present(m) for m in expected) and not any(present(m) for m in forbidden)


async def _run_scenario(client: httpx.AsyncClient, endpoint: dict, sc: QAScenario) -> dict[str, Any]:
    repo = InMemoryRepository()
    rt = MemoryRuntime(repo, default_workspace_id="qa_ws")
    run_id, step_id = await sc.seed(rt, "qa_ws")

    async def _answer(strategy: RetrievalStrategy) -> tuple[str, str]:
        ctx = await rt.retrieve_context(
            RetrievalRequest(run_id=run_id, step_id=step_id, query=sc.question, strategy=strategy)
        )
        ctx_text = _context_text(ctx.context_blocks)
        prompt = f"Project memory context:\n{ctx_text}\n\nQuestion: {sc.question}"
        return ctx_text, await _chat(client, endpoint, _SYSTEM, prompt)

    mem_ctx, mem_answer = await _answer(RetrievalStrategy.variant_2)
    _none_ctx, none_answer = await _answer(RetrievalStrategy.baseline_0)
    memory_correct = _scored(mem_answer, sc.expected_markers, sc.forbidden_markers)
    nomemory_correct = _scored(none_answer, sc.expected_markers, sc.forbidden_markers)
    return {
        "scenario": sc.name,
        "question": sc.question,
        "memory_context": mem_ctx,
        "memory_answer": mem_answer,
        "nomemory_answer": none_answer,
        "memory_correct": memory_correct,
        "nomemory_correct": nomemory_correct,
        "memory_improves": bool(memory_correct and not nomemory_correct),
        "passed": memory_correct,
    }


async def run_qa_bench(output_dir: str = "reports") -> dict[str, Any]:
    endpoints = _resolve_endpoints()
    if not endpoints:
        return {
            "skipped": True,
            "reason": (
                "No LLM endpoint configured. Set MEMTRACE_LLM_API_KEY (+ optional "
                "MEMTRACE_LLM_BASE_URL / MEMTRACE_LLM_MODEL) to run the real-LLM Q&A bench."
            ),
        }
    endpoint = endpoints[0]
    async with httpx.AsyncClient() as client:
        results = [await _run_scenario(client, endpoint, sc) for sc in SCENARIOS]
    payload = {
        "skipped": False,
        "endpoint": {"name": endpoint.get("name"), "base_url": endpoint["base_url"], "model": endpoint["model"]},
        "scenarios": results,
        "passed": all(r["passed"] for r in results),
        "memory_improvement_count": sum(1 for r in results if r["memory_improves"]),
    }
    os.makedirs(output_dir, exist_ok=True)
    with open(os.path.join(output_dir, "qa_bench_results.json"), "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Real-LLM Q&A bench over MemTrace context")
    parser.add_argument("--output-dir", default="reports")
    args = parser.parse_args()
    payload = asyncio.run(run_qa_bench(args.output_dir))
    if payload.get("skipped"):
        print(f"qa_bench skipped: {payload['reason']}")
        return 0
    for r in payload["scenarios"]:
        mark = "PASS" if r["passed"] else "FAIL"
        improved = " (memory improves over no-memory)" if r["memory_improves"] else ""
        print(f"[{mark}] {r['scenario']}{improved}")
        print(f"    with memory:   {r['memory_answer'][:140]}")
        print(f"    without memory:{r['nomemory_answer'][:140]}")
    print(f"\nqa_bench overall: {'PASS' if payload['passed'] else 'FAIL'} "
          f"({payload['memory_improvement_count']}/{len(payload['scenarios'])} improved by memory)")
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
