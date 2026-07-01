"""Tree-shaped, long-horizon agentic-trace benchmark (ROADMAP §7).

Unlike the flat `dataset_bench` (which seeds memory items directly), this builds a
*real execution trace* through `MemoryRuntime` for every scenario: a long run with
a tree of subgoals, where each subgoal may make one or more attempts that FAIL and
get rolled back (dead branches) before a recovery attempt succeeds. Memories are
created by the real write path, so they carry genuine `branch_status` /
`state_node` provenance, and retrieval runs the full pipeline (state tree →
active-path filtering → admission gate → context packing / compaction).

This exercises what a plain vector store structurally cannot represent — the
execution tree — so it measures MemTrace's edge on three axes at once:

  - **Contamination**: wrong facts left on failed/rolled-back branches. MemTrace
    isolates them; plain vector admits them, and contamination grows with the
    number of dead branches in a long trace.
  - **Recall**: the current correct fact (on the active/recovered path) is kept.
  - **Context cost**: over a long horizon `long_context` dumps everything (token
    bloat); MemTrace keeps context compact.

Fully deterministic (no LLM, no network): facts are carried as free-form
`tool_result` content, scored by substring markers in positive context, exactly
like `dataset_bench`.

    uv run python -m app.benchmark.trace_bench --scenarios 100 --subgoals 6 --output-dir reports
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from typing import Any

from app.benchmark.generate_dataset import TOPICS
from app.providers.factory import deterministic_provider_registry
from app.retrieval.packer import estimate_tokens
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

_ALL_STRATEGIES = [
    RetrievalStrategy.baseline_0,
    RetrievalStrategy.long_context,
    RetrievalStrategy.baseline_1,
    RetrievalStrategy.variant_1,
    RetrievalStrategy.variant_2,
    RetrievalStrategy.variant_3,
]
_TOKEN_BUDGET = 256


class Subgoal:
    __slots__ = ("subject", "correct", "wrong_attempts")

    def __init__(self, subject: str, correct: str, wrong_attempts: list[str]):
        self.subject = subject
        self.correct = correct
        self.wrong_attempts = wrong_attempts


class Scenario:
    __slots__ = ("scenario_id", "subgoals")

    def __init__(self, scenario_id: str, subgoals: list[Subgoal]):
        self.scenario_id = scenario_id
        self.subgoals = subgoals


def generate_scenarios(count: int, subgoals: int) -> list[Scenario]:
    """Deterministically build ``count`` scenarios of ``subgoals`` subgoals each.

    Each subgoal draws a (subject, correct, wrong) topic; the number of failed
    attempts (dead branches) before success cycles 0/1/2 so traces vary in depth.
    A second wrong value (from another topic) is used for the 2-attempt case.
    """
    scenarios: list[Scenario] = []
    for i in range(count):
        sgs: list[Subgoal] = []
        for j in range(subgoals):
            subject, correct, wrong = TOPICS[(i * subgoals + j) % len(TOPICS)]
            n_fail = (i + j) % 3  # 0, 1, or 2 dead branches
            wrongs = [wrong]
            if n_fail == 2:
                _, _, wrong2 = TOPICS[(i * subgoals + j + 5) % len(TOPICS)]
                if wrong2 != wrong and wrong2 != correct:
                    wrongs.append(wrong2)
            sgs.append(Subgoal(subject, correct, wrongs[:max(1, n_fail)] if n_fail else []))
        scenarios.append(Scenario(f"trace_{i:05d}", sgs))
    return scenarios


def _ev(run_id, step_id, content, status=None):
    return WriteEventRequest(
        run_id=run_id, step_id=step_id, role=EventRole.tool,
        event_type=EventType.tool_result if status else EventType.tool_call,
        tool_name="bash", content=content, status=status,
    )


async def build_trace(rt: MemoryRuntime, ws: str, scenario: Scenario) -> tuple[str, str]:
    """Drive the real runtime to build the scenario's execution tree."""
    run = await rt.start_run(StartRunRequest(session_id=scenario.scenario_id, task="configure the project", workspace_id=ws))
    for sg in scenario.subgoals:
        last_failed: str | None = None
        # dead branches: each failed attempt establishes a WRONG fact, then rolls back
        for wrong in sg.wrong_attempts:
            sf = await rt.start_step(StartStepRequest(run_id=run.run_id, intent=f"try {sg.subject}",
                                                      recovery_from_step_id=last_failed))
            await rt.write_event(_ev(run.run_id, sf.step_id,
                                     f"Tried {wrong} for the {sg.subject}; it failed and was abandoned.",
                                     status="failed"))
            await rt.finish_step(FinishStepRequest(run_id=run.run_id, step_id=sf.step_id,
                                                   status=StepStatus.failed, error_message=f"{wrong} failed"))
            await rt.rollback_branch(RollbackRequest(run_id=run.run_id, step_id=sf.step_id, reason=f"{wrong} failed"))
            last_failed = sf.step_id
        # success on the active/recovered path establishes the CORRECT fact
        ss = await rt.start_step(StartStepRequest(run_id=run.run_id, intent=f"configure {sg.subject}",
                                                  recovery_from_step_id=last_failed, goal=f"set {sg.subject}"))
        await rt.write_event(_ev(run.run_id, ss.step_id,
                                 f"Confirmed the {sg.subject} is {sg.correct}.", status="success"))
        await rt.finish_step(FinishStepRequest(run_id=run.run_id, step_id=ss.step_id,
                                               status=StepStatus.completed, summary=f"{sg.subject} set to {sg.correct}"))
    retr = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="answer", goal="answer questions"))
    return run.run_id, retr.step_id


