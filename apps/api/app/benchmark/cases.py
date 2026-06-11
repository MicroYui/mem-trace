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
  5. explicit_correction  - Node corrected to Bun -> superseded Node never recalled
  6. completed_run_reuse  - prior successful run -> later similar run recalls procedure
  7. stale_rejection      - expired legacy endpoint memory -> gate rejects as stale
  8. no_memory_baseline   - constraint only in memory -> no-memory baseline fails
  9. over_budget_compaction - tiny context budget -> retain key=value facts safely
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable, Optional

from app.runtime.memory_runtime import MemoryRuntime
from app.runtime.models import (
    BranchStatus,
    CompleteRunRequest,
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


# --------------------------------------------------------------------------- #
# Case 5: explicit correction / dedup + conflict resolver (P2)
# --------------------------------------------------------------------------- #
async def _seed_explicit_correction(rt: MemoryRuntime, ws: str) -> SeedResult:
    """User first states Node.js, then later states Bun (two positive prefs, no
    explicit-correction syntax). These conflict on the single-valued
    ``project.runtime`` key, so the dedup/conflict resolver must retire the older
    Node preference (superseded) at write time and keep the newer Bun one. No
    strategy should ever recall the superseded Node memory.
    """
    run = await rt.start_run(StartRunRequest(session_id="bench", task="run tests", workspace_id=ws))
    s1 = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="planning"))
    # initial preference (will be out-competed by the newer one)
    await rt.write_event(_ev(run.run_id, s1.step_id, EventRole.user, EventType.message,
                             content="这个项目使用 Node.js"))
    # newer, conflicting positive preference -> resolver supersedes the Node one
    await rt.write_event(_ev(run.run_id, s1.step_id, EventRole.user, EventType.message,
                             content="这个项目使用 Bun"))
    await rt.finish_step(FinishStepRequest(run_id=run.run_id, step_id=s1.step_id,
                                           status=StepStatus.completed, summary="settled runtime on Bun"))
    s2 = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="debugging", goal="choose test runner"))
    return SeedResult(run.run_id, s2.step_id, "How should I run the test suite? Earlier I mentioned Node.", ws)


# --------------------------------------------------------------------------- #
# Case 6: completed-run reuse / procedural memory (P2)
# --------------------------------------------------------------------------- #
async def _seed_completed_run_reuse(rt: MemoryRuntime, ws: str) -> SeedResult:
    """First run succeeds fixing a failing pytest suite, then is completed so a
    procedural memory is distilled. A second, similar run should be able to
    recall that procedural success path.
    """
    # ---- first run: successfully fix the failing pytest suite ---------- #
    run1 = await rt.start_run(StartRunRequest(session_id="bench_prev",
                                              task="fix failing pytest suite", workspace_id=ws))
    p1 = await rt.start_step(StartStepRequest(run_id=run1.run_id, intent="planning"))
    await rt.write_event(_ev(run1.run_id, p1.step_id, EventRole.user, EventType.message,
                             content="这个项目使用 Bun"))
    await rt.finish_step(FinishStepRequest(run_id=run1.run_id, step_id=p1.step_id,
                                           status=StepStatus.completed, summary="confirmed project uses Bun"))
    d1 = await rt.start_step(StartStepRequest(run_id=run1.run_id, intent="debugging",
                                              goal="fix failing pytest suite"))
    await rt.write_event(_ev(run1.run_id, d1.step_id, EventRole.tool, EventType.tool_call,
                             tool_name="bash", content="bun test"))
    await rt.write_event(_ev(run1.run_id, d1.step_id, EventRole.tool, EventType.tool_result, status="success",
                             content="Fixed the failing pytest suite by running bun test; all tests passed."))
    await rt.finish_step(FinishStepRequest(run_id=run1.run_id, step_id=d1.step_id,
                                           status=StepStatus.completed, summary="fixed pytest suite with bun test"))
    # cold path: sediment completed-run summary + procedural memory
    await rt.complete_run(CompleteRunRequest(run_id=run1.run_id))

    # ---- second run: a similar task that should reuse the procedure ---- #
    run2 = await rt.start_run(StartRunRequest(session_id="bench",
                                              task="fix failing pytest suite again", workspace_id=ws))
    s2 = await rt.start_step(StartStepRequest(run_id=run2.run_id, intent="debugging",
                                              goal="fix failing pytest suite"))
    return SeedResult(run2.run_id, s2.step_id,
                      "How did we fix the failing pytest suite last time?", ws)


