from __future__ import annotations

import asyncio
from typing import Any

from memtrace_sdk import MemTrace, MemTraceLangGraphAdapter
from memtrace_sdk.types import StartRunRequest


async def main() -> dict[str, Any]:
    """Run a minimal LangGraph integration, or skip cleanly without the extra."""

    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError:
        print(
            "LangGraph is not installed; skipping this example. "
            "Install it with: pip install memtrace-sdk[langgraph]"
        )
        return {"status": "skipped", "reason": "langgraph_not_installed"}

    client = MemTrace.in_memory(default_workspace_id="ws_langgraph_example")
    run = await client.start_run(
        StartRunRequest(session_id="langgraph-example", task="Run a LangGraph node")
    )
    adapter = MemTraceLangGraphAdapter(client, run_id=run.run_id)

    async def answer_node(state: dict[str, Any]) -> dict[str, Any]:
        context = state["memtrace_context"]
        return {
            **state,
            "answer": f"retrieved {len(context.context_blocks)} context blocks before answering",
        }

    graph_builder = StateGraph(dict)
    graph_builder.add_node(
        "answer",
        adapter.wrap_node(
            answer_node,
            node_name="answer",
            query="what context should this graph node use?",
        ),
    )
    graph_builder.add_edge(START, "answer")
    graph_builder.add_edge("answer", END)
    graph = graph_builder.compile()

    state = await graph.ainvoke({"question": "What did MemTrace inject?"})
    timeline = await client.get_timeline(run.run_id)
    steps = await client.get_steps(run.run_id)
    event_source = timeline[-1].event_source if timeline else None
    step_status = steps[-1].status.value if steps else None

    print("LangGraph adapter example completed")
    print(f"answer: {state['answer']}")
    print(f"event_source: {event_source}")
    print(f"step_status: {step_status}")
    return {
        "status": "ran",
        "answer": state["answer"],
        "event_source": event_source,
        "step_status": step_status,
    }


if __name__ == "__main__":
    asyncio.run(main())