def _rate(hits: int, total: int) -> float:
    return round(hits / total, 6) if total else 0.0


async def run_trace_bench(
    *, scenarios: int = 100, subgoals: int = 6, output_dir: str | None = "reports",
    strategies: list[RetrievalStrategy] | None = None,
) -> dict[str, Any]:
    strategies = strategies or _ALL_STRATEGIES
    specs = generate_scenarios(scenarios, subgoals)
    agg = {s.value: {"recall_t": 0, "recall_h": 0, "contam_t": 0, "contam_h": 0,
                     "clean_h": 0, "tok_sum": 0, "tok_n": 0, "dead_branches": 0} for s in strategies}

    for scenario in specs:
        for strategy in strategies:
            repo = InMemoryRepository()
            rt = MemoryRuntime(repo, default_workspace_id="trace_ws", provider_registry=deterministic_provider_registry())
            run_id, step_id = await build_trace(rt, "trace_ws", scenario)
            for sg in scenario.subgoals:
                ctx = await rt.retrieve_context(RetrievalRequest(
                    run_id=run_id, step_id=step_id, query=f"What is the {sg.subject} for this project?",
                    strategy=strategy, token_budget=_TOKEN_BUDGET, top_k=12))
                blocks = positive_blocks(ctx)
                text = " ".join((b.content or "").lower() for b in blocks)
                tokens = sum(estimate_tokens(b.content or "") for b in ctx.context_blocks)
                recall_hit = sg.correct.lower() in text
                contam = any(w.lower() in text for w in sg.wrong_attempts)
                b = agg[strategy.value]
                b["recall_t"] += 1
                b["recall_h"] += int(recall_hit)
                b["tok_sum"] += tokens
                b["tok_n"] += 1
                if sg.wrong_attempts:
                    b["contam_t"] += 1
                    b["contam_h"] += int(contam)
                    b["dead_branches"] += len(sg.wrong_attempts)
                b["clean_h"] += int(recall_hit and not contam)

    by_strategy = {
        name: {
            "recall_rate": _rate(b["recall_h"], b["recall_t"]),
            "contamination_rate": _rate(b["contam_h"], b["contam_t"]),
            "clean_context_rate": _rate(b["clean_h"], b["recall_t"]),
            "avg_context_tokens": round(b["tok_sum"] / b["tok_n"], 2) if b["tok_n"] else 0.0,
        }
        for name, b in agg.items()
    }
    plain = by_strategy.get(RetrievalStrategy.baseline_1.value)
    memtrace = by_strategy.get(RetrievalStrategy.variant_2.value)
    longc = by_strategy.get(RetrievalStrategy.long_context.value)
    delta: dict[str, Any] = {}
    if plain and memtrace:
        delta = {
            "contamination_reduction": round(plain["contamination_rate"] - memtrace["contamination_rate"], 6),
            "recall_cost": round(plain["recall_rate"] - memtrace["recall_rate"], 6),
            "clean_context_gain": round(memtrace["clean_context_rate"] - plain["clean_context_rate"], 6),
            "context_token_ratio_vs_long_context": (
                round(memtrace["avg_context_tokens"] / longc["avg_context_tokens"], 4)
                if longc and longc["avg_context_tokens"] else None
            ),
        }
    payload = {
        "scenarios": scenarios, "subgoals_per_scenario": subgoals,
        "probe_count": scenarios * subgoals,
        "strategies": [s.value for s in strategies],
        "by_strategy": by_strategy, "delta": delta,
    }
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
        with open(os.path.join(output_dir, "trace_bench_results.json"), "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Tree-shaped long-horizon agentic-trace benchmark")
    parser.add_argument("--scenarios", type=int, default=100)
    parser.add_argument("--subgoals", type=int, default=6)
    parser.add_argument("--output-dir", default="reports")
    args = parser.parse_args()
    payload = asyncio.run(run_trace_bench(scenarios=args.scenarios, subgoals=args.subgoals, output_dir=args.output_dir))
    print(f"scenarios={payload['scenarios']}  subgoals={payload['subgoals_per_scenario']}  probes={payload['probe_count']}")
    for name, b in payload["by_strategy"].items():
        print(f"  {name:>12}: recall={b['recall_rate']:.3f}  contamination={b['contamination_rate']:.3f}  "
              f"clean={b['clean_context_rate']:.3f}  ctx_tokens={b['avg_context_tokens']:.0f}")
    if payload["delta"]:
        d = payload["delta"]
        print(f"  MemTrace vs plain: contamination_reduction={d['contamination_reduction']}  "
              f"recall_cost={d['recall_cost']}  clean_gain={d['clean_context_gain']}  "
              f"ctx_vs_long={d['context_token_ratio_vs_long_context']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
