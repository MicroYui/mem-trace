"""Deterministic P0 demo: Bun vs Node.js + failed-branch isolation.

Runs the demo loop (mvp.md section 9) twice over the SAME seeded trace/memories:
  - baseline_1 (vector/lexical memory only) -> admits the failed npm memory
  - variant_2  (state-aware + admission gate) -> rejects it, keeps Bun constraint

Outputs demo_report.md and demo_report.json. No external LLM is used; the final
"action" is decided by a deterministic rule over the packed context.

Usage:
    uv run python -m app.demo.run_demo            # in-memory (no DB needed)
    uv run python -m app.demo.run_demo --sql      # against PostgreSQL
"""
from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.runtime.memory_runtime import MemoryRuntime
from app.runtime.models import (
    EventRole,
    EventType,
    FinishStepRequest,
    MemoryContext,
    RetrievalRequest,
    RetrievalStrategy,
    RollbackRequest,
    StartRunRequest,
    StartStepRequest,
    StepStatus,
)
from app.runtime.repository import InMemoryRepository

QUERY = "How do I run the test suite? I tried npm test."
WORKSPACE = "ws_demo"


async def _seed_run(rt: MemoryRuntime, *, session_id: str, workspace_id: str):
    """Build the canonical demo trace and return (run, recovery_step)."""
    run = await rt.start_run(
        StartRunRequest(session_id=session_id, task="Fix failing tests", workspace_id=workspace_id)
    )

    # step 1: planning - user states the Bun constraint
    s1 = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="planning"))
    await rt.write_event(
        _ev(run.run_id, s1.step_id, EventRole.user, EventType.message,
            content="这个项目使用 Bun，不用 Node.js")
    )
    await rt.finish_step(FinishStepRequest(run_id=run.run_id, step_id=s1.step_id, status=StepStatus.completed))

    # step 2: debugging - npm test fails (the failed branch)
    s2 = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="debugging"))
    await rt.write_event(
        _ev(run.run_id, s2.step_id, EventRole.tool, EventType.tool_call, tool_name="bash", content="npm test")
    )
    await rt.write_event(
        _ev(run.run_id, s2.step_id, EventRole.tool, EventType.tool_result, status="failed",
            content="Tried running tests with npm test, but it failed because npm was unavailable.")
    )
    await rt.finish_step(
        FinishStepRequest(run_id=run.run_id, step_id=s2.step_id, status=StepStatus.failed, error_message="npm unavailable")
    )

    # rollback the failed branch
    await rt.rollback_branch(RollbackRequest(run_id=run.run_id, step_id=s2.step_id, reason="npm unavailable"))

    # step 3: recovery debugging (attaches to step_2's parent = root)
    s3 = await rt.start_step(
        StartStepRequest(run_id=run.run_id, intent="debugging", recovery_from_step_id=s2.step_id, goal="Recovery: choose correct test runner")
    )
    return run, s3


def _ev(run_id, step_id, role, etype, *, content=None, tool_name=None, status=None):
    from app.runtime.models import WriteEventRequest
    return WriteEventRequest(
        run_id=run_id, step_id=step_id, role=role, event_type=etype,
        content=content, tool_name=tool_name, status=status,
    )


def _decide_action(ctx: MemoryContext) -> str:
    """Deterministic rule evaluator (mvp.md 10.3): choose the test command from
    the packed context.

    A failed-branch ``npm`` memory that survives gating contaminates the context
    and leads a naive agent to retry the failed ``npm`` path. Only when no failed
    npm evidence is present does the Bun project constraint win.
    """
    if _contaminated(ctx):
        return "npm test"
    text = " ".join(b.content.lower() for b in _positive_blocks(ctx))
    if "bun" in text:
        return "bun test"
    return "unknown"


def _contaminated(ctx: MemoryContext) -> bool:
    return any("npm" in b.content.lower() and "failed" in b.content.lower() for b in _positive_blocks(ctx))


def _positive_blocks(ctx: MemoryContext):
    return [
        block for block in ctx.context_blocks
        if block.type != "avoided_attempts" and block.source != "negative_evidence"
    ]


