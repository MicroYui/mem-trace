from __future__ import annotations

import asyncio
from typing import Any

from memtrace_sdk import MemTrace
from memtrace_sdk.types import (
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
    WriteEventRequest,
)


QUERY = "How do I run the test suite? I tried npm test."
WORKSPACE_ID = "ws_sdk_simple_agent"


async def main() -> dict[str, Any]:
    """Run a deterministic custom-loop demo through the public SDK facade."""

    results: dict[str, dict[str, Any]] = {}
    for strategy in (RetrievalStrategy.baseline_1, RetrievalStrategy.variant_2):
        client = MemTrace.in_memory(default_workspace_id=WORKSPACE_ID)
        run, recovery_step = await _seed_run(client, session_id=f"simple-agent-{strategy.value}")
        context = await client.retrieve_context(
            RetrievalRequest(
                run_id=run.run_id,
                step_id=recovery_step.step_id,
                query=QUERY,
                strategy=strategy,
            )
        )
        action = decide_action(context)
        results[strategy.value] = {
            "action": action,
            "failed_branch_contamination": int(_contaminated(context)),
            "context_blocks": [block.model_dump(mode="json") for block in context.context_blocks],
            "warnings": context.warnings,
        }

    summary = {
        "baseline_action": results[RetrievalStrategy.baseline_1.value]["action"],
        "variant_2_action": results[RetrievalStrategy.variant_2.value]["action"],
        "baseline_contamination": results[RetrievalStrategy.baseline_1.value][
            "failed_branch_contamination"
        ],
        "variant_2_contamination": results[RetrievalStrategy.variant_2.value][
            "failed_branch_contamination"
        ],
        "contamination_eliminated": (
            results[RetrievalStrategy.baseline_1.value]["failed_branch_contamination"] == 1
            and results[RetrievalStrategy.variant_2.value]["failed_branch_contamination"] == 0
        ),
        "strategies": results,
    }

    print(
        "baseline_1 action: "
        f"{summary['baseline_action']} "
        f"(contamination={summary['baseline_contamination']})"
    )
    print(
        "variant_2 action: "
        f"{summary['variant_2_action']} "
        f"(contamination={summary['variant_2_contamination']})"
    )
    print(f"contamination eliminated: {str(summary['contamination_eliminated']).lower()}")
    return summary


async def _seed_run(client: MemTrace, *, session_id: str):
    run = await client.start_run(
        StartRunRequest(
            session_id=session_id,
            task="Fix failing tests from a custom loop",
            workspace_id=WORKSPACE_ID,
        )
    )

    planning = await client.start_step(StartStepRequest(run_id=run.run_id, intent="planning"))
    await client.write_event(
        WriteEventRequest(
            run_id=run.run_id,
            step_id=planning.step_id,
            role=EventRole.user,
            event_type=EventType.message,
            content="这个项目使用 Bun，不用 Node.js",
        )
    )
    await client.finish_step(
        FinishStepRequest(run_id=run.run_id, step_id=planning.step_id, status=StepStatus.completed)
    )

    failed = await client.start_step(StartStepRequest(run_id=run.run_id, intent="debugging"))
    await client.write_event(
        WriteEventRequest(
            run_id=run.run_id,
            step_id=failed.step_id,
            role=EventRole.tool,
            event_type=EventType.tool_call,
            tool_name="bash",
            content="npm test",
        )
    )
    await client.write_event(
        WriteEventRequest(
            run_id=run.run_id,
            step_id=failed.step_id,
            role=EventRole.tool,
            event_type=EventType.tool_result,
            tool_name="bash",
            status="failed",
            content="Tried running tests with npm test, but it failed because npm was unavailable.",
        )
    )
    await client.finish_step(
        FinishStepRequest(
            run_id=run.run_id,
            step_id=failed.step_id,
            status=StepStatus.failed,
            error_message="npm unavailable",
        )
    )
    await client.rollback_branch(
        RollbackRequest(run_id=run.run_id, step_id=failed.step_id, reason="npm unavailable")
    )

    recovery = await client.start_step(
        StartStepRequest(
            run_id=run.run_id,
            intent="debugging",
            recovery_from_step_id=failed.step_id,
            goal="Recovery: choose correct test runner",
        )
    )
    return run, recovery


def decide_action(context: MemoryContext) -> str:
    """Tiny local policy over packed context; no private demo helper imports."""

    if _contaminated(context):
        return "npm test"
    positive_text = " ".join(block.content.lower() for block in _positive_blocks(context))
    if "bun" in positive_text:
        return "bun test"
    return "unknown"


def _contaminated(context: MemoryContext) -> bool:
    return any("npm" in block.content.lower() and "failed" in block.content.lower() for block in _positive_blocks(context))


def _positive_blocks(context: MemoryContext):
    return [
        block
        for block in context.context_blocks
        if block.type != "avoided_attempts" and block.source != "negative_evidence"
    ]


if __name__ == "__main__":
    asyncio.run(main())
