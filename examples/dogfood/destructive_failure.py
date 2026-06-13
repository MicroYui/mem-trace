from __future__ import annotations

import asyncio

from app.runtime.models import BranchStatus, MemoryItem, MemoryType, RiskFlags
from app.runtime.memory_runtime import MemoryRuntime
from app.runtime.repository import InMemoryRepository
from memtrace_sdk import MemTrace
from memtrace_sdk.types import RetrievalRequest, RetrievalStrategy, StartRunRequest, StartStepRequest


async def main() -> dict[str, bool]:
    repo = InMemoryRepository()
    client = MemTrace.in_process(MemoryRuntime(repo, default_workspace_id="ws_dogfood_destructive"))
    run = await client.start_run(StartRunRequest(session_id="dogfood-destructive", task="Recover safely"))
    step = await client.start_step(StartStepRequest(run_id=run.run_id, intent="recover from destructive attempt"))

    await repo.add_memory(
        MemoryItem(
            workspace_id="ws_dogfood_destructive",
            run_id=run.run_id,
            source_state_node_id=step.state_node_id,
            memory_type=MemoryType.tool_evidence,
            content="Tried rm -rf /tmp/project-cache and it failed dangerously.",
            branch_status=BranchStatus.failed,
            risk_flags=RiskFlags(destructive_command=True),
        )
    )
    context = await client.retrieve_context(
        RetrievalRequest(
            run_id=run.run_id,
            step_id=step.step_id,
            query="What should I avoid after the previous destructive rm operation failure?",
            strategy=RetrievalStrategy.variant_2,
        )
    )
    rendered = "\n".join(block.content for block in context.context_blocks)
    sanitized = "has been redacted" in rendered.lower() or "do not repeat destructive operations" in rendered.lower()
    raw_absent = "rm -rf" not in rendered
    print(f"destructive_failure_sanitized: {str(sanitized and raw_absent).lower()}")
    return {"sanitized": sanitized and raw_absent}


if __name__ == "__main__":
    asyncio.run(main())
