from __future__ import annotations

import asyncio

from memtrace_sdk import MemTrace
from memtrace_sdk.types import (
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


async def main() -> dict[str, object]:
    client = MemTrace.in_memory(default_workspace_id="ws_dogfood_coding")
    run = await client.start_run(
        StartRunRequest(session_id="dogfood-coding", task="Recover from a failed test command")
    )

    preference = await client.start_step(StartStepRequest(run_id=run.run_id, intent="record project runtime"))
    await client.write_event(
        WriteEventRequest(
            run_id=run.run_id,
            step_id=preference.step_id,
            role=EventRole.user,
            event_type=EventType.message,
            content="这个项目使用 Bun，不用 Node.js",
        )
    )
    await client.finish_step(FinishStepRequest(run_id=run.run_id, step_id=preference.step_id))

    failed = await client.start_step(StartStepRequest(run_id=run.run_id, intent="try old test command"))
    await client.write_event(
        WriteEventRequest(
            run_id=run.run_id,
            step_id=failed.step_id,
            role=EventRole.tool,
            event_type=EventType.tool_result,
            tool_name="bash",
            status="failed",
            content="Tried npm test, but npm is unavailable in this workspace.",
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
    await client.rollback_branch(RollbackRequest(run_id=run.run_id, step_id=failed.step_id, reason="npm unavailable"))

    recovery = await client.start_step(
        StartStepRequest(run_id=run.run_id, recovery_from_step_id=failed.step_id, intent="choose test command")
    )
    context = await client.retrieve_context(
        RetrievalRequest(
            run_id=run.run_id,
            step_id=recovery.step_id,
            query="How should I run tests after npm failed?",
            strategy=RetrievalStrategy.variant_2,
        )
    )

    positive_text = "\n".join(
        block.content for block in context.context_blocks if block.type != "avoided_attempts" and block.source != "negative_evidence"
    ).lower()
    avoids_npm = "npm" not in positive_text and any(block.type == "avoided_attempts" for block in context.context_blocks)
    command = "bun test" if "bun" in positive_text else "unknown"
    print(f"variant_2 avoids npm: {str(avoids_npm).lower()}")
    print(f"recovery command: {command}")
    return {"variant_2_avoids_npm": avoids_npm, "recovery_command": command}


if __name__ == "__main__":
    asyncio.run(main())
