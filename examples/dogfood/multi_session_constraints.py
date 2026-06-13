from __future__ import annotations

import asyncio

from memtrace_sdk import MemTrace
from memtrace_sdk.types import (
    EventRole,
    EventType,
    FinishStepRequest,
    RetrievalRequest,
    RetrievalStrategy,
    StartRunRequest,
    StartStepRequest,
    WriteEventRequest,
)


async def main() -> dict[str, str]:
    client = MemTrace.in_memory(default_workspace_id="ws_dogfood_multi_session")

    run1 = await client.start_run(StartRunRequest(session_id="dogfood-session-1", task="Record project setup"))
    step1 = await client.start_step(StartStepRequest(run_id=run1.run_id, intent="record runtime"))
    await client.write_event(
        WriteEventRequest(
            run_id=run1.run_id,
            step_id=step1.step_id,
            role=EventRole.user,
            event_type=EventType.message,
            content="这个项目使用 Bun，不用 Node.js",
        )
    )
    await client.finish_step(FinishStepRequest(run_id=run1.run_id, step_id=step1.step_id))

    run2 = await client.start_run(StartRunRequest(session_id="dogfood-session-2", task="Use remembered setup"))
    step2 = await client.start_step(StartStepRequest(run_id=run2.run_id, intent="retrieve runtime"))
    context = await client.retrieve_context(
        RetrievalRequest(
            run_id=run2.run_id,
            step_id=step2.step_id,
            query="Which runtime/package manager does this project use?",
            strategy=RetrievalStrategy.variant_2,
        )
    )
    text = "\n".join(block.content for block in context.context_blocks)
    runtime = "Bun" if "Bun" in text or "bun" in text.lower() else "unknown"
    print(f"session_2_retrieved_project_runtime: {runtime}")
    return {"runtime": runtime}


if __name__ == "__main__":
    asyncio.run(main())
