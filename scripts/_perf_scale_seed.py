"""Seed helper for scripts/perf-scale.sh — seed N memories + a run/step in the
shared Postgres, printing the run/step ids for the load driver. Prints
'SKIP_NO_DB' to stderr and exits non-zero if the database is unreachable."""
from __future__ import annotations

import asyncio
import sys

from sqlalchemy import text

from app.runtime.memory_runtime import MemoryRuntime
from app.runtime.models import (
    MemoryItem,
    MemoryScope,
    MemoryType,
    StartRunRequest,
    StartStepRequest,
)
from app.storage.db import make_engine, make_session_factory
from app.storage.sql_repository import SqlRepository

WS = "scale_ws"
SESSION = "scale:session"
TOPICS = ["cache layer", "database", "test runner", "message broker", "cloud provider"]


async def main(n: int) -> int:
    engine = make_engine()
    try:
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except Exception:  # noqa: BLE001
            print("SKIP_NO_DB", file=sys.stderr)
            return 3

        async with engine.begin() as conn:
            for tbl in ("memory_items", "agent_events", "agent_steps", "state_nodes", "agent_runs"):
                await conn.execute(text(f"DELETE FROM {tbl} WHERE workspace_id = :ws"), {"ws": WS})

        repo = SqlRepository(make_session_factory(engine))
        for i in range(n):
            topic = TOPICS[i % len(TOPICS)]
            await repo.add_memory(MemoryItem(
                memory_id=f"scale_m_{i}", workspace_id=WS, memory_type=MemoryType.episodic,
                scope=MemoryScope.workspace, content=f"note {i}: the {topic} for module {i} is value_{i}",
                summary=f"note {i} {topic}"))

        rt = MemoryRuntime(repo, default_workspace_id=WS)
        run = await rt.start_run(StartRunRequest(session_id=SESSION, task="scale", workspace_id=WS))
        step = await rt.start_step(StartStepRequest(run_id=run.run_id, intent="answer"))
        print(f"RUNID {run.run_id}")
        print(f"STEPID {step.step_id}")
        return 0
    finally:
        await engine.dispose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main(int(sys.argv[1]))))