async def run_demo(*, use_sql: bool = False) -> dict:
    engine = None
    if use_sql:
        from app.storage.db import make_engine, make_session_factory
        from app.storage.sql_repository import SqlRepository
        engine = make_engine()
        sql_repo = SqlRepository(make_session_factory(engine))

    results: dict[str, dict] = {}
    timeline_dump = None
    tree_dump = None

    for strategy in (RetrievalStrategy.baseline_1, RetrievalStrategy.variant_2):
        # Identical seeded trace per strategy. In-memory uses a fresh repo;
        # SQL shares one DB but isolates via a per-strategy workspace/session so
        # the seeded memories are equivalent and never cross-contaminate.
        if use_sql:
            repo = sql_repo
        else:
            repo = InMemoryRepository()
        # unique workspace per strategy keeps SQL runs isolated yet equivalent
        ws = f"{WORKSPACE}_{strategy.value}_{uuid.uuid4().hex[:6]}" if use_sql else WORKSPACE
        rt = MemoryRuntime(repo, default_workspace_id=ws)
        run, s3 = await _seed_run(rt, session_id=f"sess_{strategy.value}", workspace_id=ws)
        ctx = await rt.retrieve_context(
            RetrievalRequest(run_id=run.run_id, step_id=s3.step_id, query=QUERY, strategy=strategy)
        )
        action = _decide_action(ctx)
        access = await rt.inspect_access(ctx.access_id)
        results[strategy.value] = {
            "access_id": ctx.access_id,
            "context_blocks": [b.model_dump(mode="json") for b in ctx.context_blocks],
            "warnings": ctx.warnings,
            "profile": ctx.profile,
            "final_action": action,
            "task_success": 1 if action == "bun test" else 0,
            "failed_branch_contamination": 1 if _contaminated(ctx) else 0,
            "gate_decisions": [g.model_dump(mode="json") for g in (access.gate_decisions if access else [])],
        }
        if strategy == RetrievalStrategy.variant_2:
            timeline_dump = [e.model_dump(mode="json") for e in await rt.get_timeline(run.run_id)]
            tree_dump = [n.model_dump(mode="json") for n in await rt.get_state_tree(run.run_id)]

    if engine is not None:
        await engine.dispose()

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "query": QUERY,
        "workspace_id": WORKSPACE,
        "timeline": timeline_dump,
        "state_tree": tree_dump,
        "strategies": results,
        "summary": {
            "baseline_1_contamination": results["baseline_1"]["failed_branch_contamination"],
            "variant_2_contamination": results["variant_2"]["failed_branch_contamination"],
            "baseline_1_action": results["baseline_1"]["final_action"],
            "variant_2_action": results["variant_2"]["final_action"],
            "contamination_eliminated": (
                results["baseline_1"]["failed_branch_contamination"] == 1
                and results["variant_2"]["failed_branch_contamination"] == 0
            ),
        },
    }
    return report


def _render_markdown(report: dict) -> str:
    s = report["summary"]
    lines = [
        "# MemTrace P0 Demo Report",
        "",
        f"- Generated: {report['generated_at']}",
        f"- Workspace: `{report['workspace_id']}`",
        f"- Query: `{report['query']}`",
        "",
        "## State Tree",
        "",
        "```text",
    ]
    for n in report["state_tree"]:
        indent = "  " * n["depth"]
        reason = f"  # failure_reason: {n['failure_reason']}" if n.get("failure_reason") else ""
        lines.append(f"{indent}{n['node_type']} {n['status']}{reason}")
    lines += ["```", "", "## Run Timeline", "", "| seq | role | type | status | content |", "|---|---|---|---|---|"]
    for e in report["timeline"]:
        content = (e.get("content") or "").replace("|", "\\|")[:60]
        lines.append(f"| {e['sequence_no']} | {e['role']} | {e['event_type']} | {e.get('status') or ''} | {content} |")

    for strat in ("baseline_1", "variant_2"):
        r = report["strategies"][strat]
        lines += [
            "",
            f"## Strategy: {strat}",
            "",
            f"- Final action: **{r['final_action']}**  (task_success={r['task_success']})",
            f"- Failed-branch contamination: **{r['failed_branch_contamination']}**",
            f"- Warnings: {r['warnings']}",
            f"- Profile: {r['profile']}",
            "",
            "### Memory Access / Gate Decisions",
            "",
            "| decision | reason | branch | final_score | content |",
            "|---|---|---|---|---|",
        ]
        for g in r["gate_decisions"]:
            content = (g.get("content") or "").replace("|", "\\|")[:50]
            lines.append(
                f"| {g['decision']} | {g.get('reject_reason') or ''} | {g.get('branch_status') or ''} | {g['final_score']:.3f} | {content} |"
            )
        lines += ["", "### Packed Context Blocks", ""]
        for b in r["context_blocks"]:
            lines.append(f"- `{b['type']}` ({b['tokens']} tok): {b['content']}")

    lines += [
        "",
        "## Summary",
        "",
        f"- baseline_1 contamination: {s['baseline_1_contamination']} -> action `{s['baseline_1_action']}`",
        f"- variant_2 contamination: {s['variant_2_contamination']} -> action `{s['variant_2_action']}`",
        f"- **Contamination eliminated by state-aware + gate: {s['contamination_eliminated']}**",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="MemTrace P0 demo")
    parser.add_argument("--sql", action="store_true", help="use PostgreSQL backend")
    parser.add_argument("--out", default="reports", help="output directory")
    args = parser.parse_args()

    report = asyncio.run(run_demo(use_sql=args.sql))
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "demo_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    (out_dir / "demo_report.md").write_text(_render_markdown(report))

    s = report["summary"]
    print(f"baseline_1: action={s['baseline_1_action']} contamination={s['baseline_1_contamination']}")
    print(f"variant_2 : action={s['variant_2_action']} contamination={s['variant_2_contamination']}")
    print(f"contamination_eliminated={s['contamination_eliminated']}")
    print(f"reports written to {out_dir}/demo_report.md and demo_report.json")


if __name__ == "__main__":
    main()