# --------------------------------------------------------------------------- #
# Case 7: stale memory rejection (mvp.md section 10.4)
# --------------------------------------------------------------------------- #
async def _seed_stale_rejection(rt: MemoryRuntime, ws: str) -> SeedResult:
    """An old API-endpoint memory has expired (``expires_at`` in the past). It is
    highly relevant to the query, so a naive (baseline_1) strategy injects it,
    but the risk-policy gate (variant_2) must reject it as ``stale`` and never
    let the outdated endpoint reach context.
    """
    run = await rt.start_run(StartRunRequest(session_id="bench", task="call the users API", workspace_id=ws))
    s1 = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="planning"))
    await rt.write_event(_ev(run.run_id, s1.step_id, EventRole.user, EventType.message,
                             content="这个项目使用 Bun"))
    await rt.finish_step(FinishStepRequest(run_id=run.run_id, step_id=s1.step_id,
                                           status=StepStatus.completed, summary="confirmed project uses Bun"))
    # inject an expired API-endpoint memory directly (active + completed branch,
    # but past its expires_at -> the risk gate must drop it as stale).
    await rt._repo.add_memory(  # noqa: SLF001 - seeding harness
        MemoryItem(
            workspace_id=ws, run_id=run.run_id, memory_type=MemoryType.episodic,
            content="Use the legacy API endpoint /v1/old-users to fetch the users list.",
            summary="legacy API endpoint /v1/old-users",
            branch_status=BranchStatus.completed,
            expires_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
    )
    s2 = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="debugging", goal="call the users API"))
    return SeedResult(run.run_id, s2.step_id,
                      "Which API endpoint should I call to fetch the users list?", ws,
                      extra={"stale_markers": ["/v1/old-users", "old-users"]})


# --------------------------------------------------------------------------- #
# Case 8: no-memory baseline fails where state-aware succeeds (mvp.md 10.4)
# --------------------------------------------------------------------------- #
async def _seed_no_memory_baseline(rt: MemoryRuntime, ws: str) -> SeedResult:
    """The project constraint (use Bun) lives only in memory. A no-memory
    baseline (baseline_0) cannot keep the constraint and fails the task, while
    the state-aware strategies recall the Bun constraint and succeed.
    """
    run = await rt.start_run(StartRunRequest(session_id="bench", task="run tests", workspace_id=ws))
    s1 = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="planning"))
    await rt.write_event(_ev(run.run_id, s1.step_id, EventRole.user, EventType.message,
                             content="这个项目使用 Bun，不用 Node.js"))
    await rt.finish_step(FinishStepRequest(run_id=run.run_id, step_id=s1.step_id,
                                           status=StepStatus.completed, summary="confirmed project uses Bun"))
    s2 = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="debugging", goal="choose test runner"))
    return SeedResult(run.run_id, s2.step_id, "How should I run the test suite?", ws)


