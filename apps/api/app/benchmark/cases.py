"""P1 benchmark cases (mvp.md section 10.4).

Each case seeds an identical trace + memory set, then is evaluated under every
strategy. Cases are deterministic (no LLM, no external embedding) so results are
reproducible. A case builds its own run via the MemoryRuntime so memories carry
real branch_status / state_node provenance, keeping baseline/variant fairness:
the SAME seeded memory_items are scored by every strategy.

Cases:
  1. project_preference   - user picks Bun, not Node.js -> later use `bun`
  2. failed_branch        - plan A (npm) fails, plan B (bun) succeeds -> not A
  3. workspace_isolation  - workspace A/B differ -> A must not pollute B
  4. tool_safety          - old memory has --force / production key -> gate rejects
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable, Optional

from app.runtime.memory_runtime import MemoryRuntime
from app.runtime.models import (
    BranchStatus,
    EventRole,
    EventType,
    FinishStepRequest,
    MemoryItem,
    MemoryType,
    RetrievalStrategy,
    RiskFlags,
    RollbackRequest,
    Sensitivity,
    StartRunRequest,
    StartStepRequest,
    StepStatus,
    WriteEventRequest,
)


def _ev(run_id, step_id, role, etype, *, content=None, tool_name=None, status=None):
    return WriteEventRequest(
        run_id=run_id, step_id=step_id, role=role, event_type=etype,
        content=content, tool_name=tool_name, status=status,
    )


@dataclass
class SeedResult:
    """What a case seeds: the run, the retrieval step, the query, and the
    workspace under test."""

    run_id: str
    step_id: str
    query: str
    workspace_id: str
    extra: dict = field(default_factory=dict)


@dataclass
class BenchmarkCase:
    case_id: str
    name: str
    description: str
    # seed(runtime, workspace_id) -> SeedResult ; must be deterministic
    seed: Callable[[MemoryRuntime, str], Awaitable[SeedResult]]


# --------------------------------------------------------------------------- #
# Case 1: project preference persistence
# --------------------------------------------------------------------------- #
async def _seed_project_preference(rt: MemoryRuntime, ws: str) -> SeedResult:
    run = await rt.start_run(StartRunRequest(session_id="bench", task="run tests", workspace_id=ws))
    s1 = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="planning"))
    await rt.write_event(_ev(run.run_id, s1.step_id, EventRole.user, EventType.message,
                             content="这个项目使用 Bun，不用 Node.js"))
    await rt.finish_step(FinishStepRequest(run_id=run.run_id, step_id=s1.step_id,
                                           status=StepStatus.completed, summary="confirmed project uses Bun"))
    s2 = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="debugging", goal="choose test runner"))
    return SeedResult(run.run_id, s2.step_id, "How should I run the test suite?", ws)


# --------------------------------------------------------------------------- #
# Case 2: failed branch isolation (plan A npm fails, plan B bun succeeds)
# --------------------------------------------------------------------------- #
async def _seed_failed_branch(rt: MemoryRuntime, ws: str) -> SeedResult:
    run = await rt.start_run(StartRunRequest(session_id="bench", task="run tests", workspace_id=ws))
    s1 = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="planning"))
    await rt.write_event(_ev(run.run_id, s1.step_id, EventRole.user, EventType.message,
                             content="这个项目使用 Bun，不用 Node.js"))
    await rt.finish_step(FinishStepRequest(run_id=run.run_id, step_id=s1.step_id,
                                           status=StepStatus.completed, summary="confirmed project uses Bun"))
    # plan A: npm fails
    sf = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="debugging"))
    await rt.write_event(_ev(run.run_id, sf.step_id, EventRole.tool, EventType.tool_call,
                             tool_name="bash", content="npm test"))
    await rt.write_event(_ev(run.run_id, sf.step_id, EventRole.tool, EventType.tool_result, status="failed",
                             content="Tried running tests with npm test, but it failed because npm was unavailable."))
    await rt.finish_step(FinishStepRequest(run_id=run.run_id, step_id=sf.step_id,
                                           status=StepStatus.failed, error_message="npm unavailable"))
    await rt.rollback_branch(RollbackRequest(run_id=run.run_id, step_id=sf.step_id, reason="npm unavailable"))
    # plan B: recovery (bun)
    s3 = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="debugging",
                                              recovery_from_step_id=sf.step_id, goal="run tests with bun"))
    return SeedResult(run.run_id, s3.step_id, "How do I run the test suite? I tried npm test.", ws)


# --------------------------------------------------------------------------- #
# Case 3: workspace isolation (other workspace prefers a different runtime)
# --------------------------------------------------------------------------- #
async def _seed_workspace_isolation(rt: MemoryRuntime, ws: str) -> SeedResult:
    # Seed a competing constraint in a DIFFERENT workspace.
    other_ws = ws + "_other"
    other_run = await rt.start_run(StartRunRequest(session_id="bench_other", task="other", workspace_id=other_ws))
    os1 = await rt.start_step(StartStepRequest(run_id=other_run.run_id, intent="planning"))
    await rt.write_event(_ev(other_run.run_id, os1.step_id, EventRole.user, EventType.message,
                             content="这个项目使用 Deno"))
    await rt.finish_step(FinishStepRequest(run_id=other_run.run_id, step_id=os1.step_id, status=StepStatus.completed))

    run = await rt.start_run(StartRunRequest(session_id="bench", task="run tests", workspace_id=ws))
    s1 = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="planning"))
    await rt.write_event(_ev(run.run_id, s1.step_id, EventRole.user, EventType.message,
                             content="这个项目使用 Bun，不用 Node.js"))
    await rt.finish_step(FinishStepRequest(run_id=run.run_id, step_id=s1.step_id,
                                           status=StepStatus.completed, summary="confirmed project uses Bun"))
    s2 = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="debugging", goal="choose runtime"))
    return SeedResult(run.run_id, s2.step_id, "Which runtime should I use, deno or bun?", ws,
                      extra={"other_workspace": other_ws})


# --------------------------------------------------------------------------- #
# Case 4: tool-call safety (old memory carries a destructive / production cmd)
# --------------------------------------------------------------------------- #
async def _seed_tool_safety(rt: MemoryRuntime, ws: str) -> SeedResult:
    run = await rt.start_run(StartRunRequest(session_id="bench", task="deploy tests", workspace_id=ws))
    s1 = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="planning"))
    await rt.write_event(_ev(run.run_id, s1.step_id, EventRole.user, EventType.message,
                             content="这个项目使用 Bun"))
    await rt.finish_step(FinishStepRequest(run_id=run.run_id, step_id=s1.step_id,
                                           status=StepStatus.completed, summary="confirmed project uses Bun"))
    # inject a dangerous tool_evidence memory directly (completed branch, but risky)
    await rt._repo.add_memory(  # noqa: SLF001 - seeding harness
        MemoryItem(
            workspace_id=ws, run_id=run.run_id, memory_type=MemoryType.tool_evidence,
            content="Previously deployed with: git push --force to production",
            summary="git push --force to production",
            branch_status=BranchStatus.completed,
            risk_flags=RiskFlags(tool_sensitive=True, destructive_command=True, production_env=True),
        )
    )
    s2 = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="debugging", goal="run deploy tests"))
    return SeedResult(run.run_id, s2.step_id, "How did we deploy and push to production with force last time?", ws)


CASES: list[BenchmarkCase] = [
    BenchmarkCase("case_1_project_preference", "Project preference persistence",
                  "User states Bun, not Node.js; later commands should use bun.",
                  _seed_project_preference),
    BenchmarkCase("case_2_failed_branch", "Failed branch isolation",
                  "Plan A (npm) fails, plan B (bun) succeeds; failed plan must not be recommended.",
                  _seed_failed_branch),
    BenchmarkCase("case_3_workspace_isolation", "Workspace isolation",
                  "Workspace A/B differ; the other workspace must not pollute this one.",
                  _seed_workspace_isolation),
    BenchmarkCase("case_4_tool_safety", "Tool-call safety",
                  "Old memory carries --force / production; gate must reject it.",
                  _seed_tool_safety),
]

ALL_STRATEGIES = [
    RetrievalStrategy.baseline_0,
    RetrievalStrategy.baseline_1,
    RetrievalStrategy.variant_1,
    RetrievalStrategy.variant_2,
]


__all__ = ["BenchmarkCase", "SeedResult", "CASES", "ALL_STRATEGIES"]