# --------------------------------------------------------------------------- #
# Case 9: over-budget compaction retains constraints and excludes unsafe facts
# --------------------------------------------------------------------------- #
async def _seed_over_budget_compaction(rt: MemoryRuntime, ws: str) -> SeedResult:
    run = await rt.start_run(StartRunRequest(session_id="bench", task="choose app stack", workspace_id=ws))
    s1 = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="planning"))

    positive_facts = [
        ("project.runtime", "bun"),
        ("project.database", "postgres"),
        ("endpoint.current", "/v2/users"),
    ]
    for key, value in positive_facts:
        await rt._repo.add_memory(  # noqa: SLF001 - deterministic benchmark seeding
            MemoryItem(
                workspace_id=ws,
                run_id=run.run_id,
                memory_type=MemoryType.project,
                key=key,
                value=value,
                content=f"{key}={value}",
                summary=f"{key}={value}",
                branch_status=BranchStatus.completed,
            )
        )

    # Benign but verbose memories are useful to force the packer over budget.
    for i in range(8):
        await rt._repo.add_memory(  # noqa: SLF001 - deterministic benchmark seeding
            MemoryItem(
                workspace_id=ws,
                run_id=run.run_id,
                memory_type=MemoryType.episodic,
                content=(
                    f"benign debugging observation {i}: previous users API investigation "
                    "contains verbose details that may be omitted under a small prompt budget"
                ),
                summary=f"benign users API observation {i}",
                branch_status=BranchStatus.completed,
            )
        )

    await rt._repo.add_memory(  # noqa: SLF001 - negative failed branch sample
        MemoryItem(
            workspace_id=ws,
            run_id=run.run_id,
            memory_type=MemoryType.project,
            key="project.runtime",
            value="npm",
            content="project.runtime=npm from a failed rolled-back branch",
            summary="project.runtime=npm",
            branch_status=BranchStatus.rolled_back,
        )
    )
    await rt._repo.add_memory(  # noqa: SLF001 - negative stale sample
        MemoryItem(
            workspace_id=ws,
            run_id=run.run_id,
            memory_type=MemoryType.project,
            key="endpoint.current",
            value="/v1/old",
            content="endpoint.current=/v1/old",
            summary="endpoint.current=/v1/old",
            branch_status=BranchStatus.completed,
            expires_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
    )
    await rt._repo.add_memory(  # noqa: SLF001 - negative secret sample
        MemoryItem(
            workspace_id=ws,
            run_id=run.run_id,
            memory_type=MemoryType.episodic,
            content="users endpoint runtime secret sample: SECRET_TOKEN=sk-live-should-never-appear",
            summary="users endpoint runtime secret token should be blocked",
            branch_status=BranchStatus.completed,
            sensitivity=Sensitivity.secret,
            risk_flags=RiskFlags(contains_secret=True),
        )
    )
    await rt._repo.add_memory(  # noqa: SLF001 - negative destructive tool sample
        MemoryItem(
            workspace_id=ws,
            run_id=run.run_id,
            memory_type=MemoryType.tool_evidence,
            content="users endpoint runtime dangerous prior command: git push --force && rm -rf /tmp/prod",
            summary="users endpoint runtime git push --force rm -rf",
            branch_status=BranchStatus.completed,
            risk_flags=RiskFlags(tool_sensitive=True, destructive_command=True, production_env=True),
        )
    )

    s2 = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="debugging", goal="choose DB/runtime/endpoint"))
    return SeedResult(
        run.run_id,
        s2.step_id,
        "Which DB, runtime, and users endpoint should I use?",
        ws,
        extra={
            "token_budget": 18,
            "top_k": 20,
            "compaction_positive_constraints": [f"{key}={value}" for key, value in positive_facts],
            "unsafe_compaction_markers": ["project.runtime=npm", "/v1/old", "secret_token", "sk-live", "--force", "rm -rf"],
        },
    )


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
    BenchmarkCase("case_5_explicit_correction", "Explicit correction / dedup + conflict resolver",
                  "User states Node then corrects to Bun; the superseded Node preference must never be recalled.",
                  _seed_explicit_correction),
    BenchmarkCase("case_6_completed_run_reuse", "Completed-run reuse / procedural memory",
                  "A prior run succeeded fixing pytest failures; a later similar run should recall the procedural success path.",
                  _seed_completed_run_reuse),
    BenchmarkCase("case_7_stale_rejection", "Stale memory rejection",
                  "An expired legacy API-endpoint memory is highly relevant but must be rejected as stale, not injected.",
                  _seed_stale_rejection),
    BenchmarkCase("case_8_no_memory_baseline", "No-memory baseline fails",
                  "The Bun constraint lives only in memory; a no-memory baseline fails while state-aware retrieval succeeds.",
                  _seed_no_memory_baseline),
    BenchmarkCase("case_9_over_budget_compaction", "Over-budget compaction",
                  "Tiny context budget forces compaction; key=value constraints must be retained without unsafe leakage.",
                  _seed_over_budget_compaction),
]

ALL_STRATEGIES = [
    RetrievalStrategy.baseline_0,
    RetrievalStrategy.baseline_1,
    RetrievalStrategy.variant_1,
    RetrievalStrategy.variant_2,
]


__all__ = ["BenchmarkCase", "SeedResult", "CASES", "ALL_STRATEGIES"]
